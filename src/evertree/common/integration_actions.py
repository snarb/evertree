"""Compile semantic choices into an attributed, atomic graph proposal."""

import json
from copy import deepcopy

from evertree.common.structured import validate
from evertree.core.graph.types import ARITIES, VALUE_TYPES, Slot
from evertree.core.provider import ToolDefinition
from evertree.core.values import ContractError, timestamp


def _object(properties):
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


_TEXT = {"type": "string", "minLength": 1}
_ID = {"type": "integer"}
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
        "output_path": {"type": "array", "items": {"type": ["string", "integer"]}},
    }
)
_SOURCES = {"type": "array", "items": _REFERENCE, "minItems": 1}
_NAMED = {"name": _TEXT, "description": _OPTIONAL_TEXT, "sources": _SOURCES}
_SCALAR = {"type": ["string", "number", "boolean", "null"]}
_VALUE = {"anyOf": [_SCALAR, {"type": "array", "items": _SCALAR}]}


def _action(action_name, **fields):
    return _object({"action": {"type": "string", "enum": [action_name]}, **fields})


ACTION_SCHEMAS = {
    name: _action(name, **fields)
    for name, fields in {
        "search": {"query": _TEXT, "next_page": {"type": "boolean"}},
        "describe": {"subject": {"type": ["integer", "string"]}},
        "create_concept": _NAMED,
        "create_prototype": {
            **_NAMED,
            "parent": {
                "type": ["integer", "null"],
                "description": "ID of a more general class, or null when no parent is justified.",
            },
        },
        "create_instance": {**_NAMED, "prototype": _ID},
        "create_facet": {
            **_NAMED,
            "instance": _ID,
            "valid_from": _STATE_START,
            "valid_until": _STATE_END,
        },
        "define_relation": {
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
        },
        "relate": {
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
        },
        "save_note": {
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
        },
        "reuse": {"object": _ID, "sources": _SOURCES},
        "trace_only": {"sources": _SOURCES},
        "unresolved": {"sources": _SOURCES, "reason": _TEXT},
        "fulfill": {
            "intent": _TEXT,
            "objects": {"type": "array", "items": _ID, "minItems": 1},
        },
        "discard": {"object": _ID},
        "retract": {"object": {"type": "integer", "minimum": 1}, "sources": _SOURCES},
        "change_state_end": {
            "object": {**_ID, "description": "ID of the existing or staged facet to update."},
            "valid_until": _STATE_END,
            "sources": _SOURCES,
        },
    }.items()
}

_TOOL_DESCRIPTIONS = {
    "search": "Find existing objects before choosing an identity or representation.",
    "describe": "Read an existing object, its relation schema and known assertions.",
    "create_concept": "Stage a useful distinction not expressed by an existing concept.",
    "create_prototype": "Stage a class, without asserting typical properties.",
    "create_instance": "Stage one identifiable object and its class membership.",
    "create_facet": "Stage a changing aspect of an object, with known or unknown time bounds.",
    "define_relation": "Stage a relation type with meaningful participant roles.",
    "relate": "Stage an assertion using an existing or staged relation type.",
    "save_note": "Stage the source text as a Note, retaining its qualifications and origin.",
    "reuse": "Select existing knowledge as the representation of a source.",
    "trace_only": "Mark source material reviewed without adding a graph representation.",
    "unresolved": "Record a concrete obstacle to deciding or preserving source material.",
    "fulfill": "Associate staged or reused objects with the meaning of a preservation intent.",
    "discard": "Cancel a staged object, or all staged changes to an existing object.",
    "retract": "Stage removal of existing knowledge when sources establish a correction.",
    "change_state_end": "Stage an evidence-backed correction to a facet's end time.",
}

INTEGRATION_TOOLS = tuple(
    ToolDefinition(
        name,
        _TOOL_DESCRIPTIONS[name],
        _object({key: value for key, value in schema["properties"].items() if key != "action"}),
        read_only=name in {"search", "describe"},
    )
    for name, schema in ACTION_SCHEMAS.items()
) + (
    ToolDefinition(
        "finish",
        "Check all sources and preservation obligations, then commit the staged changes atomically. "
        "Returns errors for repair, or a final complete/blocked receipt and ends this invocation.",
        _object({}),
    ),
)


def validate_action(action):
    if not isinstance(action, dict) or action.get("action") not in ACTION_SCHEMAS:
        raise ContractError("Unknown semantic action")
    validate(action, ACTION_SCHEMAS[action["action"]])
    if action["action"] == "relate":
        for field in ("arguments", "conditions"):
            for item in action[field]:
                value = item["value"]
                for part in value if isinstance(value, list) else [value]:
                    validate(part, _SCALAR)


def _contains(parent, child):
    return (
        parent["event_ref"] == child["event_ref"]
        and child["output_path"][: len(parent["output_path"])] == parent["output_path"]
    )


def _overlaps(left, right):
    return _contains(left, right) or _contains(right, left)


class IntegrationDraft:
    """Staged actions carry their own grounds; the model never constructs bookkeeping."""

    def __init__(self, material, nodes=()):
        self.material = deepcopy(material)
        self.nodes = {node["id"]: deepcopy(node) for node in nodes}
        self._creates, self._updates, self._deletes = {}, {}, []
        self._groups, self._decisions, self._fulfillments = {}, [], {}
        self._next_id = -1
        self.intents = {
            item["id"]: item for item in material["context"].get("preservation_intents", [])
        }

    def remember_read(self, result):
        def visit(value):
            if isinstance(value, dict):
                if type(value.get("id")) is int and "kind" in value and "name" in value:
                    self.nodes[value["id"]] = {**self.nodes.get(value["id"], {}), **deepcopy(value)}
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(result)

    def _node(self, identity, kind=None):
        if type(identity) is not int or identity == 0:
            raise ContractError("Use an object ID returned by a read or earlier action")
        node = self._creates.get(identity, self.nodes.get(identity))
        if node is None or identity in self._deletes:
            raise ContractError(f"Unknown or retracted object {identity}")
        accepted = {kind}
        if kind == "prototype":
            accepted = {"prototype", "process", "relation_type", "property"}
        if kind not in {None, "node", "concept"} and node["kind"] not in accepted:
            raise ContractError(f"Object {identity} must be {kind}")
        return {**node, **self._updates.get(identity, {})}

    def _schema(self, subject):
        if isinstance(subject, str):
            matches = [
                node
                for node in self.nodes.values()
                if node["name"] == subject and node["kind"] == "relation_type"
            ]
            if len(matches) != 1:
                raise ContractError(f"Read the built-in relation {subject}")
            subject = matches[0]["id"]
        node = self._node(subject, "relation_type")
        if "signature" not in node:
            raise ContractError(f"Describe relation {subject} before using it")
        return node

    def required_reads(self, action):
        validate_action(action)
        name, subjects = action["action"], []
        if name == "create_instance":
            subjects = [action["prototype"], "IDENTITY_TYPE"]
        elif name == "create_facet":
            subjects = [action["instance"], "STATE_IDENTITY"]
        elif name == "create_prototype" and action["parent"] is not None:
            subjects = [action["parent"], "SUBTYPE_OF"]
        elif name == "relate":
            relation = self._creates.get(action["relation"], self.nodes.get(action["relation"]))
            if relation is None or "signature" not in relation:
                return [action["relation"]]
            kinds = {slot["label"]: slot["value_type"] for slot in relation["signature"]}
            for argument in action["arguments"]:
                if kinds.get(argument["role"]) in {
                    "node",
                    "concept",
                    "prototype",
                    "instance",
                    "facet",
                }:
                    value = argument["value"]
                    subjects.extend(value if isinstance(value, list) else [value])
        elif name in {"reuse", "retract", "change_state_end"}:
            subjects = [action["object"]]
        result = []
        for subject in subjects:
            if subject is None:
                continue
            if isinstance(subject, str):
                if not any(n["name"] == subject and "signature" in n for n in self.nodes.values()):
                    result.append(subject)
            elif type(subject) is int and subject > 0 and subject not in self.nodes:
                result.append(subject)
        return list(dict.fromkeys(result))

    def _resolve(self, ref):
        validate(ref, _REFERENCE)
        if any(type(part) is int and part < 0 for part in ref["output_path"]):
            raise ContractError("Source array indices must be nonnegative")
        for item in self.material["experience"]:
            if not _contains(item["reference"], ref):
                continue
            value = item["content"]
            try:
                for part in ref["output_path"][len(item["reference"]["output_path"]) :]:
                    if isinstance(value, list) and (type(part) is not int or part < 0):
                        raise KeyError(part)
                    value = value[part]
            except (KeyError, IndexError, TypeError) as error:
                raise ContractError("Source path does not address supplied experience") from error
            return value, item
        raise ContractError("Source is outside supplied experience")

    def _sources(self, refs):
        for ref in refs:
            self._resolve(ref)
        return deepcopy(refs)

    def _create(self, **fields):
        identity, self._next_id = self._next_id, self._next_id - 1
        self._creates[identity] = {"id": identity, **fields}
        return identity

    def _fact(self, relation, args, description=None, conditions=None):
        fields = {
            "name": relation["name"],
            "kind": "relation_instance",
            "relation_type": relation["id"],
            "args": args,
            "description": description,
        }
        if conditions:
            fields["properties"] = {"conditions": conditions}
        return self._create(**fields)

    def _decision(self, disposition, sources, ids=(), reason=None):
        decision = {
            "disposition": disposition,
            "source_refs": sources,
            "affected_ids": list(ids),
            "preservation_ids": [],
        }
        if reason is not None:
            decision["reason"] = reason
        self._decisions.append(decision)

    def apply(self, action):
        validate_action(action)
        before = deepcopy(self.__dict__)
        try:
            return self._apply(action)
        except (ValueError, TypeError, KeyError):
            self.__dict__.update(before)
            raise

    def _apply(self, action):
        name = action["action"]
        sources = self._sources(action["sources"]) if "sources" in action else []
        if name in {"trace_only", "unresolved"}:
            self._decision(name, sources, reason=action.get("reason"))
            return {"disposition": name}
        if name == "fulfill":
            self._fulfill(action["intent"], action["objects"])
            return {"fulfilled": action["intent"]}
        if name == "discard":
            return self._discard(action["object"])
        if name in {"reuse", "retract", "change_state_end"}:
            return self._existing(action, sources)
        previous_ids = set(self._creates)
        if name in {"create_concept", "create_prototype", "create_instance", "create_facet"}:
            kind = name.removeprefix("create_")
            fields = {"kind": kind, "name": action["name"], "description": action["description"]}
            if kind == "facet":
                start, end = action["valid_from"], action["valid_until"]
                self._interval(start, end)
                fields.update(valid_from=start, valid_until=end)
            identity = self._create(**fields)
            if kind == "instance":
                self._node(action["prototype"], "prototype")
                self._fact(
                    self._schema("IDENTITY_TYPE"),
                    {"instance": identity, "type": action["prototype"]},
                )
            elif kind == "facet":
                self._node(action["instance"], "instance")
                self._fact(
                    self._schema("STATE_IDENTITY"),
                    {"facet": identity, "instance": action["instance"]},
                )
            elif kind == "prototype" and action["parent"] is not None:
                self._node(action["parent"], "prototype")
                self._fact(
                    self._schema("SUBTYPE_OF"), {"type": identity, "supertype": action["parent"]}
                )
        elif name == "define_relation":
            roles = action["roles"]
            for role in roles:
                Slot(**role)
            labels = [role["label"] for role in roles]
            if len(labels) != len(set(labels)):
                raise ContractError("Relation role labels must be unique")
            identity = self._create(
                name=action["name"],
                kind="relation_type",
                description=action["description"],
                signature=deepcopy(roles),
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
            schema = self._schema(action["relation"])
            args = self._arguments(schema, action["arguments"])
            conditions = {item["parameter"]: item["value"] for item in action["conditions"]}
            if len(conditions) != len(action["conditions"]):
                raise ContractError("Condition parameters must be unique")
            identity = self._fact(schema, args, action["description"], conditions)
        elif name == "save_note":
            value, item = self._resolve(action["source"])
            origin = item.get("origin", {})
            analytical = origin.get("operator") == "analytical_note" and origin.get(
                "output_type", ""
            ).endswith(".AnalyticalNote")
            fragment = (
                origin.get("program") == "ExperienceFragments"
                and origin.get("operator") == "experience_fragment"
                and isinstance(value, dict)
                and value.get("encoding") == "analytical_text"
                and isinstance(value.get("text"), str)
            )
            if (
                (analytical or fragment)
                and not item["reference"]["output_path"]
                and action["source"] == item["reference"]
            ):
                # The source reference retains the fragment's offsets and original Note metadata.
                text = value["text"]
            else:
                text = (
                    value
                    if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False, indent=2)
                )
            if action["source"] not in sources:
                sources.append(deepcopy(action["source"]))
            identity = self._create(
                name=action["name"],
                kind="note",
                description=text,
                properties={"source_ref": deepcopy(action["source"])},
            )
        else:
            raise ContractError("Search and describe must be executed through the runtime")
        created = [key for key in self._creates if key not in previous_ids]
        self._groups[identity] = set(created)
        self._decision("materialize", sources, created)
        if name == "save_note":
            for intent in self.intents.values():
                if _overlaps(action["source"], intent["source_ref"]) and intent["text"] == text:
                    self._fulfill(intent["id"], [identity])
        return {"object": identity}

    @staticmethod
    def _interval(start, end):
        def parse(value):
            return timestamp(value.get("$datetime") if isinstance(value, dict) else value)

        start, end = (
            parse(start) if start is not None else None,
            parse(end) if end is not None else None,
        )
        if start is not None and end is not None and end <= start:
            raise ContractError("State interval must end after it starts")

    def _arguments(self, schema, arguments):
        args = {item["role"]: item["value"] for item in arguments}
        roles = {slot["label"]: slot for slot in schema["signature"]}
        if len(args) != len(arguments) or args.keys() - roles.keys():
            raise ContractError("Arguments must use distinct declared relation roles")
        for label, slot in roles.items():
            value = args.get(label)
            arity = slot["arity"]
            if label not in args and arity != "optional":
                raise ContractError(f"Missing required role {label}")
            if arity == "optional" and value is None:
                continue
            if arity in {"list0", "list1"}:
                if not isinstance(value, list) or (arity == "list1" and not value):
                    raise ContractError(f"Role {label} requires {arity}")
                values = value
            else:
                values = [value]
            kind = slot["value_type"]
            for item in values:
                if kind in {"node", "concept", "prototype", "instance", "facet"}:
                    self._node(item, None if kind == "node" else kind)
                elif kind == "any":
                    validate(item, _SCALAR)
                else:
                    validate(item, {"type": kind})
        return deepcopy(args)

    def _existing(self, action, sources):
        identity, name = action["object"], action["action"]
        node = self._node(identity, "facet" if name == "change_state_end" else None)
        if name == "reuse":
            if identity < 0:
                raise ContractError(
                    "Reuse selects existing graph objects; reference staged objects directly"
                )
            self._decision("reuse", sources, [identity])
        elif name == "retract":
            self._supersede(identity, include_reuse=True)
            self._updates.pop(identity, None)
            self._deletes.append(identity)
            self._decision("materialize", sources, [identity])
        else:
            self._interval(node.get("valid_from"), action["valid_until"])
            self._supersede(identity)
            if identity < 0:
                self._creates[identity]["valid_until"] = action["valid_until"]
            else:
                self._updates.setdefault(identity, {})["valid_until"] = action["valid_until"]
            self._decision("materialize", sources, [identity])
        return {"object": identity}

    def _supersede(self, identity, *, include_reuse=False):
        # Overwritten choices remain reviewed, but no longer justify the final mutation.
        for decision in self._decisions:
            if decision["affected_ids"] == [identity] and (
                decision["disposition"] == "materialize" or include_reuse
            ):
                decision.update(disposition="trace_only", affected_ids=[], preservation_ids=[])
        self._fulfillments = {
            key: ids for key, ids in self._fulfillments.items() if identity not in ids
        }

    def _fulfill(self, intent_id, identities):
        intent = self.intents.get(intent_id)
        if intent is None:
            raise ContractError("Unknown preservation intent")
        for identity in identities:
            self._node(identity)
            if not any(
                identity in decision["affected_ids"]
                and decision["disposition"] in {"materialize", "reuse"}
                and any(_overlaps(ref, intent["source_ref"]) for ref in decision["source_refs"])
                for decision in self._decisions
            ):
                raise ContractError(
                    "Preservation must select an action grounded in its analytical source"
                )
        self._fulfillments[intent_id] = list(identities)

    def _references(self, node):
        if node["kind"] != "relation_instance":
            return set()
        result = {node["relation_type"]}
        for slot in self._schema(node["relation_type"])["signature"]:
            if slot["value_type"] in {"node", "concept", "prototype", "instance", "facet"}:
                value = node["args"].get(slot["label"])
                result.update(value if isinstance(value, list) else [value])
        return result

    def _discard(self, identity):
        if identity > 0:
            if not any(identity in decision["affected_ids"] for decision in self._decisions):
                raise ContractError("Object has no prepared choice to discard")
            self._updates.pop(identity, None)
            self._deletes = [key for key in self._deletes if key != identity]
            self._decisions = [d for d in self._decisions if identity not in d["affected_ids"]]
            self._fulfillments = {
                key: ids for key, ids in self._fulfillments.items() if identity not in ids
            }
            return {"discarded": [identity]}
        removed = self._groups.get(identity)
        if removed is None:
            raise ContractError("Discard selects an object returned by a creation action")
        if any(
            self._references(node) & removed
            for key, node in self._creates.items()
            if key not in removed
        ):
            raise ContractError("Discard dependent staged objects first")
        for key in removed:
            self._creates.pop(key)
        self._groups.pop(identity)
        self._decisions = [d for d in self._decisions if not set(d["affected_ids"]) & removed]
        self._fulfillments = {
            key: ids for key, ids in self._fulfillments.items() if not set(ids) & removed
        }
        return {"discarded": sorted(removed)}

    @property
    def proposal(self):
        return deepcopy(
            {
                "creates": list(self._creates.values()),
                "updates": [
                    {"id": identity, "changes": changes}
                    for identity, changes in self._updates.items()
                ],
                "deletes": self._deletes,
            }
        )

    @property
    def decisions(self):
        decisions = deepcopy(self._decisions)
        for intent, ids in self._fulfillments.items():
            if set(ids) & set(self._deletes):
                continue
            for decision in decisions:
                if set(ids) & set(decision["affected_ids"]) and any(
                    _overlaps(ref, self.intents[intent]["source_ref"])
                    for ref in decision["source_refs"]
                ):
                    decision["preservation_ids"].append(intent)
        return decisions

    def snapshot(self):
        decisions = self.decisions
        reviewed = []
        for decision in decisions:
            for source in decision["source_refs"]:
                if source not in reviewed:
                    reviewed.append(source)
        fulfilled = {intent for decision in decisions for intent in decision["preservation_ids"]}
        return {
            "objects": [deepcopy(self._creates[key]) for key in self._groups],
            "changed_states": [
                {"object": identity, "valid_until": changes["valid_until"]}
                for identity, changes in self._updates.items()
            ],
            "retracted": list(self._deletes),
            "reviewed_sources": reviewed,
            "pending_preservation_ids": sorted(self.intents.keys() - fulfilled),
        }
