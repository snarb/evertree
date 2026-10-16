"""Numerical estimator updates and dispatch; no storage or credit assignment."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Protocol


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite numeric value")
    return float(value)


class EstimatorUpdater(Protocol):
    def apply(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return estimator parameters with the prepared contribution applied."""
        ...

    def retract(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Return parameters with a contribution removed, or None if retraction is unsupported."""
        ...


class BetaBernoulliUpdater:
    def apply(
        self, parameters: dict[str, Any], data: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Accumulate weighted binary outcomes without mutating the supplied parameters."""
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
        """Subtract retained binary contributions from sufficient statistics."""
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
        """Accumulate weighted outcomes within the estimator's declared category set."""
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
        """Subtract retained category contributions from sufficient statistics."""
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
        """Accumulate weighted numeric moments for mean and variance estimates."""
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
        """Subtract numeric moments, resetting residual statistics after the last observation."""
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
        """Take weighted gradient steps for the declared feature dimension."""
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
        """Return None because gradient contributions cannot be independently retracted."""
        return None  # noqa: RET501


class UpdateDispatcher:
    def __init__(self) -> None:
        self._updaters: dict[str, EstimatorUpdater] = {
            "beta_bernoulli": BetaBernoulliUpdater(),
            "categorical": CategoricalUpdater(),
            "mean": MeanUpdater(),
            "linear_regression": LinearRegressionUpdater(),
        }

    def get(self, kind: str) -> EstimatorUpdater:
        """Return the updater registered for an estimator kind."""
        return self._updaters[kind]

    def register(self, kind: str, updater: EstimatorUpdater) -> None:
        """Register a trusted estimator updater extension; unavailable to agent tools."""
        self._updaters[kind] = updater
