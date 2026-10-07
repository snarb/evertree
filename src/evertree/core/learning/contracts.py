"""Validated learning signals, credit, bindings, requests and receipts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..datasets import freeze_json, thaw_json
from ..evaluation.contracts import EvaluationResult, MetricSample
from .estimators import _number


@dataclass(frozen=True)
class LearningObjective:
    metrics: tuple[str, ...]
    direction: str
    source: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", tuple(self.metrics))
        if not self.metrics or self.direction not in {"minimize", "maximize"}:
            raise ValueError("Learning objective needs metrics and an improvement direction")

    def to_dict(self) -> dict[str, Any]:
        return {"metrics": list(self.metrics), "direction": self.direction, "source": self.source}


@dataclass(frozen=True)
class LearningSignal:
    evaluation: EvaluationResult
    objective: LearningObjective
    outcome_values: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.evaluation.status != "evaluated":
            raise ValueError("LearningSignal can only use evaluated outcomes")
        values = dict(self.outcome_values)
        if not values or not set(values) <= set(self.evaluation.outcome_ids):
            raise ValueError("Every learning outcome must belong to the evaluation")
        if not set(self.objective.metrics) <= {
            sample.metric for sample in self.evaluation.metric_samples
        }:
            raise ValueError("Learning objective refers to metrics absent from its evaluation")
        if "prediction_unexpectedness" in self.objective.metrics:
            raise ValueError("Unexpectedness is diagnostic, not a learning objective")
        object.__setattr__(self, "outcome_values", freeze_json(thaw_json(values)))

    @property
    def metric_samples(self) -> tuple[MetricSample, ...]:
        return tuple(
            sample
            for sample in self.evaluation.metric_samples
            if sample.metric in self.objective.metrics
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation": self.evaluation.to_dict(),
            "objective": self.objective.to_dict(),
            "outcome_values": thaw_json(self.outcome_values),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LearningSignal:
        values = dict(data)
        values["evaluation"] = EvaluationResult.from_dict(values["evaluation"])
        values["objective"] = LearningObjective(**values["objective"])
        return cls(**values)


@dataclass(frozen=True)
class LearningCredit:
    target: str
    signal: LearningSignal
    attribution_weight: float = 1.0
    context: Mapping[str, Any] = field(default_factory=dict)
    resolves: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.target or not 0 < _number(self.attribution_weight) <= 1:
            raise ValueError("Learning credit needs a target and attribution weight in (0, 1]")
        object.__setattr__(self, "context", freeze_json(thaw_json(self.context)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target": self.target,
            "signal": self.signal.to_dict(),
            "attribution_weight": self.attribution_weight,
            "context": thaw_json(self.context),
            "resolves": self.resolves,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LearningCredit:
        values = dict(data)
        values["signal"] = LearningSignal.from_dict(values["signal"])
        return cls(**values)


@dataclass(frozen=True)
class UnresolvedCredit:
    target: str
    reason: str
    observation_ids: tuple[str, ...] = ()
    signal: LearningSignal | None = None
    missing_requirements: tuple[str, ...] = ()
    context: Mapping[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.target or self.reason not in {"missing_prediction", "ambiguous_attribution"}:
            raise ValueError("An unresolved credit needs a known target and supported reason")
        if self.reason == "missing_prediction" and self.signal is not None:
            raise ValueError("An absent prediction cannot produce a fictitious learning signal")
        object.__setattr__(self, "observation_ids", tuple(self.observation_ids))
        object.__setattr__(self, "missing_requirements", tuple(self.missing_requirements))
        object.__setattr__(self, "context", freeze_json(thaw_json(self.context)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target": self.target,
            "reason": self.reason,
            "observation_ids": list(self.observation_ids),
            "signal": self.signal.to_dict() if self.signal else None,
            "missing_requirements": list(self.missing_requirements),
            "context": thaw_json(self.context),
        }


@dataclass(frozen=True)
class LearningBinding:
    target: str
    state: str
    metrics: tuple[str, ...]
    direction: str = "minimize"
    subject: str | None = None
    allow_multiple_examples: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", tuple(self.metrics))
        if not self.target or not self.state or not self.metrics:
            raise ValueError("Learning binding needs target, state and objective metrics")
        if self.direction not in {"minimize", "maximize"}:
            raise ValueError("Unknown objective direction")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "state": self.state,
            "metrics": list(self.metrics),
            "direction": self.direction,
            "subject": self.subject,
            "allow_multiple_examples": self.allow_multiple_examples,
        }


@dataclass(frozen=True)
class PreparedUpdate:
    source_credit: LearningCredit
    state: str
    updater_input: Mapping[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.state or not isinstance(self.source_credit, LearningCredit):
            raise ValueError("Updates require a resolved credit and explicit state address")
        object.__setattr__(self, "updater_input", freeze_json(thaw_json(self.updater_input)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_credit": self.source_credit.to_dict(),
            "state": self.state,
            "updater_input": thaw_json(self.updater_input),
        }


@dataclass(frozen=True)
class UpdateBlocked:
    source_credit: LearningCredit
    reason: str


@dataclass(frozen=True)
class CreditRetraction:
    credit: LearningCredit
    state: str
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "credit": self.credit.to_dict(), "state": self.state}


@dataclass(frozen=True)
class UpdateReceipt:
    request_id: str
    state: str
    status: str
    reason: str | None = None
    state_revision: int | None = None

    def __post_init__(self) -> None:
        if self.status not in {"applied", "retracted", "adjusted", "skipped", "rejected"}:
            raise ValueError("Unknown update receipt status")

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)
