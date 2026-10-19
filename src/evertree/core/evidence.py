"""Evidence batches for graph elements and their protected recording.

A graph element's belief target is derived from its identity (`element_target`).
Its grounds are the experience recorded with each semantic write. Agent-derived
results (analytical Notes, conscious steps, Program outputs) are not independent
evidence: they are expanded to the primary experience they depend on, so a
restatement cannot add support to the source it restates.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from .beliefs import BeliefStore, element_target
from .graph.store import GraphStore
from .graph.types import RelationInstance
from .memory.store import TraceStore
from .memory.types import TraceOutputRef
from .semantics.reading import card, fact_nodes
from .values import ContractError, json_value

ASSESSABLE_KINDS = frozenset(
    {"relation_instance", "claim", "note", "facet", "instance", "concept", "prototype"}
)
TEXT_LIMIT = 2000
MAX_EXPANSION_DEPTH = 4
PRIOR_BOUNDS = (0.05, 0.95)


def _reference(value: Any) -> TraceOutputRef | None:
    if isinstance(value, TraceOutputRef):
        return value
    if isinstance(value, Mapping) and set(value) <= {"event_ref", "output_path"}:
        try:
            return TraceOutputRef(value["event_ref"], tuple(value.get("output_path", ())))
        except (KeyError, ContractError):
            return None
    return None


def _key(reference: TraceOutputRef) -> str:
    return json.dumps(json_value(reference), sort_keys=True)


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        for field in ("content", "text"):
            if isinstance(value.get(field), str):
                value = value[field]
                break
    if not isinstance(value, str):
        value = json.dumps(json_value(value), ensure_ascii=False)
    return value if len(value) <= TEXT_LIMIT else value[:TEXT_LIMIT] + " …"


class _Sources:
    """Primary evidence sources of one batch, keyed S1, S2, … in order of discovery."""

    def __init__(self, memory: TraceStore):
        self.memory = memory
        self.entries: dict[str, dict] = {}

    def expand(self, reference: TraceOutputRef, *, new: bool, depth: int = 0) -> list[str]:
        """Return keys of the primary sources behind a reference; derived results are unfolded."""
        try:
            event = self.memory.get_event(reference.event_ref)
            value = self.memory.resolve(reference)
        except (ContractError, KeyError):
            return []
        kind = self._kind(event)
        if kind == "fragment":
            parent = event.dependencies[0] if event.dependencies else None
            try:
                kind = self._kind(self.memory.get_event(parent.event_ref)) if parent else "agent"
            except KeyError:
                kind = "agent"
            if kind == "agent" and parent is not None:
                return self.expand(parent, new=new, depth=depth + 1)
        if kind == "agent":
            if depth >= MAX_EXPANSION_DEPTH:
                return []
            keys = []
            for dependency in event.dependencies:
                keys.extend(self.expand(dependency, new=new, depth=depth + 1))
            return list(dict.fromkeys(keys))
        # A citation of one field and of the whole record are the same logical evidence.
        reference = TraceOutputRef(reference.event_ref)
        value = self.memory.resolve(reference)
        identity = _key(reference)
        for key, entry in self.entries.items():
            if entry["identity"] == identity:
                entry["new"] = entry["new"] or new
                return [key]
        key = f"S{len(self.entries) + 1}"
        self.entries[key] = {
            "identity": identity,
            "ref": json_value(reference),
            "kind": kind,
            "recorded_at": event.occurred_at.isoformat(),
            "text": _text(value),
            "new": new,
        }
        return [key]

    @staticmethod
    def _kind(event) -> str:
        output = event.output if isinstance(event.output, Mapping) else {}
        arguments = event.arguments if isinstance(event.arguments, Mapping) else {}
        if event.operator == "user_input":
            return "user"
        if event.operator == "observation":
            if output.get("role") == "user" or str(arguments.get("source_id", "")).startswith(
                "input:"
            ):
                return "user"
            return "observation"
        if event.operator == "provider_event" and output.get("kind") in {
            "tool_result",
            "file_change",
        }:
            return "observation"
        if event.operator == "experience_fragment":
            return "fragment"
        return "agent"

    def public(self) -> list[dict]:
        return [
            {"key": key, **{k: v for k, v in entry.items() if k != "identity"}}
            for key, entry in self.entries.items()
        ]


class GraphEvidence:
    """Select graph elements that need evidence assessment and record assessed contributions."""

    def __init__(self, graph: GraphStore, memory: TraceStore, beliefs: BeliefStore):
        self.graph, self.memory, self.beliefs = graph, memory, beliefs

    def _node(self, identity: int):
        try:
            return self.graph.get(identity)
        except KeyError:
            return None

    def assessable(self, node) -> bool:
        """Tell whether a node is a semantic graph element this program assesses as binary."""
        if node.kind not in ASSESSABLE_KINDS or node.properties.get("process"):
            return False
        # Explicit bindings (attribution scopes) belong to their own updaters.
        return not (isinstance(node, RelationInstance) and node.belief_target)

    def _grounds(self, identity: int, sources: _Sources, assessed: int) -> list[str]:
        keys = []
        for change in self.graph.changes_of(identity):
            reference = _reference(change.provenance)
            if reference is None:
                continue
            try:
                event = self.memory.get_event(reference.event_ref)
            except KeyError:
                continue
            if event.operator != "graph_delta":
                continue
            for dependency in event.dependencies:
                keys.extend(sources.expand(dependency, new=change.seq > assessed))
        return list(dict.fromkeys(keys))

    def _active(self, target: str, sources: _Sources) -> list[dict]:
        result = []
        for component in self.beliefs.active_sources(target):
            reference = _reference(component.source_ref)
            if reference is None:
                continue
            for key in sources.expand(reference, new=False):
                effect = component.contribution[0]
                direction = (
                    "supports" if effect > 0 else "opposes" if effect < 0 else "non_discriminating"
                )
                result.append({"source": key, "direction": direction})
        return result

    def _card(self, node) -> dict:
        if isinstance(node, RelationInstance):
            relation = self.graph.get(node.relation_type)
            args = {}
            for label, value in node.args.items():
                values = value if isinstance(value, (list, tuple)) else (value,)
                named = [
                    card(self.graph.get(item))
                    if type(item) is int and item in fact_nodes(self.graph, node)
                    else item
                    for item in values
                ]
                args[label] = named if isinstance(value, (list, tuple)) else named[0]
            result = {**card(node), "relation": relation.name, "args": json_value(args)}
            if node.properties.get("conditions"):
                result["conditions"] = json_value(node.properties["conditions"])
            return result
        return card(node)

    def _neighbors(self, node) -> list[int]:
        """Elements that may compete with or qualify a changed element.

        A fact's competitors share a participant and relation type, such as another state
        of the same instance; their other participants (that state's Facet) come along.
        """
        if not isinstance(node, RelationInstance):
            return [
                fact.id
                for fact in self.graph.iter_facts()
                if node.id in fact_nodes(self.graph, fact)
            ]
        shared = fact_nodes(self.graph, node)
        result = []
        for fact in self.graph.iter_facts(node.relation_type):
            participants = fact_nodes(self.graph, fact)
            if fact.id != node.id and shared & participants:
                result.extend((fact.id, *sorted(participants - shared)))
        return result

    def pending(
        self,
        experience_refs: list | tuple = (),
        candidates: list | tuple = (),
        *,
        limit: int = 24,
        related_limit: int = 16,
    ) -> dict:
        """Build one assessment batch: changed elements, related elements and their sources.

        Advances the assessment cursor past changes that need no further assessment.
        """
        sources = _Sources(self.memory)
        for raw in experience_refs:
            reference = _reference(raw)
            if reference is None:
                raise ContractError("Invalid experience reference")
            sources.expand(reference, new=True)
        touched: dict[int, int] = {}
        for change in self.graph.changes_since(self.beliefs.assessment_cursor):
            for identity in (*change.before, *change.after):
                touched[identity] = change.seq
        waiting = []
        for identity, seq in sorted(touched.items(), key=lambda item: (item[1], item[0])):
            node = self._node(identity)
            if node is None or not self.assessable(node):
                continue
            target = element_target(node)
            assessed = self.beliefs.assessed_revision(target) or 0
            if assessed >= seq:
                continue
            # Bootstrap and lifecycle changes carry no experience to assess.
            probe = _Sources(self.memory)
            if not self._grounds(identity, probe, assessed):
                continue
            waiting.append((seq, node, assessed))
        self.beliefs.advance_assessment_cursor(
            min(seq for seq, _, _ in waiting) - 1 if waiting else self.graph.revision
        )
        targets = []
        for _, node, assessed in waiting[:limit]:
            target = element_target(node)
            try:
                self.beliefs.target(target)
                new_target = False
            except KeyError:
                new_target = True
            targets.append(
                {
                    "element": node.id,
                    "card": self._card(node),
                    "new_target": new_target,
                    "grounds": self._grounds(node.id, sources, assessed),
                    "active": [] if new_target else self._active(target, sources),
                }
            )
        chosen = {item["element"] for item in targets}
        related_ids = list(candidates)
        for item in targets:
            related_ids.extend(self._neighbors(self.graph.get(item["element"])))
        related = []
        for identity in dict.fromkeys(related_ids):
            if len(related) >= related_limit:
                break
            node = self._node(identity) if type(identity) is int else None
            if node is None or identity in chosen or not self.assessable(node):
                continue
            target = element_target(node)
            try:
                self.beliefs.target(target)
                known = True
            except KeyError:
                known = False
            if not known and not self._grounds(identity, _Sources(self.memory), 0):
                continue
            related.append(
                {
                    "element": identity,
                    "card": self._card(node),
                    "new_target": not known,
                    "active": self._active(target, sources) if known else [],
                }
            )
            chosen.add(identity)
        return {
            "revision": self.graph.revision,
            "sources": sources.public(),
            "targets": targets,
            "related": related,
            "remaining": max(len(waiting) - limit, 0),
        }

    def record(
        self,
        element: int,
        revision: int,
        *,
        prior: float | None = None,
        assign: list | tuple = (),
        retract: list | tuple = (),
        created_by: Any = None,
    ) -> dict:
        """Apply one element's assessed evidence: register, retract, assign, then mark assessed.

        Inputs are validated before any change, so a rejected record leaves beliefs unchanged.
        """
        node = self._node(element)
        if node is None or not self.assessable(node):
            raise ContractError("Evidence can be recorded only for an assessable graph element")
        if type(revision) is not int or not 0 <= revision <= self.graph.revision:
            raise ContractError("Assessment revision must be a known graph revision")
        target = element_target(node)
        retractions = [_reference(item) for item in retract]
        assignments = []
        for item in assign:
            reference, root = _reference(item.get("source_ref")), item.get("dependency_root")
            likelihoods = item.get("likelihoods")
            if reference is None or root is not None and _reference(root) is None:
                raise ContractError("Evidence needs a retained source reference")
            if not isinstance(likelihoods, Mapping) or set(likelihoods) != {"false", "true"}:
                raise ContractError("Graph element likelihoods are keyed by false and true")
            if not all(
                isinstance(value, (int, float)) and math.isfinite(value) and value > 0
                for value in likelihoods.values()
            ):
                raise ContractError("Likelihoods must be positive and finite")
            self.memory.resolve(reference)
            assignments.append((reference, dict(likelihoods), _reference(root) if root else None))
        if any(reference is None for reference in retractions):
            raise ContractError("Retraction needs a source reference")
        try:
            self.beliefs.target(target)
        except KeyError:
            low, high = PRIOR_BOUNDS
            value = 0.5 if prior is None else min(max(float(prior), low), high)
            self.beliefs.register_binary(target, value)
        active = {_key(_reference(item.source_ref)) for item in self.beliefs.active_sources(target)}
        retracted = []
        for reference in retractions:
            if _key(reference) in active:
                self.beliefs.retract(target, reference)
                retracted.append(json_value(reference))
        created = []
        for reference, likelihoods, root in assignments:
            assignment = self.beliefs.assess_likelihoods(
                target,
                reference,
                likelihoods,
                # The heuristic observation model is not independently validated,
                # so its influence stays under the shared unsupported cap.
                backed=False,
                dependency_root=root,
                created_by=created_by,
            )
            self.memory.retain(reference, "evidence:" + target)
            created.append(assignment.id)
        self.beliefs.mark_assessed(target, revision)
        return {
            "element": element,
            "target": target,
            "assignments": created,
            "retracted": retracted,
            "belief": json_value(self.beliefs.read(target)),
        }
