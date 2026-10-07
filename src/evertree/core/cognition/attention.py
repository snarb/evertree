"""Task admission, conscious focus and preparation of task context."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Any
from uuid import uuid4

from ..datasets import freeze_json, thaw_json
from .tasks import TaskSpecification, TaskState, TaskStore


class AttentionRuntime:
    """Single-Task execution gate. OS process liveness stays with the controller.

    A switch requires synchronous confirmation of a stopped execution tree; a
    queued request or merely setting a workflow's cancelled flag is insufficient.
    """

    def __init__(self, tasks: TaskStore) -> None:
        self.tasks = tasks
        self.focus: str | None = None
        self.running_task: str | None = None
        self._queue: dict[str, tuple[float, int]] = {}
        self._sequence = 0
        self._lock = RLock()

    def request_attention(self, task_id: str, priority: float, *, reason: str = "") -> None:
        state = self.tasks.get(task_id)
        if state.terminal:
            raise ValueError("Completed tasks cannot request attention")
        if not math.isfinite(priority):
            raise ValueError("Attention priority must be finite")
        with self._lock:
            state.attention_priority = priority
            if task_id != self.focus:
                old = self._queue.get(task_id)
                self._sequence += old is None
                self._queue[task_id] = (priority, old[1] if old else self._sequence)

    def next_task(self) -> str | None:
        with self._lock:
            live = [
                (identity, item)
                for identity, item in self._queue.items()
                if not self.tasks.get(identity).terminal
            ]
            return min(live, key=lambda item: (-item[1][0], item[1][1]))[0] if live else None

    def admit(
        self,
        task_id: str,
        *,
        conscious: bool = True,
        stop_current: Callable[[str], bool] | None = None,
    ) -> TaskState:
        with self._lock:
            state = self.tasks.get(task_id)
            if state.terminal:
                raise ValueError("Completed tasks cannot execute or recover")
            if state.execution_budget is None:
                raise ValueError("Consciousness must assign both budgets before task execution")
            if state.budget_exhausted or state.hard_limit_reached or state.review_required:
                raise ValueError("Task requires a budget reassessment before execution")
            if self.running_task and self.running_task != task_id:
                old = self.tasks.get(self.running_task)
                if stop_current is None or stop_current(old.id) is not True:
                    raise RuntimeError("Previous Task execution has not been confirmed stopped")
                old.execution_stopped = True
                if not old.terminal:
                    old.status = "suspended"
            self.running_task = task_id
            self.focus = task_id if conscious else None
            self._queue.pop(task_id, None)
            state.status = "running"
            state.execution_stopped = False
            state.waiting_for = []
            return state

    def release(self, task_id: str, *, execution_stopped: bool, status: str = "suspended") -> None:
        with self._lock:
            if not execution_stopped:
                raise RuntimeError("Cannot release execution ownership before actual stop")
            state = self.tasks.get(task_id)
            if not state.terminal:
                if status not in {"suspended", "waiting", "queued"}:
                    raise ValueError("Release does not establish a final task outcome")
                state.status = status
            state.execution_stopped = True
            if self.running_task == task_id:
                self.running_task = None
            if self.focus == task_id:
                self.focus = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "focus": self.focus,
            "running_task": self.running_task,
            "queue": {key: list(value) for key, value in self._queue.items()},
            "sequence": self._sequence,
        }

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any], tasks: TaskStore) -> AttentionRuntime:
        runtime = cls(tasks)
        runtime.focus = data.get("focus")
        runtime.running_task = data.get("running_task")
        runtime._queue = {key: tuple(value) for key, value in data.get("queue", {}).items()}
        runtime._sequence = data.get("sequence", 0)
        for identity in {*runtime._queue, runtime.focus, runtime.running_task} - {None}:
            if tasks.get(identity).terminal:
                raise ValueError("Attention snapshot attempts to restore a completed task")
        if runtime.focus is not None and runtime.focus != runtime.running_task:
            raise ValueError("Conscious focus must belong to the admitted task")
        return runtime


@dataclass(frozen=True)
class PreparedContext:
    task_id: str
    episode_id: str | None
    specification: TaskSpecification
    incoming: Any
    messages: tuple[Mapping[str, Any], ...] = ()
    source_ids: tuple[str, ...] = ()
    state: Mapping[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        object.__setattr__(self, "incoming", freeze_json(thaw_json(self.incoming)))
        object.__setattr__(
            self, "messages", tuple(freeze_json(thaw_json(message)) for message in self.messages)
        )
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
        object.__setattr__(self, "state", freeze_json(thaw_json(self.state)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "episode_id": self.episode_id,
            "specification": self.specification.to_dict(),
            "incoming": thaw_json(self.incoming),
            "messages": thaw_json(self.messages),
            "source_ids": list(self.source_ids),
            "state": thaw_json(self.state),
        }


def prepare_context(
    task: TaskState,
    episode_id: str | None,
    incoming: Any,
    *,
    messages: Iterable[Mapping[str, Any]] = (),
    source_ids: Iterable[str] = (),
) -> PreparedContext:
    """Preserve the complete current input; caller selects relevant prior sources."""
    return PreparedContext(
        task.id,
        episode_id,
        task.specification,
        incoming,
        tuple(messages),
        tuple(dict.fromkeys((*task.source_ids, *source_ids))),
        {
            "progress": task.progress,
            "plan": task.plan,
            "unresolved_questions": task.unresolved_questions,
            "waiting_for": task.waiting_for,
            "spent": task.spent,
            "execution_budget": task.execution_budget.to_dict() if task.execution_budget else None,
            "self_improvement_budget": task.self_improvement_budget,
        },
    )
