"""Protected verification and fixed Program acceptance criteria."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .contracts import _number


@dataclass(frozen=True)
class VerificationResult:
    status: str
    reasons: tuple[str, ...] = ()
    missing_checks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"verified", "failed", "need_checks"}:
            raise ValueError("Unknown verification status")

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reasons": list(self.reasons),
            "missing_checks": list(self.missing_checks),
        }


@dataclass(frozen=True)
class MetricGuardrail:
    metric: str
    direction: str = "maximize"
    threshold: float | None = None
    max_regression: float = 0.0

    def __post_init__(self) -> None:
        if self.direction not in {"minimize", "maximize"}:
            raise ValueError("Unknown metric direction")
        if _number(self.max_regression) < 0:
            raise ValueError("Regression tolerance cannot be negative")
        if self.threshold is not None:
            _number(self.threshold)


@dataclass(frozen=True)
class AcceptanceCriteria:
    required_checks: tuple[str, ...]
    target_metric: str | None = None
    direction: str = "maximize"
    threshold: float | None = None
    min_improvement: float = 0.0
    guardrails: tuple[MetricGuardrail, ...] = ()
    require_independent: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_checks", tuple(self.required_checks))
        object.__setattr__(self, "guardrails", tuple(self.guardrails))
        if self.direction not in {"minimize", "maximize"}:
            raise ValueError("Unknown criterion direction")
        if _number(self.min_improvement) < 0:
            raise ValueError("Minimum improvement cannot be negative")
        if self.threshold is not None:
            _number(self.threshold)
        if not self.required_checks:
            raise ValueError("Acceptance needs at least one mandatory check")


def assess_candidate(
    *,
    criteria: AcceptanceCriteria,
    checks: Mapping[str, bool | None],
    candidate_metrics: Mapping[str, float],
    baseline_metrics: Mapping[str, float] | None = None,
    independent: bool = False,
    uncertainty: Mapping[str, tuple[float, float]] | None = None,
) -> VerificationResult:
    """A fixed veto procedure; passing never itself accepts or activates a candidate.

    When supplied, uncertainty intervals describe *candidate minus baseline*.
    A lower bound on practically relevant improvement must pass, not just its
    optimistic point estimate. The evaluator owns the statistical assumptions.
    """
    failures: list[str] = []
    missing: list[str] = []
    for name in criteria.required_checks:
        if checks.get(name) is False:
            failures.append(f"Mandatory check failed: {name}")
        elif checks.get(name) is not True:
            missing.append(name)
    if criteria.require_independent and not independent:
        missing.append("independent_evaluation")
    if criteria.target_metric:
        metric = criteria.target_metric
        if metric not in candidate_metrics:
            missing.append(metric)
        else:
            candidate = _number(candidate_metrics[metric])
            sign = 1 if criteria.direction == "maximize" else -1
            if criteria.threshold is not None and sign * (candidate - criteria.threshold) < 0:
                failures.append(f"Target criterion failed: {metric}")
            if baseline_metrics is not None:
                if metric not in baseline_metrics:
                    missing.append("baseline:" + metric)
                else:
                    improvement = sign * (candidate - _number(baseline_metrics[metric]))
                    if uncertainty and metric in uncertainty:
                        lower, upper = map(_number, uncertainty[metric])
                        if lower > upper:
                            raise ValueError("Invalid improvement uncertainty interval")
                        improvement = lower if sign == 1 else -upper
                    if improvement < criteria.min_improvement or (
                        criteria.min_improvement == 0 and improvement <= 0
                    ):
                        failures.append(f"Improvement criterion failed: {metric}")
            elif criteria.threshold is None:
                missing.append("target_threshold_or_baseline")
    for guardrail in criteria.guardrails:
        metric = guardrail.metric
        if metric not in candidate_metrics:
            missing.append("guardrail:" + metric)
            continue
        candidate = _number(candidate_metrics[metric])
        sign = 1 if guardrail.direction == "maximize" else -1
        if guardrail.threshold is not None and sign * (candidate - guardrail.threshold) < 0:
            failures.append(f"Guardrail threshold failed: {metric}")
        if baseline_metrics is not None:
            if metric not in baseline_metrics:
                missing.append("baseline_guardrail:" + metric)
            else:
                improvement = sign * (candidate - _number(baseline_metrics[metric]))
                if uncertainty and metric in uncertainty:
                    lower, upper = map(_number, uncertainty[metric])
                    if lower > upper:
                        raise ValueError("Invalid guardrail uncertainty interval")
                    improvement = lower if sign == 1 else -upper
                if improvement < -guardrail.max_regression:
                    failures.append(f"Guardrail regression: {metric}")
    if failures:
        return VerificationResult("failed", tuple(failures), tuple(missing))
    if missing:
        return VerificationResult("need_checks", (), tuple(dict.fromkeys(missing)))
    return VerificationResult("verified")
