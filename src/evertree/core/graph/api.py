"""Typed Program access to semantic graph reads."""

from __future__ import annotations

from typing import Any

from ..contracts import ProgramContext


async def describe(ctx: ProgramContext, subject: str | int) -> Any:
    """Describe one graph subject with its properties and relations."""
    return await ctx.step("graph.describe", {"subject": subject})


async def read(ctx: ProgramContext, name: str, arguments: dict) -> Any:
    """Run the graph read tool name (for example query or walk) with its tool arguments.

    Core validates arguments against the same schema it publishes as the LLM tool.
    """
    return await ctx.step("graph." + name, arguments)
