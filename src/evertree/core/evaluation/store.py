"""Storage of immutable evaluation results and evaluation statistics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from .contracts import (
    EvaluationResult,
    _probability,
)


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
