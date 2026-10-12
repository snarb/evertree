"""Run in PyCharm with the project's .venv interpreter; no arguments are required.

Offline by default: only model decisions and the search index are substituted.
Use --live for real Codex model decisions (signed-in account, consumes model usage).
Program orchestration, trace, validation, graph mutations and receipts are real,
in one process. This isolated harness does not run the application coordinator,
worker admission, Redis, native sandbox or durable application recovery.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from evertree.core.attribution import AttributionRuntime
from evertree.core.beliefs import BeliefStore
from evertree.core.codex.provider import CodexProvider
from evertree.core.cognition.tasks import TaskSpecification
from evertree.core.evaluation.store import EvaluationStore
from evertree.core.graph.store import GraphStore
from evertree.core.learning.state import LearningStore
from evertree.core.memory.store import TraceStore
from evertree.core.operations import CoreOperations, authorize_operation
from evertree.core.provider import AgentRequest
from evertree.core.semantics.config import SemanticConfig
from evertree.core.semantics.service import SemanticService
from evertree.core.values import json_value
from evertree.processes.semantic_processing.knowledge_integration._exec import run as integrate
from evertree.processes.semantic_processing.semantic_search._model import run as search

# Edit these three texts to explore a different experience in --live mode.
USER_TASK = (
    "Запомни историю работы насоса Н-1: когда он был выключен и когда работал. "
    "Сохрани состояния с их временными границами и связь каждого состояния с насосом."
)
INPUT_TEXT = (
    "12 октября 2026 года насос Н-1 был выключен с 09:00 до 09:10 UTC. "
    "С 09:10 до 09:20 UTC тот же насос работал. После 09:20 наблюдений нет."
)
CONSCIOUS_ANALYSIS = (
    "В абзаце описан один насос Н-1, а не два разных объекта. Менялось его рабочее "
    "состояние: выключен с 09:00 до 09:10 UTC, работает с 09:10 до 09:20 UTC "
    "12 октября 2026 года. Для задачи важны оба интервала и их принадлежность "
    "одному насосу. Сохранить эту историю; после 09:20 состояние неизвестно. "
    "Причина включения не указана, поэтому причинную связь пока не утверждаю. "
    "Это промежуточный разбор: при новых наблюдениях история будет продолжена."
)


class ExhaustiveDebugIndex:
    """Return the entire tiny graph in both channels; no embeddings or ranking."""

    async def lexical(self, nodes, query, kind):
        return [node["id"] for node in nodes if kind is None or node["kind"] == kind]

    vector = lexical


def scripted_decision(material, graph):
    """Fixed model response for this example; deliberately not a text extractor."""
    schema = {name: graph.lookup(name)[0].id for name in ("IDENTITY_TYPE", "STATE_IDENTITY")}
    creates = [
        {"id": -1, "kind": "prototype", "name": "Насос", "description": "Класс насосов"},
        {"id": -2, "kind": "instance", "name": "Насос Н-1"},
        {
            "id": -3,
            "kind": "facet",
            "name": "Н-1: выключен 12 октября 09:00–09:10 UTC",
            "description": "По сообщению пользователя насос выключен в этом интервале.",
            "valid_from": "2026-10-12T09:00:00+00:00",
            "valid_until": "2026-10-12T09:10:00+00:00",
        },
        {
            "id": -4,
            "kind": "facet",
            "name": "Н-1: работает 12 октября 09:10–09:20 UTC",
            "description": "По сообщению пользователя насос работает в этом интервале.",
            "valid_from": "2026-10-12T09:10:00+00:00",
            "valid_until": "2026-10-12T09:20:00+00:00",
        },
        {
            "id": -5,
            "kind": "relation_instance",
            "name": "IDENTITY_TYPE",
            "relation_type": schema["IDENTITY_TYPE"],
            "args": {"instance": -2, "type": -1},
        },
        *[
            {
                "id": identity,
                "kind": "relation_instance",
                "name": "STATE_IDENTITY",
                "relation_type": schema["STATE_IDENTITY"],
                "args": {"facet": facet, "instance": -2},
            }
            for identity, facet in ((-6, -3), (-7, -4))
        ],
        {"id": -8, "kind": "note", "name": "Разбор истории Н-1", "description": CONSCIOUS_ANALYSIS},
    ]
    task_ref, source_ref, note_ref = [item["reference"] for item in material["experience"]]
    decisions = [
        {
            "disposition": "trace_only",
            "reason": "Задание задаёт цель отбора; само по себе не является фактом о насосе.",
            "source_refs": [task_ref],
            "affected_ids": [],
        },
        {
            "disposition": "materialize",
            "reason": "Один объект и два явно ограниченных во времени состояния из абзаца.",
            "source_refs": [source_ref],
            "affected_ids": list(range(-1, -8, -1)),
        },
        {
            "disposition": "materialize",
            "reason": "Сохранить промежуточный разбор и ограничения без повышения belief.",
            "source_refs": [note_ref],
            "affected_ids": [-8],
            "preservation_ids": [
                item["id"] for item in material["context"]["preservation_intents"]
            ],
        },
    ]
    return {
        "action": "commit",
        "query": "",
        "delta_json": json.dumps({"creates": creates}, ensure_ascii=False),
        "decisions_json": json.dumps(decisions, ensure_ascii=False),
        "summary": "Сохранить один насос, два состояния, три связи и аналитическую Note.",
    }


class DebugSession:
    """Inspect graph, memory, calls, experience_refs and receipt in the debugger."""

    def __init__(self, output_dir: Path, *, live=False):
        self.output_dir = output_dir
        self.config = SemanticConfig()
        self.graph, self.memory, beliefs = GraphStore(), TraceStore(), BeliefStore()
        self.graph.bootstrap(provenance="debug-bootstrap")
        self.seed_ids = {node.id for node in self.graph.nodes()}
        attribution = AttributionRuntime(self.graph, beliefs)
        self.operations = CoreOperations(
            self.graph, self.memory, beliefs, attribution, EvaluationStore(), LearningStore(), set()
        )
        self.service = SemanticService(
            self.graph,
            self.memory,
            attribution,
            self.config,
            ExhaustiveDebugIndex(),
            self.operations,
        )
        revision = hashlib.sha256(Path(integrate.__code__.co_filename).read_bytes()).hexdigest()
        self.metadata = {
            "task_id": "debug-pump-history",
            "run_id": "debug-integration-run",
            "run_mode": "evaluation",
            "program": {"role": "exec", "revision": revision},
            # The host grants this only to the isolated integration call below.
            "knowledge_integration_authorized": True,
            "integration_operation_id": "pump-history-step-1",
            "integration_context": {
                "task": {
                    "id": "debug-pump-history",
                    "specification": TaskSpecification(USER_TASK).to_dict(),
                },
                "values": [
                    {
                        "name": "EpistemicQuality",
                        "description": "Сохранять основания и неопределённость.",
                        "origin": "debug configuration",
                    }
                ],
                "self": [],
            },
        }
        self.provider = CodexProvider(state_dir=output_dir / "codex") if live else None
        self.calls = []
        self.experience_refs = []
        self.receipt = None

    def record_experience(self):
        run = self.memory.start_run("DebugUserInput", "debug", {}, run_mode="evaluation")
        for text in (USER_TASK, INPUT_TEXT):
            event = self.memory.record(run, "user_input", output=text)
            self.experience_refs.append(json_value(self.memory.output_ref(event)))
        self.memory.finish_run(run)
        note_ref = self.operations.execute(
            "memory.note",
            {"text": CONSCIOUS_ANALYSIS, "source_refs": self.experience_refs[1:], "preserve": True},
            metadata={**self.metadata, "knowledge_integration_authorized": False},
        )
        self.experience_refs.append(note_ref)

    async def model(self, payload):
        if self.provider is None:
            return scripted_decision(json.loads(payload["prompt"])["material"], self.graph)
        parsed = None
        async for event in self.provider.run(
            uuid4().hex,
            AgentRequest(
                payload["prompt"],
                self.output_dir,
                instructions=payload["instructions"],
                output_schema=payload["output_schema"],
                model=self.config.remember.model,
                effort=self.config.remember.effort,
                timeout_seconds=120,
            ),
        ):
            if event.kind == "error":
                raise RuntimeError(event.data)
            if event.kind == "completed":
                parsed = event.data.get("parsed")
        if not isinstance(parsed, dict):
            raise TypeError("Модель не вернула структурированный результат; см. calls.json")
        return parsed

    async def step(self, method, payload, *, role="exec"):
        authorize_operation(method, role)
        call = {"method": method, "payload": json_value(payload)}
        self.calls.append(call)
        print(f"  → {method}", flush=True)
        metadata = {
            **self.metadata,
            "program": {**self.metadata["program"], "role": role},
            "knowledge_integration_authorized": role == "exec",
        }
        try:
            if method == "agent.run":
                result = {"parsed": await self.model(payload)}
            elif method.startswith("semantic."):
                result = await self.service.execute(method, payload, metadata)
            else:
                result = self.operations.execute(method, payload, metadata=metadata)
            call["result"] = json_value(result)
            return result
        except Exception as exc:
            call["error"] = repr(exc)
            raise

    async def call(self, program, arguments):
        if program != "semantic_search":
            raise ValueError(f"Unsupported debug child: {program}")

        async def read(method, payload):
            return await self.step(method, payload, role="model")

        return SimpleNamespace(**await search(SimpleNamespace(step=read), **arguments))

    async def run(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.record_experience()
            outcome = await integrate(
                self, self.experience_refs
            )  # Start stepping into the Program here.
            self.receipt = outcome["result"]
            if not self.receipt.get("complete"):
                raise RuntimeError(f"Интеграция не завершена: {self.receipt}")
            created = [
                json_value(node) for node in self.graph.nodes() if node.id not in self.seed_ids
            ]
            # Breakpoint here: inspect created, self.receipt, self.graph and self.memory.
            return created
        finally:
            for name, value in {
                "graph": self.graph.snapshot(),
                "trace": self.memory.snapshot(),
                "receipt": self.receipt,
                "calls": self.calls,
            }.items():
                (self.output_dir / f"{name}.json").write_text(
                    json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            if self.provider:
                await self.provider.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Решения реальной модели через Codex")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    output_dir = repository / "tmp" / "debug-integration" / uuid4().hex[:12]
    session = DebugSession(output_dir, live=args.live)
    print(f"Режим: {'реальная модель' if args.live else 'заданные решения модели'}")
    print(f"Задание: {USER_TASK}\nАбзац: {INPUT_TEXT}\nАнализ: {CONSCIOUS_ANALYSIS}")
    print(f"Артефакты: {output_dir}", flush=True)
    created = asyncio.run(session.run())
    print("\nСозданные объекты:")
    for node in created:
        print(f"  {node['id']}: {node['kind']} — {node['name']}")
    print(f"\nReceipt: {session.receipt['status']}. Граф и trace сохранены в {output_dir}")


if __name__ == "__main__":
    main()
