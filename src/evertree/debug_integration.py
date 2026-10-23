"""Debug KnowledgeIntegration.exec in-process with real Codex decisions and search.

Run this file in PyCharm using the project interpreter and sign in to Codex.
Search settings are loaded from repository .env or the environment.
Only the input experience below is supplied; the model chooses all semantic actions.

Interactive runs have no overall model deadline, so breakpoint pauses do not exhaust an
invocation limit; automated callers can pass `DebugSession(output_dir, timeout_seconds=120)`.
Network operations keep their own timeouts. Program and Core run in one process, so ordinary
breakpoints work; application scheduling, worker admission and durable restart are out of scope.

Each run writes graph.json, trace.json, result.json, calls.json (Core operations and native
tool calls in order), tools.json (tool calls only) and per-request model-*.md files under tmp/debug-integration/<run>/, also on failure.

Useful breakpoints:
- DebugSession.record_experience: source references and the analytical Note.
- knowledge_integration/_exec.py:run: native tool ports and model-facing read projections.
- core/semantics/tools.py: shared tool definitions and action validation.
- core/semantics/compile.py: graph delta construction for one write action.
- common/integration_actions.py: search/read assistance and graph tool dispatch.
- DebugSession.llm: tool dispatch from the provider callback; handlers share its stack.
- DebugSession.model: actual Codex request, declared tools and provider events.
- SemanticService.write: operation validation, idempotence and atomic persistence.
- CoreOperations.apply_delta, then GraphStore.apply: graph mutation and provenance.
- DebugSession.run at `return created`: graph, trace and successful writes together.
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from evertree.common.logging_setup import configure_logging
from evertree.common.structured import validate
from evertree.core.attribution import AttributionRuntime
from evertree.core.beliefs import BeliefStore
from evertree.core.codex.provider import CodexProvider
from evertree.core.cognition.tasks import TaskSpecification
from evertree.core.evaluation.store import EvaluationStore
from evertree.core.graph.store import GraphStore
from evertree.core.learning.state import LearningStore
from evertree.core.memory.store import TraceStore
from evertree.core.operations import CoreOperations, authorize_operation
from evertree.core.provider import LLMRequest, ToolDefinition
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
    """Load repository debug settings without overriding existing environment credentials."""
    from evertree.core.semantics.config import load_search_environment

    load_search_environment(repository, config)
    from dotenv import dotenv_values

    path = repository / ".env"
    if path.is_file():
        value = dotenv_values(path, interpolate=False).get("EVERTREE_TEST_REDIS_URL")
        if value:
            os.environ.setdefault("EVERTREE_TEST_REDIS_URL", value)
    # This harness has private graph/index state, so the configured test Redis is suitable.
    if os.environ.get("EVERTREE_TEST_REDIS_URL"):
        os.environ.setdefault(config.redis_url_env, os.environ["EVERTREE_TEST_REDIS_URL"])


class DebugSession:
    """Inspect graph, memory, calls, experience_refs and recorded writes in the debugger."""

    def __init__(self, output_dir: Path, *, timeout_seconds: float | None = None):
        self.output_dir = output_dir
        # Breakpoint pauses count toward wall time, so interactive debugging has no deadline.
        self.timeout_seconds = timeout_seconds
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
            "semantic_scope": "debug-integration",
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
            },
        }
        self.run_id = self.metadata["run_id"]
        self.provider = CodexProvider(state_dir=output_dir / "codex")
        self.calls = []
        self.experience_refs = []
        self.result = None

    def record_experience(self):
        """Record debug input and the analytical Note as addressable integration sources."""
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

    async def llm(self, payload, *, tools, tool_handler, max_tool_calls=40, stop_when=None):
        """Implement ProgramContext.llm for debugging: tool_handler runs inside the provider callback.

        The runtime instead has the workflow pull tool calls through llm.next, so there a
        breakpoint in a handler does not show the model request. Here it does. Tool calls
        are logged in self.calls as "tool:<name>".
        """
        from .core.runtime.llm import ToolCallLimitError

        self.metadata["semantic_scope"] = "debug:" + uuid4().hex
        definitions = {tool["name"]: tool for tool in json_value(tools)}
        used = 0
        failure = None
        stopped = None

        async def call_tool(name, arguments):
            nonlocal used, failure, stopped
            if stopped is not None:
                raise ValueError("This section has finished; no further tool calls are permitted")
            if name not in definitions:
                raise PermissionError("Tool was not declared")
            used += 1
            if used > max_tool_calls:
                failure = ToolCallLimitError("LLM dialogue exhausted its tool-call limit")
                raise failure
            call = {"method": f"tool:{name}", "payload": json_value(arguments)}
            self.calls.append(call)
            print(f"  ⚙ {name}", flush=True)
            try:
                validate(arguments, definitions[name]["input_schema"])
                call["result"] = json_value(await tool_handler(name, arguments))
            except Exception as error:
                call["error"] = f"{type(error).__name__}: {error}"
                if not isinstance(error, (ValueError, TypeError, PermissionError)):
                    failure = error
                raise
            if stop_when and stop_when(name, call["result"]):
                stopped = {"tool": name, "result": call["result"]}
            return call["result"]

        result = await self.model(
            {**payload, "tools": list(definitions.values())}, tool_handler=call_tool
        )
        if failure is not None:
            raise failure
        return stopped if stopped is not None else result

    def tool_calls(self):
        """Tool calls the model made, in order, with arguments, result and error."""
        return [
            {
                "name": call["method"].removeprefix("tool:"),
                "arguments": call["payload"],
                "result": call.get("result"),
                "error": call.get("error"),
            }
            for call in self.calls
            if call["method"].startswith("tool:")
        ]

    def profile(self, payload):
        """Model profile for one request; the configured integration profile by default."""
        return self.config.remember

    async def model(self, payload, *, tool_handler=None):
        """Invoke the real model and save readable requests and provider transcripts for debugging."""
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
                LLMRequest(
                    payload["prompt"],
                    self.output_dir,
                    instructions=payload["instructions"],
                    mode=payload.get("mode", "model"),
                    tools=tuple(ToolDefinition(**tool) for tool in payload.get("tools", [])),
                    output_schema=payload.get("output_schema"),
                    model=self.profile(payload).model,
                    effort=self.profile(payload).effort,
                    token_encoding=self.config.read.token_encoding,
                    timeout_seconds=self.timeout_seconds,
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

    async def step(self, method, payload, *, role="exec", journal=True):
        """Execute and log an authorized Core operation inside the isolated debug session."""
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
            if method == "llm.run":
                result = await self.model(payload)
            elif method == "trace":
                run = self.memory.start_run(
                    "IntegrationProgress",
                    metadata["program"]["revision"],
                    {},
                    run_mode="evaluation",
                )
                self.memory.record(run, payload["operator"], output=json_value(payload["output"]))
                self.memory.finish_run(run)
                result = None
            elif method.startswith("semantic.") or method in {
                "graph.query",
                "graph.walk",
                "graph.sources",
                "memory.read_source",
            }:
                result = await self.service.execute(method, payload, metadata)
            else:
                result = self.operations.execute(method, payload, metadata=metadata)
            call["result"] = json_value(result)
            return result
        except Exception as exc:
            call["error"] = repr(exc)
            raise

    async def call(self, program, arguments):
        """Run SemanticSearch in process with model-mode gateway authority."""
        if program != "semantic_search":
            raise ValueError(f"Unsupported debug child: {program}")

        async def read(method, payload, *, journal=True):
            return await self.step(method, payload, role="model", journal=journal)

        return SimpleNamespace(**await search(SimpleNamespace(step=read), **arguments))

    async def run(self):
        """Run isolated knowledge integration and save graph, trace and call artifacts even on failure."""
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
            self.record_experience()
            outcome = await integrate(self, self.experience_refs)
            self.result = outcome["result"]
            created = [
                json_value(node) for node in self.graph.nodes() if node.id not in self.seed_ids
            ]
            return created
        finally:
            try:
                for name, value in {
                    "graph": self.graph.snapshot(),
                    "trace": self.memory.snapshot(),
                    "result": self.result,
                    "calls": self.calls,
                    "tools": self.tool_calls(),
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
    """Run the configured integration debug case and print the artifact directory."""
    configure_logging()
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
