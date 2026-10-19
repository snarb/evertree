import asyncio

import pytest

from evertree.core.operations import authorize_operation
from evertree.core.runtime.llm import ProgramLLMInvocations, run_llm_dialogue

METADATA = {"run_id": "workflow", "program": {"role": "model"}}
TOOL = {
    "name": "read",
    "description": "Read.",
    "input_schema": {"type": "object"},
    "read_only": True,
}


async def test_read_context_crosses_callback_boundary_and_replays_without_leaking():
    from evertree.core.tokens import current_read_context

    budget = {"model": "gpt-5", "context_window": 1000, "remaining_tokens": 700}

    async def gateway(method, args):
        token = current_read_context.set(budget)
        try:
            await args["_tool_handler"]("read", {})
        finally:
            current_read_context.reset(token)
        return {"text": "done"}

    invocations = ProgramLLMInvocations(gateway)
    recorded = []

    class Context:
        run_id = "workflow"

        async def step(self, method, args, *, journal=True):
            if method in {"llm.enter", "llm.leave"}:
                return
            if method == "llm.next":
                event = await invocations.next(args, METADATA)
                recorded.append(event)
                return event
            return await invocations.close(args["invocation_id"], METADATA, history=args["history"])

    async def handle(name, args):
        assert current_read_context.get() == budget
        return {"total": 3}

    try:
        await run_llm_dialogue(Context(), {"prompt": "Read"}, tools=[TOOL], tool_handler=handle)
        assert recorded[0]["read_context"] == budget
        assert current_read_context.get() is None

        class Replay:
            run_id = "workflow"

            async def step(self, method, args, *, journal=True):
                if method in {"llm.enter", "llm.leave"}:
                    return
                if method == "llm.next":
                    return recorded.pop(0)

        await run_llm_dialogue(Replay(), {"prompt": "Read"}, tools=[TOOL], tool_handler=handle)
        assert current_read_context.get() is None
    finally:
        await invocations.close_all()


def payload(**changes):
    return {
        "invocation_id": "one",
        "request": {"prompt": "Read", "tools": [TOOL]},
        "history": [],
        "max_tool_calls": 2,
        **changes,
    }


async def test_bridge_rejects_forged_reply_and_other_workflow_cannot_close_session():
    stopped = asyncio.Event()

    async def gateway(method, arguments):
        try:
            return await arguments["_tool_handler"]("read", {"key": "original"})
        finally:
            stopped.set()

    invocations = ProgramLLMInvocations(gateway)
    try:
        event = await invocations.next(payload(), METADATA)
        forged = {**event["call"], "arguments": {"key": "forged"}, "result": 1, "error": None}
        with pytest.raises(ValueError, match="does not match"):
            await invocations.next(payload(history=[forged]), METADATA)
        await invocations.close("one", {**METADATA, "run_id": "other"})
        assert not stopped.is_set()
        completed = {**event["call"], "result": 7, "error": None}
        result = await invocations.next(payload(history=[completed]), METADATA)
        assert result == {"kind": "completed", "result": 7}
        assert await invocations.next(payload(history=[completed]), METADATA) == result
    finally:
        await invocations.close_all()


async def test_model_cannot_expose_effect_tools_or_native_coding():
    authorize_operation("llm.next", "model")
    authorize_operation("llm.close", "model")

    async def gateway(method, arguments):
        pytest.fail("Unauthorized provider invocation")

    invocations = ProgramLLMInvocations(gateway)
    with pytest.raises(PermissionError, match="action tools"):
        await invocations.next(
            payload(
                request={"prompt": "", "mode": "exec", "tools": [{**TOOL, "read_only": False}]}
            ),
            METADATA,
        )
    with pytest.raises(PermissionError, match="declared tools"):
        await invocations.next(payload(request={"prompt": "", "native_coding": True}), METADATA)


async def test_bridge_limits_native_tool_calls_even_if_worker_keeps_requesting():
    async def gateway(method, arguments):
        await arguments["_tool_handler"]("read", {})
        await arguments["_tool_handler"]("read", {})

    invocations = ProgramLLMInvocations(gateway)
    try:
        event = await invocations.next(payload(max_tool_calls=1), METADATA)
        completed = {**event["call"], "result": 7, "error": None}
        with pytest.raises(RuntimeError, match="tool-call limit"):
            await invocations.next(payload(history=[completed], max_tool_calls=1), METADATA)
    finally:
        await invocations.close_all()


async def test_tool_schema_rejects_invalid_arguments_before_workflow_dispatch():
    definition = {
        **TOOL,
        "input_schema": {
            "type": "object",
            "properties": {
                "values": {
                    "type": "array",
                    "items": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "maxItems": 2,
                }
            },
            "required": ["values"],
            "additionalProperties": False,
        },
    }

    async def gateway(method, arguments):
        for invalid in ({"values": ["not a number"]}, {"values": [1, 2, 3]}, {}):
            with pytest.raises(ValueError):
                await arguments["_tool_handler"]("read", invalid)
        return await arguments["_tool_handler"]("read", {"values": [1, None]})

    invocations = ProgramLLMInvocations(gateway)
    request = payload(request={"prompt": "Read", "tools": [definition]}, max_tool_calls=4)
    try:
        event = await invocations.next(request, METADATA)
        assert event["call"]["arguments"] == {"values": [1, None]}
        completed = {**event["call"], "result": "valid", "error": None}
        assert await invocations.next({**request, "history": [completed]}, METADATA) == {
            "kind": "completed",
            "result": "valid",
        }
    finally:
        await invocations.close_all()


async def test_callback_transport_failure_propagates_and_closes_inference():
    stopped = asyncio.Event()

    async def gateway(method, arguments):
        try:
            return await arguments["_tool_handler"]("read", {})
        finally:
            stopped.set()

    invocations = ProgramLLMInvocations(gateway)

    class Context:
        run_id = "workflow"

        async def step(self, method, arguments, *, journal=True):
            if method in {"llm.enter", "llm.leave"}:
                return
            if method == "llm.next":
                return await invocations.next(arguments, METADATA)
            assert method == "llm.close"
            await invocations.close(
                arguments["invocation_id"], METADATA, history=arguments["history"]
            )

    async def handle(name, arguments):
        raise RuntimeError("Protected core disconnected")

    with pytest.raises(RuntimeError, match="Protected core disconnected"):
        await run_llm_dialogue(Context(), {"prompt": "Read"}, tools=[TOOL], tool_handler=handle)
    assert stopped.is_set()
    assert not invocations.running


async def test_graceful_close_waits_for_final_usage_and_remains_cancellable():
    finishing = asyncio.Event()
    release = asyncio.Event()
    charged = []

    async def gateway(method, arguments):
        await arguments["_tool_handler"]("read", {})
        finishing.set()
        await release.wait()
        charged.append(17)
        return {"text": "ignored"}

    invocations = ProgramLLMInvocations(gateway)
    try:
        event = await invocations.next(payload(), METADATA)
        history = [{**event["call"], "result": "receipt", "error": None}]
        closing = asyncio.create_task(
            invocations.close("one", METADATA, history=history, drain=True)
        )
        await finishing.wait()
        assert invocations.running and not closing.done() and not charged
        release.set()
        await closing
        assert charged == [17]

        release.clear()
        finishing.clear()
        event = await invocations.next(payload(), METADATA)
        history = [{**event["call"], "result": "receipt", "error": None}]
        closing = asyncio.create_task(
            invocations.close("one", METADATA, history=history, drain=True)
        )
        await finishing.wait()
        await invocations.close_all()
        with pytest.raises(RuntimeError, match="Provider invocation was interrupted"):
            await closing
        assert charged == [17]
    finally:
        await invocations.close_all()


async def test_provider_cancellation_returns_error_instead_of_hanging_next():
    async def gateway(method, arguments):
        raise asyncio.CancelledError("provider interrupted")

    invocations = ProgramLLMInvocations(gateway)
    try:
        with pytest.raises(RuntimeError, match="Provider invocation was interrupted"):
            await asyncio.wait_for(invocations.next(payload(), METADATA), 5)
    finally:
        await invocations.close_all()


async def test_provider_cancellation_during_terminal_drain_returns_error():
    async def gateway(method, arguments):
        await arguments["_tool_handler"]("read", {})
        raise asyncio.CancelledError("provider interrupted")

    invocations = ProgramLLMInvocations(gateway)
    try:
        event = await invocations.next(payload(), METADATA)
        history = [{**event["call"], "result": "receipt", "error": None}]
        with pytest.raises(RuntimeError, match="Provider invocation was interrupted"):
            await asyncio.wait_for(
                invocations.close("one", METADATA, history=history, drain=True), 5
            )
    finally:
        await invocations.close_all()


async def test_cancelling_terminal_drain_caller_preserves_cancellation():
    finishing, stopped = asyncio.Event(), asyncio.Event()

    async def gateway(method, arguments):
        try:
            await arguments["_tool_handler"]("read", {})
            finishing.set()
            await asyncio.Future()
        finally:
            stopped.set()

    invocations = ProgramLLMInvocations(gateway)
    try:
        event = await invocations.next(payload(), METADATA)
        history = [{**event["call"], "result": "receipt", "error": None}]
        closing = asyncio.create_task(
            invocations.close("one", METADATA, history=history, drain=True)
        )
        await finishing.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert stopped.is_set()
        assert not invocations.running
    finally:
        await invocations.close_all()


async def test_terminal_tool_rejects_already_queued_parallel_calls_and_drains_usage():
    second_started = asyncio.Event()
    charged, executed, outcomes = [], [], []

    async def gateway(method, arguments):
        async def native_call(name):
            if name == "read":
                second_started.set()
            try:
                return await arguments["_tool_handler"](name, {})
            except RuntimeError as error:
                return {"error": str(error)}

        outcomes.extend(await asyncio.gather(native_call("finish"), native_call("read")))
        charged.append(23)
        return {"text": "ignored model answer"}

    invocations = ProgramLLMInvocations(gateway)

    class Context:
        run_id = "workflow"

        async def step(self, method, arguments, *, journal=True):
            if method in {"llm.enter", "llm.leave"}:
                return
            if method == "llm.next":
                return await invocations.next(arguments, METADATA)
            assert method == "llm.close"
            await invocations.close(
                arguments["invocation_id"],
                METADATA,
                history=arguments["history"],
                drain=arguments["drain"],
            )

    async def handle(name, arguments):
        executed.append(name)
        await second_started.wait()
        return "receipt"

    try:
        result = await asyncio.wait_for(
            run_llm_dialogue(
                Context(),
                {"prompt": "Finish"},
                tools=[TOOL, {**TOOL, "name": "finish"}],
                tool_handler=handle,
                stop_when=lambda name, result: name == "finish",
            ),
            5,
        )
        assert result == {"tool": "finish", "result": "receipt"}
        assert executed == ["finish"]
        assert outcomes == [
            "receipt",
            {"error": "LLM invocation has finished; end your response now"},
        ]
        assert charged == [23]
        assert not invocations.running
    finally:
        await invocations.close_all()
