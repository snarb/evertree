"""Typed Program access to semantic retrieval and knowledge integration."""

from __future__ import annotations

from typing import Any, TypedDict

from ..contracts import ProgramContext


class SourceMaterial(TypedDict):
    experience: list[dict]
    focus: str | None
    context: dict


async def load_sources(
    ctx: ProgramContext, experience_refs: list, *, focus: str | None = None
) -> SourceMaterial:
    """Authorize integration and resolve retained experience with its producer provenance.

    experience_refs address original trace outputs; focus optionally narrows attention.
    """
    return await ctx.step("semantic.sources", {"experience_refs": experience_refs, "focus": focus})


async def lookup(ctx: ProgramContext, query: str, *, kind: str | None, limit: int) -> Any:
    """Return exact graph matches for query, or None when no exact identity matches."""
    return await ctx.step(
        "semantic.lookup", {"query": query, "kind": kind, "limit": limit}, journal=False
    )


async def bm25(ctx: ProgramContext, query: str, *, kind: str | None) -> list:
    """Rank object ids by the lexical index."""
    return await ctx.step("semantic.bm25", {"query": query, "kind": kind}, journal=False)


async def vector(ctx: ProgramContext, query: str, *, kind: str | None) -> list:
    """Rank object ids by the vector index."""
    return await ctx.step("semantic.vector", {"query": query, "kind": kind}, journal=False)


async def results(
    ctx: ProgramContext,
    query: str,
    *,
    kind: str | None,
    items: list[dict],
    errors: list[dict],
    limit: int,
) -> Any:
    """Submit fused ranks for Core to re-check and render as search results.

    items are {"id", "channels"} in fused order; errors report failed index channels.
    """
    return await ctx.step(
        "semantic.results",
        {
            "query": query,
            "kind": kind,
            "items": items,
            "errors": errors,
            "limit": limit,
        },
        journal=False,
    )


async def write(
    ctx: ProgramContext, action: dict, *, operation_key: str, experience_refs: list
) -> Any:
    """Validate and persist one source-backed semantic operation.

    operation_key deduplicates durable retries of the same operation.
    """
    return await ctx.step(
        "semantic.write",
        {"action": action, "operation_key": operation_key, "experience_refs": experience_refs},
    )


async def call_semantic_search(ctx: ProgramContext, query: str) -> Any:
    """Run the semantic_search Program and return its result.

    Contract Program: see CALLED_PROGRAMS in evertree.core.contracts.
    """
    return (await ctx.call("semantic_search", {"query": query})).result
