"""Choose automatic control or consciousness while preserving verification gates."""

from evertree.core.cognition import commitment_control
from evertree.core.evaluation import VerificationResult


def run(
    familiar: bool,
    verification: dict | None = None,
    uncertainty: bool = False,
    high_impact: bool = False,
):
    check = VerificationResult(**verification) if verification else None
    decision = commitment_control(
        verified=check, familiar=familiar, uncertainty=uncertainty, high_impact=high_impact
    )
    return {"result": {"mode": decision.mode, "reason": decision.reason}, "feedback": None}
