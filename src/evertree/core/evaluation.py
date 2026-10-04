"""Evaluation contracts, proper scoring rules and protected acceptance checks.

Evaluation measures outcomes. It never activates a program or updates learning
state; those decisions belong to the caller and the protected lifecycle.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from .datasets import freeze_json, thaw_json


@dataclass(frozen=True)
class SupervisorFeedback:
    """External approval on its own channel; text never substitutes for its value."""

    value: float
    comment: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("Supervisor feedback must be a number in [-5, 5]")
        if not math.isfinite(self.value) or not -5 <= self.value <= 5:
            raise ValueError("Supervisor feedback must be a number in [-5, 5]")
        if self.comment is not None and not isinstance(self.comment, str):
            raise ValueError("Supervisor feedback comment must be text")
        object.__setattr__(self, "value", float(self.value))

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "comment": self.comment}


@dataclass(frozen=True)
class MetricSample:
    metric: str
    value: Any
    channel: str | None = None

    def __post_init__(self) -> None:
        if not self.metric:
            raise ValueError("A metric needs a definition")
        object.__setattr__(self, "value", freeze_json(thaw_json(self.value)))

    def to_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "value": thaw_json(self.value), "channel": self.channel}


@dataclass(frozen=True)
class EvaluationResult:
    status: str
    metric_samples: tuple[MetricSample, ...] = ()
    outcome_ids: tuple[str, ...] = ()
    evaluated_subject: str | None = None
    provenance: tuple[str, ...] = ()
    reason: str | None = None
    missing_requirements: tuple[str, ...] = ()
    skipped_metrics: Mapping[str, str] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    process_id: str | None = None
    observed_at: str | None = None
    comparison_key: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"evaluated", "not_applicable", "unresolved"}:
            raise ValueError("Unknown evaluation status")
        for name in ("metric_samples", "outcome_ids", "provenance", "missing_requirements"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "skipped_metrics", freeze_json(dict(self.skipped_metrics)))
        if self.status == "evaluated":
            if not self.metric_samples or not self.outcome_ids or not self.provenance:
                raise ValueError(
                    "Evaluated results require outcomes, metrics and a recoverable trace"
                )
        elif self.metric_samples or not self.reason:
            raise ValueError(
                "Unevaluated results need a reason and cannot contain calculated metrics"
            )

    def metrics(self) -> dict[str, Any]:
        return {sample.metric: thaw_json(sample.value) for sample in self.metric_samples}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "metric_samples": [sample.to_dict() for sample in self.metric_samples],
            "outcome_ids": list(self.outcome_ids),
            "evaluated_subject": self.evaluated_subject,
            "provenance": list(self.provenance),
            "reason": self.reason,
            "missing_requirements": list(self.missing_requirements),
            "skipped_metrics": thaw_json(self.skipped_metrics),
            "id": self.id,
            "process_id": self.process_id,
            "observed_at": self.observed_at,
            "comparison_key": self.comparison_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvaluationResult:
        values = dict(data)
        values["metric_samples"] = tuple(
            MetricSample(**sample) for sample in values.get("metric_samples", ())
        )
        status = values.pop("status")
        variants = {
            "evaluated": EvaluatedResult,
            "not_applicable": NotApplicableResult,
            "unresolved": UnresolvedEvaluationResult,
        }
        if status not in variants:
            raise ValueError("Unknown evaluation status")
        variant = variants[status]
        if cls is not EvaluationResult and cls is not variant:
            raise ValueError("Evaluation status does not match the requested result type")
        return variant(**values)


@dataclass(frozen=True)
class EvaluatedResult(EvaluationResult):
    """An outcome with calculated metrics and recoverable provenance."""

    status: Literal["evaluated"] = field(default="evaluated", init=False)


@dataclass(frozen=True)
class NotApplicableResult(EvaluationResult):
    """An explicitly inapplicable evaluation, never a zero-valued metric."""

    status: Literal["not_applicable"] = field(default="not_applicable", init=False)


@dataclass(frozen=True)
class UnresolvedEvaluationResult(EvaluationResult):
    """An evaluation blocked by missing outcomes, provenance or a valid metric."""

    status: Literal["unresolved"] = field(default="unresolved", init=False)


def exact_json_equal(left: Any, right: Any) -> bool:
    """Compare JSON values recursively, retaining boolean/number type boundaries."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        return (
            isinstance(left, Mapping)
            and isinstance(right, Mapping)
            and left.keys() == right.keys()
            and all(exact_json_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, (list, tuple)) or isinstance(right, (list, tuple)):
        return (
            isinstance(left, (list, tuple))
            and isinstance(right, (list, tuple))
            and len(left) == len(right)
            and all(exact_json_equal(a, b) for a, b in zip(left, right))
        )
    return left == right


def _number(value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("Expected a finite numeric value")
    return float(value)


def _probability(value: Any) -> float:
    result = _number(value)
    if not 0 <= result <= 1:
        raise ValueError("Probability must be in [0, 1]")
    return result


def _distribution(prediction: Any) -> dict[str, float]:
    if not isinstance(prediction, Mapping) or not prediction:
        raise ValueError("Expected a nonempty categorical distribution")
    result = {str(key): _probability(value) for key, value in prediction.items()}
    if not math.isclose(sum(result.values()), 1.0, rel_tol=0, abs_tol=1e-10):
        raise ValueError("Categorical probabilities must sum to one")
    return result


def prediction_unexpectedness(
    prediction: Any, observed: Any, *, calibration: Mapping[str, Any]
) -> float:
    """Conservative rarity 1 - P(T >= T_observed), including discrete ties.

    The supplied calibration rule is part of the immutable evaluation basis.
    Empirical calibration is allowed only with an explicit exchangeability
    assumption and pre-observation reference scores.
    """
    kind = calibration.get("kind")
    if kind == "bernoulli":
        p = _probability(prediction)
        if observed not in (0, 1, False, True):
            raise ValueError("Bernoulli outcomes must be binary")
        probabilities = (1 - p, p)
        actual = probabilities[int(observed)]
        tail = sum(prob for prob in probabilities if prob <= actual + 1e-14)
        return max(0.0, min(1.0, 1 - tail))
    if kind == "categorical":
        probabilities = _distribution(prediction)
        actual = probabilities.get(str(observed), 0.0)
        tail = sum(prob for prob in probabilities.values() if prob <= actual + 1e-14)
        return max(0.0, min(1.0, 1 - tail))
    if kind == "normal":
        mean, deviation = _number(prediction["mean"]), _number(prediction["stddev"])
        if deviation <= 0:
            raise ValueError("A normal model needs positive standard deviation")
        return math.erf(abs(_number(observed) - mean) / (deviation * math.sqrt(2)))
    if kind == "deterministic":
        return 0.0 if exact_json_equal(prediction, observed) else 1.0
    if kind == "empirical_rank":
        if calibration.get("exchangeable") is not True:
            raise ValueError("Rank calibration requires an explicit exchangeability assumption")
        scores = tuple(_number(score) for score in calibration.get("reference_scores", ()))
        if not scores:
            raise ValueError("No pre-observation calibration scores")
        discrepancy = abs(_number(observed) - _number(prediction))
        tail = (1 + sum(score >= discrepancy for score in scores)) / (len(scores) + 1)
        return 1 - tail
    raise ValueError("No supported calibration rule")


def evaluate_prediction(
    prediction: Any,
    observed: Any,
    *,
    metrics: tuple[str, ...],
    outcome_ids: tuple[str, ...],
    provenance: tuple[str, ...],
    subject: str | None = None,
    process_id: str | None = None,
    observed_at: str | None = None,
    calibration: Mapping[str, Any] | None = None,
    comparison_key: str | None = None,
    applicable: bool = True,
) -> EvaluatedResult | NotApplicableResult | UnresolvedEvaluationResult:
    if not applicable:
        return NotApplicableResult(
            reason="Prediction conditions did not apply",
            evaluated_subject=subject,
            provenance=provenance,
            process_id=process_id,
            observed_at=observed_at,
        )
    samples: list[MetricSample] = []
    skipped: dict[str, str] = {}
    if not outcome_ids or not provenance:
        return UnresolvedEvaluationResult(
            reason="Missing outcome or recoverable source trace",
            evaluated_subject=subject,
            missing_requirements=("outcome_and_trace",),
        )
    for metric in dict.fromkeys(metrics):
        try:
            channel = None
            if metric == "brier":
                p = _probability(prediction)
                if observed not in (0, 1, False, True):
                    raise ValueError("Brier outcome must be binary")
                value: Any = (p - int(observed)) ** 2
            elif metric in {"squared_error", "mse"}:
                value = (_number(prediction) - _number(observed)) ** 2
            elif metric in {"absolute_error", "mae"}:
                value = abs(_number(prediction) - _number(observed))
            elif metric == "residual":
                value = _number(observed) - _number(prediction)
            elif metric == "log_loss":
                if isinstance(prediction, Mapping):
                    probability = _distribution(prediction).get(str(observed), 0)
                else:
                    p = _probability(prediction)
                    if observed not in (0, 1, False, True):
                        raise ValueError("Binary probability needs a binary outcome")
                    probability = p if observed else 1 - p
                value = -math.log(probability) if probability > 0 else {"kind": "positive_infinity"}
            elif metric == "exact_match":
                value = float(exact_json_equal(prediction, observed))
            elif metric == "prediction_unexpectedness":
                if calibration is None:
                    raise ValueError("No supported pre-observation calibration norm")
                value = prediction_unexpectedness(prediction, observed, calibration=calibration)
                channel = metric
            else:
                raise ValueError("Unsupported metric")
            samples.append(MetricSample(metric, value, channel))
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            skipped[metric] = str(error)
    result_type = EvaluatedResult if samples else UnresolvedEvaluationResult
    return result_type(
        tuple(samples),
        outcome_ids,
        evaluated_subject=subject,
        provenance=provenance,
        reason=None if samples else "No requested metric could be calculated",
        skipped_metrics=skipped,
        process_id=process_id,
        observed_at=observed_at,
        comparison_key=comparison_key,
    )


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


def _time(value: str | datetime) -> datetime:
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if stamp.tzinfo is None:
        raise ValueError("Evaluation timestamps must include their timezone")
    return stamp.astimezone(UTC)


class EvaluationStore:
    def __init__(self) -> None:
        self._results: dict[str, EvaluationResult] = {}

    def add(self, result: EvaluationResult) -> EvaluationResult:
        old = self._results.get(result.id)
        if old is not None and old.to_dict() != result.to_dict():
            raise ValueError("An evaluation result is immutable")
        self._results[result.id] = result
        return result

    def get(self, identity: str) -> EvaluationResult:
        return self._results[identity]

    def all(self) -> tuple[EvaluationResult, ...]:
        return tuple(self._results.values())

    def get_tension_reduction(
        self,
        period: tuple[str, str],
        processes: Iterable[str],
        baseline_period: tuple[str, str] | None = None,
        *,
        descendants: Mapping[str, Iterable[str]] | None = None,
    ) -> dict[str, Any]:
        start, end = map(_time, period)
        if start >= end:
            raise ValueError("Period must be a nonempty half-open interval")
        if baseline_period is None:
            baseline = (start - (end - start), start)
        else:
            baseline = tuple(map(_time, baseline_period))
            if baseline[0] >= baseline[1]:
                raise ValueError("Baseline period must be nonempty")
        selected = set(processes)
        pending = list(selected)
        while pending:
            for child in (descendants or {}).get(pending.pop(), ()):
                if child not in selected:
                    selected.add(child)
                    pending.append(child)
        by_process: dict[str, Any] = {}
        skipped: dict[str, str] = {}
        for process in sorted(selected):
            groups: list[list[tuple[float, str | None]]] = [[], []]
            seen: set[tuple[str | None, tuple[str, ...], str | None]] = set()
            for result in self._results.values():
                if (
                    result.status != "evaluated"
                    or result.process_id != process
                    or not result.observed_at
                ):
                    continue
                values = [
                    sample.value
                    for sample in result.metric_samples
                    if sample.channel == "prediction_unexpectedness"
                ]
                if not values:
                    continue
                key = (result.evaluated_subject, result.outcome_ids, result.comparison_key)
                if key in seen:
                    continue
                seen.add(key)
                stamp = _time(result.observed_at)
                for index, bounds in enumerate((baseline, (start, end))):
                    if bounds[0] <= stamp < bounds[1]:
                        groups[index].append((_probability(values[0]), result.comparison_key))
            if not groups[0] or not groups[1]:
                skipped[process] = "insufficient_data_in_both_periods"
                continue
            if {key for _, key in groups[0]} != {key for _, key in groups[1]}:
                skipped[process] = "incomparable_calibration_or_selection_rules"
                continue
            if any(key is None for _, key in groups[0] + groups[1]):
                skipped[process] = "missing_comparison_basis"
                continue
            before = sum(value for value, _ in groups[0]) / len(groups[0])
            after = sum(value for value, _ in groups[1]) / len(groups[1])
            by_process[process] = {
                "before": before,
                "after": after,
                "delta": before - after,
                "before_count": len(groups[0]),
                "after_count": len(groups[1]),
            }
        return {
            "value": sum(value["delta"] for value in by_process.values()) / len(by_process)
            if by_process
            else None,
            "by_process": by_process,
            "skipped": skipped,
            "period": [start.isoformat(), end.isoformat()],
            "baseline_period": [stamp.isoformat() for stamp in baseline],
        }

    def snapshot(self) -> dict[str, Any]:
        return {"results": [result.to_dict() for result in self._results.values()]}

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any]) -> EvaluationStore:
        store = cls()
        for result in data.get("results", ()):
            store.add(EvaluationResult.from_dict(result))
        return store
