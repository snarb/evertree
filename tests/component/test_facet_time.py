"""Undated states stay structured without becoming facts about the present."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from evertree.core.attribution import AttributionRuntime
from evertree.core.graph.store import GraphStore
from evertree.core.graph.types import (
    AccessView,
    Facet,
    GraphDelta,
    Instance,
    Node,
    Prototype,
    RelationType,
    Slot,
)
from evertree.core.semantics.reading import describe
from evertree.core.values import UNKNOWN, ContractError

START = datetime(2025, 1, 1, tzinfo=UTC)
END = START + timedelta(days=1)


@pytest.mark.parametrize(
    ("start", "end", "at", "expected"),
    [
        (None, None, START, "unknown"),
        (START, None, START - timedelta(seconds=1), "outside"),
        (START, None, START, "applicable"),
        (START, None, START + timedelta(seconds=1), "unknown"),
        (None, END, START, "unknown"),
        (None, END, END, "outside"),
        (START, END, START, "applicable"),
        (START, END, END, "outside"),
    ],
)
def test_known_bounds_distinguish_inapplicability_from_unknown(start, end, at, expected):
    facet = Facet(1, "Observed state", valid_from=start, valid_until=end)
    assert facet.applicability(at) == expected


def world_with_unknown_state():
    graph = GraphStore()
    graph.bootstrap(provenance="bootstrap")
    prototype = Prototype(graph.reserve_id(), "Pump")
    instance = Instance(graph.reserve_id(), "Pump One")
    unknown = Facet(graph.reserve_id(), "After repair", description="Calendar time unknown")
    known = Facet(graph.reserve_id(), "Observed run", valid_from=START, valid_until=END)
    links = (
        graph.new_fact("IDENTITY_TYPE", {"instance": instance.id, "type": prototype.id}),
        graph.new_fact("STATE_IDENTITY", {"instance": instance.id, "facet": unknown.id}),
        graph.new_fact("STATE_IDENTITY", {"instance": instance.id, "facet": known.id}),
    )
    graph.apply(
        GraphDelta(creates=(prototype, instance, unknown, known, *links)), provenance="input"
    )
    return graph, instance, unknown, known


def test_unknown_boundaries_survive_restore_and_dated_views_do_not_claim_complete_results():
    graph, instance, unknown, known = world_with_unknown_state()
    assert unknown.valid_from is None and unknown.valid_until is None
    graph = GraphStore.from_snapshot(json.loads(json.dumps(graph.snapshot())))
    assert {f.id for f in graph.get_facets(instance)} == {unknown.id, known.id}
    assert graph.get_facets(instance, valid_at=START) is UNKNOWN
    graph.apply(graph.close_facet_state(unknown.id, END), provenance="end established")
    assert graph.get_facets(instance, valid_at=END) == ()
    assert graph.get_facets(instance, valid_at=START) is UNKNOWN
    with pytest.raises(ContractError, match="nonempty"):
        Facet(1, "Invalid interval", valid_from=END, valid_until=START)


def test_describe_preserves_unknown_time_and_structural_navigation():
    graph, instance, unknown, known = world_with_unknown_state()
    attribution = AttributionRuntime(graph)
    structural = describe(graph, attribution, instance.id)
    assert structural["at"] is None
    assert len(structural["relations"]) == 3
    dated = describe(graph, attribution, instance.id, at=START)
    states = {
        relation["args"]["facet"]["id"]: relation
        for relation in dated["relations"]
        if relation["relation"] == "STATE_IDENTITY"
    }
    assert states[unknown.id]["temporal_status"] == "unknown"
    assert states[unknown.id]["args"]["facet"]["valid_from"] is None
    assert states[known.id]["temporal_status"] == "applicable"
    assert states[known.id]["args"]["facet"]["valid_from"] == START.isoformat()
    assert (
        describe(graph, attribution, states[unknown.id]["id"], at=START)["fact"]["temporal_status"]
        == "unknown"
    )
    expired = describe(graph, attribution, instance.id, at=END)
    assert len(expired["relations"]) == 2
    assert (
        describe(graph, attribution, unknown.id, at=START)["subject"]["temporal_status"]
        == "unknown"
    )


def test_unknown_state_only_blocks_properties_it_can_affect():
    graph, instance, unknown, known = world_with_unknown_state()
    flow = Node(graph.reserve_id(), "Flow", kind="property")
    noise = Node(graph.reserve_id(), "Noise", kind="property")
    facts = (
        graph.new_fact("HAS_NUMERIC_VALUE", {"entity": known.id, "property": flow.id, "value": 3}),
        graph.new_fact(
            "HAS_NUMERIC_VALUE", {"entity": unknown.id, "property": noise.id, "value": 8}
        ),
    )
    graph.apply(GraphDelta(creates=(flow, noise, *facts)), provenance="observations")
    attribution = AttributionRuntime(graph)
    assert attribution.read_property(instance, flow, valid_at=START).value_U == 3
    assert attribution.read_property(instance, noise, valid_at=START) is UNKNOWN
    assert attribution.read_property(unknown, noise, valid_at=START) is UNKNOWN
    assert {p.id for p in attribution.properties_for(instance.id, at=START)} == {flow.id, noise.id}
    conflict = graph.new_fact(
        "HAS_NUMERIC_VALUE", {"entity": unknown.id, "property": flow.id, "value": 7}
    )
    graph.apply(GraphDelta(creates=(conflict,)), provenance="undated observation")
    assert attribution.read_property(instance, flow, valid_at=START) is UNKNOWN


def test_temporal_filter_considers_facets_in_list_valued_slots():
    graph, instance, unknown, known = world_with_unknown_state()
    relation = RelationType(
        graph.reserve_id(),
        "OBSERVED_STATES",
        signature=(Slot("observer", "instance"), Slot("states", "facet", "list1")),
        views=(AccessView("states_of", ("observer",), ("states",)),),
    )
    graph.apply(GraphDelta(creates=(relation,)), provenance="schema")
    fact = graph.new_fact(relation.id, {"observer": instance.id, "states": [unknown.id, known.id]})
    graph.apply(GraphDelta(creates=(fact,)), provenance="observation")
    assert (
        graph.query_view(relation.id, "states_of", observer=instance.id, valid_at=START) is UNKNOWN
    )
    assert graph.query_view(relation.id, "states_of", observer=instance.id, valid_at=END) == []
