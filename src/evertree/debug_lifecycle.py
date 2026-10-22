"""Run a Program lifecycle scenario from tests/lifecycle/cases.json against a real EverTree.

Run this file in PyCharm with the project interpreter and sign in to Codex, or run
`python -m evertree.debug_lifecycle PLC-02`. The conscious agent and the coding
provider are real Codex; Programs run in native workers. The session installs the
scenario's Programs through the real lifecycle gates, binds the developer holdouts,
gives the agent the scenario task, then probes the active Programs. It writes
state.json (graph Programs, branches, receipts, choices, bindings) and result.json
under tmp/debug-lifecycle/<run>/, also on failure.

Useful breakpoints:
- LifecycleSession.install: how a seed Program passes its own gates.
- ToolsMixin._lifecycle_operation: every lifecycle call of the agent or a meta Program.
- ProgramsMixin.evaluate_candidate and core/programs/experiments.py evaluate_pair.
- ProgramsMixin.choose_candidate: sibling dominance and decisions by candidate kind.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from evertree.core.datasets import EvaluationCase
from evertree.core.evaluation.acceptance import AcceptanceCriteria, MetricGuardrail
from evertree.core.programs.lifecycle import git
from evertree.core.values import json_value

REPOSITORY = Path(__file__).resolve().parents[2]
CASES = REPOSITORY / "tests" / "lifecycle" / "cases.json"
PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w.]*)\}")
CONTINUATIONS = 2


def load_cases() -> list[dict]:
    """Read every lifecycle scenario."""
    return json.loads(CASES.read_text(encoding="utf-8"))


def load_case(case_id: str) -> dict:
    """Read one lifecycle scenario by id."""
    for case in load_cases():
        if case["id"] == case_id:
            return case
    raise KeyError(f"Unknown lifecycle case: {case_id}")


def criteria_from(values: dict | None) -> AcceptanceCriteria:
    """Build the protected criteria a scenario binds; core checks are always required."""
    values = dict(values or {"target_metric": "accuracy", "threshold": 1.0})
    values["guardrails"] = tuple(MetricGuardrail(**item) for item in values.get("guardrails", ()))
    return AcceptanceCriteria(required_checks=("contracts", "tests", "holdout"), **values)


class LifecycleSession:
    """Prepare a scenario in an open EverTree, drive it, and collect its observable state."""

    def __init__(self, agent, case: dict, output_dir: Path | None = None):
        self.agent = agent
        self.case = case
        self.output_dir = output_dir
        self.names: dict[str, object] = {}
        self.setup_revisions: dict[str, str | None] = {}
        self.seed_candidates: list[str] = []
        self.steps: list[dict] = []
        self.task: dict | None = None
        self.probes: list[dict] = []
        self.outcomes: list[dict] = []
        self._task_id = None

    def task_id(self) -> str:
        """An open bookkeeping task for setup, replayed steps and probes."""
        if self._task_id is None or self.agent.tasks.get(self._task_id).terminal:
            task = self.agent.tasks.create_task("Prepare and check a lifecycle scenario")
            self.agent.tasks.assign_budget(
                task.id, {"active_time_minutes": 120}, 50, reason="Scenario harness"
            )
            self._task_id = task.id
        return self._task_id

    def fill(self, value):
        """Replace {name} placeholders; a whole-string placeholder keeps the value's type."""
        if isinstance(value, dict):
            return {key: self.fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.fill(item) for item in value]
        if isinstance(value, str):
            whole = PLACEHOLDER.fullmatch(value)
            if whole and whole.group(1) in self.names:
                return self.names[whole.group(1)]
            return PLACEHOLDER.sub(
                lambda match: str(self.names.get(match.group(1), match.group(0))), value
            )
        return value

    def _dataset(self, key: str, spec: dict, label: str):
        cases = [
            EvaluationCase(
                f"{label}-{index}",
                inputs,
                outcome,
                spec["rule"],
                (f"{self.case['id']}:{key}:{label}:{index}",),
            )
            for index, (inputs, outcome) in enumerate(spec["cases"])
        ]
        return self.agent.datasets.create(
            f"{self.case['id']}:{key}:{label}",
            cases,
            target_metrics=tuple(spec.get("metrics", ("accuracy",))),
        )

    def bind(self, key: str, spec: dict, label: str):
        """Bind a developer holdout (and a meta Program's history) to the Program's slot."""
        dataset = self._dataset(key, spec, label)
        history = (
            self._dataset(key, {**spec, "cases": spec["history"]}, label + "-history")
            if "history" in spec
            else None
        )
        self.agent.bind_evaluation(
            self.names[key],
            dataset.revision,
            criteria=criteria_from(spec.get("criteria")),
            history_dataset_revision=history.revision if history else None,
        )
        return dataset

    async def install(self, key: str, spec: dict):
        """Install a seed Program through proposal, its own seed holdout and activation."""
        agent, task_id = self.agent, self.task_id()
        proposal = agent.propose_program(
            spec["name"],
            role=spec["role"],
            claim="Install the scenario's initial implementation",
            description=spec["description"],
            candidate_name="scenario seed",
            meta=spec.get("meta", False),
        )
        program, candidate = proposal["program"], proposal["candidate"]
        self.seed_candidates.append(candidate["id"])
        self.names[key] = program["id"]
        self.names[key + ".name"] = program["name"]
        workspace = Path(candidate["workspace"])
        files = {program["properties"]["git_path"]: spec["source"], **spec.get("files", {})}
        for path, text in files.items():
            (workspace / path).parent.mkdir(parents=True, exist_ok=True)
            (workspace / path).write_text(text, encoding="utf-8")
        git(workspace, "add", "--all")
        git(workspace, "commit", "-m", "Scenario seed")
        agent.lifecycle.retain_candidate(candidate["id"])
        self.bind(key, spec["seed"], "seed")
        evaluation = await agent.evaluate_candidate(candidate["id"], task_id=task_id)
        if evaluation.get("verification", {}).get("status") != "verified":
            raise RuntimeError(f"Seed {spec['name']} failed its gates: {evaluation}")
        await agent.choose_candidate(
            task_id, candidate["id"], "activate_program", "Scenario seed passed its gates"
        )
        self.setup_revisions[key] = agent.graph.get(program["id"]).properties["revision"]

    async def setup(self):
        """Install Programs, bind scenario holdouts and replay prior live experience."""
        setup = self.case.get("setup", {})
        for key, name in setup.get("existing", {}).items():
            node = self.agent.graph.find(name)
            self.names[key] = node.id
            self.names[key + ".name"] = node.name
            self.setup_revisions[key] = node.properties.get("revision")
        for key, spec in setup.get("programs", {}).items():
            await self.install(key, spec)
        for key, spec in setup.get("proposals", {}).items():
            # The developer declares a new Program's slot and holdout before the agent develops it.
            proposal = self.agent.propose_program(
                spec["name"],
                role=spec["role"],
                claim=spec["claim"],
                description=spec["description"],
                candidate_name=spec["candidate_name"],
            )
            self.names[key] = proposal["program"]["id"]
            self.names[key + ".candidate"] = proposal["candidate"]["id"]
            self.setup_revisions[key] = None
            self.bind(key, spec["holdout"], "holdout")
        for key, spec in setup.get("bindings", {}).items():
            self.bind(key, spec, "holdout")
        for index, run in enumerate(setup.get("experience", ())):
            result = await self.agent._run_program(
                self.task_id(), self.names[run["program"]], run["arguments"]
            )
            reference = self.agent.observe(
                run["outcome"],
                source_id=f"{self.case['id']}:outcome:{index}",
                outcome_of=result["run_id"],
            )
            if run.get("surfaced"):
                # Consciousness already saw this outcome, so it can no longer be hidden.
                self.agent._surfaced.add(reference.event_ref)
        for index, item in enumerate(setup.get("trained", ())):
            # An exec Program forecasts through its model; the outcome then trains the estimator.
            await self.agent._run_program(
                self.task_id(), self.names[item["program"]], self.fill(item["arguments"])
            )
            self.agent.learn_outcome(
                item["target"],
                item["outcome"],
                context=self.fill(item["context"]),
                source_id=f"{self.case['id']}:trained:{index}",
            )
        for key, value in setup.get("names", {}).items():
            self.names[key] = value

    async def run_task(self):
        """Give the live conscious agent the scenario task and keep its final status."""
        self.task = await self.agent.run(self.fill(self.case["task"]))
        for _ in range(CONTINUATIONS):
            state = self.agent.tasks.get(self.task["task_id"])
            if state.status != "waiting" or list(state.waiting_for or ()) != ["resume"]:
                break
            # A user answers a used-up step budget by asking the agent to go on.
            self.task = await self.agent.run("Continue the task.", task_id=state.id)
        state = self.agent.tasks.get(self.task["task_id"])
        self.task["progress"] = state.progress
        self.task["waiting_for"] = list(getattr(state, "waiting_for", ()) or ())
        return self.task

    async def replay(self, provider):
        """Drive the scenario's mirror steps directly; provider plays the coding agent."""
        for step in self.case["mirror"]["steps"]:
            operation, arguments = step["op"], self.fill(step.get("args", {}))
            record = {"op": operation, "args": arguments}
            if "files" in step:
                provider.files[arguments["candidate"]] = step["files"]
            if "answers" in step:
                provider.answers.extend(step["answers"])
            if "coding" in step:
                provider.files_by_name.update(step["coding"])
            try:
                if operation == "end_task":
                    # The task's open candidates pause when its workspaces go away.
                    await self.agent._discard_workspaces(self.task_id())
                    self._task_id = None
                    result = None
                else:
                    result = await self.agent._dispatch_tool(self.task_id(), operation, arguments)
                record["result"] = json_value(result)
            except Exception as error:
                record["error"] = f"{type(error).__name__}: {error}"
                if "error" not in step:
                    self.steps.append(record)
                    raise
            if "error" in step and step["error"] not in record.get("error", ""):
                self.steps.append(record)
                raise AssertionError(f"Step {operation} should fail with {step['error']}: {record}")
            if "as" in step:
                result = record["result"]
                self.names[step["as"]] = (
                    result["candidate"]["id"] if operation == "propose_program" else result["id"]
                )
                if operation == "propose_program":
                    self.names[step["as"] + ".program"] = result["program"]["id"]
            self.steps.append(record)

    async def probe(self):
        """Run every probe expectation's Program on its arguments with the active code."""
        # The scheduler may still own the execution chain after the task stopped.
        await self.agent._execution.wait_idle()
        for expectation in self.case["expect"]:
            if expectation["kind"] != "probe":
                continue
            # A failed run stays pending in its task, so each probe gets its own task.
            self._task_id = None
            arguments = self.fill(expectation["arguments"])
            try:
                result = await self.agent._run_program(
                    self.task_id(), self.fill(expectation["program"]), arguments
                )
                self.probes.append({"arguments": arguments, "result": result["result"]})
            except Exception as error:  # noqa: BLE001 -- a failing probe is checked, not raised
                self.probes.append({"arguments": arguments, "error": str(error)})
        for index, item in enumerate(self.case.get("outcomes", ())):
            # The world later reports what happened to forecasts the probes made.
            try:
                result = self.agent.learn_outcome(
                    item["target"],
                    item["value"],
                    context=self.fill(item["context"]),
                    source_id=f"{self.case['id']}:outcome-after:{index}",
                )
            except Exception as error:  # noqa: BLE001 -- checked through the outcome record
                result = {"error": f"{type(error).__name__}: {error}"}
            self.outcomes.append({"target": item["target"], **json_value(result)})

    def state(self) -> dict:
        """Collect the observable lifecycle state the scenario checks read."""
        agent = self.agent
        lifecycle = agent.lifecycle.snapshot()
        datasets = {}
        for binding in agent._evaluation_bindings.values():
            for revision in (binding["dataset_revision"], binding.get("history_dataset_revision")):
                if revision:
                    datasets[revision] = [case.id for case in agent.datasets.get(revision).cases]
        return json_value(
            {
                "names": self.names,
                "setup_revisions": self.setup_revisions,
                "seed_candidates": self.seed_candidates,
                "programs": {
                    str(node.id): {"name": node.name, **node.properties}
                    for node in agent.graph.nodes(kind="program")
                },
                "processes": {
                    str(node.id): node.properties
                    for node in agent.graph.nodes()
                    if node.properties.get("process") is True
                },
                "branches": lifecycle["branches"],
                "evaluations": lifecycle["evaluations"],
                "choices": lifecycle["choices"],
                "bindings": agent._evaluation_bindings,
                "datasets": datasets,
                "sealed": sorted(agent.memory.sealed),
                "runs": [
                    {"program": run.program, "status": run.status, "run_mode": run.run_mode}
                    for run in agent.memory.runs
                    if isinstance(run.program, int)
                ],
                "main": git(agent.repository, "rev-parse", "main"),
                "steps": self.steps,
                "task": self.task,
                "probes": self.probes,
                "outcomes": self.outcomes,
                "learning": self._learning_state(),
            }
        )

    def _learning_state(self) -> dict:
        """Declared targets, bindings, estimator states and indexed forecasts."""
        agent = self.agent
        snapshot = agent.learning.snapshot()
        variables = [
            {
                "process": fact.args["process"],
                "target": agent.graph.get(fact.args["variable"]).name,
            }
            for fact in agent.graph.facts("PROCESS_VARIABLE")
        ]
        predictions = [
            {"id": fact.id, "target": agent.graph.get(fact.args["target"]).name}
            for fact in agent.graph.facts("PREDICTS")
        ]
        return {
            "bindings": agent.learning.bindings(),
            "states": {
                identity: {
                    "kind": state["kind"],
                    "revision": state["revision"],
                    "observed_count": state["parameters"]["observed_count"],
                    "settings": state["settings"],
                }
                for identity, state in snapshot["states"].items()
            },
            "variables": variables,
            "predictions": predictions,
            "estimates": [
                {"run": event.program_run, "state": event.output["state"]}
                for event in agent.memory.events
                if isinstance(event.output, Mapping)
                and set(event.output) == {"value", "state", "revision", "observed_count"}
            ],
        }

    def save(self, **extra):
        """Write the scenario state for inspection."""
        if self.output_dir is None:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "state.json").write_text(
            json.dumps({**self.state(), **extra}, indent=2, ensure_ascii=False), encoding="utf-8"
        )


async def run_live(case: dict, home: Path, output_dir: Path | None = None) -> dict:
    """Prepare the scenario, let the real agent solve it, probe and return the state."""
    from evertree.application import EverTree

    async with EverTree(home) as agent:
        session = LifecycleSession(agent, case, output_dir)
        try:
            await session.setup()
            await session.run_task()
            await session.probe()
            return session.state()
        finally:
            session.save()


def main():
    """Run one live scenario by id and print where its artifacts are."""
    from evertree import application
    from evertree.common.logging_setup import configure_logging

    configure_logging()
    case = load_case(sys.argv[1] if len(sys.argv) > 1 else "PLC-02")
    run = REPOSITORY / "tmp" / "debug-lifecycle" / uuid4().hex[:12]
    remote = run / "programs.git"
    remote.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    # A debug run never publishes to the developer's origin or needs a committed tree.
    os.environ["EVERTREE_PROGRAM_REMOTE"] = str(remote)
    application.require_committed_runtime = lambda _: None
    print(f"{case['id']}: {case['title']}\nArtifacts: {run}", flush=True)
    state = asyncio.run(run_live(case, run / "home", run))
    print(json.dumps({"task": state["task"], "choices": state["choices"]}, indent=2))


if __name__ == "__main__":
    main()
