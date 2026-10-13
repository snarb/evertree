"""Debug KnowledgeIntegration.exec in-process with real Codex decisions and search.

Run this file in PyCharm using the project interpreter and sign in to Codex.
Search settings are loaded from repository .env or the environment.
Only the input experience below is supplied; the model chooses all semantic actions.
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from dotenv import dotenv_values

from evertree.core.attribution import AttributionRuntime
from evertree.core.beliefs import BeliefStore
from evertree.core.codex.provider import CodexProvider
from evertree.core.cognition.tasks import TaskSpecification
from evertree.core.evaluation.store import EvaluationStore
from evertree.core.graph.store import GraphStore
from evertree.core.learning.state import LearningStore
from evertree.core.memory.store import TraceStore
from evertree.core.operations import CoreOperations, authorize_operation
from evertree.core.provider import AgentRequest, ToolDefinition
from evertree.core.runtime.agents import ProgramAgents, run_agent
from evertree.core.semantics.config import SemanticConfig
from evertree.core.semantics.index import RedisSearchIndex
from evertree.core.semantics.service import SemanticService
from evertree.core.values import json_value
from evertree.processes.semantic_processing.knowledge_integration._exec import run as integrate
from evertree.processes.semantic_processing.semantic_search._model import run as search

# Edit these inputs; KnowledgeIntegration chooses their graph representation.
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


def load_debug_environment(repository: Path, config: SemanticConfig):
    names = (config.redis_url_env, config.openai_key_env, "EVERTREE_TEST_REDIS_URL")
    path = repository / ".env"
    if path.is_file():
        values = dotenv_values(path, interpolate=False)
        for name in names:
            if values.get(name):
                os.environ.setdefault(name, values[name])
    # This harness has private graph/index state, so the configured test Redis is suitable.
    if os.environ.get("EVERTREE_TEST_REDIS_URL"):
        os.environ.setdefault(config.redis_url_env, os.environ["EVERTREE_TEST_REDIS_URL"])


class DebugSession:
    """Inspect graph, memory, calls, experience_refs and recorded writes in the debugger."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.config = SemanticConfig.load(Path(__file__).resolve().parents[2])
        self.graph, self.memory, beliefs = GraphStore(), TraceStore(), BeliefStore()
        self.graph.bootstrap(provenance="debug-bootstrap")
        self.seed_ids = {node.id for node in self.graph.nodes()}
        attribution = AttributionRuntime(self.graph, beliefs)
        self.operations = CoreOperations(
            self.graph, self.memory, beliefs, attribution, EvaluationStore(), LearningStore(), set()
        )
        self.index = RedisSearchIndex(self.config, output_dir)
        self.service = SemanticService(
            self.graph,
            self.memory,
            attribution,
            self.config,
            self.index,
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
        self.run_id = self.metadata["run_id"]
        self.agents = ProgramAgents(self._model_gateway)
        self.provider = CodexProvider(state_dir=output_dir / "codex")
        self.calls = []
        self.experience_refs = []
        self.result = None

    def record_experience(self):
        run = self.memory.start_run("DebugUserInput", "debug", {}, run_mode="evaluation")
        for text in (USER_TASK, INPUT_TEXT):
            event = self.memory.record(run, "user_input", output=text)
            self.experience_refs.append(json_value(self.memory.output_ref(event)))
        self.memory.finish_run(run)
        note_ref = self.operations.execute(
            "memory.note",
            {"text": CONSCIOUS_ANALYSIS, "source_refs": self.experience_refs[1:]},
            metadata={**self.metadata, "knowledge_integration_authorized": False},
        )
        self.experience_refs.append(note_ref)

    async def agent(self, payload, **kwargs):
        return await run_agent(self, payload, **kwargs)

    async def _model_gateway(self, method, payload):
        if method != "agent.run":
            raise ValueError("Unexpected native model gateway operation")
        payload = dict(payload)
        handler = payload.pop("_tool_handler")
        payload.pop("_runtime")
        return await self.step(method, payload, tool_handler=handler)

    async def model(self, payload, *, tool_handler=None):
        request_name = f"model-{len(self.calls):03d}"
        (self.output_dir / f"{request_name}.md").write_text(
            payload["instructions"]
            + "\n\n# Current input\n\n```json\n"
            + payload["prompt"]
            + "\n```\n\n# Native tools\n\n```json\n"
            + json.dumps(payload.get("tools", []), ensure_ascii=False, indent=2)
            + "\n```\n",
            encoding="utf-8",
        )
        events, result = [], None
        request_id = uuid4().hex
        try:
            async for event in self.provider.run(
                request_id,
                AgentRequest(
                    payload["prompt"],
                    self.output_dir,
                    instructions=payload["instructions"],
                    mode=payload.get("mode", "model"),
                    tools=tuple(ToolDefinition(**tool) for tool in payload.get("tools", [])),
                    output_schema=payload.get("output_schema"),
                    model=self.config.remember.model,
                    effort=self.config.remember.effort,
                    timeout_seconds=120,
                ),
                tool_handler=tool_handler,
            ):
                events.append({"kind": event.kind, "data": event.data})
                if event.kind == "error":
                    raise RuntimeError(event.data)
                if event.kind == "completed":
                    result = event.data
            if result is None:
                raise RuntimeError("Provider ended without a result")
            return result
        except asyncio.CancelledError:
            await self.provider.cancel(request_id)
            raise
        finally:
            (self.output_dir / f"{request_name}.json").write_text(
                json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    async def step(self, method, payload, *, role="exec", tool_handler=None):
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
            if method == "agent.next":
                result = await self.agents.next(payload, metadata)
            elif method == "agent.close":
                result = await self.agents.close(
                    payload["invocation_id"],
                    metadata,
                    history=payload.get("history"),
                    drain=payload.get("drain", False),
                )
            elif method == "agent.run":
                result = await self.model(payload, tool_handler=tool_handler)
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
            missing = [
                name
                for name in (self.config.redis_url_env, self.config.openai_key_env)
                if not os.environ.get(name)
            ]
            if missing:
                raise RuntimeError(
                    "Для штатного поиска задайте в .env или PyCharm: " + ", ".join(missing)
                )
            self.index.attach(self.graph)
            self.record_experience()
            outcome = await integrate(
                self, self.experience_refs
            )  # Start stepping into the Program here.
            self.result = outcome["result"]
            created = [
                json_value(node) for node in self.graph.nodes() if node.id not in self.seed_ids
            ]
            # Breakpoint here: inspect created, self.result, self.graph and self.memory.
            return created
        finally:
            await self.agents.close_all()
            try:
                for name, value in {
                    "graph": self.graph.snapshot(),
                    "trace": self.memory.snapshot(),
                    "result": self.result,
                    "calls": self.calls,
                }.items():
                    (self.output_dir / f"{name}.json").write_text(
                        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
            finally:
                try:
                    await self.index.close()
                finally:
                    await self.provider.close()


def main():
    repository = Path(__file__).resolve().parents[2]
    output_dir = repository / "tmp" / "debug-integration" / uuid4().hex[:12]
    session = DebugSession(output_dir)
    load_debug_environment(repository, session.config)
    print(f"Codex: {session.config.remember.model}, {session.config.remember.effort}")
    print(f"Задание: {USER_TASK}\nАбзац: {INPUT_TEXT}\nАнализ: {CONSCIOUS_ANALYSIS}")
    print(f"Артефакты: {output_dir}", flush=True)
    created = asyncio.run(session.run())
    print("\nСозданные объекты:")
    for node in created:
        print(f"  {node['id']}: {node['kind']} — {node['name']}")
    print(f"\nЗаписей: {len(session.result['writes'])}. Граф и trace сохранены в {output_dir}")


if __name__ == "__main__":
    main()
