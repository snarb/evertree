"""The debugger example exercises real writes, temporal views and receipt replay."""

import json

from evertree.core.graph.store import GraphStore
from evertree.core.memory.store import TraceStore
from evertree.core.memory.types import TraceOutputRef
from evertree.debug_integration import CONSCIOUS_ANALYSIS, DebugSession
from evertree.processes.semantic_processing.knowledge_integration._exec import run


async def test_debug_example_preserves_history_and_replays_without_another_model_call(tmp_path):
    session = DebugSession(tmp_path)
    created = await session.run()
    graph = GraphStore.from_snapshot(json.loads((tmp_path / "graph.json").read_text()))
    memory = TraceStore.from_snapshot(json.loads((tmp_path / "trace.json").read_text()))
    pump = next(node for node in created if node["kind"] == "instance")
    facets = sorted(
        (node for node in created if node["kind"] == "facet"),
        key=lambda n: graph.get(n["id"]).valid_from,
    )
    assert len(facets) == 2
    for at, expected in (
        ("2026-10-12T09:05:00+00:00", [facets[0]["id"]]),
        ("2026-10-12T09:10:00+00:00", [facets[1]["id"]]),
        ("2026-10-12T09:20:00+00:00", []),
    ):
        rows = graph.query_view("STATE_IDENTITY", "get_facets", instance=pump["id"], valid_at=at)
        assert [row.value for row in rows] == expected
    assert sum(node["kind"] == "relation_instance" for node in created) == 3
    assert (
        next(node for node in created if node["kind"] == "note")["description"]
        == CONSCIOUS_ANALYSIS
    )
    assert (
        memory.resolve(TraceOutputRef(**session.experience_refs[-1]))["text"] == CONSCIOUS_ANALYSIS
    )
    assert not session.receipt["pending_preservation_ids"]
    assert not session.operations.beliefs.snapshot()["targets"]

    before = len(session.calls), session.graph.revision
    session.metadata["run_id"] = "debug-retry"
    replay = await run(session, session.experience_refs)
    assert replay["result"] == session.receipt
    assert session.graph.revision == before[1]
    assert [call["method"] for call in session.calls[before[0] :]] == ["semantic.sources"]
