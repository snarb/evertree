"""Learning targets and estimators a Program revision declares as a module-level LEARNING literal.

The declaration is versioned with the code: targets name the Concepts a Program
predicts or learns about, and estimators are its learnable components bound to
them. Core reads it from source, checks forecasts against it at return, and owns
the estimator state; ``predict`` never trains.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..programs.design import read_literal
from .estimators import _number

# Strictly proper (or matching) scores for each forecast form; evaluate_prediction computes them.
FORM_METRICS = {
    "probability": frozenset({"brier", "log_loss"}),
    "distribution": frozenset({"log_loss"}),
    "mean": frozenset({"squared_error"}),
    "median": frozenset({"absolute_error"}),
    "value": frozenset({"exact_match"}),
}
# Calibration rules whose predictive distribution each forecast form can express.
UNEXPECTEDNESS_FORMS = {
    "bernoulli": {"probability"},
    "categorical": {"distribution"},
    "normal": {"mean", "median"},
    "deterministic": {"value"},
    "empirical_rank": {"mean", "median"},
}
ESTIMATOR_FORMS = {
    "beta_bernoulli": "probability",
    "categorical": "distribution",
    "mean": "mean",
    "linear_regression": "mean",
}


class ForecastTarget(BaseModel):
    """A PredictionTarget (or other LearningTarget) and the contract of its forecast."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    form: Literal["probability", "distribution", "mean", "median", "value"]
    result: str | None = Field(
        default=None,
        description='Key of ProgramResult.result holding the forecast; "" is the whole result. '
        "Required for a model Program, absent for an exec Program's internal target.",
    )
    subject: str = Field(min_length=1, description="Whose value is forecast.")
    horizon: str = Field(min_length=1, description="When the forecast value is realized.")
    check: str = Field(min_length=1, description="How the observed outcome is obtained.")
    metrics: list[str] = Field(min_length=1)
    categories: list[str] | None = None
    unexpectedness: dict[str, Any] | None = Field(
        default=None,
        description="Calibration rule for prediction_unexpectedness, e.g. {'kind': 'bernoulli'}, "
        "or {'omit': 'cost_not_justified' | 'no_supported_calibration'} to record why it is "
        "not calculated. Absent means no supported rule.",
    )

    @model_validator(mode="after")
    def _compatible(self) -> ForecastTarget:
        unsupported = set(self.metrics) - FORM_METRICS[self.form]
        if unsupported or len(set(self.metrics)) != len(self.metrics):
            raise ValueError(
                f"{self.form} forecasts use distinct metrics from {sorted(FORM_METRICS[self.form])}"
            )
        if (self.form == "distribution") != (self.categories is not None):
            raise ValueError("Declare categories exactly for distribution forecasts")
        if self.unexpectedness is not None:
            from ..evaluation.scoring import calibration_omission

            kind = self.unexpectedness.get("kind")
            fitting = UNEXPECTEDNESS_FORMS.get(kind)
            if "omit" in self.unexpectedness:
                calibration_omission(self.unexpectedness)
            elif fitting is None or self.form not in fitting:
                raise ValueError(f"{self.form} forecasts cannot use unexpectedness kind {kind!r}")
        if self.categories is not None and (
            not self.categories or len(set(self.categories)) != len(self.categories)
        ):
            raise ValueError("Distribution categories must be distinct and nonempty")
        return self


class EstimatorDeclaration(BaseModel):
    """A learnable component with its declared initial state."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["beta_bernoulli", "categorical", "mean", "linear_regression"]
    target: str = Field(min_length=1)
    settings: dict[str, Any] = Field(default_factory=dict)


class LearningDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: dict[str, ForecastTarget] = Field(default_factory=dict)
    estimators: dict[str, EstimatorDeclaration] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bound(self) -> LearningDeclaration:
        from .state import initial_state

        for name, estimator in self.estimators.items():
            if not name.isidentifier():
                raise ValueError(f"Estimator name must be an identifier: {name}")
            target = self.targets.get(estimator.target)
            if target is None:
                raise ValueError(f"Estimator {name} is bound to an undeclared target")
            if ESTIMATOR_FORMS[estimator.kind] != target.form:
                raise ValueError(
                    f"A {estimator.kind} estimator cannot learn a {target.form} forecast"
                )
            initial_state(estimator.kind, estimator.settings)
            if estimator.kind == "categorical" and list(
                estimator.settings.get("categories", ())
            ) != list(target.categories or ()):
                raise ValueError(f"Estimator {name} must use its target's categories")
        return self

    def check_role(self, role: str) -> None:
        """Forecast outputs belong to model Programs; exec targets stay internal."""
        for name, target in self.targets.items():
            if role == "model" and target.result is None:
                raise ValueError(f"Model target {name} must name its result key")
            if role == "exec" and target.result is not None:
                raise ValueError(f"Only a model Program returns forecasts: {name}")


def read_learning(source: str, path: str) -> LearningDeclaration | None:
    """Parse and validate the module-level LEARNING literal, or None when undeclared."""
    value = read_literal(source, path, "LEARNING")
    if value is None:
        return None
    try:
        return LearningDeclaration.model_validate(value)
    except ValidationError as error:
        raise ValueError(f"Invalid LEARNING in {path}: {error}") from error


def _check_value(form: str, value: Any, categories: list[str] | None) -> None:
    if form == "probability":
        if not 0 <= _number(value) <= 1:
            raise ValueError("probability must be in [0, 1]")
    elif form == "distribution":
        if not isinstance(value, Mapping) or set(value) != set(categories or ()):
            raise ValueError("distribution must cover exactly its declared categories")
        probabilities = [_number(item) for item in value.values()]
        if any(item < 0 for item in probabilities) or not math.isclose(
            sum(probabilities), 1, abs_tol=1e-6
        ):
            raise ValueError("distribution probabilities must be nonnegative and sum to 1")
    elif form in {"mean", "median"}:
        _number(value)
    elif value is None:
        raise ValueError("value forecast is missing")


def check_forecast(declaration: LearningDeclaration, result: Any) -> None:
    """Reject a model result that omits or misshapes a declared forecast."""
    for name, target in declaration.targets.items():
        if target.result is None:
            continue
        if target.result == "":
            value = result
        elif isinstance(result, Mapping) and target.result in result:
            value = result[target.result]
        else:
            raise ValueError(f"Forecast contract: result lacks {target.result!r} for {name}")
        try:
            _check_value(target.form, value, target.categories)
        except (ValueError, TypeError) as error:
            raise ValueError(f"Forecast contract for {name}: {error}") from error
