"""Choose automatic control or consciousness while preserving verification gates."""

from evertree.core.cognition.control import commitment_control
from evertree.core.evaluation.acceptance import VerificationResult


def run(
    familiar: bool,
    verification: dict | None = None,
    uncertainty: bool = False,
    high_impact: bool = False,
):
    """Choose automatic execution or conscious selection from verification, familiarity and risk."""
    check = VerificationResult(**verification) if verification else None
    decision = commitment_control(
        verified=check, familiar=familiar, uncertainty=uncertainty, high_impact=high_impact
    )
    return {"result": {"mode": decision.mode, "reason": decision.reason}, "feedback": None}
