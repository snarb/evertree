"""Reading supervisor evaluations together with the comments their observations keep."""

from __future__ import annotations

from typing import Any

from ..values import json_value
from .scope import ProcessScope
from .store import EvaluationStore, _interval, _iso, _time


def supervisor_feedback_history(
    evaluations: EvaluationStore, memory, scope: ProcessScope, period: tuple[str, str]
) -> dict[str, Any]:
    """Return supervisor_feedback_signal values in [start, end) with comments via provenance.

    The channel value is the number alone; the comment is read from the original
    observation so analysis and credit assignment can use the stated reason.
    """
    start, end = _interval(period)
    items = []
    for result in evaluations.all():
        if result.process_id not in scope.processes or not result.observed_at:
            continue
        if not start <= _time(result.observed_at) < end:
            continue
        for sample in result.metric_samples:
            if sample.channel != "supervisor_feedback_signal":
                continue
            observation = memory.get_event(int(result.provenance[0]))
            output = json_value(observation.output)
            items.append(
                {
                    "subject": result.evaluated_subject,
                    "process_id": result.process_id,
                    "process": scope.name(result.process_id),
                    "value": sample.value,
                    "normalized": sample.value / 5,
                    "comment": output.get("comment"),
                    "source_id": observation.arguments.get("source_id"),
                    "observed_at": result.observed_at,
                    "evaluation_id": result.id,
                    "observation_id": observation.id,
                }
            )
    items.sort(key=lambda item: item["observed_at"])
    by_process: dict[str, Any] = {}
    for item in items:
        group = by_process.setdefault(
            item["process_id"], {"name": item["process"], "count": 0, "total": 0.0}
        )
        group["count"] += 1
        group["total"] += item["value"]
    for group in by_process.values():
        group["mean"] = group.pop("total") / group["count"]
    return {
        "items": items,
        "by_process": by_process,
        "skipped": {key: {"reason": reason} for key, reason in scope.skipped.items()},
        "period": list(_iso((start, end))),
    }
