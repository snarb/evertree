"""Trace storage, provenance, retrieval, retention and snapshots."""

from __future__ import annotations

import dataclasses
import json
import re
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from ..values import ContractError, freeze, json_value, restore_value, timestamp, utcnow
from .types import (
    MemoryCandidateGroup,
    MemoryQuery,
    ProgramRun,
    RetentionPolicy,
    SemanticTrace,
    TraceEvent,
    TraceOutputRef,
    _ref,
    _references,
    _semantic_value,
)


class TraceStore:
    def __init__(self, *, policy: RetentionPolicy | None = None) -> None:
        self.policy = policy or RetentionPolicy()
        self._runs: dict[int, ProgramRun] = {}
        self._events: dict[int, TraceEvent] = {}
        self._traces: dict[int, list[int]] = {}
        self._next_run = 1
        self._next_event = 1
        self._protections: dict[int, set[str]] = {}
        self._run_protections: dict[int, set[str]] = {}
        self._deleted: dict[int, datetime] = {}
        self._reviews: dict[int, int] = {}
        self._pending_reviews: set[int] = set()
        self._early_reviews: dict[int, tuple[datetime, str]] = {}
        # Events held out of all retrieval because they serve as hidden evaluation outcomes.
        self._sealed: set[int] = set()
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self):
        """Roll back trace and retention writes together without copying immutable records."""
        with self._lock:
            fields = (
                "_runs",
                "_events",
                "_traces",
                "_next_run",
                "_next_event",
                "_protections",
                "_run_protections",
                "_deleted",
                "_reviews",
                "_pending_reviews",
                "_early_reviews",
                "_sealed",
            )
            before = {}
            for name in fields:
                value = getattr(self, name)
                if isinstance(value, dict):
                    value = {
                        k: v.copy() if isinstance(v, (set, list)) else v for k, v in value.items()
                    }
                elif isinstance(value, set):
                    value = value.copy()
                before[name] = value
            try:
                yield
            except BaseException:
                for name, value in before.items():
                    setattr(self, name, value)
                raise

    @property
    def runs(self) -> tuple[ProgramRun, ...]:
        """Return retained ProgramRun headers, including unfinished runs."""
        return tuple(self._runs.values())

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        """Return stored trace events, including those awaiting final deletion."""
        return tuple(self._events.values())

    def events_since(self, event_id: int) -> tuple[TraceEvent, ...]:
        """Return stored events recorded after an event identity, in recording order."""
        with self._lock:
            return tuple(
                self._events[identity]
                for identity in range(max(event_id, 0) + 1, self._next_event)
                if identity in self._events
            )

    def get_run(self, run_id: int) -> ProgramRun:
        """Return a retained ProgramRun by identity."""
        return self._runs[run_id]

    def get_event(self, event_id: int) -> TraceEvent:
        """Return a stored trace event by identity."""
        return self._events[event_id]

    def start_run(
        self,
        program_id: int | str,
        commit_sha: str,
        arguments: Any,
        *,
        run_mode: str = "live",
        caller_event: int | TraceEvent | None = None,
        at: datetime | None = None,
        program_revision: str | None = None,
        task_id: str | None = None,
    ) -> ProgramRun:
        """Open a ProgramRun with pinned code and input provenance, protecting required dependencies."""
        if run_mode not in {"live", "replay", "simulation", "evaluation", "test"}:
            raise ContractError("unknown ProgramRun mode")
        if not commit_sha:
            raise ContractError("ProgramRun must identify its exact code revision")
        if isinstance(caller_event, TraceEvent):
            caller_event = caller_event.id
        with self._lock:
            if caller_event is not None and caller_event not in self._events:
                raise ContractError("caller event is missing")
            arguments = _semantic_value(arguments)
            for reference in _references(arguments):
                self.resolve(reference)
            run = ProgramRun(
                self._next_run,
                program_id,
                commit_sha,
                arguments,
                run_mode,
                timestamp(at or utcnow()),
                caller_event,
                program_revision=program_revision,
                task_id=task_id,
            )
            self._runs[run.id] = run
            self._traces[run.id] = []
            self._next_run += 1
            for reference in _references(arguments):
                self._restore_provenance(reference.event_ref)
            if caller_event is not None:
                self._restore_provenance(caller_event)
            return run

    def record(
        self,
        run_id: int | ProgramRun,
        operator: int | str,
        arguments: Any = None,
        output: Any = None,
        *,
        status: str = "completed",
        at: datetime | None = None,
        dependencies: tuple[TraceOutputRef, ...] = (),
    ) -> TraceEvent:
        """Append an immutable operation event after validating its output and dependency references."""
        run_id = run_id.id if isinstance(run_id, ProgramRun) else run_id
        if status not in {"completed", "failed", "interrupted"}:
            raise ContractError("trace events record a completed, failed, or interrupted step")
        with self._lock:
            run = self.get_run(run_id)
            if run.status != "running":
                raise ContractError("cannot append events to a finished run")
            args = _semantic_value(arguments)
            value = _semantic_value(output)
            refs = tuple(dict.fromkeys((*_references(args), *_references(value), *dependencies)))
            for reference in refs:
                self.resolve(reference)
            when = timestamp(at or utcnow())
            if when < run.started_at:
                raise ContractError("event cannot precede its ProgramRun")
            event = TraceEvent(
                self._next_event,
                run_id,
                self._next_event,
                when,
                operator,
                args,
                value,
                status,
                f"{type(output).__module__}.{type(output).__qualname__}",
                refs,
            )
            self._events[event.id] = event
            self._traces[run_id].append(event.id)
            self._next_event += 1
            self._restore_provenance(event.id)
            return event

    def finish_run(
        self, run_id: int | ProgramRun, *, status: str = "completed", at: datetime | None = None
    ) -> ProgramRun:
        """Finalize a ProgramRun without rewriting an already recorded outcome."""
        run_id = run_id.id if isinstance(run_id, ProgramRun) else run_id
        if status not in {"completed", "failed", "interrupted"}:
            raise ContractError("invalid final ProgramRun status")
        with self._lock:
            run = self.get_run(run_id)
            if run.status != "running":
                if run.status != status:
                    raise ContractError("finished run status cannot be rewritten")
                return run
            when = timestamp(at or utcnow())
            if when < run.started_at or any(
                event.occurred_at > when
                for event in self._events.values()
                if event.program_run == run_id
            ):
                raise ContractError("run cannot finish before its events")
            updated = dataclasses.replace(run, status=status, finished_at=when)
            self._runs[run_id] = updated
            return updated

    def record_revision(self, run_id: int, commit_sha: str) -> ProgramRun:
        """Record a committed code revision change within a running ProgramRun."""
        with self._lock:
            run = self.get_run(run_id)
            if run.status != "running" or not commit_sha:
                raise ContractError(
                    "revision change requires a running ProgramRun and committed code"
                )
            updated = dataclasses.replace(
                run, revision_changes=run.revision_changes + ((self._next_event, commit_sha),)
            )
            self._runs[run_id] = updated
            return updated

    def semantic_trace(self, run_id: int) -> SemanticTrace:
        """Return the ordered event membership currently retained for a ProgramRun."""
        return SemanticTrace(run_id, tuple(self._traces[run_id]))

    def output_ref(
        self, event: int | TraceEvent, path: tuple[str | int, ...] = ()
    ) -> TraceOutputRef:
        """Address an event output or nested value, following forwarded references to its producer."""
        reference = TraceOutputRef(event.id if isinstance(event, TraceEvent) else event, path)
        value = self._raw_resolve(reference)
        inherited = _ref(value)
        return self.producer_of(inherited) if inherited is not None else reference

    def _raw_resolve(self, reference: TraceOutputRef) -> Any:
        try:
            value = self._events[reference.event_ref].output
            for part in reference.output_path:
                # Text indices silently turn a supposed paragraph citation into one character.
                if not isinstance(value, (Mapping, tuple, list)):
                    raise ContractError(
                        "output_path traverses object fields and array items, not text characters; "
                        "cite the supplied text reference unchanged"
                    )
                if isinstance(value, (tuple, list)) and (type(part) is not int or part < 0):
                    raise ContractError("output_path array indices must be nonnegative integers")
                value = value[part]
            return value
        except (KeyError, IndexError, TypeError) as exc:
            raise ContractError("dangling TraceOutputRef") from exc

    def resolve(self, reference: TraceOutputRef) -> Any:
        """Read an addressed output value through forwarded references, rejecting cycles."""
        seen = set()
        while reference:
            if reference in seen:
                raise ContractError("cyclic output references")
            seen.add(reference)
            value = self._raw_resolve(reference)
            forwarded = _ref(value)
            if forwarded is None:
                return value
            reference = forwarded

    def producer_of(self, reference: TraceOutputRef) -> TraceOutputRef:
        """Find the original output address behind a chain of forwarded references."""
        seen = set()
        while reference not in seen:
            seen.add(reference)
            value = self._raw_resolve(reference)
            forwarded = _ref(value)
            if forwarded is None:
                return reference
            reference = forwarded
        raise ContractError("cyclic producer references")

    def consumers_of(self, reference: TraceOutputRef) -> tuple[TraceEvent, ...]:
        """Find retained events that directly depend on the same original output."""
        producer = self.producer_of(reference)
        return tuple(
            event
            for event in self._events.values()
            if any(self.producer_of(item) == producer for item in event.dependencies)
        )

    def provenance_of(
        self, reference: TraceOutputRef, max_depth: int | None = None
    ) -> tuple[TraceEvent, ...]:
        """Walk upstream event dependencies, optionally limiting traversal depth."""
        return self._walk(reference.event_ref, downstream=False, max_depth=max_depth)

    def dependents_of(
        self, reference: TraceOutputRef, max_depth: int | None = None
    ) -> tuple[TraceEvent, ...]:
        """Walk downstream event dependencies, optionally limiting traversal depth."""
        return self._walk(reference.event_ref, downstream=True, max_depth=max_depth)

    def _walk(
        self, identity: int, *, downstream: bool, max_depth: int | None = None
    ) -> tuple[TraceEvent, ...]:
        """Traverse event provenance in either direction without revisiting dependencies or exceeding max_depth."""
        seen: set[int] = set()
        queue = [(identity, 0)]
        while queue:
            current, depth = queue.pop()
            if current in seen or max_depth is not None and depth > max_depth:
                continue
            event = self._events.get(current)
            if event is None:
                raise ContractError("provenance contains a dangling event")
            seen.add(current)
            if downstream:
                following = [
                    candidate.id
                    for candidate in self._events.values()
                    if any(ref.event_ref == current for ref in candidate.dependencies)
                ]
            else:
                following = [ref.event_ref for ref in event.dependencies]
                run = self._runs[event.program_run]
                following.extend(ref.event_ref for ref in _references(run.arguments))
                if run.caller_event is not None:
                    following.append(run.caller_event)
            queue.extend((other, depth + 1) for other in following)
        return tuple(
            sorted((self._events[identity] for identity in seen), key=lambda event: event.seq)
        )

    def _restore_provenance(self, event_id: int) -> None:
        # A new obligation protects required inputs and call context immediately,
        # including dependencies previously compacted or queued for deletion.
        for event in self._walk(event_id, downstream=False):
            self.restore_deleted(event.id)

    @property
    def sealed(self) -> frozenset[int]:
        """Events reserved as hidden evaluation outcomes."""
        return frozenset(self._sealed)

    def seal(self, event_ids) -> None:
        """Hide events from retrieval so they can serve as hidden holdout outcomes."""
        with self._lock:
            identities = {int(identity) for identity in event_ids}
            if any(identity not in self._events for identity in identities):
                raise ContractError("Only stored events can be sealed")
            self._sealed.update(identities)

    def retention_reasons(self, event_id: int) -> frozenset[str]:
        """Return why an event is retained; a reason names each use of its content."""
        return frozenset(self._protections.get(event_id, ()))

    def retrieve(
        self, query: MemoryQuery | str | Mapping, limit: int = 10
    ) -> tuple[MemoryCandidateGroup, ...]:
        """Rank matching experience by reference and text overlap, grouping only identical content.

        Sealed events are never returned.
        """
        if limit < 0:
            raise ContractError("retrieval limit must not be negative")
        if isinstance(query, str):
            query = MemoryQuery(text=query)
        elif isinstance(query, Mapping):
            fields = dict(query)
            fields["references"] = tuple(
                value if isinstance(value, TraceOutputRef) else TraceOutputRef(**value)
                for value in fields.get("references", ())
            )
            for name in ("since", "until"):
                if fields.get(name) is not None:
                    fields[name] = timestamp(fields[name])
            query = MemoryQuery(**fields)
        tokens = set(re.findall(r"\w+", query.text.casefold()))
        direct = {reference.event_ref for reference in query.references}
        for reference in query.references:
            direct.update(event.id for event in self.provenance_of(reference))
        groups: dict[str, list[TraceEvent]] = {}
        scores: dict[str, float] = {}
        for event in self._events.values():
            if event.id in self._deleted or event.id in self._sealed:
                continue
            run = self._runs[event.program_run]
            if (
                query.program is not None
                and run.program != query.program
                or query.run_mode is not None
                and run.run_mode != query.run_mode
                or query.operator is not None
                and event.operator != query.operator
            ):
                continue
            if (
                query.since is not None
                and event.occurred_at < timestamp(query.since)
                or query.until is not None
                and event.occurred_at >= timestamp(query.until)
            ):
                continue
            body = json.dumps(
                json_value((event.operator, event.arguments, event.output)),
                ensure_ascii=False,
                sort_keys=True,
            )
            terms = set(re.findall(r"\w+", body.casefold()))
            overlap = len(tokens & terms) / max(1, len(tokens))
            if tokens and not overlap and event.id not in direct:
                continue
            # Exact content grouping only: semantically significant differences
            # are never discarded by an unvalidated approximate clustering rule.
            key = body
            groups.setdefault(key, []).append(event)
            scores[key] = max(scores.get(key, 0.0), overlap + (2.0 if event.id in direct else 0.0))
        results = [
            MemoryCandidateGroup(tuple(events), scores[key]) for key, events in groups.items()
        ]
        results.sort(
            key=lambda group: (group.score, max(event.seq for event in group.events)), reverse=True
        )
        return tuple(results[:limit])

    def retain(self, reference: TraceOutputRef | int, reason: str) -> None:
        """Protect an output and its provenance from compaction or deletion for a named reason."""
        if not reason.strip():
            raise ContractError("retention requires a reason")
        identity = reference.event_ref if isinstance(reference, TraceOutputRef) else reference
        with self._lock:
            if isinstance(reference, TraceOutputRef):
                self.resolve(reference)
            else:
                self.get_event(identity)
            self._protections.setdefault(identity, set()).add(reason)
            self._restore_provenance(identity)

    def release(self, reference: TraceOutputRef | int, reason: str) -> None:
        """Remove one retention reason without deleting the referenced experience."""
        identity = reference.event_ref if isinstance(reference, TraceOutputRef) else reference
        self._protections.get(identity, set()).discard(reason)

    def retain_run(self, run_id: int, reason: str) -> None:
        """Protect a run's events, inputs and caller provenance for a named obligation."""
        if not reason.strip():
            raise ContractError("retention requires a reason")
        with self._lock:
            run = self.get_run(run_id)
            self._run_protections.setdefault(run_id, set()).add(reason)
            for event in self._events.values():
                if event.program_run == run_id:
                    self._restore_provenance(event.id)
            for reference in _references(run.arguments):
                self._restore_provenance(reference.event_ref)
            if run.caller_event is not None:
                self._restore_provenance(run.caller_event)

    def release_run(self, run_id: int, reason: str) -> None:
        """Remove one run retention obligation without changing its trace."""
        self._run_protections.get(run_id, set()).discard(reason)

    def retention_closure(self) -> frozenset[int]:
        """Compute events required by explicit protections and unfinished ProgramRuns."""
        roots = {identity for identity, reasons in self._protections.items() if reasons}
        for run in self._runs.values():
            if run.status == "running" or self._run_protections.get(run.id):
                roots.update(
                    event.id for event in self._events.values() if event.program_run == run.id
                )
                if run.caller_event is not None:
                    roots.add(run.caller_event)
                roots.update(ref.event_ref for ref in _references(run.arguments))
        closure = set()
        for identity in roots:
            closure.update(event.id for event in self._walk(identity, downstream=False))
        return frozenset(closure)

    def _deadline(self, event: TraceEvent, index: int) -> datetime:
        ladder = self.policy.memory_compaction_ladder
        offset = ladder[index] if index < len(ladder) else ladder[-1] * (index - len(ladder) + 2)
        return event.occurred_at + offset

    def request_review(self, event_id: int, reason: str, *, at: datetime | None = None) -> None:
        """Schedule an early retention review with an explicit reason."""
        self.get_event(event_id)
        if not reason:
            raise ContractError("early review needs a reason")
        self._early_reviews[event_id] = (timestamp(at or utcnow()), reason)

    def review_batch(
        self, *, at: datetime | None = None, limit: int = 100
    ) -> tuple[TraceEvent, ...]:
        """Queue due retention reviews and return a bounded batch of available events."""
        now = timestamp(at or utcnow())
        for event in self._events.values():
            early = self._early_reviews.get(event.id)
            if (
                now >= self._deadline(event, self._reviews.get(event.id, 0))
                or early is not None
                and now >= early[0]
            ):
                self._pending_reviews.add(event.id)
        return tuple(
            self._events[identity]
            for identity in sorted(self._pending_reviews)[:limit]
            if identity in self._events and identity not in self._deleted
        )

    def complete_review(self, event_id: int, *, at: datetime | None = None) -> None:
        """Advance an event's review schedule and clear its pending or early review request."""
        now = timestamp(at or utcnow())
        event = self.get_event(event_id)
        index = self._reviews.get(event_id, 0)
        while now + self.policy.early_review_tolerance >= self._deadline(event, index):
            index += 1
        self._reviews[event_id] = index
        self._pending_reviews.discard(event_id)
        self._early_reviews.pop(event_id, None)

    def compact(
        self, run_id: int, keep_events: tuple[int, ...], *, at: datetime | None = None
    ) -> SemanticTrace:
        """Reduce a run's trace membership while preserving recent and protected experience.

        Removed events remain stored until the separate deletion process permits removal.
        """
        with self._lock:
            current = set(self._traces[run_id])
            keep = set(keep_events)
            if not keep <= current:
                raise ContractError("compaction cannot introduce foreign trace events")
            protected = self.retention_closure()
            removed = current - keep
            now = timestamp(at or utcnow())
            if removed & protected:
                raise ContractError("compaction would break retention closure")
            if any(
                now < self._events[identity].occurred_at + self.policy.initial_full_retention_period
                for identity in removed
            ):
                raise ContractError("recent semantic experience must be retained in full")
            # Every retained dependency must remain addressable.  Compaction
            # removes trace membership, then deferred deletion decides storage.
            self._traces[run_id] = sorted(keep, key=lambda identity: self._events[identity].seq)
            return self.semantic_trace(run_id)

    def delete(self, event_id: int, *, at: datetime | None = None) -> None:
        """Mark an eligible event for deferred deletion and remove its trace membership."""
        with self._lock:
            event = self.get_event(event_id)
            now = timestamp(at or utcnow())
            if event_id in self.retention_closure():
                raise ContractError("protected memory cannot be deleted")
            if now < event.occurred_at + self.policy.initial_full_retention_period:
                raise ContractError("initial full retention period has not elapsed")
            self._deleted.setdefault(event_id, now)
            if event_id in self._traces[event.program_run]:
                self._traces[event.program_run].remove(event_id)

    def restore_deleted(self, event_id: int) -> None:
        """Cancel deferred deletion and restore the event's ordered trace membership."""
        event = self.get_event(event_id)
        self._deleted.pop(event_id, None)
        if event_id not in self._traces[event.program_run]:
            self._traces[event.program_run].append(event_id)
            self._traces[event.program_run].sort(key=lambda identity: self._events[identity].seq)

    def finalize_deletions(self, *, at: datetime | None = None) -> tuple[int, ...]:
        """Permanently remove expired deletions only when no surviving provenance requires them."""
        with self._lock:
            now = timestamp(at or utcnow())
            eligible = {
                identity
                for identity, deleted_at in self._deleted.items()
                if now >= deleted_at + self.policy.deleted_protection_period
            }
            protected = set(self.retention_closure())
            # All retained references, not just explicit roots, forbid dangling
            # addresses.  A dependent may be deleted in the same batch.
            changed = True
            while changed:
                changed = False
                survivors = set(self._events) - (eligible - protected)
                for identity in survivors:
                    event = self._events[identity]
                    dependencies = {ref.event_ref for ref in event.dependencies}
                    run = self._runs[event.program_run]
                    dependencies.update(ref.event_ref for ref in _references(run.arguments))
                    if run.caller_event is not None:
                        dependencies.add(run.caller_event)
                    additions = dependencies & eligible - protected
                    if additions:
                        protected.update(additions)
                        changed = True
            for identity in eligible & protected:
                self.restore_deleted(identity)
            deleted = eligible - protected
            for identity in deleted:
                del self._events[identity]
                self._deleted.pop(identity, None)
                self._protections.pop(identity, None)
                self._pending_reviews.discard(identity)
                self._early_reviews.pop(identity, None)
                self._reviews.pop(identity, None)
            # Empty run headers whose arguments/caller still reference removed
            # events are removed only when no child or protection requires them.
            for run_id, run in tuple(self._runs.items()):
                if (
                    run.status != "running"
                    and not any(event.program_run == run_id for event in self._events.values())
                    and not self._run_protections.get(run_id)
                ):
                    del self._runs[run_id]
                    self._traces.pop(run_id, None)
            self.validate()
            return tuple(sorted(deleted))

    def validate(self) -> None:
        """Check run, event and retention references for missing or inconsistent provenance."""
        for run in self._runs.values():
            if run.caller_event is not None and run.caller_event not in self._events:
                raise ContractError("run caller provenance is missing")
            for reference in _references(run.arguments):
                self.resolve(reference)
        for event in self._events.values():
            if event.program_run not in self._runs:
                raise ContractError("trace event has no ProgramRun")
            for reference in event.dependencies:
                self.resolve(reference)
        for run_id, identities in self._traces.items():
            if len(identities) != len(set(identities)) or identities != sorted(
                identities, key=lambda identity: self._events[identity].seq
            ):
                raise ContractError("SemanticTrace must contain unique ordered events")
            if any(self._events[identity].program_run != run_id for identity in identities):
                raise ContractError("SemanticTrace contains another run's event")
        for identity in self.retention_closure():
            event = self._events[identity]
            if identity in self._deleted or identity not in self._traces[event.program_run]:
                raise ContractError("SemanticTrace must preserve the active retention closure")

    def snapshot(self) -> dict:
        """Capture trace contents, retention obligations, review schedules and deferred deletions."""
        with self._lock:
            return {
                "runs": [json_value(run) for run in self._runs.values()],
                "events": [json_value(event) for event in self._events.values()],
                "traces": json_value(self._traces),
                "next_run": self._next_run,
                "next_event": self._next_event,
                "protections": {
                    str(key): sorted(value) for key, value in self._protections.items()
                },
                "run_protections": {
                    str(key): sorted(value) for key, value in self._run_protections.items()
                },
                "deleted": {str(key): value.isoformat() for key, value in self._deleted.items()},
                "reviews": json_value(self._reviews),
                "pending_reviews": sorted(self._pending_reviews),
                "early_reviews": {
                    str(key): [value[0].isoformat(), value[1]]
                    for key, value in self._early_reviews.items()
                },
                "sealed": sorted(self._sealed),
                "policy": {
                    "ladder": [
                        value.total_seconds() for value in self.policy.memory_compaction_ladder
                    ],
                    "deletion": self.policy.deleted_protection_period.total_seconds(),
                    "early_tolerance": self.policy.early_review_tolerance.total_seconds(),
                },
            }

    @classmethod
    def from_snapshot(cls, data: dict) -> TraceStore:
        """Restore trace storage and retention state, validating all retained references."""
        policy = data["policy"]
        store = cls(
            policy=RetentionPolicy(
                tuple(timedelta(seconds=value) for value in policy["ladder"]),
                timedelta(seconds=policy["deletion"]),
                timedelta(seconds=policy["early_tolerance"]),
            )
        )
        for raw in data["runs"]:
            values = restore_value(raw)
            values["arguments"] = freeze(values["arguments"])
            run = ProgramRun(**values)
            store._runs[run.id] = run
        for raw in data["events"]:
            values = restore_value(raw)
            values["arguments"] = freeze(values["arguments"])
            values["output"] = freeze(values["output"])
            values["dependencies"] = tuple(TraceOutputRef(**ref) for ref in values["dependencies"])
            event = TraceEvent(**values)
            store._events[event.id] = event
        store._traces = {int(key): list(values) for key, values in data["traces"].items()}
        store._next_run, store._next_event = data["next_run"], data["next_event"]
        store._protections = {int(key): set(values) for key, values in data["protections"].items()}
        store._run_protections = {
            int(key): set(values) for key, values in data.get("run_protections", {}).items()
        }
        store._deleted = {int(key): timestamp(value) for key, value in data["deleted"].items()}
        store._reviews = {int(key): value for key, value in data["reviews"].items()}
        store._pending_reviews = set(data["pending_reviews"])
        store._early_reviews = {
            int(key): (timestamp(value[0]), value[1])
            for key, value in data["early_reviews"].items()
        }
        store._sealed = set(data.get("sealed", ()))
        store.validate()
        return store


MemoryStore = TraceStore
