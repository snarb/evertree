"""Compact named reads shared by consciousness and semantic Programs."""

from ..graph.types import Facet, RelationInstance, RelationType
from ..values import UNKNOWN, ContractError, json_value, timestamp, utcnow


def card(node):
    return {"id": node.id, "name": node.name, "kind": node.kind, "description": node.description}


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
    return {
        **card(fact),
        "relation": relation.name,
        "args": args,
        "belief_target": fact.belief_target,
        "provenance": json_value(graph.changes_of(fact.id)[-1].provenance),
    }


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
    for definition in attribution.properties_for(node.id, at=when):
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
    result = {"subject": card(node), "at": when.isoformat(), "properties": properties}
    if focus != "properties":

        def current(fact):
            return all(
                not isinstance(subject, Facet)
                or subject.valid_from <= when
                and (subject.valid_until is None or when < subject.valid_until)
                for subject in (graph.get(i) for i in fact_nodes(graph, fact))
            )

        facts = [f for f in graph.facts() if node.id in fact_nodes(graph, f) and current(f)]
        if focus:
            term = focus.casefold()
            facts = [f for f in facts if term in str(fact_card(graph, f)).casefold()]
            result["properties"] = [p for p in properties if term in str(p).casefold()]
        result["relations"] = [fact_card(graph, f) for f in facts[:20]]
        result["relations_truncated"] = len(facts) > 20
        if isinstance(node, RelationType):
            result["schema"] = json_value(node)
        elif isinstance(node, RelationInstance):
            result["fact"] = fact_card(graph, node)
    return result
