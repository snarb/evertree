import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from evertree.common.semantic_search import search
from evertree.core.attribution import PropertyDefinition
from evertree.core.graph.types import (
    Facet,
    GraphDelta,
    Instance,
    Node,
    NodeUpdate,
    Prototype,
)
from evertree.core.semantics.reading import describe, read_property
from evertree.core.values import ContractError, json_value
from evertree.processes.semantic_processing.knowledge_integration._exec import _describe_for_model
from tests.support.semantics import EmptyIndex, context, semantic_world


async def never(_):
    pytest.fail("Search must not invoke a model")


async def test_exact_normalization_ambiguity_and_atomic_rename():
    world = semantic_world()
    g = world.graph
    cat = Node(g.reserve_id(), "  CAFÉ   animal ")
    people = (Instance(g.reserve_id(), "Alex"), Instance(g.reserve_id(), "alex"))
    person = Prototype(g.reserve_id(), "Person")
    links = tuple(
        g.new_fact("IDENTITY_TYPE", {"instance": n.id, "type": person.id}) for n in people
    )
    g.apply(GraphDelta(creates=(cat, person, *people, *links)), provenance="test")
    result = (await search(context(world, never), "cafe\u0301 ANIMAL"))["result"]
    assert result["exact"] and [n["id"] for n in result["items"]] == [cat.id]
    assert (await search(context(world, never), cat.id, kind="instance"))["result"]["items"] == []
    assert len((await search(context(world, never), "ALEX"))["result"]["items"]) == 2
    assert describe(g, world.attribution, "alex")["status"] == "ambiguous"
    revision = g.revision
    with pytest.raises(ContractError):
        g.apply(GraphDelta(creates=(Node(g.reserve_id(), "Café animal"),)), provenance="duplicate")
    with pytest.raises(ContractError):
        g.apply(
            GraphDelta(updates=(NodeUpdate(cat.id, {"name": "one two three four"}),)),
            provenance="long",
        )
    assert g.revision == revision
    g.apply(GraphDelta(updates=(NodeUpdate(cat.id, {"name": "Cat"}),)), provenance="rename")
    assert g.lookup("cat")[0].id == cat.id


async def test_parallel_indexes_rank_fusion_and_cached_pages():
    started = set()
    calls = []
    ready = asyncio.Event()

    class Index(EmptyIndex):
        async def run(self, name):
            calls.append(name)
            started.add(name)
            if len(started) == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 2)
            return (
                [ids[0], ids[17], *ids[1:6]] if name == "bm25" else [ids[6], ids[17], *ids[7:17]]
            ) * 2

        async def lexical(self, nodes, query, kind):
            assert query == "  ReLATED \t  TYPES  " and kind == "prototype"
            return await self.run("bm25")

        async def vector(self, nodes, query, kind):
            assert query == "  ReLATED \t  TYPES  " and kind == "prototype"
            return await self.run("vector")

    world = semantic_world(index=Index())
    nodes = [Prototype(world.graph.reserve_id(), f"Type{i}") for i in range(18)]
    ids = [n.id for n in nodes]
    world.graph.apply(GraphDelta(creates=nodes), provenance="test")

    first = (
        await search(context(world, never), "  ReLATED \t  TYPES  ", kind=" PROTOTYPE ", limit=5)
    )["result"]
    assert first["status"] == "complete" and len(first["items"]) == 5 and first["total"] == 18
    assert started == {"bm25", "vector"}
    assert [item["id"] for item in first["items"]] == [ids[i] for i in (17, 0, 6, 1, 7)]
    assert set(first["items"][0]["channels"]) == {"bm25", "vector"}
    assert "cursor" not in first and "has_more" not in first
    assert len(calls) == 2


@pytest.mark.parametrize("count", [0, 7, 9])
def test_describe_previews_totals_and_focused_lists(count):
    world = semantic_world()
    graph = world.graph
    entity = Node(graph.reserve_id(), "Measured object")
    properties = [Node(graph.reserve_id(), f"Reading {i}", kind="property") for i in range(count)]
    facts = [
        graph.new_fact(
            "HAS_NUMERIC_VALUE",
            {"entity": entity.id, "property": prop.id, "value": i, "unit": "m"},
        )
        for i, prop in enumerate(properties)
    ]
    graph.apply(GraphDelta(creates=(entity, *properties, *facts)), provenance="test")
    for prop in properties:
        world.attribution.register(PropertyDefinition(prop.id))
    for project in (lambda value: value, _describe_for_model):
        result = project(describe(graph, world.attribution, entity.id))
        assert "relations_truncated" not in result
        for field in ("properties", "relations"):
            assert len(result.get(field, [])) == min(count, 7)
            if count > 7:
                assert result[field + "_total"] == count
                assert list(result).index(field + "_total") < list(result).index(field)
            else:
                assert field + "_total" not in result
            focused = project(describe(graph, world.attribution, entity.id, focus=field))
            assert len(focused.get(field, [])) == count
            assert field + "_total" not in focused
            other = "relations" if field == "properties" else "properties"
            assert other not in focused


def test_describe_discovers_properties_without_computing_and_uses_one_time(monkeypatch):
    world = semantic_world()
    g, runtime = world.graph, world.attribution
    start = datetime(2025, 1, 1, tzinfo=UTC)
    entity = Instance(g.reserve_id(), "Car")
    first = Facet(g.reserve_id(), "Moving", valid_from=start, valid_until=start + timedelta(days=1))
    second = Facet(
        g.reserve_id(),
        "Stopped",
        valid_from=start + timedelta(days=1),
        valid_until=start + timedelta(days=2),
    )
    speed = Node(g.reserve_id(), "Speed", kind="property")
    estimate = Node(g.reserve_id(), "Estimate", kind="property")
    relative = Node(g.reserve_id(), "Relative speed", kind="property")
    qualitative = Node(g.reserve_id(), "Colour", kind="property")
    arbitrary = Node(g.reserve_id(), "Interesting")
    vehicle = Prototype(g.reserve_id(), "Vehicle")
    g.apply(
        GraphDelta(
            creates=tuple(
                [
                    entity,
                    first,
                    second,
                    speed,
                    estimate,
                    relative,
                    qualitative,
                    arbitrary,
                    vehicle,
                    g.new_fact("IDENTITY_TYPE", {"instance": entity.id, "type": vehicle.id}),
                ]
                + [
                    g.new_fact("STATE_IDENTITY", {"facet": f.id, "instance": entity.id})
                    for f in (first, second)
                ]
                + [
                    g.new_fact(
                        "HAS_NUMERIC_VALUE",
                        {"entity": f.id, "property": speed.id, "value": value, "unit": "km/h"},
                    )
                    for f, value in ((first, 80), (second, 0))
                ]
                + [g.new_fact("CLASSIFIED_AS", {"entity": entity.id, "class": arbitrary.id})]
            )
        ),
        provenance="test",
    )
    runtime.register(PropertyDefinition(speed.id))
    runtime.register(PropertyDefinition(estimate.id, source="program", applies_to=(entity.id,)))
    runtime.register(
        PropertyDefinition(relative.id, required_parameters=("frame",), applies_to=(entity.id,))
    )
    runtime.register(
        PropertyDefinition(
            qualitative.id, scale="nominal", classes=("red", "blue"), source="program"
        )
    )
    runtime.beliefs.register_scope("colour", ["red", "blue"])
    runtime.bind_scope(entity.id, qualitative.id, "colour")
    runtime.program_reader = lambda *a, **k: pytest.fail("describe invoked a Program")
    calls = []

    def now():
        calls.append(1)
        return start

    monkeypatch.setattr("evertree.core.semantics.reading.utcnow", now)
    result = describe(g, runtime, "Car", focus="properties")
    assert len(calls) == 1 and "relations" not in result
    properties = {p["name"]: p for p in result["properties"]}
    assert set(properties) == {"Speed", "Estimate", "Relative speed", "Colour"}
    assert properties["Speed"]["reading"]["value_U"] == 80
    assert properties["Estimate"]["status"] == "requires_computation"
    assert properties["Relative speed"]["required_parameters"] == ["frame"]
    assert properties["Colour"]["reading"]["value_U"] is None
    assert properties["Colour"]["reading"]["belief_data"]["profile"] == {"red": 0.5, "blue": 0.5}
    assert (
        read_property(g, runtime, entity.id, speed.id, at=start + timedelta(days=1))["value_U"] == 0
    )
    assert read_property(g, runtime, first.id, speed.id, at=start + timedelta(days=1)) == {
        "$unknown": True
    }
    assert read_property(g, runtime, entity.id, relative.id)["status"] == "needs_parameters"


def test_describe_preserves_relation_conditions_in_model_reads():
    world = semantic_world()
    g = world.graph
    entity = Node(g.reserve_id(), "Pump")
    prop = Node(g.reserve_id(), "Flow", kind="property")
    conditions = {"load": "high", "valve_open": False}
    fact = replace(
        g.new_fact("HAS_NUMERIC_VALUE", {"entity": entity.id, "property": prop.id, "value": 3}),
        properties={"conditions": conditions},
    )
    g.apply(GraphDelta(creates=(entity, prop, fact)), provenance="measurement")

    direct = _describe_for_model(describe(g, world.attribution, fact.id))["fact"]
    neighbor = _describe_for_model(describe(g, world.attribution, entity.id))["relations"][0]
    for reading in (direct, neighbor):
        assert reading["id"] == fact.id
        assert reading["args"]["value"] == 3
        assert reading["properties"]["conditions"] == conditions


def test_graph_declared_property_domain_inherits_to_types_and_facets():
    world = semantic_world()
    g = world.graph
    vehicle, car = Prototype(g.reserve_id(), "Vehicle"), Prototype(g.reserve_id(), "CarType")
    instance = Instance(g.reserve_id(), "My car")
    facet = Facet(g.reserve_id(), "Current state")
    prop = Node(
        g.reserve_id(),
        "Mass",
        kind="property",
        properties={"attribution": {"source": "numeric", "applies_to": [vehicle.id]}},
    )
    links = (
        g.new_fact("SUBTYPE_OF", {"type": car.id, "supertype": vehicle.id}),
        g.new_fact("IDENTITY_TYPE", {"instance": instance.id, "type": car.id}),
        g.new_fact("STATE_IDENTITY", {"facet": facet.id, "instance": instance.id}),
    )
    g.apply(
        GraphDelta(creates=(vehicle, car, instance, facet, prop, *links)), provenance="contract"
    )
    for subject in (car, instance, facet):
        result = describe(g, world.attribution, subject.id, focus="properties")
        assert [(p["name"], p["status"]) for p in result["properties"]] == [("Mass", "unknown")]


@pytest.mark.parametrize("failed", [{"bm25"}, {"vector"}, {"bm25", "vector"}])
async def test_index_failure_reports_incomplete_and_cards_are_authoritative(failed):
    class Index(EmptyIndex):
        async def lexical(self, *args):
            if "bm25" in failed:
                raise RuntimeError("unavailable")
            return [node.id]

        async def vector(self, *args):
            if "vector" in failed:
                raise RuntimeError("unavailable")
            return [node.id]

    world = semantic_world(index=Index())
    node = next(iter(world.graph.nodes()))
    result = (await search(context(world, never), "missing"))["result"]
    assert result["status"] == "incomplete"
    assert {error["channel"] for error in result["errors"]} == failed
    assert [item["id"] for item in result["items"]] == ([] if len(failed) == 2 else [node.id])
    if result["items"]:
        assert set(result["items"][0]["channels"]) == {"bm25", "vector"} - failed
    result = await world.service.execute(
        "semantic.results",
        {
            "query": "query",
            "items": [{"id": node.id, "name": "invented", "channels": ["bm25"]}],
            "errors": [],
            "limit": 20,
        },
        {"task_id": "task", "run_id": "test", "semantic_scope": "packet"},
    )
    assert result["items"][0]["name"] == node.name


@pytest.mark.parametrize("limit", [1, 20])
def test_search_returns_only_top_results_and_enforces_twenty_item_ceiling(limit):
    world = semantic_world()
    nodes = [Node(world.graph.reserve_id(), f"Candidate {i}") for i in range(25)]
    world.graph.apply(GraphDelta(creates=nodes), provenance="test")
    cards = [{"id": node.id} for node in nodes]
    result = world.service.results("query", None, cards, [], limit, "task", scope="packet")
    assert result["items"] == cards[:limit] and result["total"] == 25
    assert "cursor" not in result and "has_more" not in result
    with pytest.raises(ContractError, match="between 1 and 20"):
        world.service.lookup("query", limit=21, task_id="task", scope="packet")
    with pytest.raises(ContractError, match="between 1 and 20"):
        world.service.results("query", None, cards, [], 21, "task", scope="packet")


def test_describe_filters_relations_by_facet_time_and_removed_definitions():
    world = semantic_world()
    g = world.graph
    now = datetime(2025, 1, 1, tzinfo=UTC)
    prototype = Prototype(g.reserve_id(), "Entity")
    instance = Instance(g.reserve_id(), "Thing")
    old = Facet(g.reserve_id(), "Old", valid_from=now - timedelta(days=1), valid_until=now)
    new = Facet(g.reserve_id(), "New", valid_from=now)
    prop = Node(g.reserve_id(), "Property", kind="property")
    links = [g.new_fact("IDENTITY_TYPE", {"instance": instance.id, "type": prototype.id})]
    links += [
        g.new_fact("STATE_IDENTITY", {"instance": instance.id, "facet": f.id}) for f in (old, new)
    ]
    g.apply(GraphDelta(creates=(prototype, instance, old, new, prop, *links)), provenance="test")
    world.attribution.register(PropertyDefinition(prop.id, applies_to=(instance.id,)))
    g.apply(GraphDelta(deletes=(prop.id,)), provenance="delete")
    result = describe(g, world.attribution, instance.id, at=now)
    assert not result["properties"]
    assert {f["id"] for f in result["relations"]} == {links[0].id, links[2].id}
    assert (
        next(f for f in result["relations"] if f["id"] == links[2].id)["temporal_status"]
        == "applicable"
    )


async def test_integration_can_disambiguate_by_id_without_a_disposition():
    from evertree.processes.semantic_processing.knowledge_integration._exec import run

    world = semantic_world()
    input_run = world.memory.start_run("input", "revision", {})
    event = world.memory.record(input_run, "input", output="Ambiguous term")
    refs = [json_value(world.memory.output_ref(event))]
    identity = world.graph.find("Process").id

    async def model(payload, call):
        result = await call("describe", {"subject": identity})
        assert result["subject"]["id"] == identity

    result = await run(context(world, model, role="exec"), refs)
    assert result == {"result": {"writes": []}, "feedback": None}


@pytest.mark.parametrize(
    "kind", ["concept", "prototype", "facet", "instance", "relation_type", "relation_instance"]
)
async def test_populated_graph_exact_names_per_kind_without_external_calls(kind):
    from tests.support.semantics import populated_search_world

    class NoIndex(EmptyIndex):
        async def lexical(self, *args):
            pytest.fail("Exact names must bypass BM25")

        async def vector(self, *args):
            pytest.fail("Exact names must bypass embeddings")

    world = populated_search_world(index=NoIndex())
    target = world.targets[kind]
    result = (await search(context(world, never), target.name.upper(), kind=kind))["result"]
    assert result["exact"] and result["status"] == "complete"
    assert target.id in {item["id"] for item in result["items"]}
    assert all(item["kind"] == kind for item in result["items"])
    by_id = (await search(context(world, never), target.id, kind=kind))["result"]
    assert [item["id"] for item in by_id["items"]] == [target.id]
