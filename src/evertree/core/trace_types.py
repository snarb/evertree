"""Trace identities, immutable records, queries and retention policy."""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .graph_types import Node
from .values import ContractError, freeze


@dataclasses.dataclass(frozen=True)
class TraceOutputRef:
    event_ref: int
    output_path: tuple[str | int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_path", tuple(self.output_path))
        if not isinstance(self.event_ref, int) or self.event_ref <= 0:
            raise ContractError("TraceOutputRef requires a positive event identity")


@dataclasses.dataclass(frozen=True)
class ProgramRun:
    id: int
    program: int | str
    base_commit_sha: str
    arguments: Any
    run_mode: str
    started_at: datetime
    caller_event: int | None = None
    finished_at: datetime | None = None
    status: str = "running"
    revision_changes: tuple[tuple[int, str], ...] = ()


@dataclasses.dataclass(frozen=True)
class TraceEvent:
    id: int
    program_run: int
    seq: int
    occurred_at: datetime
    operator: int | str
    arguments: Any
    output: Any
    status: str
    output_type: str
    dependencies: tuple[TraceOutputRef, ...] = ()


@dataclasses.dataclass(frozen=True)
class SemanticTrace:
    run: int
    events: tuple[int, ...]


@dataclasses.dataclass(frozen=True)
class MemoryQuery:
    text: str = ""
    program: str | int | None = None
    run_mode: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    references: tuple[TraceOutputRef, ...] = ()
    operator: str | int | None = None


@dataclasses.dataclass(frozen=True)
class MemoryCandidateGroup:
    events: tuple[TraceEvent, ...]
    score: float


@dataclasses.dataclass(frozen=True)
class RetentionPolicy:
    memory_compaction_ladder: tuple[timedelta, ...] = (
        timedelta(days=7),
        timedelta(days=30),
        timedelta(days=365),
        timedelta(days=3650),
    )
    deleted_protection_period: timedelta = timedelta(days=7)
    early_review_tolerance: timedelta = timedelta(days=1)

    def __post_init__(self) -> None:
        ladder = self.memory_compaction_ladder
        if (
            not ladder
            or any(value <= timedelta(0) for value in ladder)
            or any(left >= right for left, right in itertools.pairwise(ladder))
        ):
            raise ContractError("memory compaction ladder must be positive and strictly increasing")
        if self.deleted_protection_period <= timedelta(
            0
        ) or self.early_review_tolerance < timedelta(0):
            raise ContractError("invalid memory retention durations")

    @property
    def initial_full_retention_period(self) -> timedelta:
        return self.memory_compaction_ladder[0]


def _ref(value: Any) -> TraceOutputRef | None:
    if isinstance(value, TraceOutputRef):
        return value
    if isinstance(value, Mapping) and set(value) == {"event_ref", "output_path"}:
        return TraceOutputRef(value["event_ref"], tuple(value["output_path"]))
    return None


def _references(value: Any) -> tuple[TraceOutputRef, ...]:
    found = _ref(value)
    if found is not None:
        return (found,)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return tuple(
            ref
            for field in dataclasses.fields(value)
            for ref in _references(getattr(value, field.name))
        )
    if isinstance(value, Mapping):
        return tuple(ref for item in value.values() for ref in _references(item))
    if isinstance(value, (list, tuple)):
        return tuple(ref for item in value for ref in _references(item))
    return ()


def _semantic_value(value: Any) -> Any:
    if isinstance(value, Node):
        return freeze({"$node": value.id})
    if isinstance(value, TraceOutputRef):
        return freeze({"event_ref": value.event_ref, "output_path": value.output_path})
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return freeze(
            {
                field.name: _semantic_value(getattr(value, field.name))
                for field in dataclasses.fields(value)
            }
        )
    if hasattr(value, "model_dump"):
        return _semantic_value(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return freeze({key: _semantic_value(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_semantic_value(item) for item in value)
    return freeze(value)


# Keep existing trace type names and pickled references valid through the public module.
for _export in (
    TraceOutputRef,
    ProgramRun,
    TraceEvent,
    SemanticTrace,
    MemoryQuery,
    MemoryCandidateGroup,
    RetentionPolicy,
    _ref,
    _references,
    _semantic_value,
):
    _export.__module__ = "evertree.core.memory"
