"""Task state, attention invariants and the deterministic boundaries of cognition.

The provider chooses an objective, a finite budget and the next action. These
classes retain those decisions and enforce their contracts without inventing a
universal budget, task router or success signal.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from .datasets import freeze_json, thaw_json
from .evaluation import VerificationResult

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
TASK_STATUSES = TERMINAL_STATUSES | {"queued", "running", "waiting", "suspended"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _finite_nonnegative(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be finite and nonnegative")
    return float(value)


@dataclass(frozen=True)
class TaskSpecification:
    objective: str
    success_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    preferences: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    revision: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ValueError("Task objective is required")
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            raise ValueError("Task specification revision must be positive")
        for name in ("success_criteria", "constraints", "preferences", "source_ids"):
            values = getattr(self, name)
            if isinstance(values, str) or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise ValueError(f"{name} must be a sequence of nonempty strings")
            object.__setattr__(self, name, tuple(values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "success_criteria": list(self.success_criteria),
            "constraints": list(self.constraints),
            "preferences": list(self.preferences),
            "source_ids": list(self.source_ids),
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TaskSpecification:
        return cls(**dict(data))


@dataclass(frozen=True)
class ExecutionBudget:
    resources: Mapping[str, float]
    reason: str = "Assigned by consciousness for this task"

    def __post_init__(self) -> None:
        if not self.resources:
            raise ValueError("Every admitted task needs a finite execution budget")
        values = {key: _finite_nonnegative(value, key) for key, value in self.resources.items()}
        if any(not key or value <= 0 for key, value in values.items()):
            raise ValueError("Budget resource names and positive finite limits are required")
        object.__setattr__(self, "resources", freeze_json(values))

    def to_dict(self) -> dict[str, Any]:
        return {"resources": dict(self.resources), "reason": self.reason}


@dataclass
class TaskState:
    id: str
    specification: TaskSpecification
    status: str = "queued"
    execution_budget: ExecutionBudget | None = None
    self_improvement_budget: float | None = None
    spent: dict[str, float] = field(default_factory=dict)
    self_improvement_spent: dict[str, float] = field(default_factory=dict)
    hard_limits: dict[str, float] = field(default_factory=dict)
    progress: str = ""
    plan: list[dict[str, Any]] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    waiting_for: list[str] = field(default_factory=list)
    episode_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    program_run_ids: list[str] = field(default_factory=list)
    result_ids: list[str] = field(default_factory=list)
    attention_priority: float = 0.0
    process_id: str | None = None
    parent_task_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    completed_at: str | None = None
    deadline: str | None = None
    outcome_reason: str | None = None
    review_required: bool = False
    execution_stopped: bool = True
    budget_history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in TASK_STATUSES or not self.id:
            raise ValueError("Invalid task identity or status")
        if self.self_improvement_budget is not None and not (
            0 <= _finite_nonnegative(self.self_improvement_budget, "self_improvement_budget") <= 100
        ):
            raise ValueError("Self-improvement fraction must be in [0, 100]")
        if (self.execution_budget is None) != (self.self_improvement_budget is None):
            raise ValueError("Execution and self-improvement budgets must be assigned together")
        for values in (self.spent, self.self_improvement_spent, self.hard_limits):
            for key, value in values.items():
                _finite_nonnegative(value, key)

    @property
    def task_id(self) -> str:
        return self.id

    @property
    def objective(self) -> str:
        return self.specification.objective

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def remaining(self, resource: str, *, self_improvement: bool = False) -> float | None:
        if self.execution_budget is None or resource not in self.execution_budget.resources:
            return None
        limit = self.execution_budget.resources[resource]
        remaining = max(0.0, limit - self.spent.get(resource, 0))
        if resource in self.hard_limits:
            remaining = min(
                remaining, max(0.0, self.hard_limits[resource] - self.spent.get(resource, 0))
            )
        if self_improvement:
            sublimit = limit * (self.self_improvement_budget or 0) / 100
            remaining = min(
                remaining, max(0.0, sublimit - self.self_improvement_spent.get(resource, 0))
            )
        return remaining

    @property
    def budget_exhausted(self) -> bool:
        return self.execution_budget is not None and any(
            self.spent.get(key, 0) >= limit
            for key, limit in self.execution_budget.resources.items()
        )

    @property
    def hard_limit_reached(self) -> bool:
        return any(self.spent.get(key, 0) >= limit for key, limit in self.hard_limits.items())

    def to_dict(self) -> dict[str, Any]:
        values = {
            name: thaw_json(value)
            for name, value in self.__dict__.items()
            if name not in {"specification", "execution_budget"}
        }
        values["specification"] = self.specification.to_dict()
        values["execution_budget"] = (
            self.execution_budget.to_dict() if self.execution_budget else None
        )
        return thaw_json(freeze_json(values))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TaskState:
        values = thaw_json(freeze_json(dict(data)))
        values["specification"] = TaskSpecification.from_dict(values["specification"])
        if values.get("execution_budget") is not None:
            values["execution_budget"] = ExecutionBudget(**values["execution_budget"])
        return cls(**values)


class TaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskState] = {}
        self._specifications: dict[str, list[TaskSpecification]] = {}
        self._usage_operations: dict[str, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._lock = RLock()

    def create_task(
        self,
        objective: str | TaskSpecification,
        *,
        task_id: str | None = None,
        episode_id: str | None = None,
        source_ids: Iterable[str] = (),
        process_id: str | None = None,
        parent_task_id: str | None = None,
        hard_limits: Mapping[str, float] | None = None,
        deadline: str | None = None,
    ) -> TaskState:
        source_ids = tuple(source_ids)
        spec = (
            objective
            if isinstance(objective, TaskSpecification)
            else TaskSpecification(objective, source_ids=source_ids)
        )
        state = TaskState(
            task_id or str(uuid4()),
            spec,
            episode_ids=[episode_id] if episode_id else [],
            source_ids=list(dict.fromkeys((*spec.source_ids, *source_ids))),
            process_id=process_id,
            parent_task_id=parent_task_id,
            hard_limits=dict(hard_limits or {}),
            deadline=deadline,
        )
        with self._lock:
            if state.id in self._tasks:
                raise ValueError("Task identity is already registered")
            if parent_task_id and parent_task_id not in self._tasks:
                raise ValueError("Unknown parent task")
            self._tasks[state.id] = state
            self._specifications[state.id] = [spec]
        return state

    def get(self, task_id: str) -> TaskState:
        return self._tasks[task_id]

    def all(self) -> tuple[TaskState, ...]:
        return tuple(self._tasks.values())

    def revise_specification(
        self, task_id: str, specification: TaskSpecification, *, provenance: str
    ) -> TaskSpecification:
        state = self.get(task_id)
        if state.terminal or not provenance:
            raise ValueError("A specification revision needs an open task and provenance")
        if specification.revision != state.specification.revision + 1:
            raise ValueError("Specification revisions must advance exactly once")
        self._specifications[task_id].append(specification)
        state.specification = specification
        self._events.append(
            {
                "kind": "specification_revised",
                "task_id": task_id,
                "revision": specification.revision,
                "provenance": provenance,
                "at": utc_now(),
            }
        )
        return specification

    def assign_budget(
        self,
        task_id: str,
        budget: ExecutionBudget | Mapping[str, float],
        self_improvement_budget: float,
        *,
        reason: str,
    ) -> None:
        state = self.get(task_id)
        if state.terminal:
            raise ValueError("Cannot assign budget to a completed task")
        budget = budget if isinstance(budget, ExecutionBudget) else ExecutionBudget(budget, reason)
        fraction = _finite_nonnegative(self_improvement_budget, "self_improvement_budget")
        if fraction > 100 or not reason.strip():
            raise ValueError("Budget allocation needs a reason and fraction in [0, 100]")
        for resource, spent in state.spent.items():
            if resource in budget.resources and budget.resources[resource] < spent:
                raise ValueError("A revised total budget cannot erase already spent resources")
        if state.execution_budget and not set(state.execution_budget.resources) <= set(
            budget.resources
        ):
            raise ValueError("Budget reassessment cannot silently remove tracked resource limits")
        for resource, hard_limit in state.hard_limits.items():
            if resource in budget.resources and budget.resources[resource] > hard_limit:
                raise ValueError("Budget exceeds a user-defined hard limit")
        state.execution_budget = budget
        state.self_improvement_budget = fraction
        state.review_required = state.budget_exhausted
        state.budget_history.append(
            {
                "budget": budget.to_dict(),
                "self_improvement_budget": fraction,
                "spent": dict(state.spent),
                "reason": reason,
                "at": utc_now(),
            }
        )

    def record_usage(
        self,
        task_id: str,
        resource: str,
        amount: float,
        *,
        operation_id: str,
        self_improvement: bool = False,
    ) -> None:
        amount = _finite_nonnegative(amount, resource)
        record = {
            "task_id": task_id,
            "resource": resource,
            "amount": amount,
            "self_improvement": self_improvement,
        }
        if not operation_id or not resource:
            raise ValueError("Usage requires a stable operation identity and resource unit")
        with self._lock:
            if operation_id in self._usage_operations:
                if self._usage_operations[operation_id] != record:
                    raise ValueError("Usage operation identity reused with different parameters")
                return
            current = self.get(task_id)
            visited: set[str] = set()
            states: list[TaskState] = []
            while current:
                if current.id in visited:
                    raise ValueError("Task ownership cycle")
                visited.add(current.id)
                states.append(current)
                current = self.get(current.parent_task_id) if current.parent_task_id else None
            for state in states:
                state.spent[resource] = state.spent.get(resource, 0) + amount
                if self_improvement:
                    state.self_improvement_spent[resource] = (
                        state.self_improvement_spent.get(resource, 0) + amount
                    )
                state.review_required = state.budget_exhausted or state.hard_limit_reached
            self._usage_operations[operation_id] = record

    def set_waiting(
        self, task_id: str, *, waiting_for: Iterable[str], reason: str, execution_stopped: bool
    ) -> None:
        state = self.get(task_id)
        if state.terminal or not execution_stopped:
            raise ValueError("Waiting task must be open and its execution stopped")
        state.status = "waiting"
        state.waiting_for = list(waiting_for)
        state.progress = reason
        state.execution_stopped = True

    def finish(
        self,
        task_id: str,
        status: str,
        *,
        reason: str,
        execution_stopped: bool,
        verification: VerificationResult | None = None,
        completed_at: str | None = None,
    ) -> None:
        state = self.get(task_id)
        if status not in TERMINAL_STATUSES or state.terminal:
            raise ValueError("Task must move from an open state to a terminal outcome")
        if not execution_stopped:
            raise ValueError(
                "Task completion requires confirmation that its execution tree stopped"
            )
        if status == "succeeded" and (verification is None or not verification.verified):
            raise ValueError("Task success must be verified against its specification")
        state.status = status
        state.execution_stopped = True
        state.completed_at = completed_at or utc_now()
        state.outcome_reason = reason
        state.waiting_for = []
        self._events.append(
            {
                "kind": "task_outcome",
                "task_id": task_id,
                "status": status,
                "reason": reason,
                "at": state.completed_at,
                "specification_revision": state.specification.revision,
            }
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tasks": [state.to_dict() for state in self._tasks.values()],
                "specifications": {
                    key: [spec.to_dict() for spec in specs]
                    for key, specs in self._specifications.items()
                },
                "usage_operations": thaw_json(freeze_json(self._usage_operations)),
                "events": thaw_json(freeze_json(self._events)),
            }

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any]) -> TaskStore:
        store = cls()
        for raw in data.get("tasks", ()):
            state = TaskState.from_dict(raw)
            if state.id in store._tasks:
                raise ValueError("Duplicate task identity in snapshot")
            store._tasks[state.id] = state
        store._specifications = {
            key: [TaskSpecification.from_dict(spec) for spec in specs]
            for key, specs in data.get("specifications", {}).items()
        }
        for identity, state in store._tasks.items():
            specs = store._specifications.get(identity, [])
            if not specs or specs[-1] != state.specification:
                raise ValueError("Current task specification does not match revision history")
            if state.parent_task_id and state.parent_task_id not in store._tasks:
                raise ValueError("Task snapshot has a missing parent")
        store._usage_operations = thaw_json(freeze_json(data.get("usage_operations", {})))
        store._events = thaw_json(freeze_json(data.get("events", [])))
        return store


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
