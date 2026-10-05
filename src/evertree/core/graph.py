"""Identity-preserving semantic graph and its atomic mutation boundary.

The graph is deliberately an in-memory store.  Its JSON snapshot is included in
the runtime's coordinated backup rather than being a second database.
"""

from __future__ import annotations

import dataclasses
import math
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any


class ContractError(ValueError):
    """A semantic interface or graph invariant was violated."""


class _Unknown:
    def __repr__(self) -> str:
        return "unknown"

    def __bool__(self) -> bool:
        raise TypeError("unknown is not a boolean; compare with UNKNOWN explicitly")


UNKNOWN = _Unknown()


def utcnow() -> datetime:
    return datetime.now(UTC)


def timestamp(value: datetime | str) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise ContractError("timestamps must include a timezone")
    return result.astimezone(UTC)


def freeze(value: Any) -> Any:
    """Detach JSON-shaped values and prevent mutations through returned reads."""
    if value is UNKNOWN:
        return UNKNOWN
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return MappingProxyType(
            {field.name: freeze(getattr(value, field.name)) for field in dataclasses.fields(value)}
        )
    if hasattr(value, "model_dump"):
        return freeze(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze(item) for item in value)
    if isinstance(value, (str, int, bool, float, datetime, type(None))):
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError("non-finite values cannot be persisted")
        return value
    raise ContractError(f"unsupported persisted value: {type(value).__name__}")


def json_value(value: Any) -> Any:
    """Encode values without importing classes or executing code on restore."""
    if value is UNKNOWN:
        return {"$unknown": True}
    if isinstance(value, datetime):
        return {"$datetime": timestamp(value).isoformat()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if hasattr(value, "model_dump"):
        return json_value(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        if len(value) == 1 and next(iter(value)) in {"$unknown", "$datetime", "$set", "$mapping"}:
            return {"$mapping": [[str(key), json_value(item)] for key, item in value.items()]}
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return {"$set": [json_value(item) for item in sorted(value, key=repr)]}
    if isinstance(value, (str, int, float, bool, type(None))):
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError("non-finite values cannot be persisted")
        return value
    raise ContractError(f"unsupported snapshot value: {type(value).__name__}")


def restore_value(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$mapping"}:
            return {key: restore_value(item) for key, item in value["$mapping"]}
        if set(value) == {"$unknown"}:
            return UNKNOWN
        if set(value) == {"$datetime"}:
            return timestamp(value["$datetime"])
        if set(value) == {"$set"}:
            return frozenset(restore_value(item) for item in value["$set"])
        return {key: restore_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(restore_value(item) for item in value)
    return value


@dataclasses.dataclass(frozen=True)
class Node:
    id: int
    name: str
    kind: str = "concept"
    description: str | None = None
    properties: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            isinstance(self.id, bool)
            or not isinstance(self.id, int)
            or self.id <= 0
            or not self.name.strip()
        ):
            raise ContractError("nodes require a positive integer identity and a name")
        expected = {
            "Prototype": "prototype",
            "Instance": "instance",
            "Facet": "facet",
            "RelationType": "relation_type",
            "RelationInstance": "relation_instance",
        }.get(type(self).__name__)
        if expected is not None and self.kind != expected:
            raise ContractError("node kind must match its structural representation")
        if type(self) is Node and self.kind in {
            "prototype",
            "instance",
            "facet",
            "relation_type",
            "relation_instance",
        }:
            raise ContractError("use the typed representation for structural graph nodes")
        object.__setattr__(self, "properties", freeze(self.properties))


@dataclasses.dataclass(frozen=True)
class Concept(Node):
    pass


@dataclasses.dataclass(frozen=True)
class Prototype(Node):
    kind: str = "prototype"


@dataclasses.dataclass(frozen=True)
class Instance(Node):
    kind: str = "instance"


@dataclasses.dataclass(frozen=True)
class Facet(Node):
    kind: str = "facet"
    valid_from: datetime = dataclasses.field(default_factory=utcnow)
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "valid_from", timestamp(self.valid_from))
        if self.valid_until is not None:
            object.__setattr__(self, "valid_until", timestamp(self.valid_until))
            if self.valid_until <= self.valid_from:
                raise ContractError("facet intervals must be nonempty [from, until)")


ARITIES = {"one", "optional", "list0", "list1"}
VALUE_TYPES = {
    "node",
    "concept",
    "prototype",
    "instance",
    "facet",
    "string",
    "number",
    "integer",
    "boolean",
    "any",
}
OPERATORS = {"==", "!=", "in", "not_in", "<", "<=", ">", ">=", "contains", "is_null", "not_null"}


@dataclasses.dataclass(frozen=True)
class Slot:
    label: str
    value_type: str = "node"
    arity: str = "one"
    concept: int | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.label.isidentifier() or self.label in {"valid_at", "known_at"}:
            raise ContractError("slot labels must be nonreserved Python identifiers")
        if self.arity not in ARITIES or self.value_type not in VALUE_TYPES:
            raise ContractError("invalid slot arity or type")


@dataclasses.dataclass(frozen=True)
class Clause:
    field: str
    op: str
    value: Any = None

    def __post_init__(self) -> None:
        if self.op not in OPERATORS:
            raise ContractError("unsupported predicate operation")
        if self.op in {"is_null", "not_null"} and self.value is not None:
            raise ContractError("null predicates have no value")
        if self.op not in {"is_null", "not_null"} and self.value is None:
            raise ContractError("predicate operation requires a value")
        object.__setattr__(self, "value", freeze(self.value))


@dataclasses.dataclass(frozen=True)
class Predicate:
    all: tuple[Clause, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "all", tuple(self.all))


@dataclasses.dataclass(frozen=True)
class AccessView:
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    output_arity: str = "list0"
    constraints: Predicate | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        if (
            not self.name.isidentifier()
            or self.name.startswith("_")
            or self.output_arity not in ARITIES
        ):
            raise ContractError("invalid view name or output arity")
        if (
            not self.outputs
            or len(set(self.inputs)) != len(self.inputs)
            or len(set(self.outputs)) != len(self.outputs)
        ):
            raise ContractError("view labels cannot repeat and outputs cannot be empty")


@dataclasses.dataclass(frozen=True)
class RelationType(Node):
    kind: str = "relation_type"
    signature: tuple[Slot, ...] = ()
    views: tuple[AccessView, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "signature", tuple(self.signature))
        object.__setattr__(self, "views", tuple(self.views))
        labels = {slot.label for slot in self.signature}
        if len(labels) != len(self.signature) or not labels:
            raise ContractError("relation signatures require unique slots")
        names = set()
        for view in self.views:
            if (
                view.name in names
                or view.name in dir(type(self))
                or view.name in {field.name for field in dataclasses.fields(self)}
            ):
                raise ContractError("view name conflicts with relation interface")
            names.add(view.name)
            if not set(view.inputs + view.outputs) <= labels:
                raise ContractError("view references an undeclared slot")
            if view.constraints:
                for clause in view.constraints.all:
                    if clause.field not in labels | {
                        "id",
                        "name",
                        "strength",
                        "support",
                        "prior_support",
                    }:
                        raise ContractError("predicate references an undeclared field")


@dataclasses.dataclass(frozen=True)
class RelationInstance(Node):
    kind: str = "relation_instance"
    relation_type: int = 0
    args: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    belief_target: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(
            self,
            "args",
            freeze(
                {
                    key: value.id if isinstance(value, Node) else value
                    for key, value in self.args.items()
                }
            ),
        )


@dataclasses.dataclass(frozen=True)
class NodeUpdate:
    id: int
    changes: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "changes", freeze(self.changes))


@dataclasses.dataclass(frozen=True)
class GraphDelta:
    creates: tuple[Node, ...] = ()
    updates: tuple[NodeUpdate, ...] = ()
    deletes: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "creates", tuple(self.creates))
        object.__setattr__(self, "updates", tuple(self.updates))
        object.__setattr__(self, "deletes", tuple(self.deletes))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GraphDelta:
        return cls(
            tuple(node_from_dict(item) for item in data.get("creates", ())),
            tuple(
                NodeUpdate(item["id"], restore_value(item["changes"]))
                for item in data.get("updates", ())
            ),
            tuple(data.get("deletes", ())),
        )


@dataclasses.dataclass(frozen=True)
class GraphChange:
    seq: int
    at: datetime
    provenance: Any
    before: Mapping[int, Node]
    after: Mapping[int, Node]


@dataclasses.dataclass(frozen=True)
class ViewMatch:
    value: Any
    source_fact: RelationInstance


def _node_data(node: Node) -> dict:
    return {"class": type(node).__name__, "fields": json_value(node)}


def _node_from_data(data: dict) -> Node:
    classes = {
        cls.__name__: cls
        for cls in (Node, Concept, Prototype, Instance, Facet, RelationType, RelationInstance)
    }
    cls = classes[data["class"]]
    fields = restore_value(data["fields"])
    if cls is RelationType:
        fields["signature"] = tuple(Slot(**slot) for slot in fields["signature"])
        views = []
        for raw in fields["views"]:
            raw = dict(raw)
            if raw["constraints"] is not None:
                raw["constraints"] = Predicate(
                    tuple(Clause(**clause) for clause in raw["constraints"]["all"])
                )
            views.append(AccessView(**raw))
        fields["views"] = tuple(views)
    try:
        return cls(**fields)
    except TypeError as exc:
        raise ContractError("invalid fields in node representation") from exc


def node_from_dict(data: Mapping[str, Any]) -> Node:
    """Read a typed node from the ordinary JSON form emitted by json_value."""
    kinds = {
        "prototype": "Prototype",
        "instance": "Instance",
        "facet": "Facet",
        "relation_type": "RelationType",
        "relation_instance": "RelationInstance",
    }
    fields = {key: value for key, value in data.items()}
    if fields.get("kind") == "relation_type":
        fields.setdefault("signature", [])
        fields.setdefault("views", [])
        fields["views"] = [{"constraints": None, **dict(view)} for view in fields["views"]]
    return _node_from_data({"class": kinds.get(fields.get("kind"), "Node"), "fields": fields})


class _BoundRelation:
    def __init__(self, graph: GraphStore, relation: RelationType) -> None:
        self._graph, self._relation = graph, relation

    def __getattr__(self, name: str) -> Any:
        if any(view.name == name for view in self._relation.views):

            def execute(**inputs: Any) -> Any:
                return self._graph.query_view(self._relation.id, name, **inputs)

            return execute
        return getattr(self._relation, name)


class GraphStore:
    def __init__(self, *, belief_reader: Callable | None = None) -> None:
        self._nodes: dict[int, Node] = {}
        self._next_id = 1
        self._history: list[GraphChange] = []
        self._activations: dict[int, dict[str, float]] = {}
        self._lock = threading.RLock()
        self.belief_reader = belief_reader
        self.known_at: datetime | None = None
        self.read_only = False

    def reserve_id(self) -> int:
        with self._lock:
            identity = self._next_id
            self._next_id += 1
            return identity

    def get(self, identity: int) -> Node:
        return self._nodes[identity]

    def nodes(self, *, kind: str | None = None) -> tuple[Node, ...]:
        return tuple(node for node in self._nodes.values() if kind is None or node.kind == kind)

    def find(self, name: str) -> Node | None:
        return next((node for node in self._nodes.values() if node.name == name), None)

    def facts(self, relation_type: int | str | None = None) -> tuple[RelationInstance, ...]:
        if isinstance(relation_type, str):
            relation = self.find(relation_type)
            if relation is None:
                return ()
            relation_type = relation.id
        return tuple(
            node
            for node in self._nodes.values()
            if isinstance(node, RelationInstance)
            and (relation_type is None or node.relation_type == relation_type)
        )

    def relation(self, relation_type: int | str) -> _BoundRelation:
        relation = (
            self.find(relation_type) if isinstance(relation_type, str) else self.get(relation_type)
        )
        if not isinstance(relation, RelationType):
            raise ContractError("requested object is not a RelationType")
        return _BoundRelation(self, relation)

    def new_fact(
        self,
        relation_type: int | str,
        args: Mapping,
        *,
        name: str | None = None,
        belief_target: str | None = None,
    ) -> RelationInstance:
        relation = (
            self.find(relation_type) if isinstance(relation_type, str) else self.get(relation_type)
        )
        if not isinstance(relation, RelationType):
            raise ContractError("fact requires a declared relation type")
        return RelationInstance(
            self.reserve_id(),
            name or relation.name,
            relation_type=relation.id,
            args=args,
            belief_target=belief_target,
        )

    def apply(
        self, delta: GraphDelta, *, provenance: Any, at: datetime | None = None
    ) -> GraphChange:
        if self.read_only:
            raise ContractError("historical graph is read-only")
        if provenance is None:
            raise ContractError("graph changes require producer provenance")
        with self._lock:
            touched = (
                [node.id for node in delta.creates]
                + [update.id for update in delta.updates]
                + list(delta.deletes)
            )
            if len(touched) != len(set(touched)):
                raise ContractError("one delta cannot modify an identity more than once")
            staged = dict(self._nodes)
            before = {identity: staged[identity] for identity in touched if identity in staged}
            for node in delta.creates:
                if node.id in staged or any(
                    node.id in change.before or node.id in change.after for change in self._history
                ):
                    raise ContractError("node identity cannot be reused")
                staged[node.id] = node
            for update in delta.updates:
                if "id" in update.changes or "kind" in update.changes:
                    raise ContractError("node identity and kind are immutable")
                if update.id not in staged:
                    raise ContractError("cannot update a missing node")
                previous = staged[update.id]
                fields = json_value(previous)
                fields.update(json_value(update.changes))
                staged[update.id] = _node_from_data(
                    {"class": type(previous).__name__, "fields": fields}
                )
            for identity in delta.deletes:
                if identity not in staged:
                    raise ContractError("cannot delete a missing node")
                del staged[identity]
            self._validate(staged)
            when = timestamp(at or utcnow())
            if self._history and when < self._history[-1].at:
                raise ContractError("graph knowledge time cannot move backwards")
            change = GraphChange(
                len(self._history) + 1,
                when,
                freeze(provenance),
                MappingProxyType(before),
                MappingProxyType(
                    {identity: staged[identity] for identity in touched if identity in staged}
                ),
            )
            self._nodes = staged
            self._history.append(change)
            self._next_id = max(self._next_id, max(staged, default=0) + 1)
            return change

    def _validate_scalar(self, value: Any, slot: Slot, nodes: dict[int, Node]) -> None:
        kind = slot.value_type
        if kind in {"node", "concept", "prototype", "instance", "facet"}:
            if isinstance(value, bool) or not isinstance(value, int) or value not in nodes:
                raise ContractError(f"{slot.label} must reference an existing {kind}")
            actual = nodes[value].kind
            if kind == "prototype" and actual not in {
                "prototype",
                "process",
                "relation_type",
                "property",
            }:
                raise ContractError(f"{slot.label} requires a Prototype/Type")
            if kind in {"instance", "facet"} and actual != kind:
                raise ContractError(f"{slot.label} requires {kind}")
        elif kind == "string" and not isinstance(value, str):
            raise ContractError(f"{slot.label} requires a string")
        elif kind in {"number", "integer"} and (
            isinstance(value, bool)
            or not isinstance(value, (int, float) if kind == "number" else int)
        ):
            raise ContractError(f"{slot.label} requires {kind}")
        elif kind == "boolean" and not isinstance(value, bool):
            raise ContractError(f"{slot.label} requires boolean")

    def _validate_slot(self, value: Any, slot: Slot, nodes: dict[int, Node]) -> None:
        if value is None and slot.arity == "optional":
            return
        if slot.arity in {"list0", "list1"}:
            if not isinstance(value, (tuple, list)) or (slot.arity == "list1" and not value):
                raise ContractError(f"{slot.label} violates {slot.arity} cardinality")
            for item in value:
                self._validate_scalar(item, slot, nodes)
        else:
            self._validate_scalar(value, slot, nodes)

    def _validate(self, nodes: dict[int, Node]) -> None:
        parents: dict[int, int] = {}
        instance_types: dict[int, int] = {}
        facet_instances: dict[int, int] = {}
        relation_names = set()
        for node in nodes.values():
            if isinstance(node, RelationType):
                if node.name in relation_names:
                    raise ContractError("relation type names must be canonical and unique")
                relation_names.add(node.name)
                for slot in node.signature:
                    if slot.concept is not None and slot.concept not in nodes:
                        raise ContractError("slot concept is missing")
                self._validate_predicates(node, nodes)
            if not isinstance(node, RelationInstance):
                continue
            relation = nodes.get(node.relation_type)
            if not isinstance(relation, RelationType):
                raise ContractError("fact relation type is missing")
            labels = {slot.label for slot in relation.signature}
            if not set(node.args) <= labels:
                raise ContractError("fact contains undeclared slots")
            for slot in relation.signature:
                if slot.label not in node.args and slot.arity != "optional":
                    raise ContractError(f"missing required slot {slot.label}")
                self._validate_slot(node.args.get(slot.label), slot, nodes)
            relation_map = {
                "SUBTYPE_OF": (parents, "type", "supertype"),
                "IDENTITY_TYPE": (instance_types, "instance", "type"),
                "STATE_IDENTITY": (facet_instances, "facet", "instance"),
            }
            if relation.name in relation_map:
                mapping, child, parent = relation_map[relation.name]
                if node.args[child] in mapping:
                    raise ContractError(f"{relation.name} must have a single parent fact")
                mapping[node.args[child]] = node.args[parent]
        for child in parents:
            seen = set()
            current = child
            while current in parents:
                if current in seen:
                    raise ContractError("taxonomy cannot contain cycles")
                seen.add(current)
                current = parents[current]
        for node in nodes.values():
            if node.kind == "instance" and node.id not in instance_types:
                raise ContractError("Instance requires exactly one IDENTITY_TYPE fact")
            if node.kind == "facet" and node.id not in facet_instances:
                raise ContractError("Facet requires exactly one STATE_IDENTITY fact")

    def _validate_predicates(self, relation: RelationType, nodes: dict[int, Node]) -> None:
        slots = {slot.label: slot for slot in relation.signature}
        for view in relation.views:
            for clause in view.constraints.all if view.constraints else ():
                slot = slots.get(clause.field)
                if slot is None:
                    slot = Slot(clause.field, "string" if clause.field == "name" else "number")
                if clause.op in {"is_null", "not_null"}:
                    continue
                if clause.op in {"<", "<=", ">", ">="} and (
                    slot.value_type not in {"number", "integer", "string"}
                    or slot.arity.startswith("list")
                ):
                    raise ContractError("ordered predicates require a scalar ordered field")
                if clause.op == "contains":
                    if not slot.arity.startswith("list") and slot.value_type != "string":
                        raise ContractError("contains requires a list or string field")
                    self._validate_scalar(clause.value, slot, nodes)
                elif clause.op in {"in", "not_in"}:
                    if not isinstance(clause.value, (tuple, list, frozenset)):
                        raise ContractError("membership predicate requires a list of values")
                    for value in clause.value:
                        self._validate_slot(value, slot, nodes)
                else:
                    self._validate_slot(clause.value, slot, nodes)

    def query_view(
        self,
        relation_type: int | str,
        view_name: str,
        *,
        valid_at: datetime | None = None,
        known_at: datetime | None = None,
        **inputs: Any,
    ) -> Any:
        relation = (
            self.find(relation_type) if isinstance(relation_type, str) else self.get(relation_type)
        )
        if not isinstance(relation, RelationType):
            raise ContractError("view requires a relation type")
        view = next((item for item in relation.views if item.name == view_name), None)
        if view is None or set(inputs) != set(view.inputs):
            raise ContractError("unknown view or invalid named arguments")
        slots = {slot.label: slot for slot in relation.signature}
        inputs = {
            key: value.id if isinstance(value, Node) else value for key, value in inputs.items()
        }
        for key, value in inputs.items():
            self._validate_slot(value, slots[key], self._nodes)
        if known_at is not None:
            when = timestamp(known_at)
            if self.known_at is not None and when != self.known_at:
                return UNKNOWN
            if self.known_at is None and self._history and when < self._history[-1].at:
                return UNKNOWN
        matches = []
        for fact in self.facts(relation.id):
            if any(fact.args.get(key) != value for key, value in inputs.items()):
                continue
            if valid_at is not None:
                at = timestamp(valid_at)
                facets = [
                    self._nodes[value]
                    for label, value in fact.args.items()
                    if slots[label].value_type in {"node", "concept", "facet"}
                    and isinstance(value, int)
                    and isinstance(self._nodes.get(value), Facet)
                ]
                if any(
                    at < facet.valid_from
                    or (facet.valid_until is not None and at >= facet.valid_until)
                    for facet in facets
                ):
                    continue
            accepted = True
            for clause in view.constraints.all if view.constraints else ():
                if clause.field in slots:
                    value = fact.args.get(clause.field)
                elif clause.field in {"id", "name"}:
                    value = getattr(fact, clause.field)
                else:
                    if self.belief_reader is None or fact.belief_target is None:
                        return UNKNOWN
                    try:
                        belief = self.belief_reader(
                            fact.belief_target, valid_at=valid_at, known_at=known_at
                        )
                    except KeyError:
                        return UNKNOWN
                    if belief is UNKNOWN:
                        return UNKNOWN
                    profile = getattr(belief, "profile", None)
                    if clause.field == "strength" and profile is not None:
                        if relation.name != "CLASSIFIED_AS":
                            return UNKNOWN
                        alternative = str(fact.args["class"])
                        if alternative not in profile:
                            return UNKNOWN
                        value = profile[alternative]
                    else:
                        value = getattr(getattr(belief, "data", belief), clause.field)
                if not _compare_clause(value, clause):
                    accepted = False
                    break
            if accepted:
                values = tuple(fact.args.get(label) for label in view.outputs)
                matches.append(ViewMatch(values[0] if len(values) == 1 else values, fact))
        if (
            view.output_arity == "one"
            and len(matches) != 1
            or view.output_arity == "optional"
            and len(matches) > 1
            or view.output_arity == "list1"
            and not matches
        ):
            raise ContractError(f"view {view.name} violates {view.output_arity} cardinality")
        if view.output_arity in {"one", "optional"}:
            return matches[0] if matches else None
        return matches

    def ancestors(self, identity: int) -> tuple[Node, ...]:
        result = []
        parents = {fact.args["type"]: fact.args["supertype"] for fact in self.facts("SUBTYPE_OF")}
        while identity in parents:
            identity = parents[identity]
            result.append(self.get(identity))
        return tuple(result)

    def descendants(self, identity: int) -> tuple[Node, ...]:
        return tuple(
            node
            for node in self._nodes.values()
            if any(parent.id == identity for parent in self.ancestors(node.id))
        )

    def common_ancestor(self, first: int, second: int) -> Node | None:
        others = {second, *(node.id for node in self.ancestors(second))}
        return next(
            (node for node in (self.get(first), *self.ancestors(first)) if node.id in others), None
        )

    def close_facet_state(self, identity: int, valid_until: datetime) -> GraphDelta:
        if not isinstance(self.get(identity), Facet):
            raise ContractError("only Facet state can be closed")
        return GraphDelta(updates=(NodeUpdate(identity, {"valid_until": timestamp(valid_until)}),))

    def get_facets(
        self,
        instance: int | Node,
        *,
        valid_at: datetime | None = None,
        known_at: datetime | None = None,
    ) -> tuple[Facet, ...] | Any:
        matches = self.query_view(
            "STATE_IDENTITY", "get_facets", instance=instance, valid_at=valid_at, known_at=known_at
        )
        if matches is UNKNOWN:
            return UNKNOWN
        return tuple(self.get(match.value) for match in matches)

    def changes_of(self, identity: int) -> tuple[GraphChange, ...]:
        return tuple(
            change
            for change in self._history
            if identity in change.before or identity in change.after
        )

    def created_at(self, identity: int) -> datetime:
        return self.changes_of(identity)[0].at

    def last_changed_at(self, identity: int) -> datetime:
        return self.changes_of(identity)[-1].at

    def provenance_of(self, identity: int) -> Any:
        return self.changes_of(identity)[0].provenance

    def activate(self, identity: int, axis: str, value: float) -> None:
        self.get(identity)
        if not math.isfinite(value):
            raise ContractError("activation must be finite")
        self._activations.setdefault(identity, {})[axis] = value

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "next_id": self._next_id,
                "nodes": [_node_data(node) for node in self._nodes.values()],
                "history": [
                    {
                        "seq": change.seq,
                        "at": change.at.isoformat(),
                        "provenance": json_value(change.provenance),
                        "before": [_node_data(node) for node in change.before.values()],
                        "after": [_node_data(node) for node in change.after.values()],
                    }
                    for change in self._history
                ],
                "activations": json_value(self._activations),
                "known_at": self.known_at.isoformat() if self.known_at else None,
            }

    @classmethod
    def from_snapshot(cls, data: dict) -> GraphStore:
        store = cls()
        store._nodes = {node.id: node for node in map(_node_from_data, data["nodes"])}
        store._next_id = data["next_id"]
        store._history = [
            GraphChange(
                item["seq"],
                timestamp(item["at"]),
                freeze(restore_value(item["provenance"])),
                MappingProxyType({node.id: node for node in map(_node_from_data, item["before"])}),
                MappingProxyType({node.id: node for node in map(_node_from_data, item["after"])}),
            )
            for item in data["history"]
        ]
        store._activations = {
            int(identity): dict(values) for identity, values in data.get("activations", {}).items()
        }
        store.known_at = timestamp(data["known_at"]) if data.get("known_at") else None
        store._validate(store._nodes)
        if store._next_id <= max(store._nodes, default=0):
            raise ContractError("snapshot identity counter is invalid")
        return store

    def bootstrap(self, *, provenance: Any) -> dict[str, int]:
        if self._nodes:
            return {
                node.name: node.id
                for node in self._nodes.values()
                if not isinstance(node, RelationInstance)
            }
        definitions = [
            (
                "SUBTYPE_OF",
                (Slot("type", "prototype"), Slot("supertype", "prototype")),
                (
                    AccessView("get_supertype", ("type",), ("supertype",), "optional"),
                    AccessView("get_subtypes", ("supertype",), ("type",)),
                ),
            ),
            (
                "IDENTITY_TYPE",
                (Slot("instance", "instance"), Slot("type", "prototype")),
                (
                    AccessView("get_type", ("instance",), ("type",), "one"),
                    AccessView("get_instances", ("type",), ("instance",)),
                ),
            ),
            (
                "STATE_IDENTITY",
                (Slot("facet", "facet"), Slot("instance", "instance")),
                (
                    AccessView("get_instance", ("facet",), ("instance",), "one"),
                    AccessView("get_facets", ("instance",), ("facet",)),
                ),
            ),
            (
                "PART_WHOLE",
                (Slot("part"), Slot("whole")),
                (
                    AccessView("get_parts", ("whole",), ("part",)),
                    AccessView("get_wholes", ("part",), ("whole",)),
                ),
            ),
            (
                "HAS_NUMERIC_VALUE",
                (
                    Slot("entity"),
                    Slot("property"),
                    Slot("value", "number"),
                    Slot("unit", "string", "optional"),
                ),
                (AccessView("get_values", ("entity", "property"), ("value", "unit")),),
            ),
            (
                "CLASSIFIED_AS",
                (Slot("entity"), Slot("class")),
                (AccessView("get_classes", ("entity",), ("class",)),),
            ),
            (
                "PROGRAM_FOR_PROCESS",
                (Slot("program"), Slot("process")),
                (AccessView("get_programs", ("process",), ("program",)),),
            ),
            (
                "EVIDENCE_DEPENDS_ON",
                (Slot("dependent"), Slot("source")),
                (AccessView("get_sources", ("dependent",), ("source",)),),
            ),
        ]
        nodes = [Prototype(self.reserve_id(), "Process")]
        nodes.extend(
            RelationType(self.reserve_id(), name, signature=signature, views=views)
            for name, signature, views in definitions
        )
        self.apply(GraphDelta(creates=tuple(nodes)), provenance=provenance)
        return {node.name: node.id for node in nodes}


def _compare_clause(value: Any, clause: Clause) -> bool:
    if clause.op == "is_null":
        return value is None
    if clause.op == "not_null":
        return value is not None
    if value is None:
        return False
    operations = {
        "==": lambda: value == clause.value,
        "!=": lambda: value != clause.value,
        "in": lambda: value in clause.value,
        "not_in": lambda: value not in clause.value,
        "<": lambda: value < clause.value,
        "<=": lambda: value <= clause.value,
        ">": lambda: value > clause.value,
        ">=": lambda: value >= clause.value,
        "contains": lambda: clause.value in value,
    }
    try:
        return operations[clause.op]()
    except TypeError as exc:
        raise ContractError("predicate is incompatible with field type") from exc
