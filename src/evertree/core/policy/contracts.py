"""The ActionDistribution contract shared by policies, Evaluation and Core sampling.

The wire form is {"choices": [[candidate, probability], ...]}, the JSON spelling of
ActionDistribution(choices=[(candidate, probability), ...]). Candidates are any JSON
values; uniqueness compares their canonical JSON. There is no implicit fallback.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

TOLERANCE = 1e-9


def action_key(candidate: Any) -> str:
    """Identify a candidate by its canonical JSON content."""
    # Self-contained, so candidate tests can import this module without the rest of Core.
    return json.dumps(candidate, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_distribution(distribution: Any, allowed: Iterable[Any] | None = None) -> dict:
    """Return a checked distribution or raise ValueError naming the violated condition.

    allowed limits the candidates when the caller supplies the admissible set.
    Zero-probability choices may be present or omitted.
    """
    if not isinstance(distribution, Mapping) or set(distribution) != {"choices"}:
        raise ValueError('An action distribution is exactly {"choices": [[candidate, p], ...]}')
    choices = distribution["choices"]
    if not isinstance(choices, Sequence) or isinstance(choices, str) or not choices:
        raise ValueError("An action distribution needs nonempty choices")
    admissible = None if allowed is None else {action_key(item) for item in allowed}
    seen, total, checked = set(), 0.0, []
    for choice in choices:
        if not isinstance(choice, Sequence) or isinstance(choice, str) or len(choice) != 2:
            raise ValueError("Each choice is a [candidate, probability] pair")
        candidate, probability = choice
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not math.isfinite(probability)
            or probability < 0
        ):
            raise ValueError("Choice probabilities must be finite and nonnegative")
        key = action_key(candidate)
        if key in seen:
            raise ValueError("Action distribution candidates must be unique")
        if admissible is not None and key not in admissible:
            raise ValueError("Action distribution contains a candidate outside the allowed set")
        seen.add(key)
        total += probability
        checked.append([candidate, float(probability)])
    if abs(total - 1.0) > TOLERANCE:
        raise ValueError("Action distribution probabilities must sum to 1")
    return {"choices": checked}


def probability_of(distribution: Mapping, candidate: Any) -> float:
    """Probability a checked distribution gives a candidate; absent candidates have zero."""
    key = action_key(candidate)
    return next(
        (p for item, p in distribution["choices"] if action_key(item) == key),
        0.0,
    )


def certain(candidate: Any) -> dict:
    """A deterministic decision."""
    return {"choices": [[candidate, 1.0]]}


def greedy_distribution(candidates: Sequence[Any], values: Sequence[float]) -> dict:
    """Spread probability uniformly over the candidates with the highest value."""
    if not candidates or len(candidates) != len(values):
        raise ValueError("Greedy selection needs one value per candidate")
    best = max(values)
    winners = [item for item, value in zip(candidates, values, strict=True) if value == best]
    return validate_distribution({"choices": [[item, 1 / len(winners)] for item in winners]})


def softmax_distribution(
    candidates: Sequence[Any], values: Sequence[float], temperature: float
) -> dict:
    """Weight candidates by exp(value / temperature); lower temperature is greedier."""
    if not candidates or len(candidates) != len(values):
        raise ValueError("Softmax selection needs one value per candidate")
    if not temperature > 0:
        raise ValueError("Softmax temperature must be positive")
    top = max(values)
    weights = [math.exp((value - top) / temperature) for value in values]
    total = sum(weights)
    choices = [[item, weight / total] for item, weight in zip(candidates, weights, strict=True)]
    # Rounding can leave the sum a few ulps off 1; give the remainder to the first choice.
    choices[0][1] += 1.0 - sum(p for _, p in choices)
    return validate_distribution({"choices": choices})
