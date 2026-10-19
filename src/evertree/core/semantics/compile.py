"""Compilation of one checked semantic write action into a graph delta."""

import dataclasses
import json

from evertree.core.graph.types import GraphDelta, NodeUpdate, RelationInstance, node_from_dict
from evertree.core.values import ContractError, json_value

from .tools import CREATE_ACTIONS, validate_action

_NODE_CREATES = CREATE_ACTIONS - {
    "define_relation",
    "create_property",
    "create_property_reference",
    "create_qualitative_property",
    "save_property_result",
}


class _DeltaBuilder:
    """Collects the nodes one action creates, allocating permanent IDs as it goes."""

    def __init__(self, graph):
        self.graph = graph
        self.creates = []

    def node(self, **fields):
        """Allocate a node in the pending delta and return its ID without applying the delta."""
        node = node_from_dict({"id": self.graph.reserve_id(), **fields})
        self.creates.append(node)
        return node.id

    def fact(self, relation, args, description=None, conditions=None, criterion=None):
        """Create a relation instance of the `relation` type."""
        return self.node(
            name=relation.name,
            kind="relation_instance",
            relation_type=relation.id,
            args=args,
            description=description,
            properties={
                **({"conditions": conditions} if conditions else {}),
                **({"criterion": criterion} if criterion is not None else {}),
            },
        )

    def relation_type(self, subject):
        """Resolve an existing relation type by name or ID."""
        node = self.graph.find(subject) if isinstance(subject, str) else self.graph.get(subject)
        if node is None or node.kind != "relation_type":
            raise ContractError("Expected an existing relation type")
        return node

    def result(self, identity):
        """Package the pending graph delta with the operation's returned semantic identity."""
        return GraphDelta(creates=tuple(self.creates)), identity


def _compile_update(graph, action, material):
    node = graph.get(action["object"])
    changes = action["changes"]
    protected = {"qualitative_norm", "norm_state"}
    if (protected & node.properties.keys() and "properties" in changes) or (
        isinstance(changes.get("properties"), dict) and protected & changes["properties"].keys()
    ):
        raise ContractError("Learned norms must be revised through revise_property_norm")
    allowed = {field.name for field in dataclasses.fields(node)} - {"id", "kind", "belief_target"}
    if not changes or changes.keys() - allowed:
        raise ContractError("Update requires nonempty mutable fields of this object type")
    # Qualifications also live in descriptions and relation definitions, not just args.
    if (isinstance(node, RelationInstance) and node.belief_target) or (
        node.kind == "relation_type" and any(fact.belief_target for fact in graph.facts(node.id))
    ):
        raise ContractError("Changing assessed evidence requires evidence assessment")
    # The typed constructor also validates complete replacement schemas and intervals.
    updated = node_from_dict({**json_value(node), **changes})
    update = NodeUpdate(node.id, {key: getattr(updated, key) for key in changes})
    return GraphDelta(updates=(update,)), node.id


def _compile_delete(graph, action, material):
    ids = action["objects"]
    if len(set(ids)) != len(ids):
        raise ContractError("Delete identities must be distinct")
    for identity in ids:
        node = graph.get(identity)
        if isinstance(node, RelationInstance) and node.belief_target:
            raise ContractError("Removing assessed evidence requires evidence assessment")
    return GraphDelta(deletes=tuple(ids)), None


def _compile_node(graph, action, material):
    """Concept, prototype, instance, facet or claim; the first three link it to its context."""
    builder = _DeltaBuilder(graph)
    kind = action["action"].removeprefix("create_")
    fields = {"name": action["name"], "description": action["description"], "kind": kind}
    if kind == "facet":
        fields.update(valid_from=action["valid_from"], valid_until=action["valid_until"])
    identity = builder.node(**fields)
    if kind == "instance":
        link = builder.relation_type("IDENTITY_TYPE")
        builder.fact(link, {"instance": identity, "type": action["prototype"]})
    elif kind == "facet":
        link = builder.relation_type("STATE_IDENTITY")
        builder.fact(link, {"facet": identity, "instance": action["instance"]})
    elif kind == "prototype" and action["parent"] is not None:
        link = builder.relation_type("SUBTYPE_OF")
        builder.fact(link, {"type": identity, "supertype": action["parent"]})
    return builder.result(identity)


def _compile_relation_type(graph, action, material):
    builder = _DeltaBuilder(graph)
    roles = action["roles"]
    labels = [role["label"] for role in roles]
    identity = builder.node(
        kind="relation_type",
        name=action["name"],
        description=action["description"],
        signature=roles,
        # One lookup view per role: given every other role, list the values of this one.
        views=[
            {
                "name": "get_" + label,
                "inputs": [other for other in labels if other != label],
                "outputs": [label],
                "output_arity": "list0",
            }
            for label in labels
        ],
    )
    return builder.result(identity)


def _compile_property(graph, action, material):
    builder = _DeltaBuilder(graph)
    scale = action.get("scale", "numeric")
    definition = {
        "scale": scale,
        "source": action.get(
            "source", "classification" if scale in {"nominal", "ordinal"} else "numeric"
        ),
        "unit": action["unit"],
        "applies_to": action["applies_to"],
        **{
            key: action[key]
            for key in (
                "classes",
                "period",
                "required_parameters",
                "parameter_types",
                "selection",
                "relation_type",
                "view",
                "subject_slot",
                "program",
            )
            if key in action
        },
    }
    identity = builder.node(
        kind="property",
        name=action["name"],
        description=action["description"],
        properties={"attribution": definition},
    )
    return builder.result(identity)


def _compile_result(graph, action, material):
    builder = _DeltaBuilder(graph)
    identity = builder.node(
        kind="concept",
        name=action["name"],
        description=action["description"],
        properties={
            "attribution_result": {
                key: action[key]
                for key in (
                    "subject",
                    "property",
                    "conditions",
                    "value_U",
                    "unit",
                    "valid_from",
                    "valid_until",
                )
                if key in action
            }
        },
    )
    return builder.result(identity)


def _compile_property_reference(graph, action, material):
    builder = _DeltaBuilder(graph)
    reference = {
        key: action[key]
        for key in (
            "property",
            "domain",
            "unit",
            "reference_kind",
            "boundaries",
            "classes",
            "samples",
            "conditions",
        )
    }
    reference["boundary_inclusive"] = action.get(
        "boundary_inclusive", [True] * len(action["boundaries"])
    )
    identity = builder.node(
        kind="concept",
        name=action["name"],
        description=action["description"],
        properties={"numeric_reference": reference},
    )
    return builder.result(identity)


def _compile_relate(graph, action, material):
    builder = _DeltaBuilder(graph)
    arguments = {item["role"]: item["value"] for item in action["arguments"]}
    conditions = {item["parameter"]: item["value"] for item in action["conditions"]}
    if len(arguments) != len(action["arguments"]) or len(conditions) != len(action["conditions"]):
        raise ContractError("Relation roles and conditions must be distinct")
    relation = builder.relation_type(action["relation"])
    identity = builder.fact(
        relation, arguments, action["description"], conditions, action.get("criterion")
    )
    return builder.result(identity)


def _note_text(item, ref):
    """Note body: trusted analytical text verbatim, other strings verbatim, the rest as JSON."""
    value, origin = item["content"], item["origin"]
    analytical = origin["operator"] == "analytical_note" and origin["output_type"].endswith(
        ".AnalyticalNote"
    )
    fragment = (
        origin["program"] == "ExperienceFragments"
        and origin["operator"] == "experience_fragment"
        and isinstance(value, dict)
        and value.get("encoding") == "analytical_text"
    )
    # Unwrap {"text": ...} only for a whole trusted output, never for a nested path inside it.
    if not ref.get("output_path") and (analytical or fragment):
        return value["text"]
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)


def _compile_note(graph, action, material):
    builder = _DeltaBuilder(graph)
    ref = action["source"]
    item = next(item for item in material["experience"] if item["reference"] == ref)
    identity = builder.node(
        kind="note",
        name=action["name"],
        description=_note_text(item, ref),
        properties={"source_ref": ref},
    )
    return builder.result(identity)


_COMPILERS = {
    "update": _compile_update,
    "delete": _compile_delete,
    "define_relation": _compile_relation_type,
    "create_property": _compile_property,
    "create_property_reference": _compile_property_reference,
    "save_property_result": _compile_result,
    "relate": _compile_relate,
    "save_note": _compile_note,
    **dict.fromkeys(_NODE_CREATES, _compile_node),
}


def compile_action(graph, action, material, *, attribution=None):
    """Compile one write action into a GraphDelta and the affected object's ID (None for delete).

    Runs inside the caller's single-operation transaction, so reserved IDs are never leaked.
    """
    validate_action(action)
    if action["action"] in {"create_qualitative_property", "revise_property_norm"}:
        from ..attribution_norms import prepare_norm, revise_norm

        if attribution is None:
            raise ContractError("Norm fitting requires the shared Attribution Runtime")
        definition = {
            key: action[key]
            for key in (
                "property",
                "domain",
                "classes",
                "conditions",
                "quantiles",
                "reference",
                "min_samples",
                "hysteresis",
            )
            if key in action
        }
        if action["action"] == "create_qualitative_property":
            return prepare_norm(attribution, action["name"], action["description"], definition)
        return revise_norm(attribution, action["object"], definition), action["object"]
    compiler = _COMPILERS.get(action["action"])
    if compiler is None:
        raise ContractError("Expected a graph write action")
    return compiler(graph, action, material)
