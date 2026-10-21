"""Typed policy boundary for Programs: build, check and sample action distributions."""

from __future__ import annotations

from typing import Any

from ..contracts import ProgramContext
from .contracts import (
    certain,
    greedy_distribution,
    probability_of,
    softmax_distribution,
    validate_distribution,
)

__all__ = [
    "certain",
    "greedy_distribution",
    "probability_of",
    "sample_action",
    "softmax_distribution",
    "validate_distribution",
]


async def sample_action(
    ctx: ProgramContext, distribution: dict, allowed: list | None = None
) -> Any:
    """Let Core check and sample a distribution; the saved choice replays on recovery.

    Returns the chosen candidate. A violated contract raises instead of choosing.
    """
    result = await ctx.step("policy.sample", {"distribution": distribution, "allowed": allowed})
    return result["candidate"]
