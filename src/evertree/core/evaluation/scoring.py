"""Prediction quality metrics and calibrated unexpectedness."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .contracts import (
    EvaluatedResult,
    MetricSample,
    NotApplicableResult,
    UnresolvedEvaluationResult,
    _distribution,
    _number,
    _probability,
    exact_json_equal,
)


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
