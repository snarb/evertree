"""Prediction quality metrics and calibrated unexpectedness."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ..datasets import content_revision
from .contracts import (
    NO_SUPPORTED_CALIBRATION,
    OMISSION_REASONS,
    EvaluatedResult,
    MetricSample,
    NotApplicableResult,
    UnresolvedEvaluationResult,
    _distribution,
    _number,
    _probability,
    exact_json_equal,
)

# Bumped whenever a calibration rule's calculation changes, so old and new values never mix.
UNEXPECTEDNESS_RULE_VERSION = "1"
MODEL_KINDS = frozenset(
    {"bernoulli", "categorical", "normal", "deterministic", "binomial", "beta_binomial"}
)
EMPIRICAL_KINDS = frozenset({"empirical_rank"})


def calibration_omission(calibration: Mapping[str, Any] | None) -> str | None:
    """Return why unexpectedness is deliberately not calculated, or None when a rule applies."""
    if calibration is None:
        return NO_SUPPORTED_CALIBRATION
    omit = calibration.get("omit")
    if omit is None:
        return (
            None
            if calibration.get("kind") in MODEL_KINDS | EMPIRICAL_KINDS
            else (NO_SUPPORTED_CALIBRATION)
        )
    if omit not in OMISSION_REASONS:
        raise ValueError("Unknown reason for omitting prediction_unexpectedness")
    return omit


def calibration_basis(calibration: Mapping[str, Any]) -> dict[str, Any]:
    """Describe the method and norm a value was calculated with, so it can be reproduced."""
    kind = calibration["kind"]
    return {
        "method": "empirical" if kind in EMPIRICAL_KINDS else "model",
        "kind": kind,
        "rule_version": UNEXPECTEDNESS_RULE_VERSION,
        "norm_digest": content_revision(dict(calibration)),
    }


def _count_tail(pmf: list[float], centre: float, observed: Any) -> float:
    """Probability of a count at least as far from the predicted mean as the observed one."""
    if isinstance(observed, bool) or not isinstance(observed, int):
        raise TypeError("A count check needs an integer observation")
    if not 0 <= observed < len(pmf):
        raise ValueError("Observed count lies outside the predicted window")
    distance = abs(observed - centre)
    # Ties count as at least as strong, which keeps the discrete scale conservative.
    return min(1.0, sum(p for count, p in enumerate(pmf) if abs(count - centre) >= distance - 1e-9))


def _trials(prediction: Mapping[str, Any]) -> int:
    n = prediction.get("n")
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ValueError("A count prediction needs a positive number of trials n")
    return n


def _binomial_pmf(n: int, p: float) -> list[float]:
    if p in (0.0, 1.0):
        return [float(k == n * p) for k in range(n + 1)]
    return [
        math.exp(
            math.lgamma(n + 1)
            - math.lgamma(k + 1)
            - math.lgamma(n - k + 1)
            + k * math.log(p)
            + (n - k) * math.log(1 - p)
        )
        for k in range(n + 1)
    ]


def _beta_binomial_pmf(n: int, alpha: float, beta: float) -> list[float]:
    def log_beta(a: float, b: float) -> float:
        return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)

    return [
        math.exp(
            math.lgamma(n + 1)
            - math.lgamma(k + 1)
            - math.lgamma(n - k + 1)
            + log_beta(k + alpha, n - k + beta)
            - log_beta(alpha, beta)
        )
        for k in range(n + 1)
    ]


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
        # A point forecast takes its dispersion from the declared rule, not from itself.
        if isinstance(prediction, Mapping):
            mean, deviation = _number(prediction["mean"]), _number(prediction["stddev"])
        else:
            mean, deviation = _number(prediction), _number(calibration["stddev"])
        if deviation <= 0:
            raise ValueError("A normal model needs positive standard deviation")
        return math.erf(abs(_number(observed) - mean) / (deviation * math.sqrt(2)))
    if kind == "deterministic":
        return 0.0 if exact_json_equal(prediction, observed) else 1.0
    if kind == "binomial":
        n, p = _trials(prediction), _probability(prediction.get("p"))
        return 1 - _count_tail(_binomial_pmf(n, p), n * p, observed)
    if kind == "beta_binomial":
        # Parameter uncertainty is averaged over the Beta posterior, not replaced by its mean.
        n = _trials(prediction)
        alpha, beta = _number(prediction.get("alpha")), _number(prediction.get("beta"))
        if alpha <= 0 or beta <= 0:
            raise ValueError("A Beta posterior needs positive alpha and beta")
        pmf = _beta_binomial_pmf(n, alpha, beta)
        return 1 - _count_tail(pmf, n * alpha / (alpha + beta), observed)
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
    """Score a forecast against retained outcomes, reporting unavailable metrics or unresolved evidence."""
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
    basis = None
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
                omitted = calibration_omission(calibration)
                if omitted is not None:
                    skipped[metric] = omitted
                    continue
                value = prediction_unexpectedness(prediction, observed, calibration=calibration)
                basis = calibration_basis(calibration)
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
        basis=basis if samples else None,
    )


POLICY_METRICS = ("action_log_loss", "reference_probability", "expected_utility")


def evaluate_policy(result: Any, outcomes: Mapping[str, Any], metrics) -> dict[str, float]:
    """Score an action distribution against a hidden reference action or utility table.

    outcomes holds "reference" (the action that should be chosen), "utilities"
    ([[action, utility], ...]) or both, and optionally "allowed". A utility table
    also bounds the admissible actions. A violated distribution contract raises.
    action_log_loss is the proper log score; zero probability on the reference is
    infinite and therefore never averages into an acceptable mean.
    """
    from ..policy.contracts import action_key, probability_of, validate_distribution

    allowed = outcomes.get("allowed")
    if allowed is None and "utilities" in outcomes:
        allowed = [action for action, _ in outcomes["utilities"]]
    distribution = validate_distribution(result, allowed)
    samples = {}
    if "reference" in outcomes:
        probability = probability_of(distribution, outcomes["reference"])
        samples["reference_probability"] = probability
        samples["action_log_loss"] = -math.log(probability) if probability > 0 else math.inf
    if "utilities" in outcomes:
        table = {action_key(action): float(value) for action, value in outcomes["utilities"]}
        samples["expected_utility"] = sum(
            probability * table[action_key(candidate)]
            for candidate, probability in distribution["choices"]
        )
    return {metric: samples[metric] for metric in metrics if metric in samples}
