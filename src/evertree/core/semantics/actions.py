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
    """Strict JSON-schema object: every listed property is required, no extras."""
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


def _read_object(properties, required=()):
    return {**_object(properties), "required": list(required)}


_QUERY_COMMON = {
    "relation": {"type": ["integer", "string", "null"]},
    "where": {
        "type": ["array", "null"],
        "description": "AND filters. Fields: args.<slot>, conditions.<parameter>, fact.id or fact.name. Conditions are recorded qualifications, not verified world conditions.",
        "items": _read_object(
            {
                "field": _TEXT,
                "op": {
                    "type": "string",
                    "enum": [
                        "==",
                        "!=",
                        "in",
                        "not_in",
                        "<",
                        "<=",
                        ">",
                        ">=",
                        "contains",
                        "is_null",
                        "not_null",
                    ],
                },
                "value": _VALUE,
            },
            ("field", "op"),
        ),
    },
    "fields": {
        "type": ["array", "null"],
        "items": {"type": "string", "enum": ["description", "properties", "schema"]},
        "description": "Extra node-card fields; defaults to description. [] gives id/name/kind and state boundaries. Properties never trigger computation.",
    },
    "at": {
        **_OPTIONAL_TEXT,
        "description": "World-time ISO timestamp; omit/null for no temporal filter.",
    },
    "max_items": {
        "type": ["integer", "null"],
        "minimum": 1,
        "description": "Optional item ceiling, defaults to configured 600. Runtime token budget may return fewer.",
    },
    "next_page": {
        "type": ["boolean", "null"],
        "description": "True continues this task's latest query/walk of the same tool; optionally change max_items. To continue an earlier selection, repeat its original filters/fields with next_page=true. Omit/false starts a fresh read. Runtime stores cursors privately.",
    },
}


TOOLS = (
    {
        "name": "search",
        "description": (
            "Find one object or reusable meaning by name or description. Exact names resolve "
            "first; otherwise lexical and semantic similarity return up to 20 candidates, not proven matches. Refine the query if none fits; no pagination."
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
            "Default previews contain up to 7 properties and 7 relations; properties_total/"
            "relations_total precede truncated lists. focus=properties or relations returns "
            "that full list. A Prototype's parent is one card or null; children lists up to 7 "
            "direct subtype names, preceded by children_total only when shortened."
        ),
        "parameters": _read_object(
            {
                "subject": {"type": ["integer", "string"]},
                "focus": {
                    **_OPTIONAL_TEXT,
                    "description": "properties: all properties only; relations: all relations only. Other text filters both lists, with at most 7 relations and all matching properties.",
                },
                "at": _OPTIONAL_TEXT,
            },
            ("subject",),
        ),
        "read_only": True,
    },
    {
        "name": "query",
        "description": "Find facts by named slots or all facts involving subject. Bind any subset of roles, select values or unique nodes. Reports total before returning a token-bounded page. Keep source facts and qualifications; a match is not proof. Count/exists modes avoid loading cards.",
        "parameters": _read_object(
            {
                **_QUERY_COMMON,
                "subject": {
                    "type": ["integer", "null"],
                    "description": "Find this node in any node-valued slot, including lists. Supply relation or subject.",
                },
                "bindings": {
                    "type": ["array", "null"],
                    "items": _object({"slot": _TEXT, "value": _VALUE}),
                    "description": "Exact values for any subset of declared slots. Use where/contains for list membership.",
                },
                "select": {
                    "type": ["array", "null"],
                    "items": _TEXT,
                    "description": "Returned slot labels. Omit for all arguments; nodes/count_nodes require exactly one node-valued slot.",
                },
                "result": {
                    "type": ["string", "null"],
                    "enum": ["matches", "nodes", "count_matches", "count_nodes", "exists", None],
                    "description": "Default matches. Node counts deduplicate node IDs; match counts count facts.",
                },
            }
        ),
        "read_only": True,
    },
    {
        "name": "walk",
        "description": "Follow one relation from a named node slot to another, breadth-first without cycles. SUBTYPE_OF supertype→type finds descendants; reverse finds ancestors. Returns unique nodes, depth and supporting facts, with total and token-bounded pages.",
        "parameters": _read_object(
            {
                **_QUERY_COMMON,
                "start": {"type": ["integer", "null"]},
                "from_slot": _OPTIONAL_TEXT,
                "to_slot": _OPTIONAL_TEXT,
                "max_depth": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "description": "Default 1; null explicitly requests all reachable levels.",
                },
                "result": {
                    "type": ["string", "null"],
                    "enum": ["nodes", "count_nodes", "exists", None],
                },
            }
        ),
        "read_only": True,
    },
    {
        "name": "read_property",
        "description": "Read a discovered property, including computed/parameterized values. Preserve uncertainty and grounds; missing parameters are reported.",
        "parameters": _read_object(
            {
                "subject": {"type": ["integer", "string"]},
                "property": {"type": ["integer", "string"]},
                "at": _OPTIONAL_TEXT,
                "parameters": {"type": ["object", "null"]},
            },
            ("subject", "property"),
        ),
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
        "description": (
            "Save a reusable predicate with named roles. Name and definition must agree. "
            "Generalize across subjects without merging different or opposite assertions; "
            "use distinct predicates or an explicit distinguishing role where needed."
        ),
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
        "description": (
            "Save an assertion using an existing relation type whose predicate fits. "
            "Preserve direction, conditions and meaningful distinctions in roles/values; "
            "the description must not negate or repair the type's meaning. Reject a type "
            "combining incompatible meanings without a role distinguishing them; define "
            "a fitting schema instead."
        ),
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
            "Save one independently revisable prose assertion with its conditions and grounds. "
            "Assertions that evidence could confirm, reject or correct separately need separate "
            "representations, including alternative explanations. Keep a hypothesis's necessary "
            "conditions and supporting argument together; it remains provisional. Do not bundle a source's "
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
# Actions that create one plain node (plus an optional link fact), unlike define_relation.
_NODE_CREATES = CREATE_ACTIONS - {"define_relation"}


def validate_action(action):
    """Check an action against its tool schema; raises ValueError (ContractError) if invalid."""
    if not isinstance(action, dict) or action.get("action") not in TOOLS_BY_NAME:
        raise ContractError("Unknown semantic action")
    validate(
        {key: value for key, value in action.items() if key != "action"},
        TOOLS_BY_NAME[action["action"]]["parameters"],
    )
    if action["action"] == "relate":
        # The schema allows any JSON in values; relation values must be scalars or scalar lists.
        for field in ("arguments", "conditions"):
            for item in action[field]:
                value = item["value"]
                for part in value if isinstance(value, list) else [value]:
                    validate(part, _SCALAR)


class _DeltaBuilder:
    """Collects the nodes one action creates, allocating permanent IDs as it goes."""

    def __init__(self, graph):
        self.graph = graph
        self.creates = []

    def node(self, **fields):
        node = node_from_dict({"id": self.graph.reserve_id(), **fields})
        self.creates.append(node)
        return node.id

    def fact(self, relation, args, description=None, conditions=None):
        """Create a relation instance of the `relation` type."""
        return self.node(
            name=relation.name,
            kind="relation_instance",
            relation_type=relation.id,
            args=args,
            description=description,
            properties={"conditions": conditions} if conditions else {},
        )

    def relation_type(self, subject):
        """Resolve an existing relation type by name or ID."""
        node = self.graph.find(subject) if isinstance(subject, str) else self.graph.get(subject)
        if node is None or node.kind != "relation_type":
            raise ContractError("Expected an existing relation type")
        return node

    def result(self, identity):
        return GraphDelta(creates=tuple(self.creates)), identity


def _compile_update(graph, action, material):
    node = graph.get(action["object"])
    changes = action["changes"]
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


def _compile_relate(graph, action, material):
    builder = _DeltaBuilder(graph)
    arguments = {item["role"]: item["value"] for item in action["arguments"]}
    conditions = {item["parameter"]: item["value"] for item in action["conditions"]}
    if len(arguments) != len(action["arguments"]) or len(conditions) != len(action["conditions"]):
        raise ContractError("Relation roles and conditions must be distinct")
    relation = builder.relation_type(action["relation"])
    identity = builder.fact(relation, arguments, action["description"], conditions)
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
    "relate": _compile_relate,
    "save_note": _compile_note,
    **dict.fromkeys(_NODE_CREATES, _compile_node),
}


def compile_action(graph, action, material):
    """Compile one write action into a GraphDelta and the affected object's ID (None for delete).

    Runs inside the caller's single-operation transaction, so reserved IDs are never leaked.
    """
    validate_action(action)
    compiler = _COMPILERS.get(action["action"])
    if compiler is None:
        raise ContractError("Expected a graph write action")
    return compiler(graph, action, material)
