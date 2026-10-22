"""Explicitly bound estimator state, prediction, statistics and snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..datasets import content_revision, freeze_json, thaw_json
from .contracts import (
    LearningBinding,
    LearningCredit,
    LearningSignal,
    UnresolvedCredit,
    UpdateReceipt,
)
from .estimators import UpdateDispatcher, _number

if TYPE_CHECKING:
    from .declaration import EstimatorDeclaration, LearningDeclaration


def initial_state(kind: str, settings: Mapping[str, Any]) -> tuple[dict, dict]:
    """Validate kind-specific settings and return them with the initial parameters."""
    if kind == "beta_bernoulli":
        settings = {"alpha": settings.get("alpha", 1.0), "beta": settings.get("beta", 1.0)}
        if any(_number(value) <= 0 for value in settings.values()):
            raise ValueError("Beta prior parameters must be positive")
        return settings, {"positive": 0.0, "negative": 0.0, "observed_count": 0}
    if kind == "categorical":
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
        return (
            {"categories": list(categories), "prior": prior},
            {"counts": {category: 0.0 for category in categories}, "observed_count": 0},
        )
    if kind == "mean":
        prior = settings.get("prior")
        if prior is not None:
            prior = _number(prior)
        return {"prior": prior}, {
            "sum": 0.0,
            "sum_squares": 0.0,
            "weight": 0.0,
            "observed_count": 0,
        }
    if kind == "linear_regression":
        dimension = settings.get("dimension")
        if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension < 1:
            raise ValueError("Linear regression needs a positive feature dimension")
        learning_rate = _number(settings.get("learning_rate", 0.05))
        if learning_rate <= 0:
            raise ValueError("Learning rate must be positive")
        return (
            {"dimension": dimension, "learning_rate": learning_rate},
            {"weights": [0.0] * dimension, "bias": 0.0, "observed_count": 0},
        )
    raise ValueError("Unsupported estimator kind")


def program_state_id(owner: str | int, name: str, estimator: EstimatorDeclaration) -> str:
    """Address a Program's estimator state by its declaration, not by revision."""
    fingerprint = content_revision(estimator.model_dump(mode="json"))[:12]
    return f"program:{owner}:{name}:{fingerprint}"


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
        """Allocate estimator state with validated kind-specific settings and initial parameters."""
        identity = state_id or str(uuid4())
        settings, parameters = initial_state(kind, settings)
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

    def install(self, owner: str, declaration: LearningDeclaration) -> dict[str, str]:
        """Make a Program's declared estimators its only learning bindings.

        A state's identity includes its declaration, so an unchanged estimator keeps
        its trained state across revisions and a changed one starts from its prior.
        """
        states = {}
        with self._lock:
            for name, estimator in declaration.estimators.items():
                identity = program_state_id(owner, name, estimator)
                if identity not in self._states:
                    self.create_state(estimator.kind, state_id=identity, **estimator.settings)
                states[name] = identity
            self._bindings = [binding for binding in self._bindings if binding.owner != str(owner)]
            for name, estimator in declaration.estimators.items():
                target = declaration.targets[estimator.target]
                self._bindings.append(
                    LearningBinding(
                        estimator.target,
                        states[name],
                        tuple(target.metrics),
                        owner=str(owner),
                    )
                )
        return states

    def release(self, owner: str) -> None:
        """Remove a displaced Program's bindings; its trained states remain for history."""
        with self._lock:
            self._bindings = [binding for binding in self._bindings if binding.owner != str(owner)]

    def bindings(self, target: str | None = None) -> list[dict[str, Any]]:
        """List declared learning bindings, optionally for one target."""
        with self._lock:
            return [
                binding.to_dict()
                for binding in self._bindings
                if target is None or binding.target == target
            ]

    def estimate(
        self, owner: str, declaration: LearningDeclaration, name: str, inputs: Any = None
    ) -> dict[str, Any]:
        """Predict with a Program's declared estimator, reporting the state version used."""
        if name not in declaration.estimators:
            raise ValueError(f"Program declares no estimator {name!r}")
        identity = program_state_id(owner, name, declaration.estimators[name])
        with self._lock:
            if identity not in self._states:
                self.install(owner, declaration)
            state = self._states[identity]
            return {
                "value": self.predict(identity, inputs),
                "state": identity,
                "revision": state["revision"],
                "observed_count": state["parameters"]["observed_count"],
            }

    def state(self, state_id: str) -> dict[str, Any]:
        """Return an independent copy of estimator state rather than exposing mutable storage."""
        with self._lock:
            return thaw_json(freeze_json(self._states[state_id]))

    def register_binding(self, binding: LearningBinding) -> None:
        """Declare how a learning target may update an existing estimator state."""
        if binding.state not in self._states:
            raise ValueError("Learning binding addresses unknown state")
        if binding not in self._bindings:
            self._bindings.append(binding)

    def predict(self, state_id: str, inputs: Any = None) -> Any:
        """Compute the selected estimator's current prediction without changing its state."""
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
        """Report observation counts and empirical statistics separately from prior-backed predictions."""
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
        """Capture estimator states, bindings, credits, contribution ledger and update receipts."""
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
        """Restore estimator state and the records needed to deduplicate or retract learning."""
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
