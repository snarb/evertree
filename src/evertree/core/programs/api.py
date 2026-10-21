"""Typed lifecycle boundary for meta Programs.

Only an exec Program with the meta role may call these, and only in live runs.
Each call is a saved step, so a recovered run replays its lifecycle decisions.
Core serves them with the same rules as the conscious agent's tools: it never
lets a meta Program manage its own candidates or change acceptance criteria.
"""

from __future__ import annotations

from typing import Any

from ..contracts import ProgramContext


async def list_programs(ctx: ProgramContext) -> list[dict]:
    """List Programs with their process, role, lifecycle status and alternatives."""
    return await ctx.step("program.list_programs", {})


async def propose_program(
    ctx: ProgramContext,
    name: str,
    *,
    role: str,
    claim: str,
    description: str,
    candidate_name: str,
    parent: int | str | None = None,
    alternative_to: int | None = None,
) -> dict:
    """Propose a new process role or an alternative Program; returns the Program and candidate."""
    payload = {
        "name": name,
        "role": role,
        "claim": claim,
        "description": description,
        "candidate_name": candidate_name,
    }
    if parent is not None:
        payload["parent"] = parent
    if alternative_to is not None:
        payload["alternative_to"] = alternative_to
    return await ctx.step("program.propose_program", payload)


async def create_candidate(
    ctx: ProgramContext, program: int, *, claim: str, candidate_name: str
) -> dict:
    """Open a candidate branch of an existing Program for one testable change claim."""
    return await ctx.step(
        "program.create_candidate",
        {"program": program, "claim": claim, "candidate_name": candidate_name},
    )


async def develop_candidate(ctx: ProgramContext, candidate: str, instruction: str) -> dict:
    """Let the coding provider implement the candidate; Core commits and retains the change."""
    return await ctx.step(
        "program.develop_candidate", {"candidate": candidate, "instruction": instruction}
    )


async def evaluate_candidate(ctx: ProgramContext, candidate: str) -> dict:
    """Run the protected holdout; the result carries metrics and verification, never cases."""
    return await ctx.step("program.evaluate_candidate", {"candidate": candidate})


async def compare_candidates(ctx: ProgramContext, candidates: list[str]) -> dict:
    """Rank evaluated candidates of one slot on its target metric."""
    return await ctx.step("program.compare_candidates", {"candidates": candidates})


async def refresh_candidate(ctx: ProgramContext, candidate: str) -> dict:
    """Reopen a paused or stale candidate on the current main."""
    return await ctx.step("program.refresh_candidate", {"candidate": candidate})


async def choose_candidate(
    ctx: ProgramContext, candidate: str, decision: str, *, reason: str
) -> Any:
    """Record an EvaluationChoice; Core still enforces acceptance gates for activation."""
    return await ctx.step(
        "program.choose_candidate",
        {"candidate": candidate, "decision": decision, "reason": reason},
    )


async def derive_holdout(ctx: ProgramContext, program: int) -> dict:
    """Extend a slot's holdout with unseen live outcomes; returns only counts and the revision."""
    return await ctx.step("program.derive_holdout", {"program": program})
