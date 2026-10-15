"""Compact named reads shared by consciousness and semantic Programs."""

from ..graph.types import Facet, Prototype, RelationInstance, RelationType
from ..values import UNKNOWN, ContractError, json_value, timestamp, utcnow


def card(node):
    result = {"id": node.id, "name": node.name, "kind": node.kind, "description": node.description}
    if isinstance(node, Facet):
        result.update(
            valid_from=node.valid_from.isoformat() if node.valid_from else None,
            valid_until=node.valid_until.isoformat() if node.valid_until else None,
        )
    return result


def resolve(graph, subject):
    matches = graph.lookup(subject)
    if len(matches) != 1:
        return {
            "status": "ambiguous" if matches else "not_found",
            "candidates": [card(n) for n in matches],
        }
    return matches[0]


def fact_nodes(graph, fact):
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
    return result


def read_property(graph, attribution, subject, property, at=None, parameters=None):
    node, prop = resolve(graph, subject), resolve(graph, property)
    if isinstance(node, dict):
        return node
    if isinstance(prop, dict):
        return prop
    parameters = parameters or {}
    definition = attribution.definitions().get(prop.id)
    if set(parameters) & {"subject", "property", "valid_at", "known_at", "_compute"}:
        raise ContractError("Temporal service arguments are not property parameters")
    if definition and (missing := set(definition.required_parameters) - parameters.keys()):
        return {"status": "needs_parameters", "required_parameters": sorted(missing)}
    return json_value(
        attribution.read_property(
            node.id, prop.id, valid_at=timestamp(at) if at else utcnow(), **parameters
        )
    )


def describe(graph, attribution, subject, focus=None, at=None):
    node = resolve(graph, subject)
    if isinstance(node, dict):
        return node
    when = timestamp(at) if at else utcnow()
    properties = []
    definitions = () if focus == "relations" else attribution.properties_for(node.id, at=when)
    for definition in definitions:
        prop = graph.get(definition.id)
        item = {**card(prop), "required_parameters": list(definition.required_parameters)}
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
    if focus not in (None, "", "properties", "relations"):
        term = focus.casefold()
        properties = [p for p in properties if term in str(p).casefold()]
    if focus != "relations":
        _preview(result, "properties", properties, None if focus else 7)
    if isinstance(node, Facet) and at is not None:
        result["subject"]["temporal_status"] = node.applicability(when)
    if focus != "properties":
        if isinstance(node, Prototype):
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
            _preview(result, "children", children, 7)
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
