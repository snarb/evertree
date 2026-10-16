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
