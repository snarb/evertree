"""Semantic graph tool catalog shared by Programs and Core, and schema checks of their actions."""

from evertree.common.structured import validate
from evertree.core.graph.types import ARITIES, VALUE_TYPES
from evertree.core.provider import ToolDefinition
from evertree.core.values import ContractError


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


READ_TOOLS = (
    ToolDefinition(
        "search",
        (
            "Find one object or reusable meaning by name or description. Exact names resolve "
            "first; otherwise lexical and semantic similarity return up to 20 candidates, not proven matches. Refine the query if none fits; no pagination."
        ),
        _object(
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
        read_only=True,
    ),
    ToolDefinition(
        "describe",
        (
            "Read an object, its relation schema and known assertions. Follow returned IDs: "
            "STATE_IDENTITY connects a Facet to its Instance; IDENTITY_TYPE connects an Instance "
            "to its Prototype; SUBTYPE_OF connects a class to its broader parent. "
            "An Instance's description also lists linked Facets. "
            "Default previews contain up to 7 properties and 7 relations; properties_total/"
            "relations_total precede truncated lists. focus=properties or relations returns "
            "that full list. A Prototype's parent is one card or null; children lists up to 7 "
            "direct subtype names, preceded by children_total only when shortened."
        ),
        _read_object(
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
        read_only=True,
    ),
    ToolDefinition(
        "query",
        "Find facts by named slots or all facts involving subject. Bind any subset of roles, select values or unique nodes. List reads report total before returning a token-bounded page. Counts return exact totals in one call; exists stops at a definite match and returns true/false/null without totals. Keep source facts and qualifications; a match is not proof.",
        _read_object(
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
        read_only=True,
    ),
    ToolDefinition(
        "walk",
        "Follow one relation from a named node slot to another, breadth-first without cycles. SUBTYPE_OF supertype→type finds descendants; reverse finds ancestors. Returns unique nodes, depth and supporting facts, with total and token-bounded pages. Counts return exact totals in one call; exists stops at a definite match and returns true/false/null without totals.",
        _read_object(
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
        read_only=True,
    ),
    ToolDefinition(
        "read_property",
        "Read a discovered property, including computed/parameterized values. Preserve uncertainty and grounds; missing parameters are reported.",
        _read_object(
            {
                "subject": {"type": ["integer", "string"]},
                "property": {"type": ["integer", "string"]},
                "at": _OPTIONAL_TEXT,
                "parameters": {"type": ["object", "null"]},
            },
            ("subject", "property"),
        ),
        read_only=True,
    ),
)

WRITE_TOOLS = (
    ToolDefinition(
        "create_concept",
        "Save a useful distinction not expressed by an existing concept.",
        _object({**_NAMED, "name": {**_TEXT, "description": "Unique canonical name, 1–3 words."}}),
        read_only=False,
    ),
    ToolDefinition(
        "create_prototype",
        (
            "Save a class under its nearest justified broader class. Create a missing parent "
            "first; only a broad root or an unclassifiable concept uses parent=null. "
            "Declaring the class does not assert typical properties."
        ),
        _object(
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
        read_only=False,
    ),
    ToolDefinition(
        "create_instance",
        "Save one identifiable object and its class membership.",
        _object({**_NAMED, "prototype": _ID}),
        read_only=False,
    ),
    ToolDefinition(
        "create_facet",
        "Save a changing aspect of an object, with known or unknown time bounds.",
        _object(
            {
                **_NAMED,
                "instance": _ID,
                "valid_from": _STATE_START,
                "valid_until": _STATE_END,
            }
        ),
        read_only=False,
    ),
    ToolDefinition(
        "define_relation",
        (
            "Save a reusable predicate with named roles. Name and definition must agree. "
            "Generalize across subjects without merging different or opposite assertions; "
            "use distinct predicates or an explicit distinguishing role where needed."
        ),
        _object(
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
        read_only=False,
    ),
    ToolDefinition(
        "relate",
        (
            "Save an assertion using an existing relation type whose predicate fits. "
            "Preserve direction, conditions and meaningful distinctions in roles/values; "
            "the description must not negate or repair the type's meaning. Reject a type "
            "combining incompatible meanings without a role distinguishing them; define "
            "a fitting schema instead."
        ),
        _object(
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
        read_only=False,
    ),
    ToolDefinition(
        "create_claim",
        (
            "Save one independently revisable prose assertion with its conditions and grounds. "
            "Assertions that evidence could confirm, reject or correct separately need separate "
            "representations, including alternative explanations. Keep a hypothesis's necessary "
            "conditions and supporting argument together; it remains provisional. Do not bundle a source's "
            "objects, state intervals or simple relationships into a summary Claim. "
            "A missing relation schema can be defined with define_relation. "
            "Saving a Claim does not assess evidence or assign confidence."
        ),
        _object(
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
        read_only=False,
    ),
    ToolDefinition(
        "save_note",
        (
            "Copy source text worth retrieving as a self-contained whole for its wording or "
            "reasoning. Use selectively: ordinarily extract reusable graph knowledge. "
            "Copies analytical text or strings verbatim; other structured sources become JSON."
        ),
        _object(
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
        read_only=False,
    ),
    ToolDefinition(
        "update",
        "Update selected fields of an existing object, preserving history and sources.",
        _object(
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
        read_only=False,
    ),
    ToolDefinition(
        "delete",
        "Remove selected objects from the current graph, preserving history. No cascading deletion.",
        _object(
            {
                "objects": {"type": "array", "items": _ID, "minItems": 1},
                "sources": _SOURCES,
            }
        ),
        read_only=False,
    ),
)

TOOLS = READ_TOOLS + WRITE_TOOLS
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}
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
    """Check an action against its tool schema; raises ValueError (ContractError) if invalid."""
    if not isinstance(action, dict) or action.get("action") not in TOOLS_BY_NAME:
        raise ContractError("Unknown semantic action")
    validate(
        {key: value for key, value in action.items() if key != "action"},
        TOOLS_BY_NAME[action["action"]].input_schema,
    )
    if action["action"] == "relate":
        # The schema allows any JSON in values; relation values must be scalars or scalar lists.
        for field in ("arguments", "conditions"):
            for item in action[field]:
                value = item["value"]
                for part in value if isinstance(value, list) else [value]:
                    validate(part, _SCALAR)
