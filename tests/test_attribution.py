import json
from datetime import UTC, datetime, timedelta

import pytest

from evertree.core.attribution import AttributionRuntime, NormalizationRule, PropertyDefinition
from evertree.core.beliefs import BeliefStore
from evertree.core.graph import (
    UNKNOWN,
    ContractError,
    Facet,
    GraphDelta,
    GraphStore,
    Instance,
    Node,
    Prototype,
)

START = datetime(2025, 1, 1, tzinfo=UTC)


def setup_properties():
    graph = GraphStore()
    graph.bootstrap(provenance="initial")
    kind = Prototype(graph.reserve_id(), "Vehicle")
    entity = Instance(graph.reserve_id(), "Car")
    facet = Facet(
        graph.reserve_id(), "Car Moving", valid_from=START, valid_until=START + timedelta(days=1)
    )
    speed = Node(graph.reserve_id(), "Speed", kind="property")
    heading = Node(graph.reserve_id(), "Heading", kind="property")
    classification = Node(graph.reserve_id(), "SpeedClass", kind="property")
    slow = Node(graph.reserve_id(), "Slow")
    fast = Node(graph.reserve_id(), "Fast")
    nodes = (kind, entity, facet, speed, heading, classification, slow, fast)
    links = (
        graph.new_fact("IDENTITY_TYPE", {"instance": entity.id, "type": kind.id}),
        graph.new_fact("STATE_IDENTITY", {"facet": facet.id, "instance": entity.id}),
    )
    graph.apply(GraphDelta(creates=nodes + links), provenance="initial")
    beliefs = BeliefStore()
    runtime = AttributionRuntime(graph, beliefs)
    runtime.register(PropertyDefinition(speed.id, unit="km/h"))
    runtime.register(PropertyDefinition(heading.id, scale="circular", period=360))
    runtime.register(
        PropertyDefinition(
            classification.id, scale="ordinal", classes=(slow.id, fast.id), source="classification"
        )
    )
    return runtime, entity, facet, speed, heading, classification, slow, fast


def test_temporal_numeric_read_and_classification_are_not_substitutes():
    runtime, entity, facet, speed, _heading, classification, _slow, fast = setup_properties()
    graph = runtime.graph
    fact = graph.new_fact("CLASSIFIED_AS", {"entity": facet.id, "class": fast.id})
    graph.apply(GraphDelta(creates=(fact,)), provenance="classify")
    assert runtime.read_property(entity, speed, valid_at=START) is UNKNOWN
    assert runtime.read_property(entity, classification, valid_at=START).value_U == fast.id
    numeric = graph.new_fact(
        "HAS_NUMERIC_VALUE",
        {"entity": facet.id, "property": speed.id, "value": 112, "unit": "km/h"},
    )
    graph.apply(GraphDelta(creates=(numeric,)), provenance="measure")
    reading = runtime.read_property(entity, speed, valid_at=START)
    assert reading.value_U == 112
    assert reading.source_facts == (numeric.id,)
    assert runtime.read_property(entity, speed, valid_at=START + timedelta(days=1)) is UNKNOWN


def test_scale_operations_and_normalization():
    runtime, _entity, _facet, speed, heading, classification, slow, fast = setup_properties()
    assert runtime.distance(heading.id, 350, 10) == 20
    assert runtime.compare(classification.id, slow.id, fast.id) == -1
    with pytest.raises(ContractError):
        runtime.distance(classification.id, slow.id, fast.id)
    runtime.register_normalization(NormalizationRule(speed.id, "Vehicle", mean=60, stddev=20))
    assert runtime.normalize(100, speed.id, "Vehicle").value_U == 2
    assert runtime.normalize(100, speed.id, "Human") is UNKNOWN


def test_categorical_scope_is_returned_without_materialized_class():
    runtime, entity, facet, _speed, _heading, classification, slow, fast = setup_properties()
    runtime.beliefs.register_scope("speed-class", [str(slow.id), str(fast.id)])
    runtime.bind_scope(facet.id, classification.id, "speed-class")
    reading = runtime.read_property(entity, classification, valid_at=START)
    assert reading.value_U is None
    assert reading.belief_data.profile == {str(slow.id): 0.5, str(fast.id): 0.5}
    assert runtime.graph.facts("CLASSIFIED_AS") == ()


def test_historical_read_requires_exact_snapshot_and_preserves_sources():
    runtime, entity, facet, speed, _heading, _classification, _slow, _fast = setup_properties()
    fact = runtime.graph.new_fact(
        "HAS_NUMERIC_VALUE", {"entity": facet.id, "property": speed.id, "value": 80, "unit": "km/h"}
    )
    runtime.graph.apply(GraphDelta(creates=(fact,)), provenance="measure")
    backup_at = datetime.now(UTC)
    historical_graph = GraphStore.from_snapshot(runtime.graph.snapshot())
    historical_graph.known_at = backup_at
    historical_graph.read_only = True
    historical = AttributionRuntime.from_snapshot(
        json.loads(json.dumps(runtime.snapshot())),
        historical_graph,
        BeliefStore.from_snapshot(runtime.beliefs.snapshot()),
    )
    runtime.historical_loader = lambda at: historical if at == backup_at else None
    assert (
        runtime.reconstruct_property(
            entity.id, speed.id, valid_at=START, known_at=backup_at
        ).value_U
        == 80
    )
    assert (
        runtime.reconstruct_property(
            entity.id, speed.id, valid_at=START, known_at=backup_at + timedelta(seconds=1)
        )
        is UNKNOWN
    )
    with pytest.raises(ContractError, match="read-only"):
        historical_graph.apply(GraphDelta(), provenance="write")
