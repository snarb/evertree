"""Typed Program access to retained experience."""

from __future__ import annotations

from typing import Any

from ..contracts import ProgramContext
from ..tokens import current_read_context


async def retrieve(ctx: ProgramContext, query: str, *, limit: int = 10) -> Any:
    """Retrieve a bounded set of retained experience groups matching query."""
    return await ctx.step("memory.retrieve", {"query": query, "limit": limit}, journal=False)


async def read_source(
    ctx: ProgramContext,
    reference: dict | None = None,
    *,
    next_page: bool = False,
    _read_context: dict | None = None,
) -> Any:
    """Read an exact retained fragment, continuing oversized content without ranking."""
    payload = {"reference": reference, "next_page": next_page}
    context = _read_context or current_read_context.get()
    if context is not None:
        payload["_read_context"] = context
    return await ctx.step("memory.read_source", payload, journal=False)
