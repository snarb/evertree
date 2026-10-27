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


async def predict(
    ctx: ProgramContext, program: str | int, arguments: dict, *, context: dict
) -> Any:
    """Call a model Program and index its declared forecasts for later matching.

    context is {process_id, subject, episode, conditions?}: observations reported
    with the same context are matched to these forecasts. Returns the model's result.
    """
    output = await ctx.call(program, arguments)
    await ctx.step("evaluation.index_forecasts", {"program": program, "context": context})
    return output.result


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


# Aggregates are journaled: experience keeps growing, and a replayed run must see the
# same result it acted on.


async def explanatory_tension(
    ctx: ProgramContext, period: list[str], processes: list[str | int]
) -> dict:
    """Mean calibrated unexpectedness in [start, end) over processes and their subtypes.

    Returns {value, by_process, skipped, period}; value is None without covered processes.
    """
    return await ctx.step(
        "evaluation.explanatory_tension", {"period": period, "processes": processes}
    )


async def tension_reduction(
    ctx: ProgramContext,
    period: list[str],
    processes: list[str | int],
    baseline_period: list[str] | None = None,
) -> dict:
    """Change of ExplanatoryTension against the baseline; positive means tension decreased.

    by_process and skipped show composition and coverage; inspect them before any
    conclusion. A trend alone proves neither improvement nor a causal effect.
    """
    return await ctx.step(
        "evaluation.tension_reduction",
        {"period": period, "processes": processes, "baseline_period": baseline_period},
    )


async def supervisor_feedback(
    ctx: ProgramContext, period: list[str], processes: list[str | int]
) -> dict:
    """Supervisor evaluations in [start, end) with their comments, per process."""
    return await ctx.step("evaluation.feedback", {"period": period, "processes": processes})


async def task_outcome_stats(
    ctx: ProgramContext, period: list[str], processes: list[str | int]
) -> dict:
    """Task success_rate and on_time_rate with numerators, denominators and omissions."""
    return await ctx.step("tasks.outcome_stats", {"period": period, "processes": processes})
