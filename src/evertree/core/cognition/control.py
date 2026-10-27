"""Verification gates, commitment decisions and task outcome statistics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import Any

from ..evaluation.acceptance import VerificationResult
from ..evaluation.contracts import COUNTED_AT_PARENT_TASK_LEVEL, MISSING_FINAL_OUTCOME
from ..evaluation.scope import ProcessScope
from ..evaluation.store import _interval, _scope, _time
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
    """Summarize mandatory checks, distinguishing explicit failure from missing evidence."""
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
    """Choose automatic commitment or conscious selection from verification and decision risk."""
    if verified is not None and not verified.verified:
        return CommitmentDecision(
            "consciousness_selection", "Mandatory verification is incomplete or failed"
        )
    if not familiar or uncertainty or high_impact:
        return CommitmentDecision(
            "consciousness_selection", "Novelty, uncertainty or consequential decision"
        )
    return CommitmentDecision("automatic", "Known behavior within its verified scope")


def _effective_deadline(task: TaskState) -> datetime | None:
    """The first deadline that passed while in force without success, else the last one.

    A later revision or cancellation cannot erase a deadline the task already missed.
    """
    history = task.deadline_history or (
        [{"deadline": task.deadline, "since": task.created_at}] if task.deadline else []
    )
    finished = _time(task.completed_at) if task.completed_at else None
    for entry, following in pairwise(history):
        if entry["deadline"] is None:
            continue
        due = _time(entry["deadline"])
        if due < _time(following["since"]) and not (
            task.status == "succeeded" and finished is not None and finished <= due
        ):
            return due
    final = history[-1]["deadline"] if history else None
    return _time(final) if final else None


def get_task_outcome_stats(
    tasks: Iterable[TaskState],
    period: tuple[str, str],
    processes: ProcessScope | Iterable[str],
) -> dict[str, Any]:
    """Aggregate final Task outcomes and deadline adherence for a process scope in [start, end).

    Each Task counts once, at the top included level, for the process doing its work.
    Cancellation is reported apart from success; open overdue Tasks count as missed.
    """
    scope = _scope(processes)
    start, end = _interval(period)
    states = tuple(task for task in tasks if task.process_id in scope.processes)
    included = {task.id for task in states}
    groups: dict[str, dict[str, Any]] = {}
    skipped: dict[str, Any] = {key: {"reason": reason} for key, reason in scope.skipped.items()}

    def blank() -> dict[str, int]:
        return {"successes": 0, "failures": 0, "on_time": 0, "due": 0, "cancelled": 0, "open": 0}

    for task in states:
        if _time(task.created_at) >= end:
            continue
        if task.parent_task_id in included:
            skipped[task.id] = {"reason": COUNTED_AT_PARENT_TASK_LEVEL}
            continue
        if task.terminal and task.completed_at is None:
            skipped[task.id] = {"reason": MISSING_FINAL_OUTCOME}
            continue
        counts = blank()
        finished = _time(task.completed_at) if task.completed_at else None
        if finished is None or finished >= end:
            counts["open"] += 1
        elif finished >= start:
            key = {"succeeded": "successes", "failed": "failures", "cancelled": "cancelled"}
            counts[key[task.status]] += 1
        due = _effective_deadline(task)
        if due is not None and start <= due < end:
            withdrawn = task.status == "cancelled" and finished is not None and finished < due
            if not withdrawn:
                counts["due"] += 1
                counts["on_time"] += int(
                    task.status == "succeeded" and finished is not None and finished <= due
                )
        if any(counts.values()):
            group = groups.setdefault(task.process_id, blank())
            for key, value in counts.items():
                group[key] += value
    total = blank()
    for counts in groups.values():
        for key in total:
            total[key] += counts[key]

    def ratios(counts: Mapping[str, int]) -> dict[str, Any]:
        decided = counts["successes"] + counts["failures"]
        return {
            "success_rate": {
                "value": counts["successes"] / decided if decided else None,
                "numerator": counts["successes"],
                "denominator": decided,
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
        "by_process": {
            key: {"name": scope.name(key), **ratios(value)} for key, value in sorted(groups.items())
        },
        "skipped": skipped,
        "period": [start.isoformat(), end.isoformat()],
    }
