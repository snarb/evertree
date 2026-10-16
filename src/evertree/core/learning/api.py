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
    return await ctx.step("learning.prepare", {"credit": credit})


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

    likelihoods are keyed by scope alternatives or binary false/true. Core always
    treats them as unsupported influence, since the source does not validate them.
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


async def call_credit_assignment(
    ctx: ProgramContext, *, target: str, observation_ids: list[str], context: dict
) -> Any:
    """Run the credit_assignment Program and return its result.

    Contract Program: see CALLED_PROGRAMS in evertree.core.contracts.
    """
    arguments = {"target": target, "observation_ids": observation_ids, "context": context}
    return (await ctx.call("credit_assignment", arguments)).result
