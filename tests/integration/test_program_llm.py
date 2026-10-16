"""Real DBOS/worker boundaries for native Program tool callbacks and recovery."""

import asyncio

import pytest

from evertree.core.runtime.controller import ProgramSpec, Runtime
from evertree.core.runtime.repository import ProgramExecutionError
from tests.support.runtime import TestProcess, commit_programs

SOURCE = """
TOOLS = [{"name": "calculate", "description": "Calculate the supplied number.",
          "input_schema": {"type": "object", "properties": {"value": {"type": "integer"}},
                           "required": ["value"], "additionalProperties": False},
          "read_only": True}]

async def run(ctx, stop=False, twice=False):
    values = []
    async def handle(name, arguments):
        result = await ctx.call("child", arguments)
        values.append(result.result)
        return {"value": result.result}
    first = await ctx.llm({"prompt": "Calculate two numbers."}, tools=TOOLS,
                            tool_handler=handle,
                            stop_when=(lambda name, result: True) if stop else None)
    second = None
    if twice:
        second = await ctx.llm({"prompt": "Calculate another number."}, tools=TOOLS,
                                 tool_handler=handle)
    return {"result": {"values": values, "first": first, "second": second}}
"""


def programs(tmp_path):
    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "parent.py": SOURCE,
            "child.py": "async def run(ctx, value): return {'result': await ctx.step('calculate', {'value': value})}\n",
        },
    )
    return (
        repository,
        ProgramSpec("parent", "parent.py", revision),
        ProgramSpec("child", "child.py", revision, role="model"),
    )


async def test_native_tools_replay_local_state_and_child_workflow_after_interruption(tmp_path):
    """A killed worker must rebuild its local draft without repeating child effects."""
    repository, parent, child = programs(tmp_path)
    interrupted, stopped = asyncio.Event(), asyncio.Event()
    requests, calculations = [], []

    async def gateway(method, payload):
        if method == "resolve_program":
            return child
        if method == "calculate":
            calculations.append(payload["value"])
            return payload["value"] * 2
        assert method == "llm.run"
        requests.append(payload)
        if len(requests) == 1:
            assert await payload["_tool_handler"]("calculate", {"value": 1}) == {"value": 2}
            interrupted.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()
        assert "already completed" in payload["prompt"]
        assert '"value": 2' in payload["prompt"]
        assert await payload["_tool_handler"]("calculate", {"value": 2}) == {"value": 4}
        return {"text": "done"}

    traces = []

    async def trace(event):
        traces.append(event)

    runtime = Runtime(tmp_path / "runtime", repository, gateway, trace, process_factory=TestProcess)
    try:
        first = asyncio.create_task(
            runtime.execute("task", parent, {}, run_id="resume-tools", timeout=30)
        )
        await asyncio.wait_for(interrupted.wait(), 30)
        with pytest.raises(RuntimeError, match="LLM invocation"):
            async with runtime.quiesce():
                pytest.fail("An open provider can still update its trace and usage")
        await runtime.cancel("task", finalize=False)
        with pytest.raises(ProgramExecutionError):
            await first
        assert stopped.is_set()
        result = await runtime.execute("task", parent, {}, run_id="resume-tools", timeout=30)
        assert result.result == {"values": [2, 4], "first": {"text": "done"}, "second": None}
        assert calculations == [1, 2]
        replay = await runtime.execute("task", parent, {}, run_id="resume-tools", timeout=30)
        assert replay == result
        assert calculations == [1, 2]
        assert len(requests) == 2
        resumed = [
            item["arguments"]
            for item in traces
            if item.get("operator") == "llm.next" and item["arguments"]["history_length"]
        ]
        assert resumed and resumed[0]["completed"]["result"] == {"value": 2}
        assert all("history" not in item and "request" not in item for item in resumed)
    finally:
        await runtime.close()


async def test_two_native_invocations_in_one_program_have_separate_sessions(tmp_path):
    """A workflow can invoke the model twice without reusing its first completion."""
    repository, parent, child = programs(tmp_path)
    prompts = []

    async def gateway(method, payload):
        if method == "resolve_program":
            return child
        if method == "calculate":
            return payload["value"]
        assert method == "llm.run"
        prompts.append(payload["prompt"])
        await payload["_tool_handler"]("calculate", {"value": len(prompts)})
        return {"text": str(len(prompts))}

    runtime = Runtime(tmp_path / "runtime", repository, gateway, process_factory=TestProcess)
    try:
        result = await runtime.execute("task", parent, {"twice": True}, timeout=30)
        assert result.result == {"values": [1, 2], "first": {"text": "1"}, "second": {"text": "2"}}
        assert prompts == ["Calculate two numbers.", "Calculate another number."]
    finally:
        await runtime.close()


async def test_finish_tool_drains_provider_and_keeps_durable_result(tmp_path):
    """Final usage can arrive after the terminal tool; model answer text is ignored."""
    repository, parent, child = programs(tmp_path)
    stopped = asyncio.Event()
    traces = []

    async def gateway(method, payload):
        if method == "resolve_program":
            return child
        if method == "calculate":
            return payload["value"]
        assert method == "llm.run"
        try:
            assert await payload["_tool_handler"]("calculate", {"value": 7}) == {"value": 7}
            with pytest.raises(RuntimeError, match="has finished"):
                await payload["_tool_handler"]("calculate", {"value": 99})
            return {"text": "ignored model answer"}
        finally:
            stopped.set()

    async def trace(event):
        traces.append(event)

    runtime = Runtime(tmp_path / "runtime", repository, gateway, trace, process_factory=TestProcess)
    try:
        result = await runtime.execute("task", parent, {"stop": True}, timeout=30)
        assert result.result["first"] == {"tool": "calculate", "result": {"value": 7}}
        assert stopped.is_set()
        closed = next(item for item in traces if item.get("operator") == "llm.close")
        assert closed["arguments"]["history"][0]["result"] == {"value": 7}
        steps = [item["arguments"] for item in traces if item.get("operator") == "llm.next"]
        assert "request" in steps[0] and steps[0]["history_length"] == 0
        assert all("history" not in item for item in steps)
    finally:
        await runtime.close()
