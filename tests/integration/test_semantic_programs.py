"""Exercise the real semantic Programs and nested workflows in the DBOS worker."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from evertree.core.graph.types import GraphDelta, Node
from evertree.core.runtime.controller import ProgramSpec, Runtime
from evertree.core.tokens import current_read_context
from evertree.core.values import json_value
from tests.support.runtime import TestProcess, commit_programs
from tests.support.semantics import semantic_world
from tests.support.tokens import offline_tokenizer  # noqa: F401 -- offline BPE fixture


async def test_integration_repairs_action_calls_search_child_and_replays_once(tmp_path):
    """Only worker/DBOS replay can prove the child call is outside a durable step."""
    root = Path(__file__).resolve().parents[2]
    paths = [
        "src/evertree/processes/self_semantic_processing/self_knowledge_integration/_exec.py",
        "src/evertree/processes/self_semantic_processing/self_semantic_search/_model.py",
        "src/evertree/common/semantic_search.py",
        "src/evertree/common/integration_actions.py",
        "src/evertree/common/structured.py",
    ]
    revision = commit_programs(tmp_path / "repository", {p: (root / p).read_text() for p in paths})
    parent = ProgramSpec(101, paths[0], revision, role="exec")
    child = ProgramSpec(102, paths[1], revision, role="model")
    world = semantic_world()
    parts = [Node(world.graph.reserve_id(), name) for name in ("Start", "End")]
    facts = [
        world.graph.new_fact(
            "PART_WHOLE", {"part": node.id, "whole": world.graph.find("Process").id}
        )
        for node in parts
    ]
    world.graph.apply(GraphDelta(creates=(*parts, *facts)), provenance="test")
    run = world.memory.start_run("input", revision, {})
    event = world.memory.record(run, "input", output="Cat is an animal")
    world.memory.finish_run(run)
    arguments = {
        "experience_refs": [json_value(world.memory.output_ref(event))],
    }
    attempts, tool_results, traces = [], [], []

    async def gateway(method, payload):
        payload = dict(payload)
        metadata = payload.pop("_runtime")
        metadata.update(
            knowledge_integration_authorized=metadata["program"]["program_id"] == parent.program_id,
            integration_operation_id="packet",
            integration_context={},
        )
        if method == "resolve_program":
            assert payload["program_id"] in {"semantic_search", child.program_id}
            return asdict(child)
        if method == "llm.run":
            assert payload["profile"] == "remember"
            assert payload["mode"] == "exec"
            assert "output_schema" not in payload
            assert "create_claim" in {tool["name"] for tool in payload["tools"]}
            attempts.append(json.loads(payload["prompt"]))
            call = payload["_tool_handler"]
            await call("search", {"queries": ["Process"]})
            fields = {
                "name": "Cat classification",
                "description": "A cat is an animal.",
                "sources": arguments["experience_refs"],
            }
            tool_results.append(await call("create_prototype", {**fields, "parent": 9999}))
            assert tool_results[-1]["error"]
            tool_results.append(await call("create_claim", fields))
            token = current_read_context.set({"model": "gpt-5", "context_window": 1000})
            try:
                graph_read = await call(
                    "query", {"relation": "SUBTYPE_OF", "result": "count_matches"}
                )
                assert graph_read["total"] == 0 and graph_read["returned"] == 0
                exists = await call("query", {"relation": "PART_WHOLE", "result": "exists"})
                assert exists == {"exists": True, "returned": 0, "has_more": False}
                first = await call(
                    "query", {"relation": "PART_WHOLE", "max_items": 1, "fields": []}
                )
                assert first["returned"] == 1 and first["has_more"]
                assert "next_cursor" not in first
                second = await call("query", {"next_page": True})
                assert second["returned"] == 1 and not second["has_more"]
                assert first["items"][0]["source_fact"] != second["items"][0]["source_fact"]
                walked = await call(
                    "walk",
                    {
                        "start": world.graph.find("Process").id,
                        "relation": "SUBTYPE_OF",
                        "from_slot": "supertype",
                        "to_slot": "type",
                        "result": "count_nodes",
                    },
                )
                assert walked["total"] == 0
            finally:
                current_read_context.reset(token)
            await call("finish_section", {"complete": True, "remaining": ""})
            return {"text": ""}
        if method.startswith("semantic.") or method in {"graph.query", "graph.walk"}:
            return await world.service.execute(method, payload, metadata)
        return world.operations.execute(method, payload, metadata=metadata)

    async def trace(event):
        traces.append(event)

    runtime = Runtime(
        tmp_path / "runtime", tmp_path / "repository", gateway, trace, process_factory=TestProcess
    )
    try:
        result = await runtime.execute("task", parent, arguments, run_id="remember")
        assert len(result.result["writes"]) == 1
        assert result.result["processing"]["status"] == "processed"
        assert world.graph.find("Cat classification").kind == "claim"
        assert len(attempts) == 1 and tool_results[0]["error"]
        assert len([e for e in traces if e["type"] == "run_started"]) == 3
        revision_before = world.graph.revision
        again = await runtime.execute("task", parent, arguments, run_id="remember")
        assert again.result == result.result and world.graph.revision == revision_before
        assert len(attempts) == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize("kinds", [None, ["RELATION_TYPE", "concept", "relation_type"]])
async def test_ranked_search_parallel_reads_and_replay_across_worker_ipc(tmp_path, kinds):
    """Real IPC and DBOS prove concurrent reads, ordered results, and replay without index calls."""
    import asyncio

    from evertree.core.semantics.config import SemanticConfig
    from tests.support.semantics import EmptyIndex

    root = Path(__file__).resolve().parents[2]
    paths = [
        "src/evertree/processes/self_semantic_processing/self_semantic_search/_model.py",
        "src/evertree/common/semantic_search.py",
        "src/evertree/common/structured.py",
    ]
    revision = commit_programs(tmp_path / "repo", {p: (root / p).read_text() for p in paths})
    started, ready = set(), asyncio.Event()
    reads = []

    class Index(EmptyIndex):
        async def leg(self, name):
            reads.append(name)
            started.add(name)
            if len(started) == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 5)
            return [ids[0], ids[2]] if name == "bm25" else [ids[1], ids[2]]

        async def lexical(self, *args):
            assert args[2] == (["concept", "relation_type"] if kinds is not None else None)
            ids = await self.leg("bm25")
            return [{"ids": ids} for _ in args[1]]

        async def vector(self, *args):
            assert args[2] == (["concept", "relation_type"] if kinds is not None else None)
            ids = await self.leg("vector")
            return [{"ids": ids} for _ in args[1]]

    world = semantic_world(index=Index(), config=SemanticConfig())
    ids = [node.id for node in world.graph.nodes() if node.kind == "relation_type"][:3]

    async def gateway(method, payload):
        payload = dict(payload)
        metadata = payload.pop("_runtime")
        if method == "llm.run":
            raise AssertionError("Search must not invoke a model")
        return await world.service.execute(method, payload, metadata)

    runtime = Runtime(tmp_path / "runtime", tmp_path / "repo", gateway, process_factory=TestProcess)
    try:
        spec = ProgramSpec(1, paths[0], revision, role="model")
        result = await runtime.execute(
            "task", spec, {"queries": ["missing", "another"], "kinds": kinds}, run_id="search"
        )
        assert result.result["status"] == "complete", result.result
        assert started == {"bm25", "vector"}
        assert [item["id"] for item in result.result["items"]] == [ids[2], ids[0], ids[1]]
        replay = await runtime.execute(
            "task", spec, {"queries": ["missing", "another"], "kinds": kinds}, run_id="search"
        )
        assert replay.result == result.result and len(reads) == 2
        reviews = [run for run in world.memory.runs if run.program == "SemanticSearchReview"]
        assert len(reviews) == 2
        for review in reviews:
            key = json_value(review.arguments["key"])
            assert world.service._search_confirmation(key) is True
            assert world.service._search_confirmation([*key[:3], None]) is (
                True if kinds is None else None
            )
    finally:
        await runtime.close()


async def test_interrupted_integration_replays_completed_write_and_continues_same_object(tmp_path):
    """A killed worker must restore tool sequencing while retaining its committed graph write."""
    import asyncio

    import pytest

    from evertree.core.runtime.repository import ProgramExecutionError
    from tests.support.semantics import recorded_experience

    root = Path(__file__).resolve().parents[2]
    paths = [
        "src/evertree/processes/self_semantic_processing/self_knowledge_integration/_exec.py",
        "src/evertree/common/integration_actions.py",
        "src/evertree/common/structured.py",
    ]
    repository = tmp_path / "repository"
    revision = commit_programs(repository, {path: (root / path).read_text() for path in paths})
    parent = ProgramSpec(101, paths[0], revision, role="exec")
    world = semantic_world()
    refs, _ = recorded_experience(world, "The pump appears hot", "The measurement shows 20 C")
    ready, stopped = asyncio.Event(), asyncio.Event()
    calls, writes = [], []
    saved_id = None

    async def gateway(method, payload):
        nonlocal saved_id
        payload = dict(payload)
        metadata = payload.pop("_runtime")
        metadata.update(
            knowledge_integration_authorized=True,
            integration_operation_id="interrupted-packet",
            integration_context={},
        )
        if method == "llm.run":
            calls.append(payload["prompt"])
            call = payload["_tool_handler"]
            if len(calls) == 1:
                saved = await call(
                    "save_note", {"name": "Temperature", "source": refs[0], "sources": []}
                )
                saved_id = saved["object"]
                assert world.graph.get(saved_id).description == "The pump appears hot"
                ready.set()
                try:
                    await asyncio.Future()
                finally:
                    stopped.set()
            assert "already completed" in payload["prompt"]
            assert str(saved_id) in payload["prompt"]
            result = await call(
                "update",
                {
                    "object": saved_id,
                    "changes": {"description": "The pump is 20 C"},
                    "sources": refs[1:],
                },
            )
            assert result["object"] == saved_id
            await call("finish_section", {"complete": True, "remaining": ""})
            return {"text": "Done"}
        if method == "semantic.write":
            writes.append(payload["operation_key"])
        if method.startswith("semantic."):
            return await world.service.execute(method, payload, metadata)
        return world.operations.execute(method, payload, metadata=metadata)

    runtime = Runtime(tmp_path / "runtime", repository, gateway, process_factory=TestProcess)
    arguments = {"experience_refs": refs}
    try:
        first = asyncio.create_task(
            runtime.execute("task", parent, arguments, run_id="resume-integration", timeout=30)
        )
        await asyncio.wait_for(ready.wait(), 30)
        await runtime.cancel("task", finalize=False)
        with pytest.raises(ProgramExecutionError):
            await first
        assert stopped.is_set()
        assert len(world.graph.nodes(kind="note")) == 1
        result = await runtime.execute(
            "task", parent, arguments, run_id="resume-integration", timeout=30
        )
        assert [write["object"] for write in result.result["writes"]] == [saved_id, saved_id]
        assert world.graph.get(saved_id).description == "The pump is 20 C"
        assert len(writes) == 2 and len(set(writes)) == 2
        assert [key.rsplit(":", 1)[1] for key in writes] == ["1", "2"]
        assert writes[0].rsplit(":", 1)[0] == writes[1].rsplit(":", 1)[0]
        assert result.result["processing"]["status"] == "processed"
        changes = [change for change in world.graph._history if saved_id in change.after]
        assert len(changes) == 2
        assert len(calls) == 2
    finally:
        await runtime.close()
