"""Source-backed assessment of declared qualitative property questions."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping

from .beliefs import element_target
from .datasets import content_revision
from .evidence import _reference, _Sources, origin_target
from .graph.matching import values_equal
from .values import UNKNOWN, ContractError, freeze, json_value, timestamp


def _belief(beliefs, target):
    try:
        result = beliefs.read(target)
    except KeyError:
        return None
    return None if result is UNKNOWN else json_value(result)


def property_context(runtime, subject, property_id, *, at=None, parameters=None):
    """Resolve a qualitative question without creating a scope or assessing evidence."""
    from .attribution_norms import interpret_norm, norm_context

    definition = runtime.definitions().get(property_id)
    if (
        definition is None
        or definition.source != "norm"
        or not runtime.applies(subject, definition)
    ):
        return UNKNOWN
    context = norm_context(runtime, property_id)
    if context is UNKNOWN:
        return UNKNOWN
    norm, state = context["definition"], context["state"]
    if state.get("status") != "ready":
        return UNKNOWN
    parameters = dict(parameters or {})
    if not values_equal(parameters, norm.get("conditions", {})):
        return UNKNOWN
    reading = runtime.read_property(subject, norm["property"], valid_at=at, **parameters)
    if reading is UNKNOWN:
        return UNKNOWN
    facts = [runtime.graph.get(identity) for identity in reading.source_facts]
    inputs = []
    for fact in facts:
        revision = runtime._fact_recency(fact)[1]
        change = next(item for item in runtime.graph.changes_of(fact.id) if item.seq == revision)
        inputs.append(
            {
                "fact": fact.id,
                "revision": revision,
                "source_ref": json_value(change.provenance),
                "belief": _belief(runtime.beliefs, element_target(fact)),
            }
        )
    sample_facts = {item["source_fact"]: item for item in context["observations"]}
    training_evidence = []
    for dependency in context["dependencies"]:
        node = runtime.graph.get(dependency["object"])
        change = next(
            change
            for change in runtime.graph.changes_of(node.id)
            if change.seq == dependency["revision"]
        )
        training_evidence.append(
            {
                **dependency,
                "name": node.name,
                "source_ref": json_value(change.provenance),
                "role": "measurement"
                if node.id in sample_facts
                else ("reference" if node.id == norm["reference"] else "definition"),
                "belief": _belief(runtime.beliefs, element_target(node)),
                **(
                    {
                        "observation": {
                            **{
                                key: sample_facts[node.id][key]
                                for key in ("subject", "name", "value")
                            },
                            "unit": context["unit"],
                        }
                    }
                    if node.id in sample_facts
                    else {}
                ),
            }
        )
    identities = [
        fact.args["instance"]
        for fact in runtime.graph.facts("STATE_IDENTITY")
        if fact.args["facet"] == subject
    ]
    if len(identities) > 1:
        return UNKNOWN
    question = {
        "subject": identities[0] if identities else subject,
        "property": property_id,
        "criterion": state["semantic_revision"],
        "conditions": parameters,
        "states": sorted({fact.args["entity"] for fact in facts}),
    }
    return {
        "target": "property-scope:" + content_revision(question),
        "subject": subject,
        "property": property_id,
        "subject_name": runtime.graph.get(subject).name,
        "property_name": runtime.graph.get(property_id).name,
        "classes": list(norm["classes"]),
        "class_meanings": json_value(state["class_meanings"]),
        "parameters": parameters,
        "at": timestamp(at).isoformat() if at is not None else None,
        "question": question,
        "norm": {
            "definition": json_value(norm),
            "state": {
                key: json_value(state[key])
                for key in (
                    "semantic_revision",
                    "revision",
                    "boundaries",
                    "boundary_bounds",
                    "count",
                    "status",
                    "approximate",
                )
                if key in state
            },
            "belief_data": json_value(context.get("model_belief_data")),
            "belief_status": context["model_belief_status"],
            "training_evidence": training_evidence,
            "source_refs": json_value(context.get("source_refs", ())),
        },
        "reading": json_value(reading),
        "conditional_interpretation": interpret_norm(
            runtime, property_id, reading.value_U, unit=reading.unit, parameters=parameters
        ),
        "inputs": inputs,
    }


class AttributionEvidence:
    """Prepare and record qualitative assessments using the existing belief store."""

    def __init__(self, runtime, memory):
        self.runtime, self.memory = runtime, memory

    def prepare(self, subject, property_id, *, at=None, parameters=None):
        """Expand input provenance and fingerprint everything an assessment relies on."""
        context = property_context(self.runtime, subject, property_id, at=at, parameters=parameters)
        if context is UNKNOWN:
            return UNKNOWN
        sources = _Sources(self.memory)
        direct = []
        for item in context["inputs"]:
            reference = _reference(item["source_ref"])
            if reference is not None:
                direct.extend(sources.expand(reference, new=True))
        direct = set(direct)
        for item in context["norm"]["training_evidence"]:
            reference = _reference(item["source_ref"])
            item["source_keys"] = sources.expand(reference, new=False) if reference else []
        records = sources.public()
        for source in records:
            reference = _reference(source["ref"])
            source["role"] = "measurement" if source["key"] in direct else "norm_context"
            source["withdrawn_by"] = json_value(self.runtime.beliefs.withdrawn_by(reference))
            source["origin_belief"] = _belief(self.runtime.beliefs, origin_target(source["origin"]))
            source["dependency_root"] = None
            for item in context["inputs"]:
                fact = self.runtime.graph.get(item["fact"])
                for component in self.runtime.beliefs.active_sources(element_target(fact)):
                    if json_value(component.source_ref) == source["ref"]:
                        root = json.loads(component.dependency_root)
                        if _reference(root) is not None:
                            source["dependency_root"] = root
        context["sources"] = records
        fingerprint = {
            "question": context["question"],
            "norm_revision": context["norm"]["state"]["revision"],
            "norm_belief": context["norm"]["belief_data"],
            "norm_belief_status": context["norm"]["belief_status"],
            "training_evidence": context["norm"]["training_evidence"],
            "reading": {
                key: context["reading"][key] for key in ("value_U", "unit", "source_facts")
            },
            "inputs": context["inputs"],
            "sources": records,
        }
        context["input_revision"] = content_revision(fingerprint)
        context["prior"] = None
        context["active"] = []
        beliefs = self.runtime.beliefs
        if beliefs.known(context["target"]):
            contract = beliefs.target(context["target"])
            context["prior"] = dict(zip(contract.alternatives, contract.prior))
            context["active"] = [
                json_value(item) for item in beliefs.active_sources(context["target"])
            ]
        return context

    def pending(self, *, limit=20):
        """Find declared qualitative readings whose prepared inputs changed."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ContractError("Property assessment limit must be between 1 and 100")
        scopes = []
        for definition in self.runtime.definitions().values():
            if definition.source != "norm":
                continue
            node = self.runtime.graph.get(definition.id)
            conditions = dict(node.properties["qualitative_norm"].get("conditions", {}))
            for subject in self.runtime.graph.nodes(kind="instance"):
                item = self.prepare(subject.id, definition.id, parameters=conditions)
                if item is UNKNOWN:
                    continue
                if self.runtime._scope_inputs.get(item["target"]) != item["input_revision"]:
                    scopes.append(item)
        return {"scopes": scopes[:limit], "remaining": max(0, len(scopes) - limit)}

    def record(
        self,
        subject,
        property,
        input_revision,
        *,
        parameters=None,
        at=None,
        prior=None,
        assign=(),
        retract=(),
        created_by=None,
    ):
        """Replace a complete scope assessment, rejecting stale or foreign evidence first."""
        property_id = property
        context = self.prepare(subject, property_id, parameters=parameters, at=at)
        if context is UNKNOWN or context["input_revision"] != input_revision:
            raise ContractError("Qualitative assessment inputs changed; prepare again")
        classes = tuple(map(str, context["classes"]))
        beliefs, target = self.runtime.beliefs, context["target"]

        def validate(values, label, *, normalized=False):
            if not isinstance(values, Mapping) or set(values) != set(classes):
                raise ContractError(f"Property {label} must cover every class")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
                for value in values.values()
            ):
                raise ContractError(f"Property {label} must be positive finite numbers")
            if normalized and not math.isclose(sum(values.values()), 1, abs_tol=1e-9):
                raise ContractError("Property prior must sum to one")
            return dict(values)

        if prior is not None:
            validate(prior, "prior", normalized=True)
        allowed = {
            content_revision(source["ref"]): source
            for source in context["sources"]
            if source["role"] == "measurement" and not source["withdrawn_by"]
        }
        records, seen = [], set()
        for item in assign:
            reference = _reference(item.get("source_ref"))
            key = content_revision(json_value(reference)) if reference is not None else None
            if key not in allowed or key in seen:
                raise ContractError("Property evidence needs a distinct primary measurement source")
            seen.add(key)
            root = _reference(item.get("dependency_root") or allowed[key]["dependency_root"])
            if item.get("dependency_root") is not None and root is None:
                raise ContractError("Property evidence dependency needs a source reference")
            if root is not None:
                self.memory.resolve(root)
            basis = item.get("basis")
            if basis is not None and not isinstance(basis, Mapping):
                raise ContractError("Property assessment basis must be an object")
            records.append(
                (
                    reference,
                    validate(item.get("likelihoods"), "likelihoods"),
                    root,
                    dict(basis or {}),
                )
            )
        retracted = set()
        for item in retract:
            reference = _reference(item)
            if reference is None:
                raise ContractError("Property retraction needs a source reference")
            self.memory.resolve(reference)
            retracted.add(content_revision(json_value(reference)))
        if retracted.intersection(seen):
            raise ContractError("A property source cannot be assigned and retracted together")
        if not beliefs.known(target):
            beliefs.register_scope(target, classes, prior)
        elif beliefs.target(target).alternatives != classes:
            raise ContractError("Property scope alternatives changed without semantic revision")
        # Assessment is complete for these inputs; absent sources must not retain an old vote.
        for component in beliefs.active_sources(target):
            if content_revision(json_value(component.source_ref)) not in seen:
                beliefs.retract(target, component.source_ref)
        assignments = []
        for reference, likelihoods, root, basis in records:
            assignment = beliefs.assess_likelihoods(
                target,
                reference,
                likelihoods,
                backed=False,
                dependency_root=root,
                created_by=created_by,
            )
            basis["property_input_revision"] = input_revision
            beliefs.set_basis(target, reference, basis)
            self.memory.retain(reference, "evidence:" + target)
            assignments.append(assignment.id)
        self.runtime.bind_scope(subject, property_id, target, conditions=parameters)
        self.runtime._scope_inputs[target] = input_revision
        return {
            "target": target,
            "assignments": assignments,
            "belief": json_value(beliefs.read(target)),
        }


def read_norm_property(
    runtime, subject, property_id, *, valid_at=None, known_at=None, **parameters
):
    """Read an assessed Profile only while its declared input revision remains current."""
    from .attribution import PropertyReading

    memory = getattr(runtime, "memory", None)
    if memory is None:
        return UNKNOWN
    context = AttributionEvidence(runtime, memory).prepare(
        subject, property_id, at=valid_at, parameters=parameters
    )
    if context is UNKNOWN:
        return UNKNOWN
    target = context["target"]
    if runtime._scope_inputs.get(target) != context["input_revision"]:
        return UNKNOWN
    reading = runtime.beliefs.read(target, valid_at=valid_at, known_at=known_at)
    if reading is UNKNOWN:
        return UNKNOWN
    return PropertyReading(
        None,
        reading,
        tuple(context["reading"]["source_facts"]),
        timestamp(valid_at) if valid_at is not None else None,
        timestamp(known_at) if known_at is not None else None,
        freeze(parameters),
        provenance=freeze(
            {
                "criterion": property_id,
                "norm_revision": context["norm"]["state"]["revision"],
                "input_revision": context["input_revision"],
            }
        ),
    )
