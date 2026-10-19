"""Real-model packets and independent snapshot forks for the large-graph live probe."""

import json
import os
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from evertree.core.attribution import AttributionRuntime
from evertree.core.graph.store import GraphStore
from evertree.core.memory.store import TraceStore
from evertree.core.semantics.reading import fact_nodes
from evertree.core.semantics.service import SemanticService
from evertree.core.values import json_value
from evertree.debug_integration import DebugSession, load_debug_environment
from evertree.processes.semantic_processing.knowledge_integration._exec import run as integrate

CORPUS = Path(__file__).resolve().parents[1] / "data" / "datacenter_experience.txt"
REPORT_CONTEXT = (
    "Общий контекст отчёта: учебная вымышленная площадка Север. "
    "Описанные события относятся к октябрю 2026 года. Все времена отчёта указаны в UTC."
)
TASK = (
    "Сопровождать эксплуатацию учебной площадки Север: находить причины повторяющихся "
    "инцидентов, планировать проверки и профилактику, переиспользовать инженерные выводы."
)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def graph_stats(graph):
    counts = Counter(node.kind for node in graph.nodes())
    domain_facts = [
        node
        for node in graph.nodes(kind="relation_instance")
        if graph.get(node.relation_type).name
        not in {"IDENTITY_TYPE", "SUBTYPE_OF", "STATE_IDENTITY"}
    ]
    linked = {identity for fact in domain_facts for identity in fact_nodes(graph, fact)}
    return {
        "total": sum(counts.values()),
        "by_kind": dict(counts),
        "domain_facts": len(domain_facts),
        "instances_without_domain_links": [
            {"id": node.id, "name": node.name}
            for node in graph.nodes(kind="instance")
            if node.id not in linked
        ],
    }


class LargeGraphSession(DebugSession):
    def __init__(self, output_dir, *, snapshot=None):
        super().__init__(output_dir, timeout_seconds=300)
        load_debug_environment(Path(__file__).resolve().parents[2], self.config)
        required = [self.config.redis_url_env, self.config.openai_key_env]
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError("Missing live-evaluation credentials: " + ", ".join(missing))
        if snapshot is not None:
            self.graph = GraphStore.from_snapshot(snapshot["graph"])
            self.memory = TraceStore.from_snapshot(snapshot["trace"])
            attribution = AttributionRuntime(self.graph, self.operations.beliefs)
            self.operations = replace(
                self.operations, graph=self.graph, memory=self.memory, attribution=attribution
            )
            self.service = SemanticService(
                self.graph, self.memory, attribution, self.config, self.index, self.operations
            )
        self.service.config = self.config
        self.metadata["task_id"] = "datacenter-evaluation"
        self.metadata["integration_context"]["task"] = {
            "id": "datacenter-evaluation",
            "specification": {"objective": TASK},
        }

    def snapshot(self):
        return {"graph": self.graph.snapshot(), "trace": self.memory.snapshot()}

    async def packet(self, directory, text, analysis):
        self.output_dir = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.calls = []
        packet_id = directory.name
        self.metadata["integration_operation_id"] = packet_id
        source_run = self.memory.start_run(
            "TechnicalExperience", "evaluation", {}, run_mode="evaluation"
        )
        source = self.memory.record(source_run, "user_input", output=REPORT_CONTEXT + "\n\n" + text)
        self.memory.finish_run(source_run)
        refs = [json_value(self.memory.output_ref(source))]
        note = self.operations.execute(
            "memory.note", {"text": analysis, "source_refs": refs}, metadata=self.metadata
        )
        refs.append(note)
        before = {node.id for node in self.graph.nodes()}
        started = time.perf_counter()
        error = None
        try:
            await integrate(self, refs)
        except Exception as exc:  # noqa: BLE001 -- retain partial graph and report failed packets
            error = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            history = self.tool_calls()
            usage = []
            for path in directory.glob("model-*.json"):
                values = [e["data"] for e in json.loads(path.read_text()) if e["kind"] == "usage"]
                if values:
                    usage.append(values[-1])
            metrics = {
                "error": error,
                "seconds": time.perf_counter() - started,
                "model_calls": len(usage),
                "tool_calls": len(history),
                "input_tokens": sum(u.get("input_tokens", 0) for u in usage),
                "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
                "created": [json_value(n) for n in self.graph.nodes() if n.id not in before],
                "graph": graph_stats(self.graph),
            }
            write_json(directory / "metrics.json", metrics)
            write_json(directory / "calls.json", self.calls)
            write_json(directory / "history.json", history)
            write_json(directory / "snapshot.json", self.snapshot())
        return metrics

    async def close(self):
        try:
            await self.index.close()
        finally:
            await self.provider.close()
        client = Redis.from_url(os.environ[self.config.redis_url_env])
        try:
            for name in tuple(self.index._ready):
                try:
                    await client.execute_command("FT.DROPINDEX", name, "DD")
                except ResponseError:
                    pass
            keys = [k async for k in client.scan_iter(self.index.namespace + ":*")]
            if keys:
                await client.delete(*keys)
        finally:
            await client.aclose()
