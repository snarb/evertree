"""Exercise the real semantic Programs and nested workflows in the DBOS worker."""

import json
from dataclasses import asdict
from pathlib import Path

from evertree.core.runtime.controller import ProgramSpec, Runtime
from evertree.core.values import json_value
from tests.support.runtime import TestProcess, commit_programs
from tests.support.semantics import semantic_world


async def test_integration_repairs_action_calls_search_child_and_replays_once(tmp_path):
    """Only worker/DBOS replay can prove the child call is outside a durable step."""
    root = Path(__file__).resolve().parents[2]
    paths = [
        "src/evertree/processes/semantic_processing/knowledge_integration/_exec.py",
        "src/evertree/processes/semantic_processing/semantic_search/_model.py",
        "src/evertree/common/semantic_search.py",
        "src/evertree/common/integration_actions.py",
        "src/evertree/common/structured.py",
    ]
    revision = commit_programs(tmp_path / "repository", {p: (root / p).read_text() for p in paths})
    parent = ProgramSpec(101, paths[0], revision, role="exec")
    child = ProgramSpec(102, paths[1], revision, role="model")
    world = semantic_world()
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
        if method == "agent.run":
            assert payload["profile"] == "remember"
            assert payload["mode"] == "exec"
            assert "output_schema" not in payload
            assert "create_concept" in {tool["name"] for tool in payload["tools"]}
            attempts.append(json.loads(payload["prompt"]))
            call = payload["_tool_handler"]
            await call("search", {"query": "Process", "next_page": False})
            fields = {
                "name": "Cat",
                "description": "The category of domestic cats",
                "sources": arguments["experience_refs"],
            }
            tool_results.append(await call("create_prototype", {**fields, "parent": 9999}))
            assert tool_results[-1]["error"]
            tool_results.append(await call("create_concept", fields))
            await call("finish", {})
            return {"text": ""}
        if method.startswith("semantic."):
            return await world.service.execute(method, payload, metadata)
        return world.operations.execute(method, payload, metadata=metadata)

    async def trace(event):
        traces.append(event)

    runtime = Runtime(
        tmp_path / "runtime", tmp_path / "repository", gateway, trace, process_factory=TestProcess
    )
    try:
        result = await runtime.execute("task", parent, arguments, run_id="remember")
        assert result.result["status"] == "complete"
        assert len(attempts) == 1 and tool_results[0]["error"]
        assert len([e for e in traces if e["type"] == "run_started"]) == 3
        revision_before = world.graph.revision
        again = await runtime.execute("task", parent, arguments, run_id="remember")
        assert again.result == result.result and world.graph.revision == revision_before
        assert len(attempts) == 1
    finally:
        await runtime.close()


async def test_ranked_search_parallel_reads_and_replay_across_worker_ipc(tmp_path):
    """Real IPC and DBOS prove concurrent reads, ordered results, and replay without index calls."""
    import asyncio

    from evertree.core.semantics.config import SemanticConfig
    from tests.support.semantics import EmptyIndex

    root = Path(__file__).resolve().parents[2]
    paths = [
        "src/evertree/processes/semantic_processing/semantic_search/_model.py",
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
            return await self.leg("bm25")

        async def vector(self, *args):
            return await self.leg("vector")

    world = semantic_world(index=Index(), config=SemanticConfig())
    ids = [node.id for node in world.graph.nodes()][:3]

    async def gateway(method, payload):
        payload = dict(payload)
        metadata = payload.pop("_runtime")
        if method == "agent.run":
            raise AssertionError("Search must not invoke a model")
        return await world.service.execute(method, payload, metadata)

    runtime = Runtime(tmp_path / "runtime", tmp_path / "repo", gateway, process_factory=TestProcess)
    try:
        spec = ProgramSpec(1, paths[0], revision, role="model")
        result = await runtime.execute("task", spec, {"query": "missing"}, run_id="search")
        assert result.result["status"] == "complete", result.result
        assert started == {"bm25", "vector"}
        assert [item["id"] for item in result.result["items"]] == [ids[2], ids[0], ids[1]]
        replay = await runtime.execute("task", spec, {"query": "missing"}, run_id="search")
        assert replay.result == result.result and len(reads) == 2
    finally:
        await runtime.close()
