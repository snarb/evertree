"""Debug KnowledgeIntegration followed by EvidenceAssessment over several experience steps.

Run this file in PyCharm using the project interpreter and sign in to Codex.
Search settings are loaded from repository .env or the environment, as in
debug_integration.py, whose DebugSession this harness extends. Each step records its
experience, integrates it, then runs EvidenceAssessment (graph assessment, then Program
assessment) with real Codex decisions, and prints every assessed graph element's belief
and its change since the previous step. A program_run step records a live run of a
named Program in the debug task (with anchored steps and called runs) without
integrating it; later user messages and observations may then concern it.

Edit STEPS to try other cases, or pass a case id from tests/evidence/cases.json. Each run writes graph.json, trace.json, beliefs.json,
evidence.json (assessment results per step), calls.json, tools.json and model-*.md
files under tmp/debug-evidence-assessment/<run>/, also on failure.

Useful breakpoints:
- EvidenceSession.record_step: recorded user inputs, observations and analytical Notes.
- core/evidence.py GraphEvidence.pending: changed elements, grounds, related elements and
  expansion of agent reasoning into the primary experience it cites.
- graph_evidence_assessment/_exec.py run and _plan: the model batch, its judgement and the
  stance → likelihood conversion through OBSERVATION_MODEL.
- core/evidence.py GraphEvidence.record: registration, retraction and assignment.
- core/program_evidence.py ProgramEvidence.pending: runs a new source may concern and their
  cards; program_evidence_assessment/_exec.py _plan: anchor versus Program attribution.
- BeliefStore.read: dependency filtering and the shared cap on unsupported influence.
- EvidenceSession.run at `self.report(...)`: beliefs after each step.
"""

import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from evertree.common.logging_setup import configure_logging
from evertree.core.anchors import AnchorResolver, CodeAnchor
from evertree.core.beliefs import element_target
from evertree.core.cognition.tasks import TaskSpecification
from evertree.core.graph.types import GraphDelta, Node, NodeUpdate, Prototype, RelationInstance
from evertree.core.semantics.reading import fact_nodes
from evertree.core.values import json_value
from evertree.debug_integration import DebugSession, load_debug_environment
from evertree.processes.self_learning.self_evidence_assessment._exec import run as assess
from evertree.processes.self_learning.self_evidence_assessment.self_graph_evidence_assessment._exec import (
    INSTRUCTIONS,
)
from evertree.processes.self_learning.self_evidence_assessment.self_graph_evidence_assessment._exec import (
    run as assess_graph,
)
from evertree.processes.self_learning.self_evidence_assessment.self_program_evidence_assessment._exec import (
    run as assess_programs,
)
from evertree.processes.self_semantic_processing.self_knowledge_integration._exec import (
    run as integrate,
)

USER_TASK = (
    "Запомни историю работы насоса Н-1: когда он был выключен и когда работал. "
    "Сохрани состояния с их временными границами и связь каждого состояния с насосом."
)
# Each step is integrated and then assessed. kind is "user" or "observation".
STEPS = [
    {
        "kind": "user",
        "content": (
            "12 октября 2026 года насос Н-1 был выключен с 09:00 до 09:10 UTC. "
            "С 09:10 до 09:20 UTC тот же насос работал."
        ),
        "analysis": (
            "Один насос Н-1, два интервала: выключен 09:00–09:10 UTC, работает "
            "09:10–09:20 UTC 12 октября 2026 года. Сохранить оба состояния насоса."
        ),
    },
    {
        "kind": "observation",
        "content": {
            "sensor": "Н-1 ток двигателя",
            "date": "2026-10-12",
            "readings": [
                {"at": "09:12Z", "amps": 11.8},
                {"at": "09:18Z", "amps": 12.1},
            ],
        },
        "analysis": "Ток двигателя Н-1 около 12 А в 09:12 и 09:18 UTC: насос работал.",
    },
    {
        "kind": "user",
        "content": (
            "Поправка: я ошибся. Насос Н-1 был выключен только с 09:00 до 09:05 UTC, "
            "а с 09:05 UTC уже работал."
        ),
        "analysis": (
            "Пользователь исправляет своё прежнее сообщение: выключен 09:00–09:05 UTC, "
            "работает с 09:05 UTC."
        ),
    },
]

# Text-based evidence cases shared with tests/evidence; run one by id.
CASES = Path(__file__).resolve().parents[2] / "tests" / "evidence" / "cases.json"


def load_case(case_id):
    """Return (task, steps) of one case in tests/evidence/cases.json."""
    for case in json.loads(CASES.read_text(encoding="utf-8")):
        if case["id"] == case_id:
            return case["task"], case["steps"]
    raise SystemExit(f"Нет сценария {case_id} в {CASES}")


class EvidenceSession(DebugSession):
    """Run integration and evidence assessment step by step in one isolated process."""

    def __init__(
        self,
        output_dir: Path,
        *,
        timeout_seconds: float | None = None,
        task: str = USER_TASK,
        steps: list | None = None,
    ):
        super().__init__(output_dir, timeout_seconds=timeout_seconds)
        self.task, self.steps = task, steps
        # Cards shown to integration and assessment include current beliefs, as in the runtime.
        self.graph.belief_reader = self.operations.beliefs.read
        self.metadata["task_id"] = "debug-evidence-assessment"
        task = self.metadata["integration_context"]["task"]
        task["id"] = "debug-evidence-assessment"
        task["specification"] = TaskSpecification(self.task).to_dict()
        self.evidence = []
        self.previous = {}
        # Programs that program_run steps registered, by name, and whether the task
        # statement was recorded with the first experience step.
        self.programs = {}
        self.task_recorded = False
        # Beliefs after each step, for case checks.
        self.history = []

    def record_step(self, index, step):
        """Record one step's experience and optional analytical Note as integration sources."""
        run = self.memory.start_run(
            "DebugInput", "debug", {}, run_mode="evaluation", task_id=self.metadata["task_id"]
        )
        refs = []
        if not self.task_recorded:
            self.task_recorded = True
            event = self.memory.record(run, "user_input", output=self.task)
            refs.append(json_value(self.memory.output_ref(event)))
        if step["kind"] == "user":
            event = self.memory.record(run, "user_input", output=step["content"])
        else:
            # kind "observation" or "document"; source_id names the origin of the record.
            arguments = {"source_id": step.get("source_id") or f"debug-sensor:{index}"}
            if step["kind"] == "document":
                arguments["source_type"] = "document"
            event = self.memory.record(
                run, "observation", arguments=arguments, output=step["content"]
            )
        refs.append(json_value(self.memory.output_ref(event)))
        self.memory.finish_run(run)
        if step.get("analysis"):
            note = self.operations.execute(
                "memory.note",
                {"text": step["analysis"], "source_refs": refs[-1:]},
                metadata={**self.metadata, "knowledge_integration_authorized": False},
            )
            refs.append(json_value(note))
        return refs

    def program(self, step):
        """Register a step's Program, or move it to the step's revision as activation would."""
        name, revision = step["program"], step.get("revision", "a" * 40)
        identity = self.programs.get(name)
        if identity is None:
            roles = step.get("roles", ["exec"])
            process = Prototype(
                self.graph.reserve_id(),
                name + "Process",
                description=step.get("process", ""),
                properties={"process": True},
            )
            node = Node(
                self.graph.reserve_id(),
                name,
                kind="program",
                description=step.get("description", ""),
                properties={
                    "process": process.id,
                    "role": roles[0],
                    "roles": roles,
                    "slug": name.lower(),
                    "revision": revision,
                    "lifecycle_status": "active",
                },
            )
            self.graph.apply(GraphDelta(creates=(process, node)), provenance="debug-lifecycle")
            self.programs[name] = identity = node.id
        node = self.graph.get(identity)
        if node.properties["revision"] != revision:
            properties = {**node.properties, "revision": revision}
            self.graph.apply(
                GraphDelta(updates=(NodeUpdate(identity, {"properties": properties}),)),
                provenance="debug-lifecycle",
            )
        return identity

    def record_program_run(self, step, caller=None):
        """Record a live run as the application does: anchors, anchored uses, calls, result."""
        identity = self.program(step)
        caller_event = None
        if caller is not None:
            caller_event = self.memory.record(
                caller, "call_program", output={"program": identity}
            ).id
        run = self.memory.start_run(
            identity,
            "0" * 40,
            step.get("arguments", {}),
            caller_event=caller_event,
            program_revision=self.graph.get(identity).properties["revision"],
            task_id=self.metadata["task_id"],
        )
        uses = step.get("anchors", [])
        if uses:
            anchors = tuple(
                CodeAnchor(identity, op_id, "src/evertree/processes/debug/_exec.py", "0" * 40, line)
                for line, op_id in enumerate(dict.fromkeys(use[0] for use in uses), start=1)
            )
            event = self.memory.record(run, "code_anchors", output=json_value(anchors))
            AnchorResolver(self.graph).install(anchors, provenance=self.memory.output_ref(event))
            for op_id, arguments, output in uses:
                operator = self.graph.find(f"op:{identity}:{op_id}")
                self.memory.record(run, operator.id, arguments=arguments, output=output)
        for child in step.get("calls", []):
            self.record_program_run(child, caller=run)
        self.memory.record(
            run,
            "run_finished",
            output={"type": "run_finished", "result": {"result": step["result"], "feedback": None}},
        )
        self.memory.finish_run(run)

    def programs_now(self):
        """Current belief of every assessed Program revision and anchored operator."""
        names = {identity: name for name, identity in self.programs.items()}
        beliefs = self.operations.beliefs
        result = {}
        for target in beliefs.target_ids():
            if not target.startswith(("program:", "op:")):
                continue
            subject, revision = target.rsplit("@", 1)
            parts = subject.split(":")
            program, op_id = (
                names.get(int(parts[1]), parts[1]),
                parts[2] if len(parts) > 2 else None,
            )
            reading = beliefs.read(target)
            label = program + (f":{op_id}" if op_id else "") + "@" + revision
            result[label] = {
                "program": program,
                "op": op_id,
                "revision": revision,
                "strength": round(reading.strength, 3),
                "support": round(reading.support, 3),
                "evidence_count": reading.stats.evidence_count,
            }
        return result

    def profile(self, payload):
        """Assessment uses EVERTREE_EVIDENCE_MODEL when set, to compare models on one case."""
        model = os.environ.get("EVERTREE_EVIDENCE_MODEL")
        if model and payload["instructions"] == INSTRUCTIONS:
            return replace(self.config.remember, model=model)
        return super().profile(payload)

    async def call(self, program, arguments):
        """Run evidence assessment children and SemanticSearch in process."""
        if program == "graph_evidence_assessment":
            return SimpleNamespace(**await assess_graph(self, **arguments))
        if program == "program_evidence_assessment":
            return SimpleNamespace(**await assess_programs(self, **arguments))
        return await super().call(program, arguments)

    def beliefs_now(self):
        """Current belief of every assessed graph element, keyed by element id."""
        result = {}
        for node in self.graph.nodes():
            target = element_target(node)
            if not self.operations.beliefs.known(target):
                continue
            reading = self.operations.beliefs.read(target)
            result[node.id] = {
                "name": node.name,
                "kind": node.kind,
                "description": node.description,
                "text": self.element_text(node),
                "strength": round(reading.strength, 3),
                "support": round(reading.support, 3),
                "evidence_count": reading.stats.evidence_count,
                "scope": self.operations.beliefs.scope_of(target),
            }
        return result

    def origins_now(self):
        """Current reliability belief of every assessed source origin, keyed by origin id."""
        beliefs = self.operations.beliefs
        result = {}
        for target in beliefs.snapshot()["current"]:
            if target.startswith("origin:"):
                reading = beliefs.read(target)
                result[target.removeprefix("origin:")] = {
                    "reliability": round(reading.strength, 3),
                    "support": round(reading.support, 3),
                    "evidence_count": reading.stats.evidence_count,
                }
        return result

    def snapshot(self):
        """Beliefs after a step, for case checks."""
        return {
            "elements": self.beliefs_now(),
            "origins": self.origins_now(),
            "programs": self.programs_now(),
        }

    def element_text(self, node):
        """Searchable text of an element: its own text plus, for a fact, its participants."""
        parts = [node.name or "", node.description or ""]
        if isinstance(node, RelationInstance):
            parts.append(self.graph.get(node.relation_type).name)
            for identity in sorted(fact_nodes(self.graph, node)):
                other = self.graph.get(identity)
                parts.extend((other.name or "", other.description or ""))
            parts.append(json.dumps(json_value(node.args), ensure_ascii=False))
        return " ".join(parts)

    def report(self, index):
        """Print beliefs after a step, marking changes since the previous step."""
        current = self.beliefs_now()
        print(f"\nУбеждения после шага {index + 1}:")
        for identity, item in sorted(current.items()):
            before = self.previous.get(identity)
            change = (
                "новое"
                if before is None
                else f"Δstrength {item['strength'] - before['strength']:+.3f}, "
                f"Δsupport {item['support'] - before['support']:+.3f}"
            )
            label = item["description"] or item["name"]
            scope = f" [{item['scope']}]" if item["scope"] else ""
            print(
                f"  {identity} {item['kind']}{scope}: {label[:70]}\n"
                f"      strength={item['strength']} support={item['support']} "
                f"evidence={item['evidence_count']} ({change})"
            )
        self.previous = current
        for label, item in self.programs_now().items():
            print(
                f"  программа {label}: strength={item['strength']} support={item['support']} "
                f"evidence={item['evidence_count']}"
            )
        for origin, item in self.origins_now().items():
            print(
                f"  источник {origin}: надёжность={item['reliability']} evidence={item['evidence_count']}"
            )

    async def run(self):
        """Integrate and assess each step, saving artifacts even on failure."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            for index, step in enumerate(self.steps or STEPS):
                if step["kind"] == "program_run":
                    print(f"\n=== Шаг {index + 1}: запуск {step['program']} ===", flush=True)
                    self.record_program_run(step)
                    self.history.append(self.snapshot())
                    continue
                print(f"\n=== Шаг {index + 1}: {step['kind']} ===\n{step['content']}", flush=True)
                self.metadata["integration_operation_id"] = f"evidence-debug-step-{index + 1}"
                refs = self.record_step(index, step)
                outcome = await integrate(self, refs)
                print(f"  записей интеграции: {len(outcome['result']['writes'])}")
                assessed = await assess(self, refs)
                self.evidence.append(assessed["result"])
                graph = assessed["result"]["graph"]
                print(
                    f"  оценено: {len(graph['assessed'])}, "
                    f"не решено: {len(graph['unresolved'])}, осталось: {graph['remaining']}"
                )
                programs = assessed["result"]["programs"]
                print(
                    f"  программ оценено: {len(programs['assessed'])}, "
                    f"не решено: {len(programs['unresolved'])}"
                )
                self.report(index)
                self.history.append(self.snapshot())
            return self.beliefs_now()
        finally:
            try:
                for name, value in {
                    "graph": self.graph.snapshot(),
                    "trace": self.memory.snapshot(),
                    "beliefs": self.operations.beliefs.snapshot(),
                    "evidence": self.evidence,
                    "calls": self.calls,
                    "tools": self.tool_calls(),
                }.items():
                    (self.output_dir / f"{name}.json").write_text(
                        json.dumps(json_value(value), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            finally:
                try:
                    await self.index.close()
                finally:
                    await self.provider.close()


def main():
    """Run the configured steps and print the artifact directory."""
    configure_logging()
    repository = Path(__file__).resolve().parents[2]
    output_dir = repository / "tmp" / "debug-evidence-assessment" / uuid4().hex[:12]
    task, steps = load_case(sys.argv[1]) if len(sys.argv) > 1 else (USER_TASK, None)
    session = EvidenceSession(output_dir, task=task, steps=steps)
    load_debug_environment(repository, session.config)
    missing = [
        name
        for name in (session.config.redis_url_env, session.config.openai_key_env)
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit("Для штатного поиска задайте в .env или PyCharm: " + ", ".join(missing))
    print(f"Codex: {session.config.remember.model}, {session.config.remember.effort}")
    if os.environ.get("EVERTREE_EVIDENCE_MODEL"):
        print(f"Оценка свидетельств: {os.environ['EVERTREE_EVIDENCE_MODEL']}")
    print(f"Артефакты: {output_dir}", flush=True)
    asyncio.run(session.run())
    print(f"\nГраф, trace и убеждения сохранены в {output_dir}")


if __name__ == "__main__":
    main()
