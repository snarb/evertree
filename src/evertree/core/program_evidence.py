"""Evidence batches for Program revisions and their anchored operators.

A Program's belief target is the pair (Program, program_revision), so evidence about
one revision never supports the next. Each anchored operator use (a `# et:op=` Code
Anchor) has its own target in that revision: how suitable and reliable the operator is
at that control-flow point. Unanchored implementation details get no evidence.

Evidence is experience about a run's result: a user message or observation recorded in
a task after Program runs of that task, or of the task that ran just before it, since a
verdict on a delivered answer usually opens a new task. Core pairs each new source with
the runs it may concern; the assessment decides whether and to which target it applies,
the anchor it directly checks first. An observation recorded with outcome_of is never shown here:
lifecycle keeps such outcomes unseen so it can hold them out as evaluation cases.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .beliefs import BeliefStore, operator_target, program_target
from .evidence import (
    STALE_RELIABILITY,
    TEXT_LIMIT,
    _key,
    _reference,
    _Sources,
    active_directions,
    apply_binary,
    binary_items,
    origin_target,
)
from .graph.store import GraphStore
from .memory.store import TraceStore
from .memory.types import ProgramRun, TraceEvent
from .values import ContractError, json_value

CURSOR = "programs"
SOURCE_KINDS = frozenset({"user", "observation", "document"})
# Experience the host recorded: user messages and observations. Tool results inside a
# step record the agent's own actions, not a check of an earlier run's result.
SOURCE_OPERATORS = frozenset({"user_input", "observation"})
# Programs that maintain the agent's knowledge after each step; their runs, and runs they
# call, do not produce the results a user or observation judges.
SERVICE_SLUGS = frozenset(
    {
        "knowledge_integration",
        "evidence_assessment",
        "graph_evidence_assessment",
        "program_evidence_assessment",
    }
)
EVENT_LIMIT = 3
EVENT_TEXT_LIMIT = 600


def program_claim(roles) -> str:
    """State what belief in a Program revision is about, from its roles."""
    if "model" in roles:
        claim = "This revision accurately describes its process"
        if "simulation" in roles:
            claim += ", including the material dynamics of the simulated states it works with"
    else:
        claim = "This revision reliably implements its intended behaviour"
        if "simulation" in roles:
            claim += " with the stated simulated states or processes"
    if "meta" in roles:
        claim += ", and reliably performs its stated operations on other agent mechanisms"
    return claim + "."


def _value_text(value: Any, limit: int = TEXT_LIMIT) -> str:
    """Show a run's argument, result or recorded use whole, as JSON within a length limit."""
    text = value if isinstance(value, str) else json.dumps(json_value(value), ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " …"


class ProgramEvidence:
    """Select runs that new experience may concern and record evidence for their targets."""

    def __init__(self, graph: GraphStore, memory: TraceStore, beliefs: BeliefStore):
        self.graph, self.memory, self.beliefs = graph, memory, beliefs

    def _program(self, run: ProgramRun):
        if type(run.program) is not int:
            return None
        try:
            node = self.graph.get(run.program)
        except KeyError:
            return None
        return node if node.kind == "program" else None

    def _service(self, run: ProgramRun, seen: frozenset = frozenset()) -> bool:
        """Tell whether a run or a run that called it belongs to a service Program."""
        node = self._program(run)
        if node is not None and node.properties.get("slug") in SERVICE_SLUGS:
            return True
        if run.caller_event is None or run.id in seen:
            return False
        try:
            caller = self.memory.get_run(self.memory.get_event(run.caller_event).program_run)
        except KeyError:
            return False
        return self._service(caller, seen | {run.id})

    def _assessable(self) -> list[ProgramRun]:
        return [
            run
            for run in self.memory.runs
            if run.run_mode == "live"
            and run.status == "completed"
            and run.finished_at is not None
            and run.program_revision is not None
            and self._program(run) is not None
            and not self._service(run)
        ]

    def _task(self, event: TraceEvent) -> str | None:
        run = self.memory.get_run(event.program_run)
        arguments = run.arguments if isinstance(run.arguments, Mapping) else {}
        return run.task_id or arguments.get("task_id")

    def _candidates(self, event: TraceEvent, runs: list[ProgramRun], run_limit: int) -> list:
        """Recent runs that finished before a source: its task's, then the previous task's.

        A task closes when its answer is delivered, so a verdict on that answer arrives in
        the next task; the assessment judges whether the source concerns those runs at all.
        """
        arguments = event.arguments if isinstance(event.arguments, Mapping) else {}
        task = self._task(event)
        if task is None or arguments.get("outcome_of") is not None:
            return []
        earlier = sorted(
            (run for run in runs if run.finished_at <= event.occurred_at),
            key=lambda run: run.finished_at,
            reverse=True,
        )
        previous = next((run.task_id for run in earlier if run.task_id not in (task, None)), None)
        own = [run for run in earlier if run.task_id == task]
        before = [run for run in earlier if previous is not None and run.task_id == previous]
        return (own + before)[:run_limit]

    def _events(self, run: ProgramRun, sealed: frozenset) -> list[TraceEvent]:
        return [
            self.memory.get_event(identity)
            for identity in self.memory.semantic_trace(run.id).events
            if identity not in sealed
        ]

    def _operators(self, run: ProgramRun, events: list[TraceEvent], sources: _Sources) -> list:
        """Anchored operators the run executed, with a few of their recorded uses."""
        uses: dict[str, list[TraceEvent]] = {}
        for event in events:
            if type(event.operator) is not int:
                continue
            try:
                node = self.graph.get(event.operator)
            except KeyError:
                continue
            if node.kind == "operator" and node.properties.get("code_node") == run.program:
                uses.setdefault(node.properties["local_id"], []).append(event)
        result = []
        for op_id, recorded in uses.items():
            target = operator_target(run.program, op_id, run.program_revision)
            known = self.beliefs.known(target)
            result.append(
                {
                    "op_id": op_id,
                    "target": target,
                    "new_target": not known,
                    "uses": [
                        {
                            "status": event.status,
                            "arguments": _value_text(event.arguments, EVENT_TEXT_LIMIT),
                            "output": _value_text(event.output, EVENT_TEXT_LIMIT),
                        }
                        for event in recorded[:EVENT_LIMIT]
                    ],
                    "uses_total": len(recorded),
                    "active": active_directions(self.beliefs, target, sources) if known else [],
                }
            )
        return result

    def _card(self, run: ProgramRun, sources: _Sources, sealed: frozenset) -> dict:
        node = self._program(run)
        roles = list(node.properties.get("roles", (node.properties.get("role"),)))
        process = node.properties.get("process")
        try:
            process = self.graph.get(process)
            process = {"name": process.name, "description": process.description}
        except (KeyError, TypeError):
            process = None
        events = self._events(run, sealed)
        finished = next((event for event in events if event.operator == "run_finished"), None)
        output = finished.output if finished is not None else None
        result = output.get("result") if isinstance(output, Mapping) else None
        if isinstance(result, Mapping) and "result" in result:
            result = result["result"]
        target = program_target(run.program, run.program_revision)
        known = self.beliefs.known(target)
        return {
            "run": run.id,
            "program": {
                "id": node.id,
                "name": node.name,
                "description": node.description,
                "process": process,
                "roles": roles,
            },
            "claim": program_claim(roles),
            "target": target,
            "new_target": not known,
            "arguments": _value_text(run.arguments),
            "result": _value_text(result),
            "finished_at": run.finished_at.isoformat(),
            "operators": self._operators(run, events, sources),
            "active": active_directions(self.beliefs, target, sources) if known else [],
        }

    def _caller(self, run: ProgramRun) -> int | None:
        if run.caller_event is None:
            return None
        try:
            return self.memory.get_event(run.caller_event).program_run
        except KeyError:
            return None

    def pending(self, *, limit: int = 12, run_limit: int = 6) -> dict:
        """Build one batch: new sources after the cursor and the runs each may concern.

        through is the last memory event the batch covers; recording the batch moves the
        cursor there. Sources with no candidate run need no assessment and are passed;
        remaining counts later sources left for the next batch.
        """
        cursor = self.beliefs.cursor(CURSOR)
        runs = self._assessable()
        sources = _Sources(self.memory)
        chosen: dict[int, list[str]] = {}
        linked: list[tuple[str, list[ProgramRun]]] = []
        through, remaining = cursor, 0
        sealed = self.memory.sealed
        for event in self.memory.events_since(cursor):
            if (
                event.operator not in SOURCE_OPERATORS
                or _Sources._kind(event) not in SOURCE_KINDS
                or event.id in sealed
            ):
                if not remaining:
                    through = event.id
                continue
            if remaining or len(linked) >= limit:
                remaining += 1
                continue
            candidates = self._candidates(event, runs, run_limit)
            if not candidates:
                through = event.id
                continue
            keys = sources.expand(self.memory.output_ref(event), new=True)
            for key in keys:
                linked.append((key, candidates))
            through = event.id
        for key, candidates in linked:
            for run in candidates:
                chosen.setdefault(run.id, [])
                if key not in chosen[run.id]:
                    chosen[run.id].append(key)
        keys = {identity: f"R{index + 1}" for index, identity in enumerate(sorted(chosen))}
        batch_runs = []
        for identity in sorted(chosen):
            run = self.memory.get_run(identity)
            card = self._card(run, sources, sealed)
            caller = self._caller(run)
            batch_runs.append(
                {
                    "key": keys[identity],
                    **card,
                    "called_by": keys.get(caller),
                    "sources": chosen[identity],
                }
            )
        public = sources.public()
        identities = {_key(_reference(source["ref"])): source["key"] for source in public}
        for source in public:
            withdrawer = self.beliefs.withdrawn_by(_reference(source["ref"]))
            if withdrawer is not None:
                reference = _reference(withdrawer)
                source["withdrawn_by"] = (
                    identities.get(_key(reference), "earlier") if reference else "earlier"
                )
        origins = {}
        for name in sources.origins():
            try:
                origins[name] = round(self.beliefs.read(origin_target(name)).strength, 3)
            except KeyError:
                origins[name] = None
        return {
            "sources": public,
            "runs": batch_runs,
            "origins": origins,
            "through": through,
            "remaining": remaining,
        }

    def _validate_target(self, target: Any) -> None:
        if not isinstance(target, str) or "@" not in target:
            raise ContractError("A Program evidence target names a revision")
        name, revision = target.rsplit("@", 1)
        if not revision:
            raise ContractError("A Program evidence target names a revision")
        if name.startswith("program:"):
            identity = name.removeprefix("program:")
            try:
                node = self.graph.get(int(identity)) if identity.isdigit() else None
            except KeyError:
                node = None
            if node is None or node.kind != "program":
                raise ContractError("Program evidence needs a registered Program")
        elif name.startswith("op:"):
            node = self.graph.find(name)
            if node is None or node.kind != "operator":
                raise ContractError("Operator evidence needs an anchored operator")
            if revision not in node.properties.get("revisions", ()):
                raise ContractError("The operator is not anchored in that Program revision")
        else:
            raise ContractError("Program evidence targets a Program or an anchored operator")

    def record(
        self, through: int | None, records: list | tuple = (), *, created_by: Any = None
    ) -> dict:
        """Apply assessed evidence per target, then move the cursor to through.

        Every record is validated before any change, so a rejected batch records nothing
        and its sources are found again by the next batch.
        """
        if through is not None and (type(through) is not int or through < 0):
            raise ContractError("through is a memory event position")
        for record in records:
            if not isinstance(record, Mapping):
                raise ContractError("A Program evidence record is an object")
            self._validate_target(record.get("target"))
            binary_items(self.memory, record.get("assign", ()), record.get("retract", ()))
        recorded = [
            apply_binary(
                self.beliefs,
                self.memory,
                record["target"],
                None,
                record.get("assign", ()),
                record.get("retract", ()),
                created_by,
            )
            for record in records
        ]
        if through is not None:
            self.beliefs.advance_cursor(CURSOR, through)
        return {"recorded": recorded, "cursor": self.beliefs.cursor(CURSOR)}

    def stale(self, threshold: float = STALE_RELIABILITY) -> list[dict]:
        """Active Program and operator contributions judged under an outdated reliability."""
        result = []
        for target, source_ref, basis in self.beliefs.bases():
            if not target.startswith(("program:", "op:")):
                continue
            try:
                self._validate_target(target)
            except ContractError:
                continue
            origin = basis.get("origin")
            if not origin or "reliability" not in basis:
                continue
            try:
                reliability = self.beliefs.read(origin_target(origin)).strength
            except KeyError:
                continue
            if abs(reliability - basis["reliability"]) > threshold:
                result.append(
                    {
                        "target": target,
                        "source_ref": json_value(source_ref),
                        "basis": json_value(basis),
                        "reliability": reliability,
                    }
                )
        return result
