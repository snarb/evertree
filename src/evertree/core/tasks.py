"""Task specifications, finite budgets, resource accounting and state transitions."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
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
        state.review_required = False
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


# Keep existing trace type names and pickled references valid through the public module.
for _export in (
    utc_now,
    _finite_nonnegative,
    TaskSpecification,
    ExecutionBudget,
    TaskState,
    TaskStore,
):
    _export.__module__ = "evertree.core.cognition"
