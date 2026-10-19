"""Explicit, versioned population fitting for qualitative property criteria.

Boundaries describe the retained sample. They do not manufacture a categorical
belief: a shared evidence assessment supplies the Profile for an actual subject.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from itertools import pairwise

from .attribution_population import (
    _belief_status,
    _read_belief,
    collect_observations,
    convert_value,
    finite_number,
    validate_reference,
)
from .beliefs import element_target
from .datasets import content_revision
from .graph.matching import values_equal
from .graph.types import GraphDelta, Node, NodeUpdate
from .values import UNKNOWN, ContractError, json_value, utcnow


def norm_definition(definition):
    """Complete a quantile criterion without fitting it or changing graph state."""
    result = dict(definition)
    classes = result.get("classes", ())
    result.setdefault("conditions", {})
    result.setdefault("quantiles", [i / len(classes) for i in range(1, len(classes))])
    result.setdefault("reference", None)
    result.setdefault("min_samples", 3)
    result.setdefault("hysteresis", 0.05)
    return json_value(result)


def semantic_revision(definition, class_meanings):
    """Identify class meaning independently of fitted boundaries and update policy."""
    return content_revision(
        {
            **{
                key: definition[key]
                for key in ("property", "domain", "classes", "conditions", "quantiles", "reference")
            },
            "class_meanings": class_meanings,
        }
    )


def _binding(definition):
    return {
        "scale": "ordinal",
        "source": "norm",
        "classes": list(definition["classes"]),
        "applies_to": [definition["domain"]],
        "required_parameters": sorted(definition["conditions"]),
    }


def validate_norm(node, nodes, parents):
    """Validate the criterion and its retained checkpoint before a graph commit."""
    definition = node.properties.get("qualitative_norm")
    expected = {
        "property",
        "domain",
        "classes",
        "conditions",
        "quantiles",
        "reference",
        "min_samples",
        "hysteresis",
    }
    if (
        node.kind != "property"
        or not isinstance(definition, Mapping)
        or set(definition) != expected
    ):
        raise ContractError("Qualitative norm requires a complete property criterion")
    classes, quantiles = definition["classes"], definition["quantiles"]
    if not isinstance(classes, (list, tuple)) or len(classes) < 2:
        raise ContractError("Qualitative norm requires at least two ordered classes")
    if len(quantiles) != len(classes) - 1:
        raise ContractError("Norm quantiles must separate every ordered class")
    quantiles = [finite_number(value) for value in quantiles]
    if any(not 0 < value < 1 for value in quantiles) or any(a >= b for a, b in pairwise(quantiles)):
        raise ContractError("Norm quantiles must be strictly increasing inside (0, 1)")
    prop = nodes.get(definition["property"])
    unit = prop.properties.get("attribution", {}).get("unit") if prop else None
    validate_reference(
        {
            "property": definition["property"],
            "domain": definition["domain"],
            "unit": unit,
            "reference_kind": "bands",
            "boundaries": quantiles,
            "classes": classes,
            "samples": [],
            "conditions": definition["conditions"],
        },
        nodes,
        parents,
    )
    if type(definition["min_samples"]) is not int or definition["min_samples"] < 1:
        raise ContractError("Norm min_samples must be a positive integer")
    if not 0 <= finite_number(definition["hysteresis"]) <= 1:
        raise ContractError("Norm hysteresis must be a fraction of the observed range")
    if not values_equal(node.properties.get("attribution"), _binding(definition)):
        raise ContractError("Qualitative property declaration must match its norm criterion")
    reference = definition["reference"]
    if reference is not None:
        data = nodes[reference].properties.get("numeric_reference") if reference in nodes else None
        if (
            data is None
            or data["reference_kind"] != "distribution"
            or any(
                not values_equal(data[key], definition[key])
                for key in ("property", "domain", "conditions")
            )
        ):
            raise ContractError("Norm reference requires one matching numeric distribution")
    state = node.properties.get("norm_state")
    # Class edits remain valid graph changes; refresh captures their new meaning.
    meanings = state.get("class_meanings") if isinstance(state, Mapping) else None
    if (
        not isinstance(meanings, (list, tuple))
        or len(meanings) != len(classes)
        or any(
            not isinstance(item, Mapping)
            or set(item) != {"id", "name", "description"}
            or type(item["id"]) is not int
            or item["id"] != identity
            or not isinstance(item["name"], str)
            or (item["description"] is not None and not isinstance(item["description"], str))
            for identity, item in zip(classes, meanings)
        )
    ):
        raise ContractError("Norm checkpoint requires pinned class meanings in class order")
    if state.get("semantic_revision") != semantic_revision(definition, meanings):
        raise ContractError("Norm checkpoint must match the criterion's semantic revision")
    if type(state.get("revision")) is not int or state["revision"] < 1:
        raise ContractError("Norm checkpoint requires a positive revision")
    if state.get("status") not in {"ready", "needs_data", "degenerate"}:
        raise ContractError("Unknown norm checkpoint status")
    rows = state.get("rows")
    if not isinstance(rows, (list, tuple)):
        raise ContractError("Norm checkpoint requires retained rows")
    convert_value(1, state.get("unit"), unit)
    if rows:
        validate_reference(
            {
                "property": definition["property"],
                "domain": definition["domain"],
                "unit": state["unit"],
                "reference_kind": "distribution",
                "boundaries": [],
                "classes": [],
                "samples": rows,
                "conditions": definition["conditions"],
            },
            nodes,
            parents,
        )
    if type(state.get("count")) is not int or state["count"] != sum(row["count"] for row in rows):
        raise ContractError("Norm checkpoint count must describe its retained rows")
    dependencies = state.get("dependencies")
    if not isinstance(dependencies, (list, tuple)) or any(
        not isinstance(item, Mapping)
        or set(item) != {"object", "revision"}
        or any(type(value) is not int or value <= 0 for value in item.values())
        for item in dependencies
    ):
        raise ContractError("Norm checkpoint dependencies require graph identities and revisions")
    expected_revision = content_revision(
        {"rows": rows, "dependencies": dependencies, "conditions": definition["conditions"]}
    )
    if state.get("data_revision") != expected_revision:
        raise ContractError("Norm checkpoint data revision must identify its retained input")
    if (state["count"] < definition["min_samples"]) != (state["status"] == "needs_data"):
        raise ContractError("Norm checkpoint status must respect its minimum sample policy")
    if state["status"] == "ready":
        boundaries = [finite_number(value) for value in state.get("boundaries", ())]
        if len(boundaries) != len(classes) - 1 or any(a >= b for a, b in pairwise(boundaries)):
            raise ContractError("Ready norm requires strictly increasing class boundaries")
        bounds = state.get("boundary_bounds", ())
        if len(bounds) != len(boundaries) or any(
            not isinstance(pair, (list, tuple))
            or len(pair) != 2
            or not finite_number(pair[0]) <= value <= finite_number(pair[1])
            for value, pair in zip(boundaries, bounds)
        ):
            raise ContractError("Norm boundary precision must contain each representative boundary")


def _dependency(graph, identity):
    return {"object": identity, "revision": graph.changes_of(identity)[-1].seq}


def _training_data(runtime, definition):
    graph = runtime.graph
    property_id, domain = definition["property"], definition["domain"]
    unit = runtime.definitions()[property_id].unit
    dependencies = [
        _dependency(graph, identity) for identity in (property_id, domain, *definition["classes"])
    ]
    reference = definition["reference"]
    if reference is None:
        data = collect_observations(runtime, domain, property_id, **definition["conditions"])
        if data.get("status") == "needs_parameters":
            raise ContractError("Norm conditions must supply the numeric property's parameters")
        rows, observations = data["rows"], data["observations"]
        dependencies.extend(_dependency(graph, item["source_fact"]) for item in observations)
        excluded = data["excluded"]
    else:
        source = graph.get(reference).properties["numeric_reference"]
        rows = [
            {
                "lower": convert_value(row["lower"], source["unit"], unit),
                "upper": convert_value(row["upper"], source["unit"], unit),
                "count": row["count"],
            }
            for row in source["samples"]
        ]
        dependencies.append(_dependency(graph, reference))
        observations, excluded = [], []
    revision = content_revision(
        {"rows": rows, "dependencies": dependencies, "conditions": definition["conditions"]}
    )
    return {
        "rows": rows,
        "observations": observations,
        "excluded": excluded,
        "dependencies": dependencies,
        "data_revision": revision,
        "unit": unit,
        "class_meanings": [
            {"id": node.id, "name": node.name, "description": node.description}
            for node in (graph.get(identity) for identity in definition["classes"])
        ],
    }


def _quantile(rows, probability, field):
    count = sum(row["count"] for row in rows)
    rank = (count - 1) * probability

    def at_rank(index):
        for row in rows:
            if index < row["count"]:
                return row[field]
            index -= row["count"]
        raise AssertionError("Rank outside retained norm distribution")

    low, high = math.floor(rank), math.ceil(rank)
    fraction = rank - low
    return at_rank(low) * (1 - fraction) + at_rank(high) * fraction


def fit_norm(definition, data, *, previous=None):
    """Fit explicit weighted quantiles, retaining interval precision and boundary hysteresis."""
    rows = data["rows"]
    count = sum(row["count"] for row in rows)
    meaning = semantic_revision(definition, data["class_meanings"])
    prior = previous if previous and previous["semantic_revision"] == meaning else None
    bounds = (
        [
            [_quantile(rows, q, field) for field in ("lower", "upper")]
            for q in definition["quantiles"]
        ]
        if count
        else []
    )
    boundaries = [math.fsum(value / 2 for value in pair) for pair in bounds]
    status = "needs_data" if count < definition["min_samples"] else "ready"
    if status == "ready" and any(a >= b for a, b in pairwise(boundaries)):
        status = "degenerate"
    held = False
    if status == "ready" and prior and prior["status"] == "ready" and prior["unit"] == data["unit"]:
        span = max(rows[-1]["upper"], prior["rows"][-1]["upper"]) - min(
            rows[0]["lower"], prior["rows"][0]["lower"]
        )
        held = all(
            abs(a - b) <= definition["hysteresis"] * span
            for a, b in zip(boundaries, prior["boundaries"])
        )
        if held:
            boundaries = list(prior["boundaries"])
            bounds = json_value(prior["boundary_bounds"])
    return {
        "semantic_revision": meaning,
        "class_meanings": data["class_meanings"],
        "revision": previous["revision"] + 1 if previous else 1,
        "data_revision": data["data_revision"],
        "status": status,
        "boundaries": boundaries,
        "boundary_bounds": bounds,
        "count": count,
        "rows": json_value(rows),
        "dependencies": data["dependencies"],
        "unit": data["unit"],
        "hysteresis_applied": held,
        "approximate": any(row["lower"] != row["upper"] for row in rows)
        or any(low != high for low, high in bounds),
        "updated_at": utcnow().isoformat(),
    }


def prepare_norm(runtime, name, description, definition, *, identity=None):
    """Prepare one qualitative property and fitted checkpoint as an unapplied graph delta."""
    definition = norm_definition(definition)
    identity = runtime.graph.reserve_id() if identity is None else identity
    data = _training_data(runtime, definition)
    node = Node(
        identity,
        name,
        kind="property",
        description=description,
        properties={
            "attribution": _binding(definition),
            "qualitative_norm": definition,
            "norm_state": fit_norm(definition, data),
        },
    )
    return GraphDelta(creates=(node,)), identity


def refresh_norm(runtime, identity):
    """Prepare a new checkpoint after a data batch; unchanged data produces no update."""
    node = runtime.graph.get(identity)
    definition, previous = node.properties["qualitative_norm"], node.properties["norm_state"]
    data = _training_data(runtime, definition)
    if (
        data["data_revision"] == previous["data_revision"]
        and semantic_revision(definition, data["class_meanings"]) == previous["semantic_revision"]
    ):
        return GraphDelta()
    properties = {**node.properties, "norm_state": fit_norm(definition, data, previous=previous)}
    return GraphDelta(updates=(NodeUpdate(identity, {"properties": properties}),))


def revise_norm(runtime, identity, definition):
    """Replace a criterion explicitly, separating changed meaning from parameter refreshes."""
    node = runtime.graph.get(identity)
    definition = norm_definition(definition)
    data = _training_data(runtime, definition)
    properties = {
        **node.properties,
        "attribution": _binding(definition),
        "qualitative_norm": definition,
        "norm_state": fit_norm(definition, data, previous=node.properties["norm_state"]),
    }
    return GraphDelta(updates=(NodeUpdate(identity, {"properties": properties}),))


def norm_context(runtime, identity):
    """Read a retained norm with all evidence dependencies; stale data returns UNKNOWN."""
    try:
        node = runtime.graph.get(identity)
        definition, state = node.properties["qualitative_norm"], node.properties["norm_state"]
        data = _training_data(runtime, definition)
    except (KeyError, ContractError):
        return UNKNOWN
    if state["data_revision"] != data["data_revision"] or state[
        "semantic_revision"
    ] != semantic_revision(definition, data["class_meanings"]):
        return UNKNOWN
    belief = _read_belief(runtime, element_target(node), None)
    provenance = [
        runtime.graph.changes_of(item["object"])[-1].provenance for item in data["dependencies"]
    ]
    return {
        "definition": json_value(definition),
        "state": json_value(state),
        **data,
        "source_refs": [
            json_value(item)
            for item in provenance
            if isinstance(item, Mapping) and "event_ref" in item
        ],
        "model_belief_data": json_value(belief.data) if belief is not None else None,
        "model_belief_status": _belief_status(belief),
    }


def interpret_norm(runtime, identity, value, *, unit=None, parameters=None):
    """Apply a retained norm conditionally without training or inventing epistemic confidence."""
    context = norm_context(runtime, identity)
    if context is UNKNOWN or context["state"]["status"] != "ready":
        return UNKNOWN
    state, definition = context["state"], context["definition"]
    if not values_equal(parameters or {}, definition["conditions"]):
        return UNKNOWN
    value = convert_value(value, unit, state["unit"])
    boundaries = state["boundaries"]
    index = next((i for i, boundary in enumerate(boundaries) if value <= boundary), len(boundaries))
    possible = [
        label
        for i, label in enumerate(definition["classes"])
        if (not i or value > state["boundary_bounds"][i - 1][0])
        and (i == len(boundaries) or value <= state["boundary_bounds"][i][1])
    ]
    return {
        "kind": "conditional_norm_result",
        "class": definition["classes"][index],
        "value": value,
        "unit": state["unit"],
        "lower_bound": boundaries[index - 1] if index else None,
        "upper_bound": boundaries[index] if index < len(boundaries) else None,
        "lower_inclusive": False if index else None,
        "upper_inclusive": True if index < len(boundaries) else None,
        "norm": identity,
        "norm_revision": state["revision"],
        "semantic_revision": state["semantic_revision"],
        "approximate": state["approximate"],
        "possible_classes": possible,
        "boundary_bounds": state["boundary_bounds"],
        "count": state["count"],
        "domain": definition["domain"],
        "conditions": definition["conditions"],
        "reference": definition["reference"],
        "model_belief_data": context["model_belief_data"],
        "model_belief_status": context["model_belief_status"],
        "source_refs": context["source_refs"][:20],
        "source_refs_total": len(context["source_refs"]),
    }
