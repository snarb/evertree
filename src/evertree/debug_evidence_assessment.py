"""Debug KnowledgeIntegration followed by EvidenceAssessment over several experience steps.

Run this file in PyCharm using the project interpreter and sign in to Codex.
Search settings are loaded from repository .env or the environment, as in
debug_integration.py, whose DebugSession this harness extends. Each step records its
experience, integrates it, then runs EvidenceAssessment (graph assessment, then the
Program assessment placeholder) with real Codex decisions, and prints every assessed
graph element's belief and its change since the previous step.

Edit STEPS to try other cases. Each run writes graph.json, trace.json, beliefs.json,
evidence.json (assessment results per step), calls.json, tools.json and model-*.md
files under tmp/debug-evidence-assessment/<run>/, also on failure.

Useful breakpoints:
- EvidenceSession.record_step: recorded user inputs, observations and analytical Notes.
- core/evidence.py GraphEvidence.pending: changed elements, grounds, related elements and
  expansion of agent reasoning into the primary experience it cites.
- graph_evidence_assessment/_exec.py run and _plan: the model batch, its judgement and the
  stance → likelihood conversion through OBSERVATION_MODEL.
- core/evidence.py GraphEvidence.record: registration, retraction and assignment.
- BeliefStore.read: dependency filtering and the shared cap on unsupported influence.
- EvidenceSession.run at `self.report(...)`: beliefs after each step.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from evertree.common.logging_setup import configure_logging
from evertree.core.beliefs import element_target
from evertree.core.values import json_value
from evertree.debug_integration import DebugSession, load_debug_environment
from evertree.processes.learning.evidence_assessment._exec import run as assess
from evertree.processes.learning.evidence_assessment.graph_evidence_assessment._exec import (
    run as assess_graph,
)
from evertree.processes.learning.evidence_assessment.program_evidence_assessment._exec import (
    run as assess_programs,
)
from evertree.processes.semantic_processing.knowledge_integration._exec import run as integrate

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

# Other scenarios: python -m evertree.debug_evidence_assessment <name>. Each is (task, steps).
SCENARIOS = {
    "location": (
        "Запомни, где находится насос Н-2: сохрани его местоположение как отдельное состояние.",
        [
            {
                "kind": "user",
                "content": "Насос Н-2 находится в цехе 3.",
                "analysis": "Пользователь сообщает, что насос Н-2 находится в цехе 3.",
            },
            {
                "kind": "observation",
                "content": {"scanner": "инвентаризация", "asset": "Н-2", "zone": "цех 3"},
                "analysis": "Инвентаризационный сканер независимо видит Н-2 в цехе 3.",
            },
            {
                "kind": "user",
                "content": "Как я уже говорил, Н-2 стоит в третьем цехе.",
                "analysis": "Пользователь повторяет, что Н-2 стоит в цехе 3.",
            },
            {
                "kind": "observation",
                "content": {
                    "scanner": "RFID-ворота",
                    "asset": "Н-2",
                    "zone": "цех 5",
                    "at": "10:00Z",
                },
                "analysis": "RFID-ворота фиксируют Н-2 в цехе 5.",
            },
            {
                "kind": "user",
                "content": "Кажется, Н-2 могли перевезти в цех 5, но я не уверен.",
                "analysis": "Пользователь неуверенно предполагает, что Н-2 перевезли в цех 5.",
            },
        ],
    ),
}


class EvidenceSession(DebugSession):
    """Run integration and evidence assessment step by step in one isolated process."""

    def __init__(
        self,
        output_dir: Path,
        *,
        timeout_seconds: float | None = None,
        scenario: str | None = None,
    ):
        super().__init__(output_dir, timeout_seconds=timeout_seconds)
        self.task, self.steps = SCENARIOS[scenario] if scenario else (USER_TASK, None)
        self.metadata["task_id"] = "debug-evidence-assessment"
        self.metadata["integration_context"]["task"]["id"] = "debug-evidence-assessment"
        self.evidence = []
        self.previous = {}

    def record_step(self, index, step):
        """Record one step's experience and optional analytical Note as integration sources."""
        run = self.memory.start_run("DebugInput", "debug", {}, run_mode="evaluation")
        refs = []
        if index == 0:
            event = self.memory.record(run, "user_input", output=self.task)
            refs.append(json_value(self.memory.output_ref(event)))
        if step["kind"] == "user":
            event = self.memory.record(run, "user_input", output=step["content"])
        else:
            event = self.memory.record(
                run,
                "observation",
                arguments={"source_id": f"debug-sensor:{index}"},
                output=step["content"],
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
            try:
                self.operations.beliefs.target(target)
            except KeyError:
                continue
            reading = self.operations.beliefs.read(target)
            result[node.id] = {
                "name": node.name,
                "kind": node.kind,
                "description": node.description,
                "strength": round(reading.strength, 3),
                "support": round(reading.support, 3),
                "evidence_count": reading.stats.evidence_count,
            }
        return result

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
            print(
                f"  {identity} {item['kind']}: {label[:70]}\n"
                f"      strength={item['strength']} support={item['support']} "
                f"evidence={item['evidence_count']} ({change})"
            )
        self.previous = current

    async def run(self):
        """Integrate and assess each step, saving artifacts even on failure."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            for index, step in enumerate(self.steps or STEPS):
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
                self.report(index)
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
    session = EvidenceSession(output_dir, scenario=sys.argv[1] if len(sys.argv) > 1 else None)
    load_debug_environment(repository, session.config)
    missing = [
        name
        for name in (session.config.redis_url_env, session.config.openai_key_env)
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit("Для штатного поиска задайте в .env или PyCharm: " + ", ".join(missing))
    print(f"Codex: {session.config.remember.model}, {session.config.remember.effort}")
    print(f"Артефакты: {output_dir}", flush=True)
    asyncio.run(session.run())
    print(f"\nГраф, trace и убеждения сохранены в {output_dir}")


if __name__ == "__main__":
    main()
