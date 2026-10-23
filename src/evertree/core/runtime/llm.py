"""Lets Program workflow code serve the tool calls of an LLM session that runs in Core."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from uuid import uuid4

from ..provider import ToolDefinition
from ..tokens import current_read_context
from ..values import json_value


class ToolCallLimitError(RuntimeError):
    """A model invocation used its allowance; already completed handlers remain durable."""


async def run_llm_dialogue(ctx, payload, *, tools, tool_handler, max_tool_calls=40, stop_when=None):
    """Implement ProgramContext.llm: the model runs in Core, tool handlers run in the workflow.

    Each llm.next step returns the model's next tool call or its final response. The
    handler's result is sent back with the following llm.next, so the step results are
    durable and the handler's own durable operations replay on recovery. Handlers run
    again during recovery to rebuild local state.
    """
    if type(max_tool_calls) is not int or not 1 <= max_tool_calls <= 1000:
        raise ValueError("max_tool_calls must be between 1 and 1000")
    ctx._llm_sequence = getattr(ctx, "_llm_sequence", 0) + 1
    identity = f"{ctx.run_id}:llm:{ctx._llm_sequence}"
    request = {**payload, "tools": json_value(tools)}
    history = []
    failed = False
    drain = False
    await ctx.step("llm.enter", {"invocation_id": identity}, journal=False)
    try:
        while True:
            event = await ctx.step(
                "llm.next",
                {
                    "invocation_id": identity,
                    "request": request,
                    "history": history,
                    "max_tool_calls": max_tool_calls,
                },
            )
            if event["kind"] == "completed":
                return event["result"]
            if event["kind"] == "tool_limit":
                raise ToolCallLimitError(event["error"])
            if event["kind"] != "tool_call":
                raise ValueError("Invalid LLM dialogue event")
            if len(history) >= max_tool_calls:
                raise ToolCallLimitError("LLM dialogue exhausted its tool-call limit")
            call = event["call"]
            context_token = current_read_context.set(event.get("read_context"))
            try:
                result = json_value(await tool_handler(call["name"], call["arguments"]))
                completed = {**call, "result": result, "error": None}
            except (ValueError, TypeError, PermissionError) as error:
                completed = {**call, "result": None, "error": f"{type(error).__name__}: {error}"}
            finally:
                current_read_context.reset(context_token)
            history.append(completed)
            if completed["error"] is None and stop_when and stop_when(call["name"], result):
                drain = True
                return {"tool": call["name"], "result": result}
    except BaseException:
        failed = True
        raise
    finally:
        try:
            await ctx.step(
                "llm.close", {"invocation_id": identity, "history": history, "drain": drain}
            )
        except BaseException:
            if not failed:
                raise
        finally:
            await ctx.step("llm.leave", {"invocation_id": identity}, journal=False)


@dataclass
class _Invocation:
    request: dict
    metadata: dict
    limit: int
    history: list
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict = field(default_factory=dict)
    delivered: dict | None = None
    task: asyncio.Task | None = None
    calls: int = 0
    closing: bool = False
    error: str | None = None


class ProgramLLMInvocations:
    """Core-side LLM sessions behind llm.next and llm.close.

    A session exists only in memory; after a restart it is recreated from the
    completed tool calls that DBOS recorded.
    """

    def __init__(self, gateway):
        self.gateway = gateway
        self._invocations = {}

    @property
    def running(self):
        """Whether any LLM session is still running."""
        return any(not item.task.done() for item in self._invocations.values())

    @staticmethod
    def _key(identity, metadata):
        if not isinstance(identity, str) or not identity or len(identity) > 256:
            raise ValueError("Invalid LLM invocation identity")
        return metadata["run_id"], identity

    @staticmethod
    def _history(history):
        if not isinstance(history, list):
            raise TypeError("LLM history must be a list")
        for item in history:
            if (
                not isinstance(item, dict)
                or set(item) != {"call_id", "name", "arguments", "result", "error"}
                or not isinstance(item["call_id"], str)
                or not isinstance(item["name"], str)
                or not isinstance(item["arguments"], dict)
                or (item["error"] is not None and not isinstance(item["error"], str))
            ):
                raise ValueError("Invalid completed tool call")
        return json.loads(json.dumps(history, allow_nan=False))

    @staticmethod
    def _acknowledge(invocation, history):
        """Resolve a pending provider callback only when workflow history matches the delivered call."""
        if history == invocation.history:
            return
        event = invocation.delivered
        if (
            not event
            or event["kind"] != "tool_call"
            or len(history) != len(invocation.history) + 1
            or history[:-1] != invocation.history
            or any(history[-1][key] != value for key, value in event["call"].items())
        ):
            raise ValueError("Tool response does not match the pending invocation")
        completed = history[-1]
        future = invocation.pending.pop(completed["call_id"])
        if not future.done():
            future.set_result(completed)
        invocation.history = history
        invocation.delivered = None

    async def next(self, payload, metadata):
        """Accept the result of the previous tool call; return the model's next tool call or final response."""
        key = self._key(payload["invocation_id"], metadata)
        history = self._history(payload.get("history", []))
        request = json.loads(json.dumps(payload["request"], allow_nan=False))
        if not isinstance(request, dict) or any(key.startswith("_") for key in request):
            raise ValueError("Invalid Program model request")
        if not isinstance(request.get("prompt"), str):
            raise TypeError("LLM prompt must be a string")
        if metadata["program"]["role"] == "model":
            request["mode"] = "model"
        mode = request.get("mode", "model")
        if mode not in {"model", "exec"} or request.get("native_coding"):
            raise PermissionError("Program LLM calls only expose their declared tools")
        definitions = [ToolDefinition(**item) for item in request.get("tools", [])]
        if any(
            not isinstance(item.name, str)
            or not item.name
            or not isinstance(item.input_schema, dict)
            or type(item.read_only) is not bool
            for item in definitions
        ):
            raise ValueError("Invalid LLM tool definition")
        names = {item.name for item in definitions}
        if len(names) != len(definitions):
            raise ValueError("LLM tool names must be unique")
        if mode == "model" and any(not item.read_only for item in definitions):
            raise PermissionError("Model calls cannot expose action tools")
        limit = payload.get("max_tool_calls", 40)
        if type(limit) is not int or not 1 <= limit <= 1000 or len(history) > limit:
            raise ValueError("Invalid LLM tool-call limit")
        invocation = self._invocations.get(key)
        if invocation is None:
            invocation = _Invocation(request, dict(metadata), limit, history, calls=len(history))
            self._invocations[key] = invocation
            invocation.task = asyncio.create_task(
                self._produce(invocation, {item.name: item for item in definitions})
            )
        elif request != invocation.request or limit != invocation.limit:
            raise ValueError("An active LLM invocation cannot change its request")
        if invocation.closing:
            raise RuntimeError("LLM invocation is closing")
        async with invocation.lock:
            self._acknowledge(invocation, history)
            if invocation.delivered is None:
                invocation.delivered = await invocation.queue.get()
            event = invocation.delivered
            if event["kind"] == "error":
                raise RuntimeError(event["error"])
            return event

    async def _produce(self, invocation, definitions):
        """Bridge provider tool callbacks to workflow events, restoring the transcript after restart."""
        from evertree.common.structured import validate

        async def handle_tool(name, arguments):
            if invocation.closing:
                raise RuntimeError("LLM invocation has finished; end your response now")
            if invocation.calls >= invocation.limit:
                await invocation.queue.put(
                    {"kind": "tool_limit", "error": "LLM dialogue exhausted its tool-call limit"}
                )
                raise RuntimeError("LLM dialogue exhausted its tool-call limit")
            invocation.calls += 1
            if name not in definitions:
                raise PermissionError("Tool was not declared")
            if not isinstance(arguments, dict):
                raise TypeError("Tool arguments must be an object")
            validate(arguments, definitions[name].input_schema)
            call = {
                "call_id": uuid4().hex,
                "name": name,
                "arguments": json.loads(json.dumps(arguments, allow_nan=False)),
            }
            future = asyncio.get_running_loop().create_future()
            invocation.pending[call["call_id"]] = future
            event = {"kind": "tool_call", "call": call}
            if current_read_context.get() is not None:
                event["read_context"] = dict(current_read_context.get())
            await invocation.queue.put(event)
            completed = await future
            if completed["error"] is not None:
                raise RuntimeError(completed["error"])
            return completed["result"]

        request = dict(invocation.request)
        if invocation.history:
            # SDK sessions are transient. A restarted worker replays its callbacks
            # first, then supplies these completed results to a fresh model call.
            request["prompt"] += (
                "\n\nExecution resumed after interruption. These tool calls have already "
                "completed. Use their results and continue the remaining work; do not "
                "repeat completed changes.\n"
                + json.dumps(invocation.history, ensure_ascii=False, allow_nan=False)
            )
        try:
            result = await self.gateway(
                "llm.run",
                {
                    **request,
                    "_runtime": invocation.metadata,
                    "_tool_handler": handle_tool,
                },
            )
            await invocation.queue.put({"kind": "completed", "result": result})
        except asyncio.CancelledError:
            invocation.error = "Provider invocation was interrupted"
            invocation.queue.put_nowait({"kind": "error", "error": invocation.error})
            raise
        except Exception as error:  # noqa: BLE001 -- provider failure crosses the worker boundary
            invocation.error = f"{type(error).__name__}: {error}"
            await invocation.queue.put({"kind": "error", "error": invocation.error})

    async def close(self, identity, metadata, *, history=None, drain=False):
        """Finish an invocation, optionally draining final provider events after a terminal tool."""
        key = self._key(identity, metadata)
        invocation = self._invocations.get(key)
        if invocation is None:
            return
        try:
            invocation.closing = True
            if history is not None:
                self._acknowledge(invocation, self._history(history))
            if drain:
                # Parallel native calls may already be waiting behind the terminal
                # call. Reject them before draining so the provider can finish.
                for future in invocation.pending.values():
                    if not future.done():
                        future.set_result(
                            {
                                "result": None,
                                "error": "LLM invocation has finished; end your response now",
                            }
                        )
                invocation.pending.clear()
                # Let the provider deliver final usage after a successful terminal
                # tool. User cancellation still cancels this task immediately.
                try:
                    await invocation.task
                except asyncio.CancelledError as error:
                    if asyncio.current_task().cancelling():
                        raise
                    # A cancelled provider is an operation failure, not cancellation
                    # of the RPC responder; the worker still needs its error reply.
                    raise RuntimeError("Provider invocation was interrupted") from error
                if invocation.error:
                    raise RuntimeError(invocation.error)
        finally:
            self._invocations.pop(key, None)
            await self._stop(invocation)

    @staticmethod
    async def _stop(invocation):
        for future in invocation.pending.values():
            future.cancel()
        invocation.task.cancel()
        await asyncio.gather(invocation.task, return_exceptions=True)

    async def close_all(self):
        """Cancel all transient model invocations and their pending tool calls."""
        invocations, self._invocations = self._invocations, {}
        await asyncio.gather(*(self._stop(item) for item in invocations.values()))
