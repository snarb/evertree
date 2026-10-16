"""Typed Program boundaries with the outside world: LLM, observations, actions and trace.

Program code is ordinary async Python. Only these boundaries, Core operations and
child Program calls survive a worker restart; local computation reruns on recovery.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..contracts import ProgramContext


async def llm(
    ctx: ProgramContext, prompt: str, *, instructions: str, output_schema: dict, mode: str = "model"
) -> dict:
    """Run one tool-free LLM request; the response carries text and, when valid, parsed."""
    return await ctx.step(
        "llm.run",
        {
            "prompt": prompt,
            "instructions": instructions,
            "mode": mode,
            "output_schema": output_schema,
        },
    )


async def llm_with_tools(
    ctx: ProgramContext,
    prompt: str,
    *,
    instructions: str,
    tools,
    tool_handler: Callable[[str, dict], Awaitable[Any]],
    mode: str = "exec",
    profile: str | None = None,
    max_tool_calls: int = 40,
    stop_when: Callable[[str, Any], bool] | None = None,
) -> Any:
    """Let the LLM work on prompt while calling tools served by tool_handler in Program code.

    Returns the final response, or {"tool", "result"} once stop_when accepts a successful
    tool result. ValueError, TypeError and PermissionError from the handler are reported
    to the model; other errors fail the call. The handler may use any Core API function.
    """
    # Not one step: each model exchange is saved separately so handler operations replay.
    payload = {"mode": mode, "instructions": instructions, "prompt": prompt}
    if profile is not None:
        payload["profile"] = profile
    return await ctx.llm(
        payload,
        tools=tools,
        tool_handler=tool_handler,
        max_tool_calls=max_tool_calls,
        stop_when=stop_when,
    )


async def next_observation(ctx: ProgramContext, *, timeout_seconds: float = 60) -> Any:
    """Wait for the next observation delivered to this exec Program run.

    Already delivered observations return immediately and in delivery order. Returns
    None when timeout_seconds pass without one; that does not mean the source ended.
    """
    return await ctx.next_observation(timeout_seconds)


async def list_actions(ctx: ProgramContext, session: str) -> Any:
    """List the external commands currently offered by a live action session."""
    return await ctx.step("actions.list", {"session": session})


async def take_action(
    ctx: ProgramContext, session: str, command: Any, *, operation_id: str | None = None
) -> Any:
    """Execute an offered external command after user approval; live runs only.

    operation_id deduplicates the action across retries. By default it is derived from
    the run and the action's order in it, which stays stable when the run is recovered.
    """
    if operation_id is None:
        ctx._action_sequence = getattr(ctx, "_action_sequence", 0) + 1
        operation_id = f"{ctx.run_id}:action:{ctx._action_sequence}"
    return await ctx.step(
        "actions.take", {"session": session, "command": command, "operation_id": operation_id}
    )


async def emit(ctx: ProgramContext, operator: str, *, arguments=None, output=None) -> Any:
    """Record a semantic trace event for an operation performed by this Program."""
    return await ctx.emit(operator, arguments=arguments, output=output)


async def checkpoint(ctx: ProgramContext) -> Any:
    """Yield a durable coordination boundary to Core, for example between long work chunks."""
    return await ctx.checkpoint()
