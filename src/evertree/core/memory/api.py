"""Typed Program access to retained experience."""

from __future__ import annotations

from typing import Any

from ..contracts import ProgramContext


async def retrieve(ctx: ProgramContext, query: str, *, limit: int = 10) -> Any:
    """Retrieve a bounded set of retained experience groups matching query."""
    return await ctx.step("memory.retrieve", {"query": query, "limit": limit})
