"""Typed Program access to credit assignment, evidence and protected learning."""

from __future__ import annotations

from typing import Any

from ..contracts import ProgramContext


async def credit(
    ctx: ProgramContext,
    target: str,
    *,
    signal: dict | None = None,
    ambiguous: bool = False,
    observation_ids: list[str] | None = None,
    context: dict | None = None,
) -> Any:
    """Assign learning credit to target; without signal the observations stay unresolved."""
    return await ctx.step(
        "learning.credit",
        {
            "target": target,
            "signal": signal,
            "ambiguous": ambiguous,
            "observation_ids": observation_ids or [],
            "context": context or {},
        },
    )


async def prepare(ctx: ProgramContext, credit: dict) -> Any:
    """Plan a compatible estimator update for resolved credit without applying it."""
    return await ctx.step("learning.prepare", {"credit": credit}, journal=False)


async def learn(
    ctx: ProgramContext,
    signal: dict,
    target: str,
    *,
    context: dict | None = None,
    attribution_weight: float = 1.0,
    ambiguous: bool = False,
) -> Any:
    """Apply a learning signal through credit assignment, planning and a transactional update."""
    return await ctx.step(
        "learning.learn",
        {
            "signal": signal,
            "target": target,
            "context": context or {},
            "attribution_weight": attribution_weight,
            "ambiguous": ambiguous,
        },
    )


async def assess_evidence(
    ctx: ProgramContext,
    target: str,
    source_ref: dict,
    likelihoods: dict,
    *,
    dependency_root: str | None = None,
) -> Any:
    """Submit source likelihoods for a declared belief target.

    likelihoods are keyed by scope alternatives or binary false/true. Core caps their
    influence as unsupported, since a stored source does not validate the likelihood model.
    """
    return await ctx.step(
        "evidence.assess",
        {
            "target": target,
            "source_ref": source_ref,
            "likelihoods": likelihoods,
            "dependency_root": dependency_root,
        },
    )


async def pending_evidence(
    ctx: ProgramContext,
    *,
    experience_refs: list | None = None,
    candidates: list[int] | None = None,
    limit: int = 24,
    related_limit: int = 16,
) -> Any:
    """Read one batch of graph elements awaiting evidence assessment.

    Returns {revision, sources, targets, related, remaining}. Sources are primary
    experience keyed S1, S2, …; agent-derived results are expanded to what they cite.
    candidates are element ids, such as search results, to offer as related targets.
    """
    return await ctx.step(
        "evidence.pending",
        {
            "experience_refs": experience_refs or [],
            "candidates": candidates or [],
            "limit": limit,
            "related_limit": related_limit,
        },
    )


async def record_evidence(
    ctx: ProgramContext,
    element: int,
    revision: int,
    *,
    prior: float | None = None,
    assign: list[dict] | None = None,
    retract: list[dict] | None = None,
) -> Any:
    """Record assessed evidence for one graph element and mark it assessed at revision.

    assign items are {source_ref, likelihoods: {false, true}, dependency_root?}; retract
    lists source refs whose active contribution no longer applies. prior is used only
    when the element's target is first registered; Core caps its unsupported influence.
    """
    return await ctx.step(
        "evidence.record",
        {
            "element": element,
            "revision": revision,
            "prior": prior,
            "assign": assign or [],
            "retract": retract or [],
        },
    )


async def call_credit_assignment(
    ctx: ProgramContext, *, target: str, observation_ids: list[str], context: dict
) -> Any:
    """Run the credit_assignment Program and return its result.

    Contract Program: see CALLED_PROGRAMS in evertree.core.contracts.
    """
    arguments = {"target": target, "observation_ids": observation_ids, "context": context}
    return (await ctx.call("credit_assignment", arguments)).result
