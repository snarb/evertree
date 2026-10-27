"""Storage of immutable evaluation results and evaluation statistics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..datasets import freeze_json, thaw_json
from .contracts import (
    INCOMPARABLE_PERIODS,
    INSUFFICIENT_DATA,
    MISSING_COMPARISON_BASIS,
    OMISSION_REASONS,
    EvaluationResult,
    _probability,
)
from .scope import ProcessScope


def _time(value: str | datetime) -> datetime:
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if stamp.tzinfo is None:
        raise ValueError("Evaluation timestamps must include their timezone")
    return stamp.astimezone(UTC)


def _interval(bounds: tuple[str, str]) -> tuple[datetime, datetime]:
    start, end = map(_time, bounds)
    if start >= end:
        raise ValueError("Period must be a nonempty half-open interval")
    return start, end


def _iso(bounds: tuple[datetime, datetime]) -> tuple[str, str]:
    return (bounds[0].isoformat(), bounds[1].isoformat())


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return sum(items) / len(items) if items else None


def _scope(processes: ProcessScope | Iterable[str]) -> ProcessScope:
    if isinstance(processes, ProcessScope):
        return processes
    return ProcessScope({str(process): str(process) for process in processes})


def _label(scope: ProcessScope, process: str, reason: str) -> dict[str, str]:
    return {"name": scope.name(process), "reason": reason}


def _coverage(
    scope: ProcessScope, covered: Iterable[str], skipped: dict[str, str], measured: set[str]
) -> tuple[dict[str, Any], dict[str, int]]:
    """Report omissions of selected or measured processes; count never-measured subtypes.

    A subtree such as [Process] holds many processes no prediction ever measured; they
    are counted rather than listed so the components that matter stay readable.
    """
    listed = {
        key: _label(scope, key, reason)
        for key, reason in skipped.items()
        if key in measured or key in scope.roots or key not in scope.processes
    }
    unmeasured = sum(1 for key in skipped if key in scope.processes and key not in listed)
    covered = list(covered)
    return listed, {
        "selected": len(scope.processes),
        "covered": len(covered),
        "skipped": len(listed),
        "never_measured": unmeasured,
    }


@dataclass(frozen=True)
class ExplanatoryTensionResult:
    """Mean unusualness of prediction discrepancies over the covered part of a group."""

    value: float | None
    by_process: Mapping[str, Any]
    skipped: Mapping[str, Any] = field(default_factory=dict)
    period: tuple[str, str] | None = None
    coverage: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "by_process", freeze_json(thaw_json(self.by_process)))
        object.__setattr__(self, "skipped", freeze_json(thaw_json(self.skipped)))
        object.__setattr__(self, "coverage", freeze_json(thaw_json(self.coverage)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "by_process": thaw_json(self.by_process),
            "skipped": thaw_json(self.skipped),
            "coverage": thaw_json(self.coverage),
            "period": list(self.period) if self.period else None,
        }


@dataclass(frozen=True)
class TensionReductionResult:
    """Change of ExplanatoryTension between periods; positive means tension decreased."""

    value: float | None
    by_process: Mapping[str, Any]
    skipped: Mapping[str, Any]
    period: tuple[str, str]
    baseline_period: tuple[str, str]
    tension_before: float | None = None
    tension_after: float | None = None
    coverage: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "by_process", freeze_json(thaw_json(self.by_process)))
        object.__setattr__(self, "skipped", freeze_json(thaw_json(self.skipped)))
        object.__setattr__(self, "coverage", freeze_json(thaw_json(self.coverage)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "by_process": thaw_json(self.by_process),
            "skipped": thaw_json(self.skipped),
            "period": list(self.period),
            "baseline_period": list(self.baseline_period),
            "tension_before": self.tension_before,
            "tension_after": self.tension_after,
            "coverage": thaw_json(self.coverage),
        }


class EvaluationStore:
    def __init__(self) -> None:
        self._results: dict[str, EvaluationResult] = {}

    def add(self, result: EvaluationResult) -> EvaluationResult:
        """Register an immutable evaluation result, allowing identical retries by identity."""
        old = self._results.get(result.id)
        if old is not None and old.to_dict() != result.to_dict():
            raise ValueError("An evaluation result is immutable")
        self._results[result.id] = result
        return result

    def get(self, identity: str) -> EvaluationResult:
        """Return an evaluation result by its stable identity."""
        return self._results[identity]

    def all(self) -> tuple[EvaluationResult, ...]:
        """Return all retained evaluation results, including unresolved cases."""
        return tuple(self._results.values())

    def _measured(self, scope: ProcessScope) -> set[str]:
        """Processes with any saved check of prediction_unexpectedness, calculated or omitted."""
        return {
            result.process_id
            for result in self._results.values()
            if result.process_id in scope.processes
            and (
                "prediction_unexpectedness" in result.skipped_metrics
                or any(
                    sample.channel == "prediction_unexpectedness"
                    for sample in result.metric_samples
                )
            )
        }

    def _unexpectedness(
        self, scope: ProcessScope, bounds: tuple[datetime, datetime]
    ) -> tuple[dict[str, list[tuple[float, str | None]]], dict[str, str]]:
        """Collect calibrated values per process for one interval, with omission reasons.

        A result belongs to the interval holding the end of the evaluated outcome, not to
        the time it was calculated. Duplicate results of one check are counted once.
        """
        values: dict[str, list[tuple[float, str | None]]] = {}
        omitted: dict[str, str] = {}
        seen: set[tuple[str | None, tuple[str, ...], str | None]] = set()
        for result in self._results.values():
            if result.process_id not in scope.processes or not result.observed_at:
                continue
            if not bounds[0] <= _time(result.observed_at) < bounds[1]:
                continue
            samples = [
                sample.value
                for sample in result.metric_samples
                if sample.channel == "prediction_unexpectedness"
            ]
            if not samples:
                reason = result.skipped_metrics.get("prediction_unexpectedness")
                if reason in OMISSION_REASONS:
                    omitted.setdefault(result.process_id, reason)
                continue
            key = (result.evaluated_subject, result.outcome_ids, result.comparison_key)
            if key in seen:
                continue
            seen.add(key)
            values.setdefault(result.process_id, []).append(
                (_probability(samples[0]), result.comparison_key)
            )
        return values, omitted

    def explanatory_tension(
        self, window: tuple[str, str], processes: ProcessScope | Iterable[str]
    ) -> ExplanatoryTensionResult:
        """Average calibrated unexpectedness within each process, then across processes.

        Processes have equal weights regardless of how many checks they contributed.
        """
        scope = _scope(processes)
        bounds = _interval(window)
        values, omitted = self._unexpectedness(scope, bounds)
        by_process: dict[str, Any] = {}
        skipped = dict(scope.skipped)
        for process in sorted(scope.processes):
            scores = values.get(process)
            if not scores:
                skipped[process] = omitted.get(process, INSUFFICIENT_DATA)
                continue
            by_process[process] = {
                "name": scope.name(process),
                "mean": sum(value for value, _ in scores) / len(scores),
                "count": len(scores),
            }
        listed, coverage = _coverage(scope, by_process, skipped, self._measured(scope))
        return ExplanatoryTensionResult(
            _mean(item["mean"] for item in by_process.values()),
            by_process,
            listed,
            _iso(bounds),
            coverage,
        )

    def get_tension_reduction(
        self,
        period: tuple[str, str],
        processes: ProcessScope | Iterable[str],
        baseline_period: tuple[str, str] | None = None,
    ) -> TensionReductionResult:
        """Compare calibrated prediction unexpectedness across comparable process periods.

        Without baseline_period, use the immediately preceding interval of equal length.
        Both ExplanatoryTension values cover the same processes with evidence and one
        shared calibration and selection basis in both periods.
        """
        scope = _scope(processes)
        after_bounds = _interval(period)
        start, end = after_bounds
        if baseline_period is None:
            before_bounds = (start - (end - start), start)
        else:
            before_bounds = _interval(baseline_period)
        before, omitted_before = self._unexpectedness(scope, before_bounds)
        after, omitted_after = self._unexpectedness(scope, after_bounds)
        by_process: dict[str, Any] = {}
        skipped = dict(scope.skipped)
        for process in sorted(scope.processes):
            old, new = before.get(process), after.get(process)
            if not old or not new:
                skipped[process] = (
                    omitted_after.get(process) or omitted_before.get(process) or INSUFFICIENT_DATA
                )
                continue
            keys = {key for _, key in old + new}
            if None in keys:
                skipped[process] = MISSING_COMPARISON_BASIS
                continue
            if {key for _, key in old} != {key for _, key in new}:
                skipped[process] = INCOMPARABLE_PERIODS
                continue
            mean_before = sum(value for value, _ in old) / len(old)
            mean_after = sum(value for value, _ in new) / len(new)
            by_process[process] = {
                "name": scope.name(process),
                "before": mean_before,
                "after": mean_after,
                "delta": mean_before - mean_after,
                "before_count": len(old),
                "after_count": len(new),
            }
        tension_before = _mean(item["before"] for item in by_process.values())
        tension_after = _mean(item["after"] for item in by_process.values())
        listed, coverage = _coverage(scope, by_process, skipped, self._measured(scope))
        return TensionReductionResult(
            _mean(item["delta"] for item in by_process.values()),
            by_process,
            listed,
            _iso(after_bounds),
            _iso(before_bounds),
            tension_before,
            tension_after,
            coverage,
        )

    def snapshot(self) -> dict[str, Any]:
        """Capture retained evaluation results and their source provenance."""
        return {"results": [result.to_dict() for result in self._results.values()]}

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any]) -> EvaluationStore:
        """Restore evaluation result variants and enforce immutable identities."""
        store = cls()
        for result in data.get("results", ()):
            store.add(EvaluationResult.from_dict(result))
        return store
