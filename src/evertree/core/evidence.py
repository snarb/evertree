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

from .beliefs import OTHER, BeliefStore, element_target
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
ORIGIN_LIMIT = 30
# Change in an origin's reliability that makes contributions judged under it stale.
STALE_RELIABILITY = 0.02


def _reference(value: Any) -> TraceOutputRef | None:
    if isinstance(value, TraceOutputRef):
        return value
    if isinstance(value, Mapping) and set(value) <= {"event_ref", "output_path"}:
        try:
            return TraceOutputRef(value["event_ref"], tuple(value.get("output_path", ())))
        except (KeyError, ContractError):
            return None
    return None


def _alternative(label: str) -> int | str:
    """Show a scope alternative as its element id, or "other"."""
    return OTHER if label == OTHER else int(label.removeprefix("graph:"))


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


def origin_target(origin: str) -> str:
    """Return the belief target for the reliability of one source origin."""
    return f"origin:{origin}"


def binary_items(memory: TraceStore, assign: list | tuple, retract: list | tuple) -> tuple:
    """Validate binary assign and retract items; return (assignments, retractions)."""
    retractions = [_reference(item) for item in retract]
    assignments = []
    for item in assign:
        reference, root = _reference(item.get("source_ref")), item.get("dependency_root")
        likelihoods, basis = item.get("likelihoods"), item.get("basis")
        if reference is None or root is not None and _reference(root) is None:
            raise ContractError("Evidence needs a retained source reference")
        if not isinstance(likelihoods, Mapping) or set(likelihoods) != {"false", "true"}:
            raise ContractError("Binary likelihoods are keyed by false and true")
        if not all(
            isinstance(value, (int, float)) and math.isfinite(value) and value > 0
            for value in likelihoods.values()
        ):
            raise ContractError("Likelihoods must be positive and finite")
        if basis is not None and not isinstance(basis, Mapping):
            raise ContractError("An assessment basis is an object")
        memory.resolve(reference)
        assignments.append(
            (reference, dict(likelihoods), _reference(root) if root else None, basis)
        )
    if any(reference is None for reference in retractions):
        raise ContractError("Retraction needs a source reference")
    return assignments, retractions


def apply_binary(
    beliefs: BeliefStore,
    memory: TraceStore,
    target: str,
    prior: float | None,
    assign: list | tuple,
    retract: list | tuple,
    created_by: Any = None,
) -> dict:
    """Register a binary target if new, then retract and assign assessed contributions.

    Inputs are validated before any change, so a rejected record leaves beliefs unchanged.
    Each assignment keeps its basis and retains its source for the target.
    """
    assignments, retractions = binary_items(memory, assign, retract)
    try:
        beliefs.target(target)
    except KeyError:
        low, high = PRIOR_BOUNDS
        value = 0.5 if prior is None else min(max(float(prior), low), high)
        beliefs.register_binary(target, value)
    active = {_key(_reference(item.source_ref)) for item in beliefs.active_sources(target)}
    retracted = []
    for reference in retractions:
        if _key(reference) in active:
            beliefs.retract(target, reference)
            retracted.append(json_value(reference))
    created = []
    for reference, likelihoods, root, basis in assignments:
        assignment = beliefs.assess_likelihoods(
            target,
            reference,
            likelihoods,
            # The heuristic observation model is not independently validated,
            # so its influence stays under the shared unsupported cap.
            backed=False,
            dependency_root=root,
            created_by=created_by,
        )
        beliefs.set_basis(target, reference, basis)
        memory.retain(reference, "evidence:" + target)
        created.append(assignment.id)
    return {
        "target": target,
        "assignments": created,
        "retracted": retracted,
        "belief": json_value(beliefs.read(target)),
    }


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
            "origin": self._origin(event, kind),
            "recorded_at": event.occurred_at.isoformat(),
            "text": _text(value),
            "new": new,
        }
        return [key]

    @staticmethod
    def _origin(event, kind: str) -> str:
        """Name where a primary source comes from; its reliability is assessed per origin."""
        if kind == "user":
            return "user"
        arguments = event.arguments if isinstance(event.arguments, Mapping) else {}
        if arguments.get("source_id"):
            return str(arguments["source_id"])
        output = event.output if isinstance(event.output, Mapping) else {}
        data = output.get("data") if isinstance(output.get("data"), Mapping) else {}
        return f"tool:{data['name']}" if data.get("name") else kind

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
            # A document reports what its author states; an observation records the world.
            return "document" if arguments.get("source_type") == "document" else "observation"
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

    def origins(self) -> list[str]:
        return list(dict.fromkeys(entry["origin"] for entry in self.entries.values()))


def active_directions(beliefs: BeliefStore, target: str, sources: _Sources) -> list[dict]:
    """Sources already counted for a binary target, keyed in the batch, with their direction."""
    result = []
    for component in beliefs.active_sources(target):
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


class GraphEvidence:
    """Select graph elements that need evidence assessment and record assessed contributions."""

    def __init__(self, graph: GraphStore, memory: TraceStore, beliefs: BeliefStore):
        self.graph, self.memory, self.beliefs = graph, memory, beliefs

    def _node(self, identity: int):
        try:
            return self.graph.get(identity)
        except KeyError:
            return None

    def _current(self, label: str) -> bool:
        """Tell whether a scope alternative still names an assessable element."""
        if label == OTHER:
            return True
        node = self._node(int(label.removeprefix("graph:")))
        return node is not None and self.assessable(node)

    def assessable(self, node) -> bool:
        """Tell whether a node is a semantic graph element this program assesses as binary."""
        qualitative = node.kind == "property" and "qualitative_norm" in node.properties
        if (not qualitative and node.kind not in ASSESSABLE_KINDS) or node.properties.get(
            "process"
        ):
            return False
        # Explicit bindings (attribution scopes) belong to their own updaters.
        return not (isinstance(node, RelationInstance) and node.belief_target)

    def _grounds(self, identity: int, sources: _Sources, assessed: int) -> list[str]:
        keys = []
        changes = list(self.graph.changes_of(identity))
        node = self.graph.get(identity)
        if "qualitative_norm" in node.properties:
            for dependency in node.properties["norm_state"].get("dependencies", ()):
                changes.extend(
                    change
                    for change in self.graph.changes_of(dependency["object"])
                    if change.seq == dependency["revision"]
                )
        for change in changes:
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
        return active_directions(self.beliefs, target, sources)

    def _card(self, node) -> dict:
        if "attribution_result" in node.properties:
            result = json_value(node.properties["attribution_result"])
            value = result["value_U"]
            if isinstance(value, dict) and len(value.get("quantiles", ())) > 20:
                value["quantiles_total"] = len(value["quantiles"])
                value["quantiles"] = value["quantiles"][:20]
                value["truncated"] = True
            return {**card(node), "attribution_result": result}
        if "qualitative_norm" in node.properties:
            definition, state = node.properties["qualitative_norm"], node.properties["norm_state"]
            return {
                **card(node),
                "criterion": json_value(definition),
                "class_meanings": [
                    card(self.graph.get(identity)) for identity in definition["classes"]
                ],
                "fitted_norm": {
                    key: json_value(state[key])
                    for key in (
                        "status",
                        "boundaries",
                        "boundary_bounds",
                        "count",
                        "unit",
                        "approximate",
                    )
                    if key in state
                },
                "dependency_count": len(state.get("dependencies", ())),
                "assessment_question": "Does this fitted criterion describe its stated population?",
            }
        if "numeric_reference" in node.properties:
            return {
                **card(node),
                "numeric_reference": json_value(node.properties["numeric_reference"]),
            }
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
            new_target = not self.beliefs.known(target)
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
        # Alternatives competing with a changed element are judged together with it.
        related_ids = [sibling for item in targets for sibling in self._siblings(item["element"])]
        related_ids.extend(candidates)
        for item in targets:
            related_ids.extend(self._neighbors(self.graph.get(item["element"])))
        # A search hit on an entity also brings the facts about it: a correction may concern
        # an earlier fact that integration did not touch.
        for identity in candidates:
            node = self._node(identity) if type(identity) is int else None
            if node is not None:
                related_ids.extend(self._neighbors(node))
        related = []
        for identity in dict.fromkeys(related_ids):
            if len(related) >= related_limit:
                break
            node = self._node(identity) if type(identity) is int else None
            if node is None or identity in chosen or not self.assessable(node):
                continue
            target = element_target(node)
            known = self.beliefs.known(target)
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
        scopes = self._scopes(targets + related, sources)
        origins = self._origins(sources)
        keys = {item["origin"]: item["key"] for item in origins}
        public = sources.public()
        identities = {_key(_reference(source["ref"])): source["key"] for source in public}
        for source in public:
            source["origin_key"] = keys.get(source["origin"])
            withdrawer = self.beliefs.withdrawn_by(_reference(source["ref"]))
            if withdrawer is not None:
                reference = _reference(withdrawer)
                source["withdrawn_by"] = (
                    identities.get(_key(reference), "earlier") if reference else "earlier"
                )
        return {
            "revision": self.graph.revision,
            "sources": public,
            "origins": origins,
            "scopes": scopes,
            "targets": targets,
            "related": related,
            "remaining": max(len(waiting) - limit, 0),
        }

    def _siblings(self, element: int) -> list[int]:
        scope = self.beliefs.scope_of(f"graph:{element}")
        if scope is None:
            return []
        return [
            int(label.removeprefix("graph:"))
            for label in self.beliefs.scope(scope)["alternatives"]
            if label != OTHER and label != f"graph:{element}"
        ]

    def _scopes(self, items: list[dict], sources: _Sources) -> list[dict]:
        """Describe the competition scopes of batch elements, keyed C1, C2, …; mark members."""
        result, keys = [], {}
        for item in items:
            scope = self.beliefs.scope_of(f"graph:{item['element']}")
            if scope is None:
                continue
            if scope not in keys:
                keys[scope] = f"C{len(keys) + 1}"
                declared = self.beliefs.scope(scope)
                labels = declared["alternatives"]
                active = []
                for component in self.beliefs.active_sources(scope):
                    reference = _reference(component.source_ref)
                    if reference is None:
                        continue
                    favoured = labels[component.contribution.index(max(component.contribution))]
                    for key in sources.expand(reference, new=False):
                        active.append({"source": key, "favours": _alternative(favoured)})
                result.append(
                    {
                        "key": keys[scope],
                        "scope": scope,
                        "question": declared["question"],
                        # A deleted alternative is gone; judging without it versions the scope.
                        "alternatives": [
                            _alternative(label) for label in labels if self._current(label)
                        ],
                        "active": active,
                    }
                )
            item["scope"] = keys[scope]
        return result

    def _origins(self, sources: _Sources, limit: int = ORIGIN_LIMIT) -> list[dict]:
        """Origins of the batch's sources first, then other origins already assessed."""
        names = sources.origins()
        for target in self.beliefs.target_ids():
            if target.startswith("origin:"):
                names.append(target.removeprefix("origin:"))
        result = []
        for name in list(dict.fromkeys(names))[:limit]:
            item = {"key": f"O{len(result) + 1}", "origin": name, "new_target": True}
            try:
                reading = self.beliefs.read(origin_target(name))
            except KeyError:
                item["reliability"] = None
            else:
                item.update(
                    new_target=False,
                    reliability=round(reading.strength, 3),
                    support=round(reading.support, 3),
                    evidence_count=reading.stats.evidence_count,
                    # Earlier statements about the origin, so a new one can withdraw them.
                    active=self._active(origin_target(name), sources),
                )
            result.append(item)
        return result

    def stale(self, threshold: float = STALE_RELIABILITY) -> list[dict]:
        """Active contributions judged under an origin reliability that has since changed."""
        result = []
        for target, source_ref, basis in self.beliefs.bases():
            origin = basis.get("origin")
            if not origin or "reliability" not in basis:
                continue
            try:
                reliability = self.beliefs.read(origin_target(origin)).strength
            except KeyError:
                continue
            if abs(reliability - basis["reliability"]) <= threshold:
                continue
            item = {
                "target": target,
                "source_ref": json_value(source_ref),
                "basis": json_value(basis),
                "reliability": reliability,
            }
            if target.startswith("graph:"):
                node = self._node(int(target.removeprefix("graph:")))
                if node is None or not self.assessable(node):
                    continue
                item["element"] = node.id
            elif target.startswith("origin:"):
                item["origin"] = target.removeprefix("origin:")
            elif target.startswith("scope:"):
                declared = self.beliefs.scope(target)
                # A scope that lost an alternative is versioned at its next judgement instead.
                if not all(self._current(label) for label in declared["alternatives"]):
                    continue
                item.update(
                    scope=target,
                    question=declared["question"],
                    alternatives=[_alternative(label) for label in declared["alternatives"]],
                )
            else:
                continue
            result.append(item)
        return result

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
        if self.beliefs.scope_of(target) is not None:
            raise ContractError("A scope alternative's evidence is recorded for its scope")
        result = apply_binary(self.beliefs, self.memory, target, prior, assign, retract, created_by)
        self.beliefs.mark_assessed(target, revision)
        return {"element": element, **result}

    def withdraw(self, source_ref: Any, by: Any, keep: list | tuple = ()) -> dict:
        """Record that a later source withdrew an earlier one and retract its graph evidence.

        A withdrawn source gives no new evidence, and its contributions are retracted from
        every graph, origin and scope target except those in keep, where the assessment
        judged that the correction does not concern them. Program and operator targets
        are left to Program assessment, which judges whether the correction concerns a run.
        """
        reference, withdrawer = _reference(source_ref), _reference(by)
        if reference is None or withdrawer is None:
            raise ContractError("Withdrawal needs source references")
        self.memory.resolve(reference)
        self.memory.resolve(withdrawer)
        self.beliefs.withdraw(reference, withdrawer)
        retracted = []
        for target in self.beliefs.targets_of(reference):
            if target not in keep and not target.startswith(("program:", "op:")):
                self.beliefs.retract(target, reference)
                retracted.append(target)
        return {
            "withdrawn": json_value(reference),
            "by": json_value(withdrawer),
            "retracted": retracted,
        }

    def record_origin(
        self,
        origin: str,
        *,
        prior: float | None = None,
        assign: list | tuple = (),
        retract: list | tuple = (),
        created_by: Any = None,
    ) -> dict:
        """Apply assessed evidence about the reliability of one source origin."""
        if not isinstance(origin, str) or not origin:
            raise ContractError("An origin is a non-empty name")
        return {
            "origin": origin,
            **apply_binary(
                self.beliefs, self.memory, origin_target(origin), prior, assign, retract, created_by
            ),
        }

    def record_scope(
        self,
        revision: int,
        *,
        alternatives: list | tuple,
        question: str,
        other: bool = True,
        scope: str | None = None,
        prior: Mapping | None = None,
        assign: list | tuple = (),
        retract: list | tuple = (),
        created_by: Any = None,
    ) -> dict:
        """Record evidence for mutually exclusive graph elements as one competition scope.

        alternatives are element ids; other adds the alternative that none of them is
        true. A different set of alternatives than scope declares creates a new scope
        version. Elements joining a scope stop counting their binary evidence: the scope's
        evidence judges every source against all alternatives at once. likelihoods and
        prior are keyed by element id (as a string) and "other".
        """
        if type(revision) is not int or not 0 <= revision <= self.graph.revision:
            raise ContractError("Assessment revision must be a known graph revision")
        elements = list(dict.fromkeys(alternatives))
        if not isinstance(question, str) or not question:
            raise ContractError("A competition scope states its question")
        for element in elements:
            node = self._node(element) if type(element) is int else None
            if node is None or not self.assessable(node):
                raise ContractError("Scope alternatives must be assessable graph elements")
        labels = [f"graph:{element}" for element in elements] + ([OTHER] if other else [])
        if len(labels) < 2:
            raise ContractError("A competition scope needs at least two alternatives")
        names = {str(element): f"graph:{element}" for element in elements} | {OTHER: OTHER}

        def keyed(mapping, what):
            if not isinstance(mapping, Mapping) or set(mapping) != {
                key for key, label in names.items() if label in labels
            }:
                raise ContractError(f"Scope {what} must cover exactly its alternatives")
            values = {names[key]: value for key, value in mapping.items()}
            if not all(
                isinstance(value, (int, float)) and math.isfinite(value) and value > 0
                for value in values.values()
            ):
                raise ContractError(f"Scope {what} must be positive and finite")
            return values

        assignments = []
        for item in assign:
            reference, root = _reference(item.get("source_ref")), item.get("dependency_root")
            if reference is None or root is not None and _reference(root) is None:
                raise ContractError("Evidence needs a retained source reference")
            basis = item.get("basis")
            if basis is not None and not isinstance(basis, Mapping):
                raise ContractError("An assessment basis is an object")
            self.memory.resolve(reference)
            assignments.append(
                (reference, keyed(item.get("likelihoods"), "likelihoods"), root, basis)
            )
        retractions = [_reference(item) for item in retract]
        if any(reference is None for reference in retractions):
            raise ContractError("Retraction needs a source reference")
        weights = keyed(prior, "prior") if prior is not None else None
        # An unnamed scope over exactly an existing scope's alternatives is that scope.
        target = scope or self.beliefs.scope_of(labels[0])
        if (
            target is None
            or not self.beliefs.known(target)
            or set(self.beliefs.scope(target)["alternatives"]) != set(labels)
        ):
            count = sum(item.startswith("scope:") for item in self.beliefs.target_ids())
            target = f"scope:{count + 1}"
            if weights is not None:
                low = PRIOR_BOUNDS[0] / len(labels)
                total = sum(max(value, low) for value in weights.values())
                weights = {key: max(value, low) / total for key, value in weights.items()}
            self.beliefs.declare_scope(target, question, labels, weights)
        released = []
        for label in labels:
            if (
                label == OTHER
                or not self.beliefs.known(label)
                or label not in self.beliefs.target_ids()
            ):
                continue
            for component in self.beliefs.active_sources(label):
                self.beliefs.retract(label, component.source_ref)
                released.append(
                    {
                        "element": int(label.removeprefix("graph:")),
                        "source_ref": json_value(component.source_ref),
                    }
                )
        active = {_key(_reference(item.source_ref)) for item in self.beliefs.active_sources(target)}
        retracted = []
        for reference in retractions:
            if _key(reference) in active:
                self.beliefs.retract(target, reference)
                retracted.append(json_value(reference))
        created = []
        for reference, likelihoods, root, basis in assignments:
            assignment = self.beliefs.assess_likelihoods(
                target,
                reference,
                likelihoods,
                backed=False,
                dependency_root=_reference(root) if root else None,
                created_by=created_by,
            )
            self.beliefs.set_basis(target, reference, basis)
            self.memory.retain(reference, "evidence:" + target)
            created.append(assignment.id)
        for label in labels:
            if label != OTHER:
                self.beliefs.mark_assessed(label, revision)
        return {
            "scope": target,
            "alternatives": [_alternative(label) for label in labels],
            "assignments": created,
            "retracted": retracted,
            "released": released,
            "belief": json_value(self.beliefs.read(target)),
        }
