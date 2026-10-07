import math
from datetime import UTC, datetime, timedelta

import pytest

from evertree.core.attribution import AttributionRuntime, PropertyDefinition
from evertree.core.beliefs import BeliefStore
from evertree.core.graph import (
    UNKNOWN,
    AccessView,
    Clause,
    ContractError,
    GraphDelta,
    GraphStore,
    Node,
    NodeUpdate,
    Predicate,
    RelationType,
    Slot,
)

EARLY = datetime(2025, 1, 1, 10, tzinfo=UTC)


LATER = EARLY + timedelta(hours=1)


def parentage_graph():
    graph = GraphStore()
    graph.bootstrap(provenance="initial")
    relation = RelationType(
        graph.reserve_id(),
        "PARENTAGE",
        signature=(Slot("parent"), Slot("child")),
        views=(
            AccessView("parent_of", ("child",), ("parent",), "one"),
            AccessView("children_of", ("parent",), ("child",)),
        ),
    )
    anna, boris = Node(graph.reserve_id(), "Anna"), Node(graph.reserve_id(), "Boris")
    graph.apply(GraphDelta(creates=(relation, anna, boris)), provenance="family")
    fact = graph.new_fact(relation.id, {"parent": anna.id, "child": boris.id})
    graph.apply(GraphDelta(creates=(fact,)), provenance="one-observation")
    return graph, relation, anna, boris, fact


def numeric_property():
    graph = GraphStore()
    graph.bootstrap(provenance="initial")
    room = Node(graph.reserve_id(), "Room")
    temperature = Node(graph.reserve_id(), "Temperature", kind="property")
    graph.apply(GraphDelta(creates=(room, temperature)), provenance="schema")
    beliefs = BeliefStore()
    runtime = AttributionRuntime(graph, beliefs)
    runtime.register(PropertyDefinition(temperature.id, unit="C"))
    return runtime, room, temperature


def temporal_beliefs():
    beliefs = BeliefStore()
    beliefs.register_binary("measurement-valid")
    beliefs.assign(
        "measurement-valid", "early", math.log(4), backed=True, observed_scope=(EARLY, LATER)
    )
    beliefs.assign(
        "measurement-valid", "later", -math.log(4), backed=True, observed_scope=(LATER, None)
    )
    return beliefs


def belief_filtered_graph(reader):
    graph = GraphStore(belief_reader=reader)
    relation = RelationType(
        graph.reserve_id(),
        "TEST_MEASUREMENT",
        signature=(Slot("subject"),),
        views=(
            AccessView(
                "reliable",
                (),
                ("subject",),
                "one",
                Predicate((Clause("strength", ">=", 0.75),)),
            ),
        ),
    )
    subject = Node(graph.reserve_id(), "Sensor")
    graph.apply(GraphDelta(creates=(relation, subject)), provenance="schema")
    fact = graph.new_fact(relation.id, {"subject": subject.id}, belief_target="measurement-valid")
    graph.apply(GraphDelta(creates=(fact,)), provenance="reading")
    return graph


def membership_graph():
    beliefs = BeliefStore()
    graph = GraphStore(belief_reader=beliefs.read)
    graph.bootstrap(provenance="schema")
    subject = Node(graph.reserve_id(), "Agent")
    low, high = Node(graph.reserve_id(), "Low"), Node(graph.reserve_id(), "High")
    relation = graph.find("CLASSIFIED_AS")
    confidence_view = AccessView(
        "confident_classes",
        ("entity",),
        ("class",),
        "list0",
        Predicate((Clause("strength", ">=", 0.75),)),
    )
    support_view = AccessView(
        "supported_classes",
        ("entity",),
        ("class",),
        "list0",
        Predicate((Clause("support", ">=", 1.0),)),
    )
    graph.apply(
        GraphDelta(
            creates=(subject, low, high),
            updates=(
                NodeUpdate(
                    relation.id, {"views": (*relation.views, confidence_view, support_view)}
                ),
            ),
        ),
        provenance="property-scale",
    )
    beliefs.register_scope("level", (str(low.id), str(high.id)))
    beliefs.assess_likelihoods(
        "level", "assessment", {str(low.id): 0.2, str(high.id): 0.8}, backed=True
    )
    facts = tuple(
        graph.new_fact(
            "CLASSIFIED_AS", {"entity": subject.id, "class": value.id}, belief_target="level"
        )
        for value in (low, high)
    )
    graph.apply(GraphDelta(creates=facts), provenance="assessment")
    return graph, beliefs, subject, low, high


def test_sem_02_inverse_views_share_one_fact_without_mutating_graph():
    graph, relation, anna, boris, fact = parentage_graph()
    before = graph.snapshot()
    parent = graph.query_view(relation.id, "parent_of", child=boris)
    children = graph.query_view(relation.id, "children_of", parent=anna)
    assert parent.value == anna.id
    assert [child.value for child in children] == [boris.id]
    assert parent.source_fact.id == children[0].source_fact.id == fact.id
    assert graph.snapshot() == before


def test_sem_03_one_view_rejects_ambiguity_instead_of_choosing_latest():
    graph, relation, _anna, boris, _fact = parentage_graph()
    other = Node(graph.reserve_id(), "Other parent")
    fact = graph.new_fact(relation.id, {"parent": other.id, "child": boris.id})
    graph.apply(GraphDelta(creates=(other, fact)), provenance="other-observation")
    with pytest.raises(ContractError, match="cardinality"):
        graph.query_view(relation.id, "parent_of", child=boris)


def test_sem_04_qualitative_fact_does_not_invent_numeric_measurement():
    runtime, room, temperature = numeric_property()
    warm = Node(runtime.graph.reserve_id(), "Warm")
    classification = Node(runtime.graph.reserve_id(), "TemperatureClass", kind="property")
    runtime.graph.apply(GraphDelta(creates=(warm, classification)), provenance="classes")
    runtime.register(
        PropertyDefinition(
            classification.id, scale="nominal", source="classification", classes=(warm.id,)
        )
    )
    fact = runtime.graph.new_fact("CLASSIFIED_AS", {"entity": room.id, "class": warm.id})
    runtime.graph.apply(GraphDelta(creates=(fact,)), provenance="qualitative-observation")
    assert runtime.read_property(room, temperature, valid_at=EARLY) is UNKNOWN
    assert runtime.read_property(room, classification, valid_at=EARLY).value_U == warm.id


def test_sem_05_exact_backup_excludes_later_temperature_and_rules():
    runtime, room, temperature = numeric_property()
    first = runtime.graph.new_fact(
        "HAS_NUMERIC_VALUE",
        {"entity": room.id, "property": temperature.id, "value": 20, "unit": "C"},
    )
    runtime.graph.apply(GraphDelta(creates=(first,)), provenance="early-reading")
    backup_at = datetime.now(UTC)
    historical_graph = GraphStore.from_snapshot(runtime.graph.snapshot())
    historical_graph.known_at = backup_at
    historical_graph.read_only = True
    historical = AttributionRuntime.from_snapshot(
        runtime.snapshot(), historical_graph, BeliefStore.from_snapshot(runtime.beliefs.snapshot())
    )
    second = runtime.graph.new_fact(
        "HAS_NUMERIC_VALUE",
        {"entity": room.id, "property": temperature.id, "value": 25, "unit": "C"},
    )
    runtime.graph.apply(GraphDelta(creates=(second,)), provenance="later-reading")
    runtime.historical_loader = lambda at: historical if at == backup_at else None
    reading = runtime.reconstruct_property(room, temperature, valid_at=EARLY, known_at=backup_at)
    assert reading.value_U == 20
    assert reading.source_facts == (first.id,)
    assert runtime.read_property(room, temperature).value_U == 25
    assert (
        runtime.reconstruct_property(
            room, temperature, valid_at=EARLY, known_at=backup_at + timedelta(seconds=1)
        )
        is UNKNOWN
    )


def test_sem_05_missing_historical_property_definition_returns_unknown():
    runtime, room, temperature = numeric_property()
    backup_at = datetime.now(UTC)
    graph = GraphStore.from_snapshot(runtime.graph.snapshot())
    graph.known_at = backup_at
    # The graph identity survived, but this backup has no reader definition.
    historical = AttributionRuntime(graph, BeliefStore())
    runtime.historical_loader = lambda _: historical
    assert (
        runtime.reconstruct_property(room, temperature, valid_at=EARLY, known_at=backup_at)
        is UNKNOWN
    )


def test_sem_05_property_confidence_uses_the_requested_world_time():
    """SEM-05 boundary: a property's belief obeys the same valid_at as its value."""
    runtime, room, temperature = numeric_property()
    runtime.beliefs = temporal_beliefs()
    fact = runtime.graph.new_fact(
        "HAS_NUMERIC_VALUE",
        {"entity": room.id, "property": temperature.id, "value": 20, "unit": "C"},
        belief_target="measurement-valid",
    )
    runtime.graph.apply(GraphDelta(creates=(fact,)), provenance="measurement")
    assert runtime.read_property(room, temperature, valid_at=EARLY).belief_data.strength == (
        pytest.approx(0.8)
    )
    assert runtime.read_property(room, temperature, valid_at=LATER).belief_data.strength == (
        pytest.approx(0.2)
    )


def test_sem_05_view_belief_filter_uses_requested_world_time():
    graph = belief_filtered_graph(temporal_beliefs().read)
    assert graph.query_view("TEST_MEASUREMENT", "reliable", valid_at=EARLY).source_fact
    with pytest.raises(ContractError, match="cardinality"):
        graph.query_view("TEST_MEASUREMENT", "reliable", valid_at=LATER)


def test_sem_03_unknown_belief_is_returned_before_view_cardinality_check():
    graph = belief_filtered_graph(lambda *_args, **_kwargs: UNKNOWN)
    assert graph.query_view("TEST_MEASUREMENT", "reliable") is UNKNOWN


def test_bel_11_sem_02_membership_filter_reads_strength_of_its_own_alternative():
    """BEL-11/SEM-02: a likely High does not make Low pass the same strength filter."""
    graph, beliefs, subject, _low, high = membership_graph()
    before = beliefs.snapshot()
    matches = graph.query_view("CLASSIFIED_AS", "confident_classes", entity=subject.id)
    assert [match.value for match in matches] == [high.id]
    assert beliefs.snapshot() == before


def test_bel_11_sem_02_membership_support_is_shared_by_the_scope():
    graph, beliefs, subject, low, high = membership_graph()
    matches = graph.query_view("CLASSIFIED_AS", "supported_classes", entity=subject.id)
    assert {match.value for match in matches} == {low.id, high.id}
    assert beliefs.read("level").support == pytest.approx(math.log(4))


def test_bel_11_sem_02_membership_missing_profile_alternative_is_unknown():
    graph, _beliefs, subject, _low, _high = membership_graph()
    other = Node(graph.reserve_id(), "Outside the declared scale")
    fact = graph.new_fact(
        "CLASSIFIED_AS", {"entity": subject.id, "class": other.id}, belief_target="level"
    )
    graph.apply(GraphDelta(creates=(other, fact)), provenance="incomplete-scope-binding")
    assert graph.query_view("CLASSIFIED_AS", "confident_classes", entity=subject.id) is UNKNOWN


def test_sem_05_missing_historical_categorical_belief_returns_unknown():
    runtime, room, prop = numeric_property()
    runtime.register(
        PropertyDefinition(
            prop.id, scale="nominal", source="classification", classes=("Low", "High")
        )
    )
    runtime.beliefs.register_scope("level", ("Low", "High"))
    runtime.bind_scope(room.id, prop.id, "level")
    backup_at = datetime.now(UTC)
    graph = GraphStore.from_snapshot(runtime.graph.snapshot())
    graph.known_at = backup_at
    graph.read_only = True
    # The scale/binding survived; the required historical belief did not.
    historical = AttributionRuntime.from_snapshot(runtime.snapshot(), graph, BeliefStore())
    runtime.historical_loader = lambda at: historical if at == backup_at else None
    assert runtime.read_property(room, prop).belief_data.profile == {"Low": 0.5, "High": 0.5}
    assert runtime.reconstruct_property(room, prop, valid_at=EARLY, known_at=backup_at) is UNKNOWN
