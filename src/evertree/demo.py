"""A repeatable Program evolution demonstration.

Run ``python -m evertree.demo --home .state/demo`` on Windows. The default
provider is explicitly scripted and makes no paid model calls, while Programs
still run in real AppContainer workers and DBOS workflows. ``--live`` uses the
configured Codex SDK, local authentication and Luna/high, and can consume usage.

The sorting domain exists only in this example, never in the bootstrap graph.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from .application import EverTree
from .core.codex_provider import CodexProvider
from .core.datasets import EvaluationCase
from .core.provider import AgentEvent, AgentRequest, ProviderError
from .core.runtime import Runtime


class DemoProvider:
    """Explicit offline fixture that exercises the ordinary provider/tool boundary."""

    name = "demo-scripted"

    def __init__(
        self, *, stage: str, program_id: int, git_path: str, candidate: dict[str, Any] | None = None
    ):
        self.stage, self.program_id, self.git_path = stage, program_id, git_path
        self.candidate = candidate
        self.calls: list[dict[str, Any]] = []
        self.requests: list[AgentRequest] = []
        self.cancelled: set[str] = set()
        self.last_result: list[int] | None = None
        self.observed_incident: list[int] | None = None

    async def run(self, request_id, request, *, tool_handler=None, approval_handler=None):
        self.requests.append(request)
        yield AgentEvent("session", {"provider": self.name, "id": request_id})
        if request_id in self.cancelled:
            yield AgentEvent("cancelled")
            return
        if request.native_coding:
            if (
                self.candidate is None
                or request.workspace.resolve() != Path(self.candidate["workspace"]).resolve()
            ):
                raise ProviderError("Demo coding must stay in the isolated candidate workspace")
            destination = (request.workspace / self.git_path).resolve()
            if not destination.is_relative_to(request.workspace.resolve()):
                raise ProviderError("Invalid candidate path")
            destination.parent.mkdir(parents=True, exist_ok=True)
            expression = "sorted(set(values))" if self.stage == "initial" else "sorted(values)"
            source = (
                '"""Return ascending input values in the evaluated domain."""\n\n'
                "def run(values: list[int]):\n"
                "    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):\n"
                '        raise ValueError("Expected integer values")\n'
                f'    return {{"result": {expression}, "feedback": None}}\n'
            )
            destination.write_text(source, encoding="utf-8")
            tests = request.workspace / "tests"
            tests.mkdir(exist_ok=True)
            examples = [([9, 2, 5], [2, 5, 9]), ([], [])]
            if self.stage != "initial":
                examples.append(([3, 1, 3], [1, 3, 3]))
            (tests / "test_sort_values.py").write_text(
                "import importlib.util, pathlib, unittest\n"
                f"path = pathlib.Path(__file__).parents[1] / {self.git_path!r}\n"
                "spec = importlib.util.spec_from_file_location('sorting', path)\n"
                "program = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(program)\n"
                "class SortTests(unittest.TestCase):\n"
                "    def test_examples(self):\n"
                f"        for values, expected in {examples!r}:\n"
                "            with self.subTest(values=values):\n"
                "                self.assertEqual(program.run(values)['result'], expected)\n",
                encoding="utf-8",
            )
            yield AgentEvent("file_change", {"path": str(destination), "kind": "candidate"})
            yield AgentEvent(
                "completed",
                {
                    "text": "Implemented candidate; protected evaluation is still required.",
                    "parsed": None,
                },
            )
            return
        properties = (request.output_schema or {}).get("properties", {})
        if "execution_budget" in properties:
            payload = {
                "objective": "Develop the sorting skill"
                if self.stage != "reuse"
                else "Reuse the verified sorting skill",
                "success_criteria": [
                    "The actual Program output matches the requested sorted sequence"
                ],
                "constraints": [
                    "Change only the candidate workspace; use protected evaluation and acceptance"
                ],
                "preferences": ["Use the simplest sufficient implementation"],
                "execution_budget": {"active_time_minutes": 8 if self.stage != "reuse" else 2},
                "self_improvement_budget": 90 if self.stage != "reuse" else 0,
                "budget_reason": "Small deterministic demonstration with independent native executions",
            }
        elif "verified" in properties:
            expected = [2, 5, 9] if self.stage == "initial" else [1, 3, 3]
            payload = {
                "verified": self.last_result == expected,
                "reason": "Verified against the actual Program result and requested sequence",
            }
        else:
            if request.mode != "exec" or tool_handler is None:
                raise ProviderError("Demo needs an executing consciousness with declared tools")

            async def call(name, arguments):
                if name not in {tool.name for tool in request.tools}:
                    raise ProviderError("Demo attempted an undeclared tool: " + name)
                output = await tool_handler(name, arguments)
                self.calls.append({"name": name, "arguments": arguments, "result": output})
                return output

            if self.stage == "improvement":
                arguments = {"program": self.program_id, "arguments": {"values": [3, 1, 3]}}
                yield AgentEvent("tool_call", {"name": "run_program", "arguments": arguments})
                incident = await call("run_program", arguments)
                self.observed_incident = incident["result"]
                yield AgentEvent("tool_result", {"name": "run_program", "result": incident})
                if self.observed_incident != [1, 3]:
                    raise ProviderError(
                        "The demonstration did not reproduce the expected domain-expansion incident"
                    )
                arguments = {
                    "program": self.program_id,
                    "claim": "Removing the set conversion preserves repeated observations without changing order semantics",
                }
                yield AgentEvent("tool_call", {"name": "create_candidate", "arguments": arguments})
                self.candidate = await call("create_candidate", arguments)
                yield AgentEvent(
                    "tool_result", {"name": "create_candidate", "result": self.candidate}
                )
            if self.stage != "reuse":
                if self.candidate is None:
                    raise ProviderError("No inactive candidate was prepared")
                for name, arguments in (
                    (
                        "develop_candidate",
                        {
                            "candidate": self.candidate["id"],
                            "instruction": "Implement ascending integer sorting in the declared Program path. "
                            + (
                                "The evaluated initial domain contains distinct values."
                                if self.stage == "initial"
                                else "Extend the contract to repeated values and preserve every occurrence."
                            ),
                        },
                    ),
                    ("evaluate_candidate", {"candidate": self.candidate["id"]}),
                    (
                        "choose_candidate",
                        {
                            "candidate": self.candidate["id"],
                            "decision": "merge_branch",
                            "reason": "The independent fixed acceptance criteria passed for this exact committed revision",
                        },
                    ),
                ):
                    yield AgentEvent("tool_call", {"name": name, "arguments": arguments})
                    output = await call(name, arguments)
                    yield AgentEvent("tool_result", {"name": name, "result": output})
                    if name == "evaluate_candidate" and output.get("status") != "evaluated":
                        raise ProviderError("Candidate evaluation remained unresolved")
            values = [9, 2, 5] if self.stage == "initial" else [3, 1, 3]
            arguments = {"program": self.program_id, "arguments": {"values": values}}
            yield AgentEvent("tool_call", {"name": "run_program", "arguments": arguments})
            result = await call("run_program", arguments)
            self.last_result = result["result"]
            yield AgentEvent("tool_result", {"name": "run_program", "result": result})
            if self.last_result != sorted(values):
                raise ProviderError("Actual execution did not satisfy the demonstration objective")
            payload = {
                "status": "completed",
                "answer": json.dumps(self.last_result),
                "progress": "The accepted Program was executed and its result checked",
            }
        yield AgentEvent("completed", {"text": json.dumps(payload), "parsed": payload})

    async def cancel(self, request_id):
        self.cancelled.add(request_id)

    async def doctor(self):
        return {"provider": self.name, "available": True, "offline": True}

    async def close(self):
        pass


def _dataset(agent: EverTree, *, repeated: bool):
    prefix = "expanded-domain" if repeated else "initial-domain"
    examples = (
        [([4, 2, 4, 1], [1, 2, 4, 4]), ([5, 5], [5, 5])]
        if repeated
        else [
            ([7, 1, 4], [1, 4, 7]),
            ([-2, 8, 0], [-2, 0, 8]),
        ]
    )
    cases = [
        EvaluationCase(
            f"{prefix}-{index}",
            {"values": values},
            expected,
            "exact",
            (f"developer-heldout:{prefix}:{index}",),
        )
        for index, (values, expected) in enumerate(examples)
    ]
    return agent.datasets.create(prefix, cases, target_metrics=("accuracy",))


async def run_demo(
    home: str | Path, *, live: bool = False, runtime_factory=Runtime
) -> dict[str, Any]:
    """Run two accepted revisions and prove reuse after an actual close/reopen."""
    home = Path(home).resolve()
    seed_provider = (
        CodexProvider() if live else DemoProvider(stage="initial", program_id=0, git_path="")
    )
    reports: list[dict[str, Any]] = []
    async with EverTree(home, provider=seed_provider, runtime_factory=runtime_factory) as agent:
        if agent.graph.find("SortValues") is not None:
            raise ValueError("Demo home already contains SortValues; choose a fresh --home")
        proposal = agent.propose_program(
            "SortValues",
            role="exec",
            claim="Ascending sorting can be implemented as a compact reusable deterministic Program",
            description="Sort integer values ascending; initial verification covers distinct inputs",
        )
        program = proposal["program"]
        identity, path = program["id"], program["properties"]["git_path"]
        initial_dataset = _dataset(agent, repeated=False)
        agent.bind_evaluation(identity, initial_dataset.revision)
        if not live:
            seed_provider.program_id, seed_provider.git_path = identity, path
            seed_provider.candidate = proposal["candidate"]
        initial_request = (
            f"Develop candidate {proposal['candidate']['id']} for Program {identity} at {path}. "
            "Implement sorting distinct integers ascending with sorted(set(values)); initial scope explicitly excludes duplicates. "
            "First use develop_candidate to implement the Program, then evaluate_candidate to run the protected checks. "
            "Only after evaluation passes, use choose_candidate with merge_branch. "
            "Then run_program with values [9,2,5]. Return the actual output. The independent evaluation is already bound."
        )
        initial = await agent.run(initial_request)
        if initial["status"] != "succeeded":
            raise RuntimeError("Initial skill development failed: " + json.dumps(initial))
        first_revision = agent.graph.get(identity).properties["revision"]
        reports.append(
            {
                "task": initial["task_id"],
                "answer": initial["answer"],
                "revision": first_revision,
                "dataset": initial_dataset.revision,
            }
        )
        expanded_dataset = _dataset(agent, repeated=True)
        agent.bind_evaluation(identity, expanded_dataset.revision)
        improved_provider = (
            CodexProvider()
            if live
            else DemoProvider(stage="improvement", program_id=identity, git_path=path)
        )
        await agent.provider.close()
        agent.provider = improved_provider
        improved = await agent.run(
            f"Extend Program {identity} to preserve duplicates. First run_program with values [3,1,3] and inspect the failure. "
            "Create a candidate with a claim explaining the loss from set conversion, develop it using sorted(values), "
            "evaluate against the new independently bound dataset, choose_candidate only after protected acceptance, "
            "and run the accepted Program again with [3,1,3]. Preserve the returned observations in trace."
        )
        if improved["status"] != "succeeded":
            raise RuntimeError("Skill improvement failed: " + json.dumps(improved))
        second_revision = agent.graph.get(identity).properties["revision"]
        if second_revision == first_revision:
            raise RuntimeError("No new accepted revision was activated")
        reports.append(
            {
                "task": improved["task_id"],
                "answer": improved["answer"],
                "revision": second_revision,
                "dataset": expanded_dataset.revision,
            }
        )
        await agent._pump
        before_restart = {
            "events": len(agent.memory.events),
            "learning": agent.learning.statistics("verified_task_rate"),
        }
        offline_calls = [] if live else seed_provider.calls + improved_provider.calls
        incident = None if live else improved_provider.observed_incident
    reused_provider = (
        CodexProvider() if live else DemoProvider(stage="reuse", program_id=identity, git_path=path)
    )
    async with EverTree(
        home, provider=reused_provider, runtime_factory=runtime_factory
    ) as restored:
        if restored.graph.get(identity).properties["revision"] != second_revision:
            raise RuntimeError("Restart did not retain the accepted code revision")
        retained = len(restored.memory.events)
        if retained < before_restart["events"]:
            raise RuntimeError("Restart lost retained experience")
        reused = await restored.run(
            f"Use the existing accepted Program {identity} via run_program to sort [3,1,3]. "
            "Do not create or change code. Return the actual result, preserving duplicates."
        )
        if reused["status"] != "succeeded":
            raise RuntimeError("Restart reuse failed: " + json.dumps(reused))
        final_learning = restored.learning.statistics("verified_task_rate")
        if final_learning["observed_count"] < 3:
            raise RuntimeError(
                "Verified task outcomes were not learned through the standard pipeline"
            )
        if not live:
            offline_calls += reused_provider.calls
            if reused_provider.last_result != [1, 3, 3]:
                raise RuntimeError("Restored Program did not preserve duplicates")
        return {
            "provider": "codex-live" if live else "demo-scripted",
            "home": str(home),
            "program_id": identity,
            "stages": reports,
            "incident": incident,
            "restart": {
                "task": reused["task_id"],
                "answer": reused["answer"],
                "revision": second_revision,
                "retained_events": retained,
            },
            "learning": final_learning,
            "tool_calls": [call["name"] for call in offline_calls],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(".state/demo"))
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use authenticated Codex/Luna/high (consumes model usage)",
    )
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(run_demo(args.home, live=args.live))
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
