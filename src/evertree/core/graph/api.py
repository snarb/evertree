"""Typed Program access to semantic graph reads."""

from __future__ import annotations

from typing import Any

from ..contracts import ProgramContext


async def describe(ctx: ProgramContext, subject: str | int) -> Any:
    """Describe one graph subject with its properties and relations."""
    return await ctx.step("graph.describe", {"subject": subject})


async def read(ctx: ProgramContext, name: str, arguments: dict) -> Any:
    """Run a graph read tool (for example query, walk or read_property) by name with its arguments."""
    return await ctx.step("graph." + name, arguments)
