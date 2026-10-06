"""Evaluation result contracts and validation of compared values."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from ..datasets import freeze_json, thaw_json


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


# Keep existing trace type names and pickled references valid through the public module.
for _export in (
    SupervisorFeedback,
    MetricSample,
    EvaluationResult,
    EvaluatedResult,
    NotApplicableResult,
    UnresolvedEvaluationResult,
    exact_json_equal,
    _number,
    _probability,
    _distribution,
):
    _export.__module__ = "evertree.core.evaluation"
