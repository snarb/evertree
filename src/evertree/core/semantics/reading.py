"""Compact named reads shared by consciousness and semantic Programs."""

from ..attribution import validate_parameters
from ..beliefs import element_target
from ..graph.types import Facet, RelationInstance, RelationType
from ..values import UNKNOWN, json_value, timestamp, utcnow


def card(node):
    """Project a graph node into a compact semantic search or read result."""
    result = {"id": node.id, "name": node.name, "kind": node.kind, "description": node.description}
    if isinstance(node, Facet):
        result.update(
            valid_from=node.valid_from.isoformat() if node.valid_from else None,
            valid_until=node.valid_until.isoformat() if node.valid_until else None,
        )
    return result


def search_card(graph, node):
    """Expose stored meaning for retrieval without provenance or computed beliefs."""
    result = card(node)
    properties = {key: value for key, value in node.properties.items() if key != "template"}
    if properties:
        result["properties"] = json_value(properties)
    relation = (
        node
        if isinstance(node, RelationType)
        else graph.get(node.relation_type)
        if isinstance(node, RelationInstance)
        else None
    )
    if relation is not None:
        result["signature"] = json_value(relation.signature)
        result["semantic_signature"] = [
            {
                "label": slot.label,
                "value_type": slot.value_type,
                "value_concept": card(graph.get(slot.value_concept))
                if slot.value_concept
                else None,
                "role_concept": card(graph.get(slot.role_concept)) if slot.role_concept else None,
            }
            for slot in relation.signature
        ]
    references = []
    for relation_name in ("ABOUT", "RELATION_SUBJECT"):
        references.extend(
            {"relation": relation_name, "target": card(graph.get(fact.args["target"]))}
            for fact in graph.facts(relation_name)
            if fact.args["source"] == node.id
        )
    if references:
        result["semantic_links"] = references
    if isinstance(node, RelationInstance):
        relation = graph.get(node.relation_type)
        result["relation"] = relation.name
        if relation.description:
            result["relation_description"] = relation.description
        result["args"] = json_value(node.args)

        def reference(identity):
            participant = graph.get(identity)
            return {"id": participant.id, "name": participant.name, "kind": participant.kind}

        for slot in relation.signature:
            if slot.value_type not in {"node", "concept", "prototype", "instance", "facet"}:
                continue
            value = node.args.get(slot.label)
            if isinstance(value, (list, tuple)):
                result["args"][slot.label] = [reference(identity) for identity in value]
            elif value is not None:
                result["args"][slot.label] = reference(value)
    return result


def belief_summary(graph, node):
    """Read an element's current belief compactly, or None when it has not been assessed."""
    if graph.belief_reader is None:
        return None
    try:
        reading = graph.belief_reader(element_target(node))
    except KeyError:
        return None
    if reading is UNKNOWN:
        return {"status": "unknown"}
    result = {
        "strength": round(reading.strength, 3),
        "support": round(reading.support, 3),
        "prior_support": round(reading.prior_support, 3),
        "evidence_count": reading.stats.evidence_count,
    }
    if reading.profile is not None:
        result["profile"] = {key: round(value, 3) for key, value in reading.profile.items()}
    return result


def resolve(graph, subject):
    """Resolve a single graph subject, returning explicit ambiguity or absence when necessary."""
    matches = graph.lookup(subject)
    if len(matches) != 1:
        return {
            "status": "ambiguous" if matches else "not_found",
            "candidates": [card(n) for n in matches],
        }
    return matches[0]


def fact_nodes(graph, fact):
    """Collect graph identities from the node-valued slots of a relation instance."""
    relation = graph.get(fact.relation_type)
    result = set()
    for slot in relation.signature:
        if slot.value_type not in {"node", "concept", "prototype", "instance", "facet"}:
            continue
        value = fact.args.get(slot.label)
        values = value if isinstance(value, (list, tuple)) else (value,)
        result.update(v for v in values if type(v) is int)
    return result


def fact_card(graph, fact):
    """Expand a relation instance with participant cards and its latest producer provenance."""
    relation = graph.get(fact.relation_type)
    args = dict(fact.args)
    for slot in relation.signature:
        if slot.value_type in {"node", "concept", "prototype", "instance", "facet"}:
            value = args.get(slot.label)
            if isinstance(value, (tuple, list)):
                args[slot.label] = [card(graph.get(v)) for v in value]
            elif value is not None:
                args[slot.label] = card(graph.get(value))
    result = {
        **card(fact),
        "relation": relation.name,
        "args": args,
        "belief_target": fact.belief_target,
        "provenance": json_value(graph.changes_of(fact.id)[-1].provenance),
    }
    if fact.properties:
        result["properties"] = json_value(fact.properties)
    if (belief := belief_summary(graph, fact)) is not None:
        result["belief"] = belief
    return result


def read_property(
    graph, attribution, subject, property, at=None, parameters=None, point_policy=None
):
    """Resolve semantic names and read a property, reporting missing parameters explicitly."""
    node, prop = resolve(graph, subject), resolve(graph, property)
    if isinstance(node, dict):
        return node
    if isinstance(prop, dict):
        return prop
    parameters = parameters or {}
    definition = attribution.definitions().get(prop.id)
    validate_parameters(parameters)
    if definition and (missing := set(definition.required_parameters) - parameters.keys()):
        return {"status": "needs_parameters", "required_parameters": sorted(missing)}
    return json_value(
        attribution.read_property(
            node.id,
            prop.id,
            valid_at=timestamp(at) if at else None,
            point_policy=point_policy,
            **parameters,
        )
    )


def interpret_property(graph, attribution, property, value, unit=None, parameters=None):
    """Resolve a learned property and apply its retained norm to a hypothetical value."""
    from ..attribution_norms import interpret_norm

    prop = resolve(graph, property)
    if isinstance(prop, dict):
        return prop
    return json_value(interpret_norm(attribution, prop.id, value, unit=unit, parameters=parameters))


def select_properties(
    graph, attribution, subjects, filters=(), order_by=None, limit=20, at=None, parameters=None
):
    """Select candidates through their declared property readings, preserving unknown results."""
    from ..attribution_selection import select_properties as select

    return json_value(
        select(
            attribution,
            subjects,
            filters=filters,
            order_by=order_by,
            limit=limit,
            valid_at=timestamp(at) if at else None,
            parameters=parameters,
        )
    )


def summarize_property(
    graph,
    attribution,
    domain,
    property,
    value=None,
    unit=None,
    reference=None,
    at=None,
    parameters=None,
):
    """Resolve a numeric summary's domain, property and optional source reference."""
    domain_node, prop = resolve(graph, domain), resolve(graph, property)
    if isinstance(domain_node, dict):
        return domain_node
    if isinstance(prop, dict):
        return prop
    if reference is not None:
        reference = resolve(graph, reference)
        if isinstance(reference, dict):
            return reference
        reference = reference.id
    parameters = parameters or {}
    validate_parameters(parameters)
    return json_value(
        attribution.summarize_property(
            domain_node.id,
            prop.id,
            value=value,
            unit=unit,
            reference=reference,
            valid_at=timestamp(at) if at else None,
            **parameters,
        )
    )


def describe(graph, attribution, subject, focus=None, at=None):
    """Describe a subject's available properties and relation neighborhood without running bound Programs."""
    node = resolve(graph, subject)
    if isinstance(node, dict):
        return node
    when = timestamp(at) if at else utcnow()
    properties = []
    definitions = () if focus == "relations" else attribution.properties_for(node.id, at=when)
    for definition in definitions:
        prop = graph.get(definition.id)
        item = {
            **card(prop),
            "scale": definition.scale,
            "unit": definition.unit,
            "classes": list(definition.classes),
            "required_parameters": list(definition.required_parameters),
            "parameter_types": json_value(definition.parameter_types),
        }
        if definition.required_parameters:
            item["status"] = "needs_parameters"
        else:
            reading = attribution.read_property(node.id, prop.id, valid_at=when, _compute=False)
            if reading is UNKNOWN and definition.source == "program":
                item["status"] = "requires_computation"
            else:
                item.update(
                    status="unknown" if reading is UNKNOWN else "known", reading=json_value(reading)
                )
        properties.append(item)
    result = {
        "subject": card(node),
        "at": when.isoformat() if at is not None else None,
    }
    if not isinstance(node, RelationInstance) and (belief := belief_summary(graph, node)):
        result["subject"]["belief"] = belief
    definitions = {
        key: json_value(node.properties[key])
        for key in (
            "aliases",
            "examples",
            "counterexamples",
            "template",
            "specialization",
            "attribution",
            "numeric_reference",
            "qualitative_norm",
            "norm_state",
            "attribution_result",
        )
        if key in node.properties
    }
    if state := definitions.get("norm_state"):
        for field in ("rows", "dependencies"):
            if len(state.get(field, [])) > 20:
                state[field + "_total"] = len(state[field])
                state[field] = state[field][:20]
                state["truncated"] = True
    if reference := definitions.get("numeric_reference"):
        for field, limit in (
            ("samples", 20),
            ("boundaries", 20),
            ("boundary_inclusive", 20),
            ("classes", 21),
        ):
            if len(reference.get(field, [])) > limit:
                reference[field + "_total"] = len(reference[field])
                reference[field] = reference[field][:limit]
                reference["truncated"] = True
        if reference.get("truncated"):
            reference["details"] = (
                "Preview only; use query with fields=['properties'] for the complete reference."
            )
    if definitions:
        result["subject"]["properties"] = definitions
    if focus not in (None, "", "properties", "relations"):
        term = focus.casefold()
        properties = [p for p in properties if term in str(p).casefold()]
    if focus != "relations":
        _preview(result, "properties", properties, None if focus else 7)
    if isinstance(node, Facet) and at is not None:
        result["subject"]["temporal_status"] = node.applicability(when)
    if focus != "properties":
        if node.kind in {"prototype", "process", "relation_type", "property"}:
            # Many instances can fill the relation preview before a later parent link.
            result["parent"] = next(
                (
                    card(graph.get(fact.args["supertype"]))
                    for fact in graph.facts("SUBTYPE_OF")
                    if fact.args["type"] == node.id
                ),
                None,
            )
            children = [
                graph.get(fact.args["type"]).name
                for fact in graph.facts("SUBTYPE_OF")
                if fact.args["supertype"] == node.id
            ]
            _preview(result, "children", children, None if focus == "children" else 7)
            if len(children) > 7 and focus != "children":
                result["children_read"] = (
                    "Use describe with focus='children' for every child, or SUBTYPE_OF.get_subtypes."
                )
        facts = []
        for fact in graph.facts():
            if node.id not in fact_nodes(graph, fact):
                continue
            item = fact_card(graph, fact)
            if at is not None:
                status = graph.fact_applicability(fact, when)
                if status == "outside":
                    continue
                item["temporal_status"] = status
            facts.append(item)
        if focus and focus != "relations":
            term = focus.casefold()
            facts = [f for f in facts if term in str(f).casefold()]
        _preview(result, "relations", facts, None if focus == "relations" else 7)
        if isinstance(node, RelationType):
            result["schema"] = json_value(node)
        elif isinstance(node, RelationInstance):
            result["fact"] = fact_card(graph, node)
            if at is not None:
                result["fact"]["temporal_status"] = graph.fact_applicability(node, when)
    return result


def _preview(result, name, items, limit):
    if limit is not None and len(items) > limit:
        result[name + "_total"] = len(items)
    result[name] = items if limit is None else items[:limit]
