"""Typed Program boundaries: child Programs, LLM, observations, actions and checkpoints.

Program code is ordinary async Python. Only these boundaries, Core operations and
child Program calls survive a worker restart; local computation reruns on recovery.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..contracts import ProgramContext, ProgramResult


async def call_program(
    ctx: ProgramContext, program: str | int, arguments: dict | None = None
) -> ProgramResult:
    """Run another Program by name, slug or id as a child workflow at the same revision.

    A model Program can only call model Programs.
    """
    return await ctx.call(program, arguments)


async def llm(ctx: ProgramContext, prompt: str, *, instructions: str, output_schema: dict) -> dict:
    """Run one tool-free LLM request; the response carries text and, when valid, parsed."""
    return await ctx.step(
        "llm.run",
        {
            "prompt": prompt,
            "instructions": instructions,
            "mode": "model",
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
    profile: str | None = None,
    max_tool_calls: int = 40,
    stop_when: Callable[[str, Any], bool] | None = None,
) -> Any:
    """Let the LLM work on prompt while calling tools served by tool_handler in Program code.

    Returns the final response, or {"tool", "result"} once stop_when accepts a successful
    tool result. ValueError, TypeError and PermissionError from the handler are reported
    to the model; other errors fail the call. The handler may use any Core API function.
    Core limits a model Program to read-only tools. profile selects a configured model
    profile ("remember").
    """
    # Not one step: each model exchange is saved separately so handler operations replay.
    payload = {"mode": "exec", "instructions": instructions, "prompt": prompt}
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


async def checkpoint(ctx: ProgramContext) -> Any:
    """Give Core a point to pause for backup or stop a cancelled run, e.g. in long local work.

    It saves no local state: recovery still reruns the local computation.
    """
    return await ctx.checkpoint()
