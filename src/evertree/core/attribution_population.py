"""Source-preserving numeric summaries and conditional reference interpretations."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from itertools import pairwise

from .beliefs import element_target
from .datasets import content_revision
from .graph.matching import values_equal
from .graph.types import Facet
from .values import UNKNOWN, ContractError, json_value, timestamp

_UNITS = {
    "kg": ("mass", 1.0),
    "g": ("mass", 0.001),
    "mg": ("mass", 0.000001),
    "lb": ("mass", 0.45359237),
    "oz": ("mass", 0.028349523125),
    "m": ("length", 1.0),
    "cm": ("length", 0.01),
    "mm": ("length", 0.001),
    "km": ("length", 1000.0),
    "s": ("time", 1.0),
    "ms": ("time", 0.001),
    "us": ("time", 0.000001),
}
_UNIT_ALIASES = {
    "кг": "kg",
    "г": "g",
    "мг": "mg",
    "м": "m",
    "см": "cm",
    "мм": "mm",
    "км": "km",
    "с": "s",
    "мс": "ms",
    "мкс": "us",
    "µs": "us",
    "μs": "us",
}


def finite_number(value):
    """Validate a finite scalar, excluding boolean values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError("Expected a finite numeric value")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ContractError("Expected a finite numeric value")
    return float(value)


def convert_value(value, source_unit, target_unit):
    """Convert declared compatible units; missing units never imply a physical unit."""
    value = finite_number(value)
    if source_unit == target_unit:
        return value
    source = _UNITS.get(_UNIT_ALIASES.get(source_unit, source_unit))
    target = _UNITS.get(_UNIT_ALIASES.get(target_unit, target_unit))
    if source is None or target is None or source[0] != target[0]:
        raise ContractError(f"Cannot convert {source_unit!r} to {target_unit!r}")
    return finite_number(value * source[1] / target[1])


def validate_reference(reference, nodes, parents):
    """Validate a graph-backed numeric reference and every dependency before commit."""
    from .attribution import PropertyDefinition, validate_parameters

    expected = {
        "property",
        "domain",
        "unit",
        "reference_kind",
        "boundaries",
        "classes",
        "samples",
        "conditions",
    }
    if not isinstance(reference, Mapping) or set(reference) - {"boundary_inclusive"} != expected:
        raise ContractError("Numeric reference requires its complete declared contract")
    prop, domain = nodes.get(reference["property"]), nodes.get(reference["domain"])
    if prop is None or prop.kind != "property":
        raise ContractError("Numeric reference requires an existing property")
    if domain is None or domain.kind != "prototype":
        raise ContractError(
            f"Numeric reference domain {reference['domain']} requires a population type "
            f"(prototype); got {domain.kind if domain is not None else 'missing'}"
        )
    definition = prop.properties.get("attribution")
    if (
        not isinstance(definition, Mapping)
        or definition.get("scale", "numeric") != "numeric"
        or definition.get("source", "numeric") != "numeric"
    ):
        raise ContractError("Numeric reference requires a declared numeric fact property")
    ancestors = {domain.id}
    current = domain.id
    while current in parents:
        current = parents[current]
        ancestors.add(current)
    if definition.get("applies_to") and not ancestors.intersection(definition["applies_to"]):
        raise ContractError("Reference population is outside the property's domain")
    unit = reference["unit"]
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise ContractError("Reference unit must be a nonempty unit or null")
    convert_value(1, unit, definition.get("unit"))
    validate_parameters(reference["conditions"])
    contract = PropertyDefinition(id=prop.id, **definition)
    conditions = reference["conditions"]
    if set(contract.required_parameters) - conditions.keys():
        raise ContractError("Reference conditions must supply required property parameters")
    contract.validate_inputs(conditions, nodes)
    if any(
        kind == "node" and conditions.get(name) not in nodes
        for name, kind in contract.parameter_types.items()
        if name in conditions
    ):
        raise ContractError("Reference node parameters require existing graph identities")
    boundaries, classes, samples = (
        reference["boundaries"],
        reference["classes"],
        reference["samples"],
    )
    inclusivity = reference.get("boundary_inclusive", [True] * len(boundaries))
    if len(inclusivity) != len(boundaries) or any(type(item) is not bool for item in inclusivity):
        raise ContractError("Each band boundary requires a boolean inclusion policy")
    if reference["reference_kind"] == "bands":
        if samples or not boundaries or len(classes) != len(boundaries) + 1:
            raise ContractError("Bands require ordered boundaries, one more class, and no samples")
        if len(set(classes)) != len(classes) or any(
            type(identity) is not int
            or identity not in nodes
            or nodes[identity].kind not in {"concept", "prototype"}
            for identity in classes
        ):
            raise ContractError("Bands require distinct existing class concepts")
        values = [finite_number(value) for value in boundaries]
        if any(a >= b for a, b in pairwise(values)):
            raise ContractError("Band boundaries must be strictly increasing")
    elif reference["reference_kind"] == "distribution":
        if boundaries or classes or not samples:
            raise ContractError("A distribution requires samples, not classification bands")
        previous = None
        for sample in samples:
            if not isinstance(sample, Mapping) or set(sample) != {"lower", "upper", "count"}:
                raise ContractError("Distribution rows require lower, upper and count")
            lower, upper = finite_number(sample["lower"]), finite_number(sample["upper"])
            if lower > upper or previous is not None and lower < previous:
                raise ContractError("Distribution rows must be ordered nonoverlapping intervals")
            if type(sample["count"]) is not int or sample["count"] <= 0:
                raise ContractError("Distribution counts must be positive integers")
            previous = upper
    else:
        raise ContractError("Unknown numeric reference kind")


def _statistics(rows, value):
    count = sum(row["count"] for row in rows)
    if not count:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}

    def at_rank(rank, field):
        for row in rows:
            if rank < row["count"]:
                return row[field]
            rank -= row["count"]
        raise AssertionError("Rank outside distribution")

    def quantile(p, field):
        index = (count - 1) * p
        low, high = math.floor(index), math.ceil(index)
        fraction = index - low
        return at_rank(low, field) * (1 - fraction) + at_rank(high, field) * fraction

    means = [
        math.fsum(row[field] * (row["count"] / count) for row in rows)
        for field in ("lower", "upper")
    ]
    medians = [quantile(0.5, field) for field in ("lower", "upper")]
    approximate = any(row["lower"] != row["upper"] for row in rows)
    result = {
        "count": count,
        "mean": math.fsum(v / 2 for v in means),
        "median": math.fsum(v / 2 for v in medians),
        "min": rows[0]["lower"],
        "max": rows[-1]["upper"],
        "approximate": approximate,
    }
    if approximate:
        result.update(mean_bounds=means, median_bounds=medians, estimate="interval_midpoints")
    if value is not None:
        result["comparison"] = {
            "value": value,
            "difference_from_mean": value - result["mean"],
            "count_below_value": sum(row["count"] for row in rows if row["upper"] < value),
            "count_above_value": sum(row["count"] for row in rows if row["lower"] > value),
            "count_overlapping_or_equal": sum(
                row["count"] for row in rows if row["lower"] <= value <= row["upper"]
            ),
        }
    return result


def _provenance(graph, identity):
    change = graph.changes_of(identity)[-1]
    return {"object": identity, "revision": change.seq, "provenance": json_value(change.provenance)}


def _read_belief(runtime, target, at):
    if target is None:
        return None
    try:
        reading = runtime.beliefs.read(target, valid_at=at, known_at=runtime.graph.known_at)
    except KeyError:
        return None
    return None if reading is UNKNOWN else reading


def _belief_status(reading):
    if reading is None:
        return "unassessed"
    return "assessed" if reading.stats.evidence_count else "prior_only"


def _population_belief(runtime, domain, property_id, sources, parameters, at):
    revision = content_revision(
        json_value(
            {
                "sources": sources,
                "conditions": parameters,
                "at": at,
                "property": _provenance(runtime.graph, property_id),
                "domain": _provenance(runtime.graph, domain),
            }
        )
    )
    target = f"numeric-population:{domain}:{property_id}:{revision}"
    reading = _read_belief(runtime, target, at)
    return {
        "belief_target": target,
        "belief_data": json_value(reading.data) if reading is not None else None,
        "belief_status": _belief_status(reading),
        "belief_meaning": "This source describes the requested population under these conditions",
    }


def collect_observations(runtime, domain, property_id, *, valid_at=None, **parameters):
    """Collect every selected individual and source for summaries and explicit norm fitting."""
    graph = runtime.graph
    domain_node = graph.get(domain)
    if domain_node.kind != "prototype":
        raise ContractError("Population summaries require a prototype/type domain")
    definition = runtime.definitions().get(property_id)
    if definition is None or definition.scale != "numeric" or definition.source != "numeric":
        raise ContractError("Population summaries require a property with a numeric fact source")
    ancestors = {node.id for node in graph.ancestors(domain)} | {domain}
    if definition.applies_to and not ancestors.intersection(definition.applies_to):
        raise ContractError("Property is not declared for this population")
    at = timestamp(valid_at) if valid_at is not None else None
    target_unit = definition.unit
    missing = set(definition.required_parameters) - parameters.keys()
    if missing:
        return {"status": "needs_parameters", "required_parameters": sorted(missing)}
    types = {
        node.id
        for node in graph.nodes(kind="prototype")
        if node.id == domain or domain in {parent.id for parent in graph.ancestors(node.id)}
    }
    individuals = {
        fact.args["instance"] for fact in graph.facts("IDENTITY_TYPE") if fact.args["type"] in types
    }
    owners = {fact.args["facet"]: fact.args["instance"] for fact in graph.facts("STATE_IDENTITY")}
    candidates, exclusions = {}, []
    for fact in graph.facts("HAS_NUMERIC_VALUE"):
        subject = fact.args["entity"]
        owner = owners.get(subject, subject)
        if owner not in individuals or fact.args["property"] != property_id:
            continue
        if not values_equal(fact.properties.get("conditions", {}), parameters):
            continue
        if at is not None and graph.fact_applicability(fact, at) != "applicable":
            exclusions.append({"fact": fact.id, "reason": "temporal_applicability"})
            continue
        candidates.setdefault(owner, []).append(fact)
    observations, rows = [], []
    for owner, facts in sorted(candidates.items()):
        if at is not None:
            reading = runtime.read_property(
                owner, property_id, valid_at=at, known_at=graph.known_at, **parameters
            )
            if reading is UNKNOWN or len(reading.source_facts) != 1:
                exclusions.append({"subject": owner, "reason": "unresolved_property_reading"})
                continue
            fact = graph.get(reading.source_facts[0])
        else:
            fact = max(facts, key=runtime._fact_recency)
        try:
            numeric = convert_value(fact.args["value"], fact.args.get("unit"), target_unit)
        except ContractError as exc:
            exclusions.append({"fact": fact.id, "reason": str(exc)})
            continue
        belief = _read_belief(runtime, element_target(fact), at)
        subject = graph.get(fact.args["entity"])
        observation = {
            "subject": owner,
            "name": graph.get(owner).name,
            "value": numeric,
            "source_fact": fact.id,
            "source": _provenance(graph, fact.id),
            "belief_data": json_value(belief if belief.profile is not None else belief.data)
            if belief is not None
            else None,
            "belief_status": _belief_status(belief),
        }
        if isinstance(subject, Facet):
            observation.update(
                valid_from=subject.valid_from.isoformat() if subject.valid_from else None,
                valid_until=subject.valid_until.isoformat() if subject.valid_until else None,
            )
        observations.append(observation)
        rows.append({"lower": numeric, "upper": numeric, "count": 1})
    rows.sort(key=lambda row: row["lower"])
    return {
        "observations": observations,
        "rows": rows,
        "excluded": exclusions,
        "unit": target_unit,
        "at": at,
    }


def summarize_property(
    runtime,
    domain,
    property_id,
    *,
    value=None,
    unit=None,
    reference=None,
    valid_at: datetime | None = None,
    **parameters,
):
    """Summarize recorded individuals and separate references without training or belief writes.

    With no valid_at, use each individual's latest recorded measurement, including historical
    reports. Explicit world time restricts observations to applicable facts. Reference results
    are conditional calculations; neither class membership nor population reliability is implied.
    """
    graph = runtime.graph
    collected = collect_observations(runtime, domain, property_id, valid_at=valid_at, **parameters)
    if collected.get("status") == "needs_parameters":
        return collected
    observations, rows, exclusions = (
        collected[key] for key in ("observations", "rows", "excluded")
    )
    target_unit, at = collected["unit"], collected["at"]
    supplied = convert_value(value, unit, target_unit) if value is not None else None
    if value is None and unit is not None:
        raise ContractError("A comparison unit requires a comparison value")
    sources = [item["source"] for item in observations]
    nearest = None
    if supplied is not None and observations:
        closest = min(observations, key=lambda item: abs(item["value"] - supplied))["value"]
        distance = abs(closest - supplied)
        precision = 2 * max(math.ulp(closest), math.ulp(supplied))
        # Cover subtraction/conversion rounding with two input ulps; exact matches stay exact.
        matches = [
            {key: item[key] for key in ("subject", "name", "value")}
            for item in observations
            if abs(item["value"] - supplied) == distance
            or distance > 0
            and math.isclose(
                abs(item["value"] - supplied),
                distance,
                rel_tol=0,
                abs_tol=max(precision, 2 * math.ulp(item["value"])),
            )
        ]
        nearest = {"distance": distance, "items": matches[:20], "items_total": len(matches)}
    observed = {
        **_statistics(rows, supplied),
        "basis": "reported_individuals",
        "items": observations[:20],
        "items_total": len(observations),
        "nearest": nearest,
        **_population_belief(runtime, domain, property_id, sources, parameters, at),
    }
    references, reference_candidates = [], []
    for node in graph.nodes():
        data = node.properties.get("numeric_reference")
        if data is None or reference is not None and node.id != reference:
            continue
        if data["property"] != property_id:
            continue
        if data["domain"] != domain or not values_equal(data["conditions"], parameters):
            reference_candidates.append(
                {
                    "id": node.id,
                    "name": node.name,
                    "domain": {"id": data["domain"], "name": graph.get(data["domain"]).name},
                    "conditions": json_value(data["conditions"]),
                    "status": "different_population"
                    if data["domain"] != domain
                    else "needs_matching_parameters",
                }
            )
            continue
        provenance = _provenance(graph, node.id)
        source_belief = _read_belief(runtime, element_target(node), at)
        result = {
            "id": node.id,
            "name": node.name,
            "description": node.description,
            "reference_kind": data["reference_kind"],
            "conditions": json_value(data["conditions"]),
            "source": provenance,
            "source_belief_data": json_value(source_belief.data)
            if source_belief is not None
            else None,
            "source_belief_status": _belief_status(source_belief),
            **_population_belief(
                runtime,
                domain,
                property_id,
                [provenance, *(_provenance(graph, identity) for identity in data["classes"])],
                parameters,
                at,
            ),
        }
        if data["reference_kind"] == "bands":
            boundaries = [convert_value(v, data["unit"], target_unit) for v in data["boundaries"]]
            inclusivity = data.get("boundary_inclusive", [True] * len(boundaries))
            classes = [
                {"id": identity, "name": graph.get(identity).name} for identity in data["classes"]
            ]
            result.update(
                boundaries=boundaries[:20],
                classes=classes[:21],
                bands_total=len(classes),
                boundary_inclusive=list(inclusivity[:20]),
            )
            if supplied is not None:
                index = next(
                    (
                        i
                        for i, bound in enumerate(boundaries)
                        if supplied < bound or inclusivity[i] and supplied == bound
                    ),
                    len(boundaries),
                )
                result["interpretation"] = {
                    "kind": "conditional_rule_result",
                    "value": supplied,
                    "class": classes[index],
                    "lower_bound": boundaries[index - 1] if index else None,
                    "upper_bound": boundaries[index] if index < len(boundaries) else None,
                    "lower_inclusive": not inclusivity[index - 1] if index else None,
                    "upper_inclusive": inclusivity[index] if index < len(boundaries) else None,
                    "assumption": "The reported value and this reference apply",
                }
        else:
            table = [
                {
                    "lower": convert_value(row["lower"], data["unit"], target_unit),
                    "upper": convert_value(row["upper"], data["unit"], target_unit),
                    "count": row["count"],
                }
                for row in data["samples"]
            ]
            result["summary"] = {**_statistics(table, supplied), "basis": "reported_distribution"}
        references.append(result)
    if reference is not None and not references and not reference_candidates:
        raise ContractError("Reference does not match this property, population and conditions")
    return {
        "domain": domain,
        "property": property_id,
        "unit": target_unit,
        "time_basis": "world_time" if at else "latest_recorded",
        "at": at.isoformat() if at else None,
        "conditions": json_value(parameters),
        "observations": observed,
        "references": references[:20],
        "references_total": len(references),
        "reference_candidates": reference_candidates[:20],
        "reference_candidates_total": len(reference_candidates),
        "excluded": exclusions[:20],
        "excluded_total": len(exclusions),
        "interpretation_status": "conditional_on_reported_sources",
    }
