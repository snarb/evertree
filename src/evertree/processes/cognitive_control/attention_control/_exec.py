"""Propose the highest-priority ready Task; the runtime applies the switch."""

import math


def run(queue: list[dict], current_task: str | None = None):
    ready = []
    for position, task in enumerate(queue):
        priority = task["attention_priority"]
        if not isinstance(priority, (int, float)) or not math.isfinite(priority):
            raise ValueError("Task priority must be finite")
        if task.get("status") not in {"succeeded", "failed", "cancelled", "waiting"}:
            ready.append((priority, -position, task["task_id"]))
    selected = max(ready)[2] if ready else current_task
    return {
        "result": {
            "task_id": selected,
            "action": "continue" if selected == current_task else "switch",
        },
        "feedback": None,
    }
