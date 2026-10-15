"""Shared semantic action schemas and compilation of one checked graph operation."""

import dataclasses
import json

from evertree.common.structured import validate
from evertree.core.graph.types import (
    ARITIES,
    VALUE_TYPES,
    GraphDelta,
    NodeUpdate,
    RelationInstance,
    node_from_dict,
)
from evertree.core.provider import ToolDefinition
from evertree.core.values import ContractError, json_value


def _object(properties):
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


_TEXT = {"type": "string", "minLength": 1}
_ID = {"type": "integer", "minimum": 1}
_OPTIONAL_TEXT = {"type": ["string", "null"]}
_STATE_START = {
    **_OPTIONAL_TEXT,
    "description": "Inclusive start: ISO 8601 datetime with timezone, or null if unknown.",
}
_STATE_END = {
    **_OPTIONAL_TEXT,
    "description": (
        "Exclusive end: ISO 8601 datetime with timezone, or null if unknown, not infinite. "
        "When both boundaries are known, end must follow start."
    ),
}
_REFERENCE = _object(
    {
        "event_ref": {"type": "integer", "minimum": 1},
        "output_path": {
            "type": "array",
            "items": {"type": ["string", "integer"]},
            "description": (
                "Use the supplied path unchanged for plain text. Extend only with actual "
                "object keys or array indices, never paragraph numbers or character positions."
            ),
        },
    }
)
_SOURCES = {"type": "array", "items": _REFERENCE, "minItems": 1}
_NAMED = {"name": _TEXT, "description": _OPTIONAL_TEXT, "sources": _SOURCES}
_SCALAR = {"type": ["string", "number", "boolean", "null"]}
_VALUE = {"anyOf": [_SCALAR, {"type": "array", "items": _SCALAR}]}


TOOLS = (
    {
        "name": "search",
        "description": (
            "Find one object or reusable meaning by name or description. Exact names resolve "
            "first; otherwise lexical and semantic similarity return candidates, not proven matches."
        ),
        "parameters": _object(
            {
                "query": {
                    **_TEXT,
                    "description": (
                        "One name or focused phrase, e.g. 'Н-1' or 'pump operating state'. "
                        "Search different subjects separately. Do not append graph types or "
                        "field names such as prototype, facet or valid_from as search keywords: "
                        "they are not filters."
                    ),
                },
                "next_page": {"type": "boolean"},
            }
        ),
        "read_only": True,
    },
    {
        "name": "describe",
        "description": (
            "Read an object, its relation schema and known assertions. Follow returned IDs: "
            "STATE_IDENTITY connects a Facet to its Instance; IDENTITY_TYPE connects an Instance "
            "to its Prototype; SUBTYPE_OF connects a class to its broader parent. "
            "An Instance's description also lists linked Facets. "
            "relations_truncated means some links were omitted."
        ),
        "parameters": _object({"subject": {"type": ["integer", "string"]}}),
        "read_only": True,
    },
    {
        "name": "create_concept",
        "description": "Save a useful distinction not expressed by an existing concept.",
        "parameters": _object(
            {**_NAMED, "name": {**_TEXT, "description": "Unique canonical name, 1–3 words."}}
        ),
        "read_only": False,
    },
    {
        "name": "create_prototype",
        "description": (
            "Save a class under its nearest justified broader class. Create a missing parent "
            "first; only a broad root or an unclassifiable concept uses parent=null. "
            "Declaring the class does not assert typical properties."
        ),
        "parameters": _object(
            {
                **_NAMED,
                "name": {**_TEXT, "description": "Unique canonical class name, 1–3 words."},
                "parent": {
                    "type": ["integer", "null"],
                    "description": (
                        "ID of the nearest justified broader class (is-a). Reuse it or create "
                        "it first. Null is for a broad root or an unjustified classification, "
                        "not merely because the parent is absent from the graph."
                    ),
                },
            }
        ),
        "read_only": False,
    },
    {
        "name": "create_instance",
        "description": "Save one identifiable object and its class membership.",
        "parameters": _object({**_NAMED, "prototype": _ID}),
        "read_only": False,
    },
    {
        "name": "create_facet",
        "description": "Save a changing aspect of an object, with known or unknown time bounds.",
        "parameters": _object(
            {
                **_NAMED,
                "instance": _ID,
                "valid_from": _STATE_START,
                "valid_until": _STATE_END,
            }
        ),
        "read_only": False,
    },
    {
        "name": "define_relation",
        "description": "Save a relation type with meaningful participant roles.",
        "parameters": _object(
            {
                **_NAMED,
                "roles": {
                    "type": "array",
                    "minItems": 1,
                    "items": _object(
                        {
                            "label": {
                                **_TEXT,
                                "description": (
                                    "Unique Python identifier; valid_at and known_at are reserved."
                                ),
                            },
                            "value_type": {
                                "type": "string",
                                "enum": sorted(VALUE_TYPES),
                                "description": (
                                    "node/concept accept any graph object's integer ID; prototype "
                                    "accepts class schemas, including processes, relation types and "
                                    "properties; instance/facet require that kind's ID. Other types "
                                    "are literal values; any accepts a scalar, including null."
                                ),
                            },
                            "arity": {
                                "type": "string",
                                "enum": sorted(ARITIES),
                                "description": (
                                    "one: a single value; optional: omit the role or pass null; "
                                    "list0: an array, possibly empty; list1: a nonempty array."
                                ),
                            },
                        }
                    ),
                },
            }
        ),
        "read_only": False,
    },
    {
        "name": "relate",
        "description": "Save an assertion using an existing relation type.",
        "parameters": _object(
            {
                "relation": _ID,
                "arguments": {
                    "type": "array",
                    "description": (
                        "One entry per supplied role, using its exact declared label. Only optional "
                        "roles may be omitted. Node values are returned integer IDs; list roles use "
                        "one array value, not repeated entries."
                    ),
                    "items": _object({"role": _TEXT, "value": _VALUE}),
                },
                "conditions": {
                    "type": "array",
                    "description": "Conditions under which the assertion applies, with unique names.",
                    "items": _object({"parameter": _TEXT, "value": _VALUE}),
                },
                "description": _OPTIONAL_TEXT,
                "sources": _SOURCES,
            }
        ),
        "read_only": False,
    },
    {
        "name": "create_claim",
        "description": (
            "Save one independently checkable prose assertion, including its scope and "
            "qualifications; a hypothesis remains provisional. Do not bundle a source's "
            "objects, state intervals or simple relationships into a summary Claim. "
            "A missing relation schema can be defined with define_relation. "
            "Saving a Claim does not assess evidence or assign confidence."
        ),
        "parameters": _object(
            {
                **_NAMED,
                "description": {
                    **_TEXT,
                    "description": (
                        "Self-contained assertion, including the conditions and uncertainty "
                        "needed to understand and check it independently of its source text."
                    ),
                },
            }
        ),
        "read_only": False,
    },
    {
        "name": "save_note",
        "description": (
            "Copy source text worth retrieving as a self-contained whole for its wording or "
            "reasoning. Use selectively: ordinarily extract reusable graph knowledge. "
            "Copies analytical text or strings verbatim; other structured sources become JSON."
        ),
        "parameters": _object(
            {
                "name": _TEXT,
                "source": {
                    **_REFERENCE,
                    "description": "Source to copy; automatically included among this Note's grounds.",
                },
                "sources": {
                    "type": "array",
                    "items": _REFERENCE,
                    "description": "Additional grounds, or [] when the copied source is sufficient.",
                },
            }
        ),
        "read_only": False,
    },
    {
        "name": "update",
        "description": "Update selected fields of an existing object, preserving history and sources.",
        "parameters": _object(
            {
                "object": _ID,
                "changes": {
                    "type": "object",
                    "description": "Fields to replace; omitted fields stay unchanged. Nested values replace the complete field.",
                    "properties": {
                        "name": _TEXT,
                        "description": _OPTIONAL_TEXT,
                        "properties": {"type": "object"},
                        "valid_from": _STATE_START,
                        "valid_until": _STATE_END,
                        "relation_type": _ID,
                        "args": {"type": "object"},
                        "signature": {"type": "array", "items": {"type": "object"}},
                        "views": {"type": "array", "items": {"type": "object"}},
                    },
                    "additionalProperties": False,
                },
                "sources": _SOURCES,
            }
        ),
        "read_only": False,
    },
    {
        "name": "delete",
        "description": "Remove selected objects from the current graph, preserving history. No cascading deletion.",
        "parameters": _object(
            {
                "objects": {"type": "array", "items": _ID, "minItems": 1},
                "sources": _SOURCES,
            }
        ),
        "read_only": False,
    },
)

TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}

INTEGRATION_TOOLS = tuple(
    ToolDefinition(
        tool["name"], tool["description"], tool["parameters"], read_only=tool["read_only"]
    )
    for tool in TOOLS
)

WRITE_TOOLS = tuple(tool for tool in INTEGRATION_TOOLS if not tool.read_only)
CREATE_ACTIONS = frozenset(
    {
        "create_concept",
        "create_prototype",
        "create_instance",
        "create_facet",
        "create_claim",
        "define_relation",
    }
)


def validate_action(action):
    if not isinstance(action, dict) or action.get("action") not in TOOLS_BY_NAME:
        raise ContractError("Unknown semantic action")
    validate(
        {key: value for key, value in action.items() if key != "action"},
        TOOLS_BY_NAME[action["action"]]["parameters"],
    )
    if action["action"] == "relate":
        for field in ("arguments", "conditions"):
            for item in action[field]:
                value = item["value"]
                for part in value if isinstance(value, list) else [value]:
                    validate(part, _SCALAR)


def compile_action(graph, action, material):
    """Allocate permanent identities inside the caller's single-operation transaction."""
    validate_action(action)
    name = action["action"]
    creates = []

    def create(**fields):
        node = node_from_dict({"id": graph.reserve_id(), **fields})
        creates.append(node)
        return node.id

    def fact(relation, args, description=None, conditions=None):
        return create(
            name=relation.name,
            kind="relation_instance",
            relation_type=relation.id,
            args=args,
            description=description,
            properties={"conditions": conditions} if conditions else {},
        )

    def schema(subject):
        node = graph.find(subject) if isinstance(subject, str) else graph.get(subject)
        if node is None or node.kind != "relation_type":
            raise ContractError("Expected an existing relation type")
        return node

    if name == "update":
        node = graph.get(action["object"])
        changes = action["changes"]
        allowed = {field.name for field in dataclasses.fields(node)} - {
            "id",
            "kind",
            "belief_target",
        }
        if not changes or changes.keys() - allowed:
            raise ContractError("Update requires nonempty mutable fields of this object type")
        # Qualifications also live in descriptions and relation definitions, not just args.
        if (isinstance(node, RelationInstance) and node.belief_target) or (
            node.kind == "relation_type"
            and any(fact.belief_target for fact in graph.facts(node.id))
        ):
            raise ContractError("Changing assessed evidence requires evidence assessment")
        # The typed constructor also validates complete replacement schemas and intervals.
        updated = node_from_dict({**json_value(node), **changes})
        return GraphDelta(
            updates=(NodeUpdate(node.id, {k: getattr(updated, k) for k in changes}),)
        ), node.id
    if name == "delete":
        ids = action["objects"]
        if len(set(ids)) != len(ids):
            raise ContractError("Delete identities must be distinct")
        for identity in ids:
            node = graph.get(identity)
            if isinstance(node, RelationInstance) and node.belief_target:
                raise ContractError("Removing assessed evidence requires evidence assessment")
        return GraphDelta(deletes=tuple(ids)), None
    if name in {
        "create_concept",
        "create_prototype",
        "create_instance",
        "create_facet",
        "create_claim",
    }:
        kind = name.removeprefix("create_")
        fields = {"name": action["name"], "description": action["description"], "kind": kind}
        if kind == "facet":
            fields.update(valid_from=action["valid_from"], valid_until=action["valid_until"])
        identity = create(**fields)
        if kind == "instance":
            fact(schema("IDENTITY_TYPE"), {"instance": identity, "type": action["prototype"]})
        elif kind == "facet":
            fact(schema("STATE_IDENTITY"), {"facet": identity, "instance": action["instance"]})
        elif kind == "prototype" and action["parent"] is not None:
            fact(schema("SUBTYPE_OF"), {"type": identity, "supertype": action["parent"]})
    elif name == "define_relation":
        roles = action["roles"]
        labels = [role["label"] for role in roles]
        identity = create(
            kind="relation_type",
            name=action["name"],
            description=action["description"],
            signature=roles,
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
    elif name == "relate":
        arguments = {item["role"]: item["value"] for item in action["arguments"]}
        conditions = {item["parameter"]: item["value"] for item in action["conditions"]}
        if len(arguments) != len(action["arguments"]) or len(conditions) != len(
            action["conditions"]
        ):
            raise ContractError("Relation roles and conditions must be distinct")
        identity = fact(schema(action["relation"]), arguments, action["description"], conditions)
    elif name == "save_note":
        ref = action["source"]
        item = next(item for item in material["experience"] if item["reference"] == ref)
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
        if not ref.get("output_path") and (analytical or fragment):
            text = value["text"]
        else:
            text = (
                value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
            )
        identity = create(
            kind="note", name=action["name"], description=text, properties={"source_ref": ref}
        )
    else:
        raise ContractError("Expected a graph write action")
    return GraphDelta(creates=tuple(creates)), identity
