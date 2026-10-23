"""Semantic graph tool catalog shared by Programs and Core, and schema checks of their actions."""

from evertree.common.structured import validate
from evertree.core.graph.types import ARITIES, VALUE_TYPES
from evertree.core.provider import ToolDefinition
from evertree.core.semantics.searching import SEARCH_KINDS
from evertree.core.values import ContractError


def _object(properties, *, optional=()):
    """Strict JSON-schema object with explicit optional fields and no extras."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": [name for name in properties if name not in optional],
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
_NORM_FIELDS = {
    "property": {
        **_ID,
        "description": "Numeric input property whose observations define the norm.",
    },
    "domain": {
        **_ID,
        "description": "Existing population Prototype whose recorded measurements define the norm.",
    },
    "classes": {"type": "array", "items": _ID, "minItems": 2},
    "conditions": {
        "type": "object",
        "description": (
            "Exact varying measurement inputs already present in the source facts, such as "
            "exercise_state=resting; otherwise {}. Every condition filters the training rows. "
            "A comparison group, list of subjects, source or sample qualification is not a "
            "measurement condition: use domain and description. Do not add conditions to facts "
            "just to populate a norm."
        ),
    },
    "quantiles": {
        "type": "array",
        "items": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
        "description": (
            "Omit for equal default bands. Supply only an intentionally different quantile "
            "criterion, not rounded approximations of the default fractions."
        ),
    },
    "reference": {
        "type": ["integer", "null"],
        "description": "One distribution reference, or null for recorded individuals. Sources are never pooled.",
    },
    "min_samples": {"type": "integer", "minimum": 1},
    "hysteresis": {"type": "number", "minimum": 0, "maximum": 1},
}
_NORM_OPTIONAL = ("quantiles", "reference", "min_samples", "hysteresis")


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


MULTIHOP_SEARCH_INSTRUCTIONS = (
    "For a question requiring several linked facts, first find an anchor and inspect what "
    "the returned facts actually establish. Use discovered names, identifiers and relations "
    "to choose the next search or read; batch only the needs that are independent at that "
    "step. Follow evidence until every required part is supported or a specific gap remains. "
    "Once an anchor is known, prefer exact query reads of its relevant predicates and named "
    "roles to another broad text search. Different predicates require successive reads. "
    "Use walk for repeated transitions of one predicate. For a class-based question, walk "
    "SUBTYPE_OF from supertype to type, include the starting class, then query IDENTITY_TYPE "
    "with args.type in the discovered class IDs and select instance. Inspect the instances' "
    "required predicates; taxonomy membership alone does not establish their other properties. "
    "Follow has_more when completeness matters. Use sources on selected facts and read_source "
    "to verify their exact retained material when those tools are available; source references "
    "describe provenance, not independent verification of truth. "
    "Track participant roles through every hop and check that the same unknown object fills "
    "the required roles. Connected participants are not interchangeable; reject answers that "
    "contradict a required condition. A complete search reports completed retrieval channels, "
    "not exhaustive knowledge or "
    "proof that an object or fact is absent. Report unresolved parts instead of guessing."
)

SEARCH_KIND_FILTER = {
    "type": ["array", "null"],
    "minItems": 1,
    "items": {"type": "string", "enum": sorted(SEARCH_KINDS)},
    "description": (
        "Optional OR filter before retrieval quotas. Use relation_type for schemas, prototype "
        "for classes, instance/facet for participants or states, relation_instance/claim/note "
        "for assertions. Omit for all kinds when representation is unknown; widen if needed. "
        "A filtered search cannot confirm global absence or authorize creation."
    ),
}


SEARCH_QUERIES = {
    "type": "array",
    "minItems": 1,
    "items": {"anyOf": [_TEXT, _ID]},
    "description": (
        "Names, integer IDs or focused phrases, one retrieval need per entry. Batch independent "
        "needs together, e.g. ['Н-1', 'pump operating state']. Cover each independently checkable "
        "clause with a separate query, including conditions in who/which questions about a "
        "single unknown object. For 'which device measures temperature, records pressure and "
        "transmits wirelessly', use ['device measures temperature', 'device records pressure', "
        "'device wireless transmission']. Preserve useful names, source and date constraints. Do not add a topic "
        "merely because the question says a source does not discuss it. Each entry has its own "
        "top-ten budget. Graph type and field names "
        "inside text are keywords, not filters."
    ),
}


READ_TOOLS = (
    ToolDefinition(
        "search",
        (
            "Find objects or reusable meanings for one or more queries. Exact matches resolve "
            "first. Returns a merged list without duplicate objects, up to 10 per unique query. "
            "Similarity candidates are not proven matches. For linked questions, read candidates "
            "and use discovered names or relations in follow-up searches. No pagination."
        ),
        _read_object(
            {
                "queries": SEARCH_QUERIES,
                "kinds": SEARCH_KIND_FILTER,
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            ("queries",),
        ),
        read_only=True,
    ),
    ToolDefinition(
        "sources",
        "Find exact retained sources of selected graph objects or facts, with change history and upstream dependencies. Pass fact IDs to obtain their grounds; an entity's sources do not include every neighboring fact. References to older changes are not automatically evidence for the current assertion. Continue with next_page=true when has_more.",
        _read_object(
            {
                "subjects": {"type": "array", "items": _ID, "minItems": 1},
                "max_items": {"type": "integer", "minimum": 1},
                "next_page": {"type": "boolean"},
            }
        ),
        read_only=True,
    ),
    ToolDefinition(
        "read_source",
        "Read one exact retained source reference without search or ranking. Cite its original reference; offsets identify pages, not new output_path components. Continue with next_page=true to read remaining content. A context reference opens surrounding material separately from the cited fragment.",
        _read_object({"reference": _REFERENCE, "next_page": {"type": "boolean"}}),
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
                "point_policy": {"type": ["string", "null"], "enum": ["argmax", None]},
            },
            ("subject", "property"),
        ),
        read_only=True,
    ),
    ToolDefinition(
        "summarize_property",
        (
            "Summarize observed numeric values for a domain and its compatible source-backed "
            "references. Optionally interpret a value using declared bands or statistics. "
            "Observations and external references stay separate; conditional classifications "
            "are not established beliefs. Omit at for the latest recorded measurement per "
            "individual, not a current census; explicit at selects applicable world-time states. "
            "count_below_value counts reported values below the supplied value; count_above_value "
            "counts values above it. Overlapping intervals do not establish either direction. "
            "With a comparison value, observations.nearest identifies all individuals tied for "
            "the smallest absolute distance in the property's unit; use their returned IDs "
            "when choosing the nearest observed individual."
        ),
        _read_object(
            {
                "domain": {
                    "type": ["integer", "string"],
                    "description": "Existing population Prototype ID or name, such as Dog; not a plain Concept or a source.",
                },
                "property": {"type": ["integer", "string"]},
                "value": {"type": ["number", "null"]},
                "unit": _OPTIONAL_TEXT,
                "reference": {"type": ["integer", "string", "null"]},
                "at": _OPTIONAL_TEXT,
                "parameters": {
                    "type": ["object", "null"],
                    "description": (
                        "Varying applicability inputs matching saved conditions, such as "
                        "exercise_state. Omit when none apply; source identity and publication "
                        "metadata are not query parameters."
                    ),
                },
            },
            ("domain", "property"),
        ),
        read_only=True,
    ),
    ToolDefinition(
        "interpret_property",
        "Apply a saved learned qualitative norm to a hypothetical number. Returns a conditional label and the frozen norm version, not an assessed belief about a real object's class. Does not train or save an observation.",
        _read_object(
            {
                "property": {"type": ["integer", "string"]},
                "value": {"type": "number"},
                "unit": _OPTIONAL_TEXT,
                "parameters": {"type": ["object", "null"]},
            },
            ("property", "value"),
        ),
        read_only=True,
    ),
    ToolDefinition(
        "select_properties",
        "Filter explicit candidate subjects with AND predicates and optionally rank or find nearest. Numeric values use property units. Profiles require an explicit alternative and strength threshold or order; unknowns are reported separately.",
        _read_object(
            {
                "subjects": {"type": "array", "items": _ID},
                "filters": {
                    "type": "array",
                    "items": _read_object(
                        {
                            "property": _ID,
                            "op": {
                                "type": "string",
                                "enum": ["==", "!=", "<", "<=", ">", ">=", "in", "approx"],
                            },
                            "value": _VALUE,
                            "tolerance": {"type": "number", "minimum": 0},
                            "alternative": _ID,
                        },
                        ("property", "op", "value"),
                    ),
                },
                "order_by": {
                    "anyOf": [
                        {"type": "null"},
                        _read_object(
                            {
                                "property": _ID,
                                "direction": {"type": "string", "enum": ["asc", "desc", "nearest"]},
                                "value": {"type": "number"},
                                "alternative": _ID,
                            },
                            ("property", "direction"),
                        ),
                    ]
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 600},
                "at": _OPTIONAL_TEXT,
                "parameters": {"type": ["object", "null"]},
            },
            ("subjects",),
        ),
        read_only=True,
    ),
)

WRITE_TOOLS = (
    ToolDefinition(
        "create_property",
        "Define a reusable property, its scale and source. Numeric defaults to numeric facts; nominal/ordinal use explicit class concepts in order. A computed source requires an existing model Program; a relation source requires its declared view.",
        _object(
            {
                **_NAMED,
                "name": {**_TEXT, "description": "Unique canonical property name, 1–3 words."},
                "unit": {
                    **_OPTIONAL_TEXT,
                    "description": "Canonical unit symbol, preferably kg, g, m or s; null for unitless values.",
                },
                "applies_to": {
                    "type": "array",
                    "items": _ID,
                    "description": (
                        "Existing subject or Prototype IDs. For a population use its shared "
                        "Prototype, such as Dog, not a plain Concept or a guide-specific group."
                    ),
                },
                "scale": {"type": "string", "enum": ["numeric", "nominal", "ordinal", "circular"]},
                "source": {
                    "type": "string",
                    "enum": ["numeric", "classification", "relation", "program", "result"],
                },
                "classes": {"type": "array", "items": _ID},
                "period": {"type": ["number", "null"], "exclusiveMinimum": 0},
                "required_parameters": {"type": "array", "items": _TEXT},
                "parameter_types": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "string",
                        "enum": [
                            "string",
                            "number",
                            "integer",
                            "boolean",
                            "node",
                            "object",
                            "array",
                        ],
                    },
                },
                "selection": {"type": "string", "enum": ["latest", "max_support", "unique"]},
                "relation_type": {"type": ["integer", "string", "null"]},
                "view": _OPTIONAL_TEXT,
                "subject_slot": _TEXT,
                "program": {"type": ["integer", "null"]},
            },
            optional=(
                "scale",
                "source",
                "classes",
                "period",
                "required_parameters",
                "parameter_types",
                "selection",
                "relation_type",
                "view",
                "subject_slot",
                "program",
            ),
        ),
        read_only=False,
    ),
    ToolDefinition(
        "create_qualitative_property",
        "Learn a relative qualitative property such as dog size from retained numeric observations or one frequency table. Supply ordered class concepts; Core fits quantile boundaries (equal bins by default, minimum 3 samples). Belief about a real object's class is assessed separately. Never supply invented cutoffs. After creation, describe the property to check norm_state count and status before using it.",
        _object({**_NAMED, **_NORM_FIELDS}, optional=_NORM_OPTIONAL),
        read_only=False,
    ),
    ToolDefinition(
        "revise_property_norm",
        "Change a learned property's criterion explicitly. Changed class meaning creates a new semantic revision; previous results and evidence retain their old meaning. Core recomputes the checkpoint.",
        _object({"object": _ID, **_NORM_FIELDS, "sources": _SOURCES}, optional=_NORM_OPTIONAL),
        read_only=False,
    ),
    ToolDefinition(
        "save_property_result",
        "Retain a typed property result with its exact subject, property, conditions and time bounds. Omit both time bounds for a timeless result; explicit null means unknown applicability. The property must declare source=result. Numeric values may be scalar, interval, normal distribution or ordered quantiles. Confidence is assessed from sources, not supplied here.",
        _object(
            {
                **_NAMED,
                "subject": _ID,
                "property": _ID,
                "conditions": {"type": "object"},
                "value_U": {"type": ["number", "integer", "string", "object"]},
                "unit": _OPTIONAL_TEXT,
                "valid_from": _STATE_START,
                "valid_until": _STATE_END,
            },
            optional=("valid_from", "valid_until"),
        ),
        read_only=False,
    ),
    ToolDefinition(
        "create_property_reference",
        (
            "Save a source's numeric classification bands or statistical table for one property "
            "and domain. Bands use ordered boundaries and one more class than boundaries; "
            "boundary_inclusive preserves which class owns each endpoint. Distribution rows "
            "preserve lower/upper bounds and counts; an exact "
            "value has lower=upper. Use empty arrays for the other reference kind. Preserve "
            "source qualifications in description; conditions are only varying query inputs, "
            "otherwise {}. Bands require cutoffs explicitly given by the source. To learn "
            "relative labels from observations or a distribution without source cutoffs, "
            "use create_qualitative_property. Do not invent thresholds or samples."
        ),
        _object(
            {
                **_NAMED,
                "name": {**_TEXT, "description": "Unique canonical reference name, 1–3 words."},
                "property": {
                    **_ID,
                    "description": "Existing numeric property ID whose applies_to includes this population.",
                },
                "domain": {
                    **_ID,
                    "description": (
                        "Existing population Prototype ID within the property's applies_to, "
                        "such as Dog or Chihuahua. Reuse the same population across guides; "
                        "a plain Concept or the source itself is not a population type."
                    ),
                },
                "unit": _OPTIONAL_TEXT,
                "reference_kind": {"type": "string", "enum": ["bands", "distribution"]},
                "boundaries": {"type": "array", "items": {"type": "number"}},
                "boundary_inclusive": {
                    "type": "array",
                    "items": {"type": "boolean"},
                    "description": (
                        "One flag per boundary: true assigns equality to the lower class, false "
                        "to the next class. 'Up to the boundary inclusive' means true; 'below "
                        "the boundary' means false. Omit when all upper boundaries are inclusive; "
                        "[] for a distribution. Verify the source's rules at the exact boundaries."
                    ),
                },
                "classes": {"type": "array", "items": _ID},
                "samples": {
                    "type": "array",
                    "items": _object(
                        {
                            "lower": {"type": "number"},
                            "upper": {"type": "number"},
                            "count": {"type": "integer", "minimum": 1},
                        }
                    ),
                },
                "conditions": {
                    "type": "object",
                    "description": (
                        "Only varying query inputs required to apply this reference, for example "
                        '{"exercise_state": "resting"} or {"load": "high"}; default {}. '
                        "Matching is exact. Do not duplicate source identity, population, "
                        "publication status, sample count or who measured it here: use domain, "
                        "description, sources and samples instead."
                    ),
                },
            },
            optional=("boundary_inclusive",),
        ),
        read_only=False,
    ),
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
        "Save one identifiable object as a member of a class whose definition it satisfies.",
        _object(
            {
                **_NAMED,
                "prototype": {
                    **_ID,
                    "description": (
                        "Existing Prototype ID whose category includes this object. Check the "
                        "class name and definition; search for or create a fitting class when "
                        "none is known."
                    ),
                },
            }
        ),
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
                "name": {**_TEXT, "description": "Unique canonical predicate name, 1–3 words."},
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
                            "description": {
                                **_TEXT,
                                "description": (
                                    "Meaning of values in this role, including direction and scope "
                                    "when its label alone is ambiguous."
                                ),
                            },
                        },
                        optional=("description",),
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
                        "one array value, not repeated entries. Each value must fit the role's "
                        "defined meaning as well as its value type."
                    ),
                    "items": _object({"role": _TEXT, "value": _VALUE}),
                },
                "conditions": {
                    "type": "array",
                    "description": "Conditions under which the assertion applies, with unique names.",
                    "items": _object(
                        {
                            "parameter": _TEXT,
                            "value": {
                                "type": ["string", "number", "boolean", "null", "object", "array"]
                            },
                        }
                    ),
                },
                "description": _OPTIONAL_TEXT,
                "sources": _SOURCES,
                "criterion": {
                    "type": ["integer", "null"],
                    "description": "For CLASSIFIED_AS, the categorical property whose criterion this assertion uses. Required when the same class belongs to multiple applicable properties.",
                },
            },
            optional=("criterion",),
        ),
        read_only=False,
    ),
    ToolDefinition(
        "create_claim",
        (
            "Save an assertion whose argument or meaning cannot be adequately expressed by "
            "native relations, properties or states. Ordinary reported events, offers, roles, "
            "comparisons and values must use those native forms with shared participant IDs; "
            "a missing schema is created with define_relation. Do not use Claims as a shorter "
            "way to store ordinary facts, or because a source is partial or unverified. "
            "Retain the assertion's conditions and grounds. "
            "Assertions that evidence could confirm, reject or correct separately need separate "
            "representations, including alternative explanations. Keep a hypothesis's necessary "
            "conditions and supporting argument together; it remains provisional. Do not bundle a source's "
            "objects, state intervals or simple relationships into a summary Claim. "
            "A missing relation schema can be defined with define_relation. "
            "Reported or unverified relationships can still use native relations with sources and conditions. "
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
        "create_property",
        "create_property_reference",
        "create_qualitative_property",
        "save_property_result",
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
        # Relation roles remain scalar or scalar lists; conditions can carry structured inputs.
        for item in action["arguments"]:
            value = item["value"]
            for part in value if isinstance(value, list) else [value]:
                validate(part, _SCALAR)
