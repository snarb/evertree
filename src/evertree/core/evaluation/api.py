"""Typed Program access to prediction matching and review."""

from __future__ import annotations

from typing import Any, TypedDict

from ..contracts import ProgramContext


class UnmatchedCase(TypedDict):
    reason: str
    target: str
    observation_ids: list[str]
    context: dict
    parts: list


class MatchBatch(TypedDict):
    results: list
    unmatched: list[UnmatchedCase]


async def match(
    ctx: ProgramContext,
    observations: list[int],
    *,
    context: dict,
    metrics: list[str],
    selected_targets: list[str | int] | None = None,
) -> MatchBatch:
    """Match retained predictions to observations and score the matched outcomes."""
    return await ctx.step(
        "evaluation.match",
        {
            "observations": observations,
            "context": context,
            "metrics": metrics,
            "selected_targets": selected_targets or [],
        },
    )


async def review(ctx: ProgramContext, *, cases: list[UnmatchedCase], credits: list) -> Any:
    """Route unmatched prediction cases and their credit results to review."""
    return await ctx.step("evaluation.review", {"cases": cases, "credits": credits})
