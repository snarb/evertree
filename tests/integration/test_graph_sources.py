"""Exact source references and paged content survive native worker transport and DBOS replay."""

from evertree.core.graph.types import GraphDelta, Node
from evertree.core.runtime.controller import ProgramSpec, Runtime
from evertree.core.tokens import current_read_context
from tests.support.runtime import TestProcess, commit_programs
from tests.support.semantics import semantic_world
from tests.support.tokens import offline_tokenizer  # noqa: F401 -- offline BPE fixture


async def test_exact_source_tools_cross_worker_boundary_and_replay_without_new_reads(tmp_path):
    path = "src/reader.py"
    revision = commit_programs(
        tmp_path / "repo",
        {
            path: """from evertree.core.contracts import ProgramResult
from evertree.core.graph import api as graph
from evertree.core.memory import api as memory
from evertree.core.runtime.api import llm_with_tools
from evertree.core.semantics.tools import READ_TOOLS

async def run(ctx, subject):
    async def handler(name, arguments):
        if name == "sources":
            return await graph.sources(ctx, **arguments)
        return await memory.read_source(ctx, **arguments)
    result = await llm_with_tools(
        ctx, "Read the original source for object " + str(subject),
        instructions="Use sources and read_source; continue every source page.",
        tools=tuple(t for t in READ_TOOLS if t.name in {"sources", "read_source"}),
        tool_handler=handler,
    )
    return ProgramResult(result)
""",
        },
    )
    world = semantic_world()
    run = world.memory.start_run("Article", revision, {})
    body = "Полный источник — measured 17 kg.\n" * 90
    event = world.memory.record(run, "observation", output={"article": {"body": body}})
    world.memory.finish_run(run)
    reference = world.memory.output_ref(event, ("article", "body"))
    node = Node(world.graph.reserve_id(), "Recorded measurement")
    world.operations.apply_delta(
        GraphDelta(creates=(node,)),
        task_id="task",
        revision=revision,
        source_refs=(reference,),
    )
    before = world.memory.snapshot(), world.graph.snapshot()
    model_calls, reads = [], []

    async def gateway(method, payload):
        payload = dict(payload)
        metadata = payload.pop("_runtime")
        if method == "llm.run":
            model_calls.append(method)
            call = payload["_tool_handler"]
            token = current_read_context.set({"model": "gpt-5", "context_window": 3000})
            try:
                listing = await call("sources", {"subjects": [node.id]})
                assert listing["returned"] == 1
                page = await call("read_source", {"reference": listing["items"][0]["reference"]})
                chunks = [page["content"]]
                while page["has_more"]:
                    page = await call("read_source", {"next_page": True})
                    chunks.append(page["content"])
                assert len(chunks) > 1 and "".join(chunks) == body
            finally:
                current_read_context.reset(token)
            return {"text": "Full source verified"}
        reads.append(method)
        return await world.service.execute(method, payload, metadata)

    runtime = Runtime(tmp_path / "runtime", tmp_path / "repo", gateway, process_factory=TestProcess)
    spec = ProgramSpec(301, path, revision, role="model")
    try:
        result = await runtime.execute("task", spec, {"subject": node.id}, run_id="source-read")
        first_reads = list(reads)
        replay = await runtime.execute("task", spec, {"subject": node.id}, run_id="source-read")
        assert replay.result == result.result
        assert model_calls == ["llm.run"] and reads == first_reads
        assert "graph.sources" in reads and "memory.read_source" in reads
        assert (world.memory.snapshot(), world.graph.snapshot()) == before
    finally:
        await runtime.close()
