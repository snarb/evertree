"""Run an evaluative-control scenario from tests/evaluative/cases.json against a real EverTree.

Run `python -m evertree.debug_evaluative_control EVL-04` with Codex signed in. The session
seeds saved experience (calibrated unexpectedness, omissions, Tasks with outcomes and
deadlines, supervisor feedback), gives the live conscious agent the scenario task, applies
scheduled host events (feedback, cancellation) while the task runs, and collects what the
agent did and what Core recorded. It writes state.json under
tmp/debug-evaluative/<run>/, also on failure.

Useful breakpoints:
- ToolsMixin._dispatch_tool: the conscious agent's evaluative_signals calls.
- EvaluationStore.get_tension_reduction and get_task_outcome_stats: aggregate composition.
- EverTree.supervisor_feedback: feedback as an observation, a channel value and task input.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from evertree.core.evaluation.contracts import EvaluatedResult, MetricSample, SupervisorFeedback
from evertree.core.values import json_value

REPOSITORY = Path(__file__).resolve().parents[2]
CASES = REPOSITORY / "tests" / "evaluative" / "cases.json"
CONTINUATIONS = 3
# Waits a user resolves by letting the agent continue with a reviewed budget.
RESUMABLE = {"resume", "verification"}


def load_cases() -> list[dict]:
    """Read every evaluative-control scenario."""
    return json.loads(CASES.read_text(encoding="utf-8"))


def load_case(case_id: str) -> dict:
    """Read one evaluative-control scenario by id."""
    for case in load_cases():
        if case["id"] == case_id:
            return case
    raise KeyError(f"Unknown evaluative-control case: {case_id}")


def seed_unexpectedness(
    agent, process: str, at: datetime, value: float, *, key: str = "rule-1"
) -> EvaluatedResult:
    """Retain a calculated prediction_unexpectedness whose outcome ended at a past time.

    Core never backdates the outcomes it scores, so history older than a scenario is
    supplied as saved evaluation results of the same shape PredictionEvaluator stores.
    """
    identity = uuid4().hex
    return agent.evaluations.add(
        EvaluatedResult(
            (MetricSample("prediction_unexpectedness", value, "prediction_unexpectedness"),),
            (identity,),
            evaluated_subject=identity,
            provenance=(identity,),
            process_id=process,
            observed_at=at.isoformat(),
            comparison_key=key,
            basis={"method": "model", "kind": "normal", "rule_version": "1"},
        )
    )


def seed_omission(agent, process: str, at: datetime, reason: str) -> EvaluatedResult:
    """Retain a scored check whose unexpectedness was deliberately not calculated."""
    identity = uuid4().hex
    return agent.evaluations.add(
        EvaluatedResult(
            (MetricSample("squared_error", 0.1),),
            (identity,),
            evaluated_subject=identity,
            provenance=(identity,),
            skipped_metrics={"prediction_unexpectedness": reason},
            process_id=process,
            observed_at=at.isoformat(),
        )
    )


def seed_task(
    agent,
    status: str | None,
    *,
    process: str,
    created: datetime,
    completed: datetime | None = None,
    deadline: datetime | None = None,
    objective: str = "Seeded task",
    parent: str | None = None,
):
    """Register a Task with explicit lifecycle times through the TaskStore transitions."""
    from evertree.core.evaluation.acceptance import VerificationResult

    task = agent.tasks.create_task(
        objective,
        process_id=process,
        deadline=deadline.isoformat() if deadline else None,
        parent_task_id=parent,
    )
    task.created_at = created.isoformat()
    if task.deadline_history:
        task.deadline_history[0]["since"] = created.isoformat()
    if status is not None:
        agent.tasks.finish(
            task.id,
            status,
            reason="seeded " + status,
            execution_stopped=True,
            verification=VerificationResult("verified") if status == "succeeded" else None,
            completed_at=completed.isoformat() if completed else None,
        )
    return task


class EvaluativeSession:
    """Seed a scenario in an open EverTree, drive its task and collect observable state."""

    def __init__(self, agent, case: dict, output_dir: Path | None = None):
        self.agent = agent
        self.case = case
        self.output_dir = output_dir
        self.now = datetime.now(UTC)
        self.names: dict[str, str] = {}
        self.boundary = 0
        self.task: dict | None = None
        self.events: list[dict] = []

    def process(self, name: str) -> str:
        return str(self.agent.graph.find(name).id)

    def ago(self, days: float | None) -> datetime | None:
        return None if days is None else self.now - timedelta(days=days)

    def fill(self, text: str) -> str:
        for key, value in self.names.items():
            text = text.replace("{" + key + "}", value)
        return text

    def setup(self):
        """Seed experience relative to now; names map case keys to created Task ids."""
        setup = self.case.get("setup", {})
        for item in setup.get("tension", ()):
            for value in item["values"]:
                seed_unexpectedness(
                    self.agent,
                    self.process(item["process"]),
                    self.ago(item["days_ago"]),
                    value,
                    key=item.get("key", "rule-1"),
                )
        for item in setup.get("omissions", ()):
            seed_omission(
                self.agent,
                self.process(item["process"]),
                self.ago(item["days_ago"]),
                item["reason"],
            )
        for item in setup.get("tasks", ()):
            for _ in range(item.get("count", 1)):
                task = seed_task(
                    self.agent,
                    item.get("status"),
                    process=self.process(item["process"]),
                    created=self.ago(item["created_days_ago"]),
                    completed=self.ago(item.get("completed_days_ago")),
                    deadline=self.ago(item.get("deadline_days_ago")),
                    objective=item.get("objective", "Seeded task"),
                )
                if "name" in item:
                    self.names[item["name"]] = task.id
        for item in setup.get("feedback", ()):
            self.agent.supervisor_feedback(
                SupervisorFeedback(item["value"], item.get("comment")),
                source_id="seed:" + uuid4().hex,
                task_id=self.names[item["task"]],
            )
        self.boundary = max((event.id for event in self.agent.memory.events), default=0)

    async def _during(self, stream, state_id: list[str]):
        """Apply scheduled host events once the scenario task has started."""
        actions = self.case.get("during", ())
        if not actions:
            return
        async for event in stream:
            if not state_id or event.task_id != state_id[0]:
                continue
            if event.kind == "task_started":
                break
            # A Task that ends before it starts (e.g. a rate-limited framing) gets no events.
            if event.kind in {"task_completed", "task_waiting", "task_failed", "task_cancelled"}:
                return
        for action in actions:
            await asyncio.sleep(action.get("delay_seconds", 0))
            task_id = state_id[0]
            if action["action"] == "feedback":
                self.agent.supervisor_feedback(
                    SupervisorFeedback(action["value"], action.get("comment")),
                    source_id="during:" + uuid4().hex,
                    task_id=task_id,
                )
            elif action["action"] == "cancel":
                await self.agent.cancel(task_id, reason=action["reason"])
            self.events.append({"action": action, "at": datetime.now(UTC).isoformat()})

    async def run_task(self):
        """Give the live conscious agent the scenario task, with scheduled host events."""
        options = {}
        if "deadline_minutes" in self.case:
            deadline = datetime.now(UTC) + timedelta(minutes=self.case["deadline_minutes"])
            options["deadline"] = deadline.isoformat()
        if "process" in self.case:
            options["process"] = self.case["process"]
        stream = self.agent.events()
        state_id: list[str] = []
        driver = asyncio.create_task(self._during(stream, state_id))
        try:
            async with self.agent.events() as answers:
                state = await self.agent.submit(self.fill(self.case["task"]), **options)
                state_id.append(state.id)
                self.task = await self._finish(answers, state.id)
            for _ in range(CONTINUATIONS):
                state = self.agent.tasks.get(self.task["task_id"])
                if state.status != "waiting" or not set(state.waiting_for or ()) <= RESUMABLE:
                    break
                # A user answers a used-up budget by asking the agent to go on; resume
                # reviews the allocation instead of failing the Task.
                async with self.agent.events() as answers:
                    await self.agent.resume(state.id, "Continue the task.")
                    self.task = await self._finish(answers, state.id)
        finally:
            await asyncio.wait_for(driver, 600) if self.case.get("during") else driver.cancel()
            stream.close()
        return self.task

    async def _finish(self, stream, task_id: str) -> dict:
        async for event in stream:
            if event.task_id != task_id:
                continue
            if event.kind == "answer":
                await self.agent.acknowledge_delivery(event.data["delivery_id"])
            if event.kind in {"task_completed", "task_waiting", "task_failed", "task_cancelled"}:
                return {
                    "task_id": task_id,
                    "status": self.agent.tasks.get(task_id).status,
                    "answer": self.agent._results.get(task_id, {}).get("answer", ""),
                    **json_value(event.data),
                }
        raise RuntimeError("Agent closed before delivering a task outcome")

    def tool_calls(self) -> list[dict]:
        """Conscious tool calls made during the scenario task, with their results."""
        calls, results = [], {}
        for event in self.agent.memory.events:
            output = event.output
            if event.id <= self.boundary or event.operator != "provider_event":
                continue
            if not isinstance(output, Mapping):
                continue
            data = json_value(output.get("data") or {})
            if output.get("kind") == "tool_call":
                calls.append(
                    {
                        "name": data.get("name"),
                        "arguments": data.get("arguments"),
                        "id": data.get("call_id"),
                    }
                )
            elif output.get("kind") == "tool_result":
                results[data.get("call_id")] = {
                    "status": data.get("status"),
                    "result": data.get("result"),
                    "error": data.get("error"),
                }
        return [{**call, **results.get(call["id"], {})} for call in calls]

    def program_runs(self) -> list[dict]:
        """Program runs of the scenario task, with their arguments and results."""
        names = {node.id: node.name for node in self.agent.graph.nodes(kind="program")}
        task_id = self.task["task_id"] if self.task else None
        finished = {
            event.program_run: json_value(event.output)
            for event in self.agent.memory.events
            if event.operator == "run_finished"
        }
        return [
            {
                "program": names.get(run.program, str(run.program)),
                "arguments": json_value(run.arguments),
                "status": run.status,
                "result": finished.get(run.id),
            }
            for run in self.agent.memory.runs
            if run.task_id == task_id and isinstance(run.program, int)
        ]

    def state(self) -> dict:
        """Observable outcome: task, tool use, Program runs, saved signals and aggregates."""
        agent = self.agent
        task = agent.tasks.get(self.task["task_id"]).to_dict() if self.task else None
        outcome = self.process("SelfTaskOutcome")
        start = self.now.isoformat()
        return {
            "case": self.case["id"],
            "names": self.names,
            "task": self.task,
            "task_state": task,
            "events": self.events,
            "tool_calls": self.tool_calls(),
            "program_runs": self.program_runs(),
            "outcome_evaluations": [
                result.to_dict()
                for result in agent.evaluations.all()
                if result.process_id == outcome
                and result.observed_at
                and result.observed_at >= start
            ],
            "feedback": [
                result.to_dict()
                for result in agent.evaluations.all()
                if any(s.channel == "supervisor_feedback_signal" for s in result.metric_samples)
            ],
            "conscious_steps": [
                {
                    key: json_value(event.output).get(key)
                    for key in ("disposition", "progress", "user_message")
                }
                for event in agent.memory.events
                if event.id > self.boundary
                and event.operator == "conscious_step_result"
                and isinstance(event.output, Mapping)
            ],
            "now": start,
        }

    def stats(self, processes, days_before: float, days_after: float = 0) -> dict:
        """Task outcome statistics around the session start, as the host reads them."""
        period = (
            (self.now - timedelta(days=days_before)).isoformat(),
            (datetime.now(UTC) + timedelta(days=days_after)).isoformat(),
        )
        return self.agent.task_outcome_stats(period, processes)

    def save(self, **extra):
        """Write the scenario state for inspection."""
        if self.output_dir is None:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "state.json").write_text(
            json.dumps({**self.state(), **extra}, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )


async def run_live(case: dict, home: Path, output_dir: Path | None = None) -> dict:
    """Seed the scenario, let the real agent work on its task and return the state."""
    from evertree.application import EverTree
    from evertree.core.semantics.config import SemanticConfig
    from evertree.debug_integration import load_debug_environment

    # Integration searches need Redis; each run has a private home and index namespace.
    load_debug_environment(REPOSITORY, SemanticConfig.load(home))
    async with EverTree(home) as agent:
        session = EvaluativeSession(agent, case, output_dir)
        state = None
        try:
            session.setup()
            await session.run_task()
            state = session.state()
            state["stats"] = {
                json.dumps(item, sort_keys=True): session.stats(
                    item["processes"], item.get("days_before", 1), item.get("days_after", 0)
                )
                for item in case.get("expect", ())
                if item["check"] == "stats"
            }
            return state
        finally:
            session.save(stats=(state or {}).get("stats"))


def main():
    """Run one live scenario by id and print where its artifacts are."""
    from evertree import application
    from evertree.common.logging_setup import configure_logging

    configure_logging()
    case = load_case(sys.argv[1] if len(sys.argv) > 1 else "EVL-01")
    run = REPOSITORY / "tmp" / "debug-evaluative" / uuid4().hex[:12]
    remote = run / "programs.git"
    remote.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    # A debug run never publishes to the developer's origin or needs a committed tree.
    os.environ["EVERTREE_PROGRAM_REMOTE"] = str(remote)
    application.require_committed_runtime = lambda _: None
    print(f"{case['id']}: {case['title']}\nArtifacts: {run}", flush=True)
    state = asyncio.run(run_live(case, run / "home", run))
    print(json.dumps({"task": state["task"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
