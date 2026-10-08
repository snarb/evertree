import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from evertree.common.semantic_search import search
from evertree.core.attribution import PropertyDefinition
from evertree.core.graph.types import (
    AccessView,
    Facet,
    GraphDelta,
    Instance,
    Node,
    NodeUpdate,
    Prototype,
    RelationType,
    Slot,
)
from evertree.core.semantics.config import SemanticConfig
from evertree.core.semantics.reading import describe, read_property
from evertree.core.values import ContractError, json_value
from tests.support.semantics import EmptyIndex, context, semantic_world


def relation_decision(action, **kwargs):
    return {"action": action, "query": "", "id": 0, "inputs_json": "{}", "results": [], **kwargs}


async def never(_):
    pytest.fail("Exact lookup must not invoke a model")


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


async def test_parallel_channels_dedup_filter_failure_and_cached_pages():
    started = set()
    ready = asyncio.Event()

    class Index(EmptyIndex):
        async def run(self, name):
            started.add(name)
            if len(started) == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 2)
            return ids[:7] if name == "bm25" else ids[:12]

        async def lexical(self, *args):
            return await self.run("bm25")

        async def vector(self, *args):
            return await self.run("vector")

    world = semantic_world(index=Index())
    nodes = [Prototype(world.graph.reserve_id(), f"Type{i}") for i in range(25)]
    ids = [n.id for n in nodes]
    world.graph.apply(GraphDelta(creates=nodes), provenance="test")
    calls = []

    async def model(payload):
        data = json.loads(payload["prompt"])
        calls.append(data)
        if "reads" in data:
            return relation_decision("finish")
        if "nodes" in data:
            return {
                "decisions": [
                    {"id": n["id"], "include": n["id"] in ids, "descend": True}
                    for n in data["nodes"]
                ]
            }
        raise ValueError("filter unavailable")

    first = (await search(context(world, model), "related types"))["result"]
    assert first["status"] == "incomplete" and len(first["items"]) == 20 and first["total"] == 25
    assert set(first["items"][0]["channels"]) == {"bm25", "vector", "taxonomy"}
    before = len(calls)
    second = (await search(context(world, model), "related types", cursor=first["cursor"]))[
        "result"
    ]
    assert len(second["items"]) == 5 and len(calls) == before
    assert {n["id"] for n in first["items"] + second["items"]} == set(ids)
    with pytest.raises(ContractError):
        world.service.lookup("other", cursor=first["cursor"], task_id="task")


async def test_taxonomy_deep_multiple_roots_intermediate_nodes_and_concurrency():
    world = semantic_world(config=SemanticConfig(concurrency=4))
    g = world.graph
    roots = [Prototype(g.reserve_id(), f"Root{i}") for i in range(6)]
    nodes, facts = list(roots), []
    for root in roots:
        parent = root
        for depth in range(45):
            child = Prototype(g.reserve_id(), f"Branch{root.id}_{depth}")
            nodes.append(child)
            facts.append(g.new_fact("SUBTYPE_OF", {"type": child.id, "supertype": parent.id}))
            parent = child
    g.apply(GraphDelta(creates=tuple(nodes + facts)), provenance="test")
    active, maximum = 0, 0

    async def model(payload):
        nonlocal active, maximum
        data = json.loads(payload["prompt"])
        if "reads" in data:
            return relation_decision("finish")
        if "candidates" in data:
            return {"keep": [n["id"] for n in data["candidates"]]}
        active += 1
        maximum = max(active, maximum)
        await asyncio.sleep(0)
        active -= 1
        return {
            "decisions": [
                {"id": n["id"], "include": n["id"] in {roots[0].id, nodes[-1].id}, "descend": True}
                for n in data["nodes"]
            ]
        }

    result = (await search(context(world, model), "a deep category"))["result"]
    assert result["status"] == "complete"
    assert {n["id"] for n in result["items"]} == {roots[0].id, nodes[-1].id}
    assert 1 < maximum <= 4


async def test_relations_find_unmentioned_daughter_and_facet_with_evidence():
    world = semantic_world(config=SemanticConfig(taxonomy_enabled=False))
    g = world.graph
    mother, daughter = Instance(g.reserve_id(), "Светлана"), Instance(g.reserve_id(), "Анна")
    facet = Facet(g.reserve_id(), "Текущее состояние")
    relation = RelationType(
        g.reserve_id(),
        "DAUGHTER_OF",
        signature=(Slot("daughter", "instance"), Slot("mother", "instance")),
        views=(AccessView("get_daughters", ("mother",), ("daughter",)),),
    )
    person = Prototype(g.reserve_id(), "Person")
    links = tuple(
        g.new_fact("IDENTITY_TYPE", {"instance": n.id, "type": person.id})
        for n in (mother, daughter)
    )
    from evertree.core.graph.types import RelationInstance

    fact = RelationInstance(
        g.reserve_id(),
        relation.name,
        relation_type=relation.id,
        args={"daughter": daughter.id, "mother": mother.id},
    )
    state = g.new_fact("STATE_IDENTITY", {"facet": facet.id, "instance": daughter.id})
    g.apply(
        GraphDelta(creates=(person, mother, daughter, facet, relation, *links, fact, state)),
        provenance="test",
    )

    async def model(payload):
        data = json.loads(payload["prompt"])
        if "candidates" in data:
            assert data["candidates"][0]["evidence"][0]["args"]
            return {"keep": [facet.id]}
        reads = data["reads"]
        if not reads:
            return relation_decision("lookup", query="Светлана")
        if len(reads) == 1:
            return relation_decision("neighbors", id=mother.id)
        if len(reads) == 2:
            return relation_decision("neighbors", id=daughter.id)
        return relation_decision(
            "finish", results=[{"id": facet.id, "source_facts": [fact.id, state.id]}]
        )

    result = (await search(context(world, model), "дочь Светланы", kind="facet"))["result"]
    assert result["status"] == "complete" and [n["id"] for n in result["items"]] == [facet.id]
    assert result["items"][0]["source_facts"] == [fact.id, state.id]


def test_describe_discovers_properties_without_computing_and_uses_one_time(monkeypatch):
    world = semantic_world()
    g, runtime = world.graph, world.attribution
    start = datetime(2025, 1, 1, tzinfo=UTC)
    entity = Instance(g.reserve_id(), "Car")
    first = Facet(g.reserve_id(), "Moving", valid_from=start, valid_until=start + timedelta(days=1))
    second = Facet(g.reserve_id(), "Stopped", valid_from=start + timedelta(days=1))
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


def test_remember_invalid_proposal_atomic_and_idempotent_sources():
    world = semantic_world()
    g, memory = world.graph, world.memory
    run = memory.start_run("input", "revision", {})
    event = memory.record(run, "message", output="Кошка — животное")
    memory.finish_run(run)
    payload = {
        "statements": ["Кошка — животное"],
        "sources": [json_value(memory.output_ref(event))],
        "proposal": {"creates": [{"id": -1, "name": "Кошка"}, {"id": -2, "name": "кошка"}]},
    }
    metadata = {
        "run_id": "remember",
        "task_id": "task",
        "program": {"role": "exec", "revision": "revision"},
    }
    before, identity = g.revision, g._next_id
    assert world.service.commit(payload, metadata)["status"] == "invalid"
    assert g.revision == before and g._next_id == identity
    payload["proposal"]["creates"].pop()
    result = world.service.commit(payload, metadata)
    assert result["status"] == "saved"
    assert world.service.commit(payload, metadata) == result
    assert g.revision == before + 1
    change = g._history[-1]
    producer = memory.get_event(change.provenance["event_ref"])
    assert producer.dependencies == (memory.output_ref(event),)


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


async def test_taxonomy_reaches_instances_and_facets_without_relation_agent():
    world = semantic_world()
    g = world.graph
    kind = Prototype(g.reserve_id(), "Vehicle")
    instance = Instance(g.reserve_id(), "Object")
    facet = Facet(g.reserve_id(), "State")
    links = (
        g.new_fact("IDENTITY_TYPE", {"instance": instance.id, "type": kind.id}),
        g.new_fact("STATE_IDENTITY", {"instance": instance.id, "facet": facet.id}),
    )
    g.apply(GraphDelta(creates=(kind, instance, facet, *links)), provenance="source")

    async def model(payload):
        data = json.loads(payload["prompt"])
        if "reads" in data:
            return relation_decision("finish")
        if "candidates" in data:
            return {"keep": [n["id"] for n in data["candidates"]]}
        return {
            "decisions": [
                {
                    "id": n["id"],
                    "include": n["id"] in {kind.id, instance.id, facet.id},
                    "descend": False,
                }
                for n in data["nodes"]
            ]
        }

    result = (await search(context(world, model), "vehicles now", kind="facet"))["result"]
    assert result["status"] == "complete"
    assert [n["id"] for n in result["items"]] == [facet.id]
    assert result["items"][0]["source_facts"] == [f.id for f in links]
    assert result["items"][0]["evidence"][0]["provenance"] == "source"


async def test_anchor_failure_is_not_silently_successful_and_cards_are_authoritative():
    class Index(EmptyIndex):
        async def lexical(self, *args):
            raise RuntimeError("unavailable")

    world = semantic_world(index=Index())
    service = world.service
    metadata = {"task_id": "task"}
    result = await service.execute(
        "semantic.anchor", {"query": "missing", "revision": world.graph.revision}, metadata
    )
    assert result["errors"] == ["bm25: RuntimeError"]
    node = next(iter(world.graph.nodes()))
    result = await service.execute(
        "semantic.results",
        {
            "query": "query",
            "revision": world.graph.revision,
            "items": [{"id": node.id, "name": "invented", "channels": ["bm25"]}],
            "errors": [],
            "limit": 20,
        },
        metadata,
    )
    assert result["items"][0]["name"] == node.name


def test_cursor_is_repeatable_and_invalidated_by_graph_changes():
    world = semantic_world()
    cards = [{"id": n.id} for n in world.graph.nodes()]
    first = world.service.results("query", None, cards, [], 1, "task")
    second = world.service.lookup("query", limit=1, cursor=first["cursor"], task_id="task")
    again = world.service.lookup("query", limit=1, cursor=first["cursor"], task_id="task")
    assert second == again
    count = len(world.service._pages)
    world.service.lookup("query", limit=1, cursor=first["cursor"], task_id="task")
    assert len(world.service._pages) == count
    world.graph.apply(
        GraphDelta(creates=(Node(world.graph.reserve_id(), "New"),)), provenance="change"
    )
    with pytest.raises(ContractError, match="Graph changed"):
        world.service.lookup("query", cursor=first["cursor"], task_id="task")


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


def test_delta_uses_updated_signature_for_new_facts_and_observer_failure_is_postcommit():
    world = semantic_world()
    g = world.graph
    relation = RelationType(
        g.reserve_id(), "MEASURE", signature=(Slot("value", "number"),), views=()
    )
    g.apply(GraphDelta(creates=(relation,)), provenance="test")
    delta = world.service._proposal(
        {
            "updates": [
                {
                    "id": relation.id,
                    "changes": {"signature": [{"label": "value", "value_type": "node"}]},
                }
            ],
            "creates": [
                {"id": -1, "name": "Target"},
                {
                    "id": -2,
                    "kind": "relation_instance",
                    "relation_type": relation.id,
                    "args": {"value": -1},
                },
            ],
        }
    )
    g.on_change(lambda _: (_ for _ in ()).throw(RuntimeError("derived index failed")))
    g.apply(delta, provenance="test")
    assert g.facts(relation.id)[0].args["value"] == g.lookup("Target")[0].id


def test_remember_dedup_preserves_conditions_and_checks_updates():
    world = semantic_world()
    g = world.graph
    entity = Node(g.reserve_id(), "Object")
    prop = Node(g.reserve_id(), "Position", kind="property")
    args = {"entity": entity.id, "property": prop.id, "value": 1, "unit": "m"}
    from dataclasses import replace

    fact = replace(
        g.new_fact("HAS_NUMERIC_VALUE", args), properties={"conditions": {"frame": "world"}}
    )
    g.apply(GraphDelta(creates=(entity, prop, fact)), provenance="source")
    proposal = {
        "creates": [
            {**json_value(fact), "id": -1, "properties": {"conditions": {"frame": "local"}}}
        ]
    }
    delta = world.service._proposal(proposal)
    g.apply(delta, provenance="other frame")
    with pytest.raises(ContractError, match="Fact already exists"):
        world.service._proposal(
            {
                "updates": [
                    {
                        "id": delta.creates[0].id,
                        "changes": {"properties": json_value(fact.properties)},
                    }
                ]
            }
        )


async def test_invalid_relation_evidence_does_not_erase_other_channels():
    world = semantic_world()
    node = next(iter(world.graph.nodes()))
    result = await world.service.execute(
        "semantic.results",
        {
            "query": "missing",
            "revision": world.graph.revision,
            "limit": 20,
            "errors": [],
            "items": [
                {"id": node.id, "channels": ["bm25", "relations"], "source_facts": [node.id]}
            ],
        },
        {"task_id": "task"},
    )
    assert result["status"] == "incomplete"
    assert result["items"][0]["channels"] == ["bm25"]


async def test_remember_can_disambiguate_by_id():
    from types import SimpleNamespace

    from evertree.processes.semantic_processing.knowledge_remembering._exec import run

    calls = []
    answers = iter(
        [
            {"action": "describe", "query": 42, "delta_json": "", "summary": ""},
            {"action": "unresolved", "query": "", "delta_json": "", "summary": "Clarify"},
        ]
    )

    async def step(method, payload):
        calls.append((method, payload))
        return {"parsed": next(answers)} if method == "agent.run" else {}

    result = await run(SimpleNamespace(step=step), ["statement"], [])
    assert result["result"]["status"] == "unresolved"
    assert ("graph.describe", {"subject": 42}) in calls


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


async def test_relation_repeated_casefolded_lookup_reuses_read_and_can_finish():
    world = semantic_world(config=SemanticConfig(taxonomy_enabled=False))
    queries = []
    original = world.service.execute

    async def execute(method, payload, metadata):
        if method == "semantic.anchor":
            queries.append(payload["query"])
        return await original(method, payload, metadata)

    world.service.execute = execute
    decisions = iter(
        [
            relation_decision("lookup", query="Nobody"),
            relation_decision("lookup", query=" nobody "),
            relation_decision("finish"),
        ]
    )

    async def model(payload):
        return next(decisions)

    result = (await search(context(world, model), "no matching relations"))["result"]
    assert result["status"] == "complete"
    assert queries == ["Nobody"]
