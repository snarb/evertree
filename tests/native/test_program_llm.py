import os
import sys

import pytest

from evertree.core.runtime.controller import ProgramSpec, Runtime
from evertree.core.tokens import current_read_context
from tests.support.runtime import commit_programs


@pytest.mark.skipif(os.name != "nt" and sys.platform != "darwin", reason="Native workers")
async def test_native_worker_can_execute_scoped_llm_tools(tmp_path):
    """Verify the transport helper is available inside the restricted Python distribution."""
    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "program.py": """
async def run(ctx):
    async def handle(name, arguments):
        from evertree.core.tokens import current_read_context
        assert current_read_context.get()["context_window"] == 1000
        return await ctx.step("echo", arguments)
    result = await ctx.llm({"prompt": "Echo a value."}, tools=[{
        "name": "echo", "description": "Echo.", "read_only": True,
        "input_schema": {"type": "object", "properties": {"value": {"type": "integer"}},
                         "required": ["value"], "additionalProperties": False}
    }], tool_handler=handle)
    return {"result": result}
"""
        },
    )

    async def gateway(method, payload):
        if method == "echo":
            return payload["value"]
        assert method == "llm.run"
        token = current_read_context.set({"model": "gpt-5", "context_window": 1000})
        try:
            value = await payload["_tool_handler"]("echo", {"value": 7})
        finally:
            current_read_context.reset(token)
        return {"text": str(value)}

    runtime = Runtime(tmp_path / "runtime", repository, gateway)
    try:
        result = await runtime.execute(
            "task", ProgramSpec(1, "program.py", revision), {}, timeout=30
        )
        assert result.result == {"text": "7"}
    finally:
        await runtime.close()


@pytest.mark.skipif(os.name != "nt" and sys.platform != "darwin", reason="Native workers")
async def test_native_worker_reads_graph_sources_through_typed_core_wrappers(tmp_path):
    """Package exact source wrappers and carry model budgets across the native sandbox."""
    from pathlib import Path

    from evertree.core.graph.types import GraphDelta, Node
    from tests.support.semantics import semantic_world

    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "src/evertree/common/structured.py": (
                Path(__file__).resolve().parents[2] / "src/evertree/common/structured.py"
            ).read_text(),
            "program.py": """
from evertree.core.graph import api as graph
from evertree.core.memory import api as memory
from evertree.core.runtime.api import llm_with_tools
from evertree.core.semantics.tools import READ_TOOLS

async def run(ctx):
    async def handle(name, arguments):
        if name == "sources":
            return await graph.sources(ctx, **arguments)
        return await memory.read_source(ctx, **arguments)
    result = await llm_with_tools(
        ctx, "Read retained evidence.", instructions="Use exact source references.",
        tools=tuple(tool for tool in READ_TOOLS if tool.name in {"sources", "read_source"}),
        tool_handler=handle,
    )
    return {"result": result}
""",
        },
    )
    world = semantic_world()
    run = world.memory.start_run("Article", revision, {})
    event = world.memory.record(run, "observation", output={"body": "Подтверждённый факт: 17 kg."})
    world.memory.finish_run(run)
    reference = world.memory.output_ref(event, ("body",))
    node = Node(world.graph.reserve_id(), "Retained fact")
    world.operations.apply_delta(
        GraphDelta(creates=(node,)), task_id="task", revision=revision, source_refs=(reference,)
    )

    async def gateway(method, payload):
        payload = dict(payload)
        metadata = payload.pop("_runtime")
        if method != "llm.run":
            return await world.service.execute(method, payload, metadata)
        token = current_read_context.set({"model": "gpt-5", "context_window": 10000})
        try:
            sources = await payload["_tool_handler"]("sources", {"subjects": [node.id]})
            value = await payload["_tool_handler"](
                "read_source", {"reference": sources["items"][0]["reference"]}
            )
            assert value["content"] == "Подтверждённый факт: 17 kg."
            assert not value["has_more"]
        finally:
            current_read_context.reset(token)
        return {"text": "Exact source verified"}

    runtime = Runtime(tmp_path / "runtime", repository, gateway)
    try:
        result = await runtime.execute(
            "task", ProgramSpec(1, "program.py", revision, role="model"), {}, timeout=30
        )
        assert result.result == {"text": "Exact source verified"}
    finally:
        await runtime.close()
