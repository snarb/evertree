"""Credit assignment and transactional updates of explicitly bound estimators.

Both request identity (retry) and logical source identity (replay) are protected.
The in-memory transaction, including receipts, is persisted by the common agent
backup; individual updaters never write storage or perform external effects.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from .datasets import content_revision, freeze_json, thaw_json
from .evaluation import EvaluationResult, MetricSample


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite numeric value")
    return float(value)


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


class EstimatorUpdater(Protocol):
    def apply(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any]: ...

    def retract(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any] | None: ...


class BetaBernoulliUpdater:
    def apply(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any]:
        result = dict(parameters)
        for sample in data["samples"]:
            outcome = sample["value"]
            if outcome not in (0, 1, False, True):
                raise ValueError("Bernoulli outcome must be binary")
            weight = _number(sample["weight"])
            if not 0 < weight <= 1:
                raise ValueError("Attribution weight must be in (0, 1]")
            result["positive" if outcome else "negative"] += weight
            result["observed_count"] += 1
        return result

    def retract(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any]:
        result = dict(parameters)
        for sample in data["samples"]:
            key = "positive" if sample["value"] else "negative"
            result[key] = max(0.0, result[key] - sample["weight"])
            result["observed_count"] -= 1
        return result


class CategoricalUpdater:
    def apply(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any]:
        result = {
            "counts": dict(parameters["counts"]),
            "observed_count": parameters["observed_count"],
        }
        for sample in data["samples"]:
            category = str(sample["value"])
            if category not in result["counts"]:
                raise ValueError("Outcome is outside the declared category set")
            weight = _number(sample["weight"])
            if not 0 < weight <= 1:
                raise ValueError("Attribution weight must be in (0, 1]")
            result["counts"][category] += weight
            result["observed_count"] += 1
        return result

    def retract(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any]:
        result = {
            "counts": dict(parameters["counts"]),
            "observed_count": parameters["observed_count"],
        }
        for sample in data["samples"]:
            key = str(sample["value"])
            result["counts"][key] = max(0.0, result["counts"][key] - sample["weight"])
            result["observed_count"] -= 1
        return result


class MeanUpdater:
    def apply(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any]:
        result = dict(parameters)
        for sample in data["samples"]:
            value, weight = _number(sample["value"]), _number(sample["weight"])
            if not 0 < weight <= 1:
                raise ValueError("Attribution weight must be in (0, 1]")
            result["sum"] += value * weight
            result["sum_squares"] += value * value * weight
            result["weight"] += weight
            result["observed_count"] += 1
        return result

    def retract(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any]:
        result = dict(parameters)
        for sample in data["samples"]:
            value, weight = sample["value"], sample["weight"]
            result["sum"] -= value * weight
            result["sum_squares"] -= value * value * weight
            result["weight"] -= weight
            result["observed_count"] -= 1
        if result["observed_count"] == 0:
            result.update(sum=0.0, sum_squares=0.0, weight=0.0)
        return result


class LinearRegressionUpdater:
    def apply(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any]:
        result = {
            "weights": list(parameters["weights"]),
            "bias": parameters["bias"],
            "observed_count": parameters["observed_count"],
        }
        for sample in data["samples"]:
            features = tuple(map(_number, sample.get("features", ())))
            if len(features) != len(result["weights"]):
                raise ValueError("Features do not match the declared regression dimension")
            outcome = _number(sample["value"])
            predicted = (
                sum(weight * feature for weight, feature in zip(result["weights"], features))
                + result["bias"]
            )
            step = settings["learning_rate"] * sample["weight"] * (outcome - predicted)
            result["weights"] = [
                weight + step * feature for weight, feature in zip(result["weights"], features)
            ]
            result["bias"] += step
            result["observed_count"] += 1
        return result

    def retract(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> None:
        return None


class UpdateDispatcher:
    def __init__(self) -> None:
        self._updaters: dict[str, EstimatorUpdater] = {
            "beta_bernoulli": BetaBernoulliUpdater(),
            "categorical": CategoricalUpdater(),
            "mean": MeanUpdater(),
            "linear_regression": LinearRegressionUpdater(),
        }

    def get(self, kind: str) -> EstimatorUpdater:
        return self._updaters[kind]

    def register(self, kind: str, updater: EstimatorUpdater) -> None:
        """Developer extension point; never exposed as an agent tool."""
        self._updaters[kind] = updater


class LearningStore:
    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._bindings: list[LearningBinding] = []
        self._credits: dict[str, LearningCredit] = {}
        self._unresolved: dict[str, UnresolvedCredit] = {}
        self._ledger: dict[str, dict[str, Any]] = {}
        self._receipts: dict[str, UpdateReceipt] = {}
        self._requests: dict[str, str] = {}
        self._lock = RLock()
        self.dispatcher = UpdateDispatcher()

    def create_state(self, kind: str, *, state_id: str | None = None, **settings: Any) -> str:
        identity = state_id or str(uuid4())
        if kind == "beta_bernoulli":
            settings = {"alpha": settings.get("alpha", 1.0), "beta": settings.get("beta", 1.0)}
            if any(_number(value) <= 0 for value in settings.values()):
                raise ValueError("Beta prior parameters must be positive")
            parameters = {"positive": 0.0, "negative": 0.0, "observed_count": 0}
        elif kind == "categorical":
            categories = tuple(settings.get("categories", ()))
            if (
                not categories
                or len(set(categories)) != len(categories)
                or any(not isinstance(value, str) for value in categories)
            ):
                raise ValueError("Declare distinct string categories")
            prior = _number(settings.get("prior", 1.0))
            if prior <= 0:
                raise ValueError("Dirichlet prior concentration must be positive")
            settings = {"categories": list(categories), "prior": prior}
            parameters = {"counts": {category: 0.0 for category in categories}, "observed_count": 0}
        elif kind == "mean":
            prior = settings.get("prior")
            if prior is not None:
                prior = _number(prior)
            settings = {"prior": prior}
            parameters = {"sum": 0.0, "sum_squares": 0.0, "weight": 0.0, "observed_count": 0}
        elif kind == "linear_regression":
            dimension = settings.get("dimension")
            if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension < 1:
                raise ValueError("Linear regression needs a positive feature dimension")
            learning_rate = _number(settings.get("learning_rate", 0.05))
            if learning_rate <= 0:
                raise ValueError("Learning rate must be positive")
            settings = {"dimension": dimension, "learning_rate": learning_rate}
            parameters = {"weights": [0.0] * dimension, "bias": 0.0, "observed_count": 0}
        else:
            raise ValueError("Unsupported estimator kind")
        with self._lock:
            if identity in self._states:
                raise ValueError("Estimator state identity already exists")
            self._states[identity] = {
                "kind": kind,
                "parameters": parameters,
                "settings": settings,
                "revision": 0,
            }
        return identity

    def state(self, state_id: str) -> dict[str, Any]:
        with self._lock:
            return thaw_json(freeze_json(self._states[state_id]))

    def register_binding(self, binding: LearningBinding) -> None:
        if binding.state not in self._states:
            raise ValueError("Learning binding addresses unknown state")
        if binding not in self._bindings:
            self._bindings.append(binding)

    def predict(self, state_id: str, inputs: Any = None) -> Any:
        state = self.state(state_id)
        params, settings = state["parameters"], state["settings"]
        if state["kind"] == "beta_bernoulli":
            alpha = settings["alpha"] + params["positive"]
            beta = settings["beta"] + params["negative"]
            return alpha / (alpha + beta)
        if state["kind"] == "categorical":
            denominator = (
                sum(params["counts"].values()) + len(settings["categories"]) * settings["prior"]
            )
            return {
                category: (count + settings["prior"]) / denominator
                for category, count in params["counts"].items()
            }
        if state["kind"] == "mean":
            return params["sum"] / params["weight"] if params["weight"] else settings["prior"]
        if state["kind"] == "linear_regression":
            features = tuple(map(_number, inputs or ()))
            if len(features) != len(params["weights"]):
                raise ValueError("Input feature dimension mismatch")
            return (
                sum(weight * feature for weight, feature in zip(params["weights"], features))
                + params["bias"]
            )
        raise ValueError("Unsupported estimator")

    def statistics(self, state_id: str) -> dict[str, Any]:
        state = self.state(state_id)
        params = state["parameters"]
        result: dict[str, Any] = {
            "observed_count": params["observed_count"],
            "revision": state["revision"],
        }
        if state["kind"] == "beta_bernoulli":
            count = params["positive"] + params["negative"]
            result.update(
                weighted_count=count, probability=params["positive"] / count if count else None
            )
        elif state["kind"] == "categorical":
            count = sum(params["counts"].values())
            result.update(
                weighted_count=count,
                counts=params["counts"],
                probabilities={key: value / count for key, value in params["counts"].items()}
                if count
                else None,
            )
        elif state["kind"] == "mean":
            count = params["weight"]
            mean = params["sum"] / count if count else None
            result.update(
                weighted_count=count,
                mean=mean,
                variance=max(0.0, params["sum_squares"] / count - mean * mean) if count else None,
            )
        return result

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "states": thaw_json(freeze_json(self._states)),
                "bindings": [binding.to_dict() for binding in self._bindings],
                "credits": [credit.to_dict() for credit in self._credits.values()],
                "unresolved": [credit.to_dict() for credit in self._unresolved.values()],
                "ledger": thaw_json(freeze_json(self._ledger)),
                "receipts": {key: value.to_dict() for key, value in self._receipts.items()},
                "requests": dict(self._requests),
            }

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any]) -> LearningStore:
        store = cls()
        store._states = thaw_json(freeze_json(data.get("states", {})))
        for binding in data.get("bindings", ()):
            store.register_binding(LearningBinding(**binding))
        store._credits = {
            raw["id"]: LearningCredit.from_dict(raw) for raw in data.get("credits", ())
        }
        for raw in data.get("unresolved", ()):
            values = dict(raw)
            values["signal"] = (
                LearningSignal.from_dict(values["signal"]) if values.get("signal") else None
            )
            credit = UnresolvedCredit(**values)
            store._unresolved[credit.id] = credit
        store._ledger = thaw_json(freeze_json(data.get("ledger", {})))
        store._receipts = {
            key: UpdateReceipt(**value) for key, value in data.get("receipts", {}).items()
        }
        store._requests = dict(data.get("requests", {}))
        if set(store._receipts) != set(store._requests):
            raise ValueError(
                "Learning backup must restore receipts and request identities together"
            )
        if any(entry["state"] not in store._states for entry in store._ledger.values()):
            raise ValueError("Learning ledger addresses a missing estimator state")
        return store


class CreditAssignmentProgram:
    def __init__(self, store: LearningStore) -> None:
        self.store = store

    def assign(
        self,
        target: str,
        signal: LearningSignal | None = None,
        *,
        ambiguous: bool = False,
        observation_ids: tuple[str, ...] = (),
        context: Mapping[str, Any] | None = None,
        attribution_weight: float = 1.0,
        resolves: str | None = None,
    ) -> LearningCredit | UnresolvedCredit:
        if signal is None:
            # Replaying the same unmatched experience cannot create new credit.
            for existing in self.store._unresolved.values():
                if (
                    existing.reason == "missing_prediction"
                    and existing.target == target
                    and existing.observation_ids == tuple(observation_ids)
                    and thaw_json(existing.context) == thaw_json(context or {})
                ):
                    return existing
            credit = UnresolvedCredit(
                target, "missing_prediction", observation_ids, context=context or {}
            )
            self.store._unresolved[credit.id] = credit
            return credit
        if ambiguous:
            unresolved = UnresolvedCredit(
                target,
                "ambiguous_attribution",
                tuple(signal.outcome_values),
                signal,
                context=context or {},
            )
            self.store._unresolved[unresolved.id] = unresolved
            return unresolved
        if resolves and resolves not in self.store._unresolved:
            raise ValueError("Resolved credit refers to an unknown unresolved case")
        result = LearningCredit(target, signal, attribution_weight, context or {}, resolves)
        self.store._credits[result.id] = result
        return result


class UpdatePlanner:
    def __init__(self, store: LearningStore) -> None:
        self.store = store

    def prepare(self, credit: LearningCredit) -> PreparedUpdate | UpdateBlocked:
        if not isinstance(credit, LearningCredit):
            raise TypeError("Unresolved credit cannot be passed to UpdatePlanner")
        candidates = [
            binding
            for binding in self.store._bindings
            if binding.target == credit.target
            and (
                binding.subject is None
                or binding.subject == credit.signal.evaluation.evaluated_subject
            )
        ]
        if not candidates:
            return UpdateBlocked(credit, "no_learning_binding")
        candidates = [
            binding
            for binding in candidates
            if set(credit.signal.objective.metrics) <= set(binding.metrics)
            and binding.direction == credit.signal.objective.direction
        ]
        if not candidates:
            return UpdateBlocked(credit, "unsupported_signal")
        if len(candidates) != 1:
            return UpdateBlocked(credit, "ambiguous_learning_binding")
        binding = candidates[0]
        context = thaw_json(credit.context)
        example = context.get("example_id")
        if example and not binding.allow_multiple_examples:
            return UpdateBlocked(credit, "incompatible_updater_contract")
        samples = []
        for identity, value in credit.signal.outcome_values.items():
            corrections = context.get("correction_of", {})
            corrected_source = corrections.get(identity) if isinstance(corrections, dict) else None
            key = content_revision(
                {
                    "state": binding.state,
                    "outcome": corrected_source or identity,
                    "example": example,
                }
            )
            with self.store._lock:
                old = self.store._ledger.get(key)
                if old and not (corrected_source and old["status"] == "retracted"):
                    return UpdateBlocked(credit, "already_accounted")
                if corrected_source and (not old or old["status"] != "retracted"):
                    return UpdateBlocked(credit, "incompatible_updater_contract")
            sample = {
                "outcome_id": identity,
                "value": thaw_json(value),
                "weight": credit.attribution_weight,
                "logical_key": key,
            }
            if "features" in context:
                sample["features"] = context["features"]
            samples.append(sample)
        data = {"samples": samples, "example_id": example}
        state = self.store.state(binding.state)
        try:
            # Validate compatibility without storing anything or using stale output.
            # The transaction recalculates against current parameters under its lock.
            self.store.dispatcher.get(state["kind"]).apply(
                state["parameters"], data, state["settings"]
            )
        except (ValueError, TypeError, KeyError, OverflowError):
            return UpdateBlocked(credit, "incompatible_updater_contract")
        return PreparedUpdate(credit, binding.state, data)


class UpdateTransactionManager:
    def __init__(self, store: LearningStore) -> None:
        self.store = store

    def _receipt(
        self,
        request: PreparedUpdate | CreditRetraction,
        status: str,
        reason: str | None,
        fingerprint: str,
        revision: int | None = None,
    ) -> UpdateReceipt:
        receipt = UpdateReceipt(request.id, request.state, status, reason, revision)
        try:
            self.store._receipts[request.id] = receipt
            self.store._requests[request.id] = fingerprint
        except BaseException:
            self.store._receipts.pop(request.id, None)
            self.store._requests.pop(request.id, None)
            raise
        return receipt

    def _retry(self, identity: str, fingerprint: str) -> UpdateReceipt | None:
        if identity in self.store._receipts:
            if self.store._requests[identity] != fingerprint:
                raise ValueError("Update request identity reused with different parameters")
            return self.store._receipts[identity]
        return None

    def _commit(
        self,
        request: PreparedUpdate | CreditRetraction,
        state: dict[str, Any],
        entries: dict[str, dict[str, Any]],
        status: str,
        fingerprint: str,
    ) -> UpdateReceipt:
        """Publish one update together, restoring affected entries if commit fails."""
        old_state = self.store._states[request.state]
        old_entries = {key: self.store._ledger.get(key) for key in entries}
        credit = request.source_credit if isinstance(request, PreparedUpdate) else None
        credit_existed = credit is not None and credit.id in self.store._credits
        try:
            self.store._states[request.state] = state
            self.store._ledger.update(entries)
            if credit is not None:
                self.store._credits.setdefault(credit.id, credit)
            return self._receipt(request, status, None, fingerprint, state["revision"])
        except BaseException:
            self.store._states[request.state] = old_state
            for key, previous in old_entries.items():
                if previous is None:
                    self.store._ledger.pop(key, None)
                else:
                    self.store._ledger[key] = previous
            if credit is not None and not credit_existed:
                self.store._credits.pop(credit.id, None)
            self.store._receipts.pop(request.id, None)
            self.store._requests.pop(request.id, None)
            raise

    def apply(self, update: PreparedUpdate) -> UpdateReceipt:
        if not isinstance(update, PreparedUpdate):
            raise TypeError("Only prepared resolved updates can be applied")
        fingerprint = content_revision({"kind": "apply", **update.to_dict()})
        with self.store._lock:
            retry = self._retry(update.id, fingerprint)
            if retry:
                return retry
            state = self.store._states.get(update.state)
            if state is None:
                return self._receipt(update, "rejected", "unknown_state", fingerprint)
            # Check that callers did not construct a request bypassing its declared binding.
            planned = UpdatePlanner(self.store).prepare(update.source_credit)
            if isinstance(planned, UpdateBlocked):
                return self._receipt(
                    update, "rejected", planned.reason, fingerprint, state["revision"]
                )
            if planned.state != update.state or thaw_json(planned.updater_input) != thaw_json(
                update.updater_input
            ):
                return self._receipt(
                    update,
                    "rejected",
                    "incompatible_updater_contract",
                    fingerprint,
                    state["revision"],
                )
            samples = thaw_json(update.updater_input)["samples"]
            keys = [sample["logical_key"] for sample in samples]
            if len(set(keys)) != len(keys) or any(
                key in self.store._ledger and self.store._ledger[key]["status"] != "retracted"
                for key in keys
            ):
                return self._receipt(
                    update, "rejected", "already_accounted", fingerprint, state["revision"]
                )
            # No live state is handed to the updater. A failure leaves all three
            # authoritative maps (state, contribution ledger, receipt) unchanged.
            working = thaw_json(freeze_json(state["parameters"]))
            new_parameters = self.store.dispatcher.get(state["kind"]).apply(
                working, thaw_json(update.updater_input), dict(state["settings"])
            )
            new_parameters = thaw_json(freeze_json(new_parameters))
            revision = state["revision"] + 1
            entries = {
                sample["logical_key"]: {
                    "state": update.state,
                    "credit_id": update.source_credit.id,
                    "request_id": update.id,
                    "sample": sample,
                    "status": "applied",
                    "previous": self.store._ledger.get(sample["logical_key"]),
                }
                for sample in samples
            }
            new_state = {
                **state,
                "parameters": new_parameters,
                "revision": revision,
            }
            return self._commit(update, new_state, entries, "applied", fingerprint)

    def retract(self, retraction: CreditRetraction) -> UpdateReceipt:
        if not isinstance(retraction, CreditRetraction):
            raise TypeError("Retraction needs an immutable request")
        fingerprint = content_revision({"kind": "retract", **retraction.to_dict()})
        with self.store._lock:
            retry = self._retry(retraction.id, fingerprint)
            if retry:
                return retry
            state = self.store._states.get(retraction.state)
            if state is None:
                return self._receipt(retraction, "rejected", "unknown_state", fingerprint)
            entries = [
                (key, entry)
                for key, entry in self.store._ledger.items()
                if entry["state"] == retraction.state
                and entry["credit_id"] == retraction.credit.id
                and entry["status"] == "applied"
            ]
            if not entries:
                return self._receipt(
                    retraction, "skipped", "no_applied_contribution", fingerprint, state["revision"]
                )
            working = thaw_json(freeze_json(state["parameters"]))
            data = {"samples": [entry["sample"] for _, entry in entries]}
            updater = self.store.dispatcher.get(state["kind"])
            retract = getattr(updater, "retract", None)
            new_parameters = retract(working, data, dict(state["settings"])) if retract else None
            if new_parameters is None:
                return self._receipt(
                    retraction, "skipped", "unsupported_retraction", fingerprint, state["revision"]
                )
            new_parameters = thaw_json(freeze_json(new_parameters))
            revision = state["revision"] + 1
            new_state = {
                **state,
                "parameters": new_parameters,
                "revision": revision,
            }
            retracted = {
                key: {
                    **entry,
                    "status": "retracted",
                    "retraction_id": retraction.id,
                }
                for key, entry in entries
            }
            return self._commit(retraction, new_state, retracted, "retracted", fingerprint)


class LearningCoordinator:
    def __init__(self, store: LearningStore) -> None:
        self.store = store
        self.credit_assignment = CreditAssignmentProgram(store)
        self.planner = UpdatePlanner(store)
        self.transactions = UpdateTransactionManager(store)

    def learn(
        self,
        signal: LearningSignal,
        target: str,
        *,
        context: Mapping[str, Any] | None = None,
        attribution_weight: float = 1.0,
        ambiguous: bool = False,
    ) -> UpdateReceipt | UpdateBlocked | UnresolvedCredit:
        credit = self.credit_assignment.assign(
            target,
            signal,
            context=context,
            attribution_weight=attribution_weight,
            ambiguous=ambiguous,
        )
        if isinstance(credit, UnresolvedCredit):
            return credit
        update = self.planner.prepare(credit)
        if isinstance(update, UpdateBlocked):
            return update
        return self.transactions.apply(update)

    def missing_prediction(
        self,
        target: str,
        observation_ids: tuple[str, ...],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> UnresolvedCredit:
        result = self.credit_assignment.assign(
            target, observation_ids=observation_ids, context=context
        )
        assert isinstance(result, UnresolvedCredit)
        return result
