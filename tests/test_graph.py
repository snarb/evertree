import json
from datetime import UTC, datetime, timedelta

import pytest

from evertree.core.graph import (
    UNKNOWN,
    AccessView,
    Clause,
    ContractError,
    Facet,
    GraphDelta,
    GraphStore,
    Instance,
    Node,
    NodeUpdate,
    Predicate,
    Prototype,
    RelationType,
    Slot,
    freeze,
    json_value,
    restore_value,
)
from evertree.core.topology import inspect_topology, propose_reification


def bootstrap():
    graph = GraphStore()
    graph.bootstrap(provenance={"event_ref": 1, "output_path": ()})
    return graph


def test_atomic_taxonomy_validation_and_immutable_reads():
    graph = bootstrap()
    animal = Prototype(graph.reserve_id(), "Animal")
    dog = Prototype(graph.reserve_id(), "Dog")
    link = graph.new_fact("SUBTYPE_OF", {"type": dog.id, "supertype": animal.id})
    graph.apply(GraphDelta(creates=(animal, dog, link)), provenance="test")
    before = graph.snapshot()
    cycle = graph.new_fact("SUBTYPE_OF", {"type": animal.id, "supertype": dog.id})
    with pytest.raises(ContractError, match="cycle"):
        graph.apply(
            GraphDelta(creates=(cycle,), updates=(NodeUpdate(dog.id, {"name": "Canine"}),)),
            provenance="bad",
        )
    assert graph.get(dog.id).name == "Dog"
    assert len(graph.snapshot()["history"]) == len(before["history"])
    assert graph.ancestors(dog.id) == (animal,)
    assert graph.common_ancestor(animal.id, dog.id) == animal
    with pytest.raises(TypeError):
        graph.get(animal.id).properties["mutable"] = True
    with pytest.raises(ContractError):
        graph.apply(GraphDelta(deletes=(animal.id,)), provenance="bad")


def test_relation_views_preserve_sources_and_list_slots():
    graph = bootstrap()
    relation = RelationType(
        graph.reserve_id(),
        "LABELS",
        signature=(Slot("subject"), Slot("tags", "string", "list1")),
        views=(
            AccessView("get_tags", ("subject",), ("tags",)),
            AccessView("single_tags", ("subject",), ("tags",), "one"),
        ),
    )
    subject = Node(graph.reserve_id(), "Document")
    graph.apply(GraphDelta(creates=(relation, subject)), provenance="test")
    first = graph.new_fact(relation.id, {"subject": subject.id, "tags": ["one", "two"]})
    second = graph.new_fact(relation.id, {"subject": subject.id, "tags": ["one", "two"]})
    graph.apply(GraphDelta(creates=(first, second)), provenance="test")
    matches = graph.query_view(relation.id, "get_tags", subject=subject)
    assert len(matches) == 2
    assert matches[0].value == ("one", "two")
    assert matches[0].source_fact.id != matches[1].source_fact.id
    with pytest.raises(ContractError, match="cardinality"):
        graph.query_view(relation.id, "single_tags", subject=subject.id)
    with pytest.raises(ContractError):
        graph.query_view(relation.id, "get_tags", subject=subject.id, typo=True)


def test_predicate_optional_null_and_schema_validation():
    graph = bootstrap()
    relation = RelationType(
        graph.reserve_id(),
        "ANNOTATED",
        signature=(Slot("subject"), Slot("note", "string", "optional")),
        views=(
            AccessView(
                "without_note",
                ("subject",),
                ("note",),
                constraints=Predicate((Clause("note", "is_null"),)),
            ),
        ),
    )
    subject = Node(graph.reserve_id(), "Subject")
    graph.apply(GraphDelta(creates=(relation, subject)), provenance="test")
    facts = (
        graph.new_fact(relation.id, {"subject": subject.id}),
        graph.new_fact(relation.id, {"subject": subject.id, "note": "present"}),
    )
    graph.apply(GraphDelta(creates=facts), provenance="test")
    assert [
        match.value for match in graph.query_view(relation.id, "without_note", subject=subject.id)
    ] == [None]
    with pytest.raises(ContractError):
        RelationType(
            graph.reserve_id(),
            "Invalid",
            signature=(Slot("a"),),
            views=(AccessView("name", ("a",), ("a",)),),
        )


def test_facets_half_open_intervals_and_required_identity():
    graph = bootstrap()
    kind = Prototype(graph.reserve_id(), "Person")
    person = Instance(graph.reserve_id(), "Person One")
    start = datetime(2025, 1, 1, tzinfo=UTC)
    facet = Facet(graph.reserve_id(), "Person Health", valid_from=start)
    with pytest.raises(ContractError, match="IDENTITY_TYPE"):
        graph.apply(GraphDelta(creates=(kind, person)), provenance="bad")
    identity = graph.new_fact("IDENTITY_TYPE", {"instance": person.id, "type": kind.id})
    state = graph.new_fact("STATE_IDENTITY", {"facet": facet.id, "instance": person.id})
    graph.apply(GraphDelta(creates=(kind, person, facet, identity, state)), provenance="initial")
    original = graph.provenance_of(facet.id)
    end = start + timedelta(days=1)
    graph.apply(graph.close_facet_state(facet.id, end), provenance="close")
    assert (
        len(graph.query_view("STATE_IDENTITY", "get_facets", instance=person.id, valid_at=start))
        == 1
    )
    assert graph.query_view("STATE_IDENTITY", "get_facets", instance=person.id, valid_at=end) == []
    assert graph.provenance_of(facet.id) == original
    assert (
        graph.query_view("STATE_IDENTITY", "get_facets", instance=person.id, known_at=start)
        is UNKNOWN
    )


def test_snapshot_round_trip_does_not_duplicate_identity_or_inverse_facts():
    graph = bootstrap()
    restored = GraphStore.from_snapshot(json.loads(json.dumps(graph.snapshot())))
    assert restored.snapshot() == graph.snapshot()
    assert restored.find("HAS_PARTS") is None
    node = Node(restored.reserve_id(), "Persistent", properties={"nested": [1, 2]})
    restored.apply(GraphDelta(creates=(node,)), provenance="test")
    restored.apply(GraphDelta(deletes=(node.id,)), provenance="delete")
    with pytest.raises(ContractError, match="reused"):
        restored.apply(GraphDelta(creates=(node,)), provenance="recreate")


def test_topological_signals_and_connected_reification():
    graph = bootstrap()
    nodes = tuple(Node(graph.reserve_id(), str(index)) for index in range(4))
    graph.apply(GraphDelta(creates=nodes), provenance="test")
    facts = tuple(
        graph.new_fact("PART_WHOLE", {"part": nodes[a].id, "whole": nodes[b].id})
        for a, b in [(0, 1), (1, 2), (2, 0), (2, 3)]
    )
    graph.apply(GraphDelta(creates=facts), provenance="test")
    signals = inspect_topology(graph, hub_degree=3)
    assert (nodes[2].id, nodes[3].id) in signals.bridges
    assert signals.cycles
    delta = propose_reification(
        graph, name="Cycle Pattern", members=tuple(node.id for node in nodes[:3]), benefit="control"
    )
    graph.apply(delta, provenance="pattern")
    assert len(graph.facts("PART_WHOLE")) == 7


def test_typed_delta_transport_and_declarative_method_facade():
    graph = bootstrap()
    source = Prototype(graph.reserve_id(), "Source")
    target = Prototype(graph.reserve_id(), "Target")
    fact = graph.new_fact("SUBTYPE_OF", {"type": source.id, "supertype": target.id})
    transported = GraphDelta.from_dict(json_value(GraphDelta(creates=(source, target, fact))))
    graph.apply(transported, provenance="transport")
    assert graph.relation("SUBTYPE_OF").get_supertype(type=source.id).value == target.id
    graph.apply(
        GraphDelta.from_dict({"updates": [{"id": source.id, "changes": {"name": "Updated"}}]}),
        provenance="update",
    )
    assert isinstance(graph.get(source.id), Prototype)
    assert graph.get(source.id).name == "Updated"


def test_snapshot_markers_cannot_corrupt_user_payloads():
    value = {"$datetime": "ordinary user string"}
    assert restore_value(json_value(value)) == value
    nested = {"a": {"$unknown": False}, "b": {"$mapping": []}}
    assert restore_value(json_value(nested)) == freeze(nested)


def test_predicate_type_checks_happen_before_query_execution():
    graph = bootstrap()
    relation = RelationType(
        graph.reserve_id(),
        "BAD_FILTER",
        signature=(Slot("number", "number"),),
        views=(
            AccessView(
                "invalid",
                (),
                ("number",),
                constraints=Predicate((Clause("number", "contains", 2),)),
            ),
        ),
    )
    with pytest.raises(ContractError, match="contains"):
        graph.apply(GraphDelta(creates=(relation,)), provenance="bad")
