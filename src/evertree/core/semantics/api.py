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

    experience_refs address original trace outputs; focus prioritizes attention without
    excluding other source assertions.
    """
    return await ctx.step("semantic.sources", {"experience_refs": experience_refs, "focus": focus})


async def prepare_sources(
    ctx: ProgramContext, experience_refs: list, sections: list[dict], *, focus: str | None = None
) -> SourceMaterial:
    """Retain exact source sections with parent context, replaying their saved references."""
    return await ctx.step(
        "semantic.prepare_sources",
        {"experience_refs": experience_refs, "sections": sections, "focus": focus},
    )


async def lookup(
    ctx: ProgramContext, queries: list[str | int], *, kinds: list[str] | None, limit: int
) -> Any:
    """Return a merged exact batch, or None if any query needs indexed retrieval."""
    return await ctx.step(
        "semantic.lookup", {"queries": queries, "kinds": kinds, "limit": limit}, journal=False
    )


async def bm25(ctx: ProgramContext, queries: list[str | int], *, kinds: list[str] | None) -> list:
    """Rank each unresolved query's object IDs in one lexical batch."""
    return await ctx.step("semantic.bm25", {"queries": queries, "kinds": kinds}, journal=False)


async def vector(ctx: ProgramContext, queries: list[str | int], *, kinds: list[str] | None) -> list:
    """Rank unresolved queries with batched embeddings and vector retrieval."""
    return await ctx.step("semantic.vector", {"queries": queries, "kinds": kinds}, journal=False)


async def results(
    ctx: ProgramContext,
    queries: list[str | int],
    *,
    kinds: list[str] | None,
    rankings: list[dict],
    limit: int,
) -> Any:
    """Have Core validate, optionally filter and merge the per-query fused rankings."""
    return await ctx.step(
        "semantic.results",
        {"queries": queries, "kinds": kinds, "rankings": rankings, "limit": limit},
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


async def summarize_property(
    ctx: ProgramContext,
    domain: str | int,
    property: str | int,
    *,
    value: float | None = None,
    unit: str | None = None,
    reference: str | int | None = None,
    at: str | None = None,
    parameters: dict | None = None,
) -> Any:
    """Read separate observed statistics and source-backed references for a numeric property."""
    return await ctx.step(
        "graph.summarize_property",
        {
            "domain": domain,
            "property": property,
            "value": value,
            "unit": unit,
            "reference": reference,
            "at": at,
            "parameters": parameters,
        },
        journal=False,
    )


async def call_semantic_search(
    ctx: ProgramContext,
    queries: list[str | int],
    *,
    kinds: list[str] | None = None,
    limit: int = 10,
) -> Any:
    """Run the semantic_search Program and return its result.

    Contract Program: see CALLED_PROGRAMS in evertree.core.contracts.
    """
    arguments = {"queries": queries}
    if kinds is not None:
        arguments["kinds"] = kinds
    if limit != 10:
        arguments["limit"] = limit
    return (await ctx.call("semantic_search", arguments)).result


async def refresh_property_norms(ctx: ProgramContext) -> Any:
    """Fit stale learned norms once after an acquisition batch, leaving reads effect-free."""
    return await ctx.step("attribution.refresh_norms", {})
