"""Verification gates, commitment decisions and task outcome statistics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .program_acceptance import VerificationResult
from .tasks import TaskState


@dataclass(frozen=True)
class CommitmentDecision:
    mode: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"automatic", "consciousness_selection"}:
            raise ValueError("Unknown commitment mode")


def verification_result(
    required_checks: Iterable[str], results: Mapping[str, bool | None]
) -> VerificationResult:
    mandatory = tuple(required_checks)
    failed = tuple(name for name in mandatory if results.get(name) is False)
    missing = tuple(
        name for name in mandatory if results.get(name) is not True and name not in failed
    )
    if failed:
        return VerificationResult(
            "failed", tuple("Check failed: " + name for name in failed), missing
        )
    return VerificationResult("need_checks" if missing else "verified", missing_checks=missing)


def commitment_control(
    *,
    verified: VerificationResult | None,
    familiar: bool,
    uncertainty: bool = False,
    high_impact: bool = False,
) -> CommitmentDecision:
    if verified is not None and not verified.verified:
        return CommitmentDecision(
            "consciousness_selection", "Mandatory verification is incomplete or failed"
        )
    if not familiar or uncertainty or high_impact:
        return CommitmentDecision(
            "consciousness_selection", "Novelty, uncertainty or consequential decision"
        )
    return CommitmentDecision("automatic", "Known behavior within its verified scope")


def get_task_outcome_stats(
    tasks: Iterable[TaskState],
    period: tuple[str, str],
    processes: Iterable[str],
    *,
    descendants: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    from .evaluation import _time

    start, end = map(_time, period)
    if start >= end:
        raise ValueError("Period must be nonempty")
    selected = set(processes)
    pending = list(selected)
    while pending:
        for child in (descendants or {}).get(pending.pop(), ()):
            if child not in selected:
                selected.add(child)
                pending.append(child)
    states = tuple(tasks)
    included_ids = {task.id for task in states if task.process_id in selected}
    groups: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}

    def blank() -> dict[str, Any]:
        return {"successes": 0, "failures": 0, "on_time": 0, "due": 0, "cancelled": 0, "open": 0}

    total = blank()
    for task in states:
        if task.process_id not in selected:
            continue
        if task.parent_task_id in included_ids:
            skipped[task.id] = "counted_at_parent_task_level"
            continue
        counts = groups.setdefault(task.process_id, blank())
        created = _time(task.created_at)
        finished = _time(task.completed_at) if task.completed_at else None
        if created >= end:
            continue
        if task.terminal and finished is None:
            skipped[task.id] = "missing_final_outcome_time"
            continue
        if finished is None or finished >= end:
            counts["open"] += 1
        if finished is not None and start <= finished < end:
            if task.status == "succeeded":
                counts["successes"] += 1
            elif task.status == "failed":
                counts["failures"] += 1
            elif task.status == "cancelled":
                counts["cancelled"] += 1
        if task.deadline:
            due = _time(task.deadline)
            if start <= due < end:
                if task.status == "cancelled" and finished is not None and finished < due:
                    continue
                counts["due"] += 1
                counts["on_time"] += int(
                    task.status == "succeeded" and finished is not None and finished <= due
                )
    for counts in groups.values():
        for key in total:
            total[key] += counts[key]

    def ratios(counts: Mapping[str, int]) -> dict[str, Any]:
        denominator = counts["successes"] + counts["failures"]
        return {
            "success_rate": {
                "value": counts["successes"] / denominator if denominator else None,
                "numerator": counts["successes"],
                "denominator": denominator,
            },
            "on_time_rate": {
                "value": counts["on_time"] / counts["due"] if counts["due"] else None,
                "numerator": counts["on_time"],
                "denominator": counts["due"],
            },
            "cancelled": counts["cancelled"],
            "open": counts["open"],
        }

    return {
        **ratios(total),
        "by_process": {key: ratios(value) for key, value in groups.items()},
        "skipped": skipped,
        "period": list(period),
    }


# Keep existing trace type names and pickled references valid through the public module.
for _export in (
    CommitmentDecision,
    verification_result,
    commitment_control,
    get_task_outcome_stats,
):
    _export.__module__ = "evertree.core.cognition"
