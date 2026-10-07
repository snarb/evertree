"""Validated graph identities, relations, access-view contracts and deltas."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ..values import ContractError, freeze, json_value, restore_value, timestamp, utcnow


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
