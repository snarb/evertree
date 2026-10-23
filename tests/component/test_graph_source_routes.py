"""Graph routes recover exact sourced facts even when bounded text search returns distractors."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from evertree.common.semantic_search import search
from evertree.core.graph import api as graph_api
from evertree.core.graph.types import GraphDelta, Instance, Node, Prototype, RelationType, Slot
from evertree.core.memory import api as memory_api
from evertree.core.memory.types import TraceOutputRef
from evertree.core.tokens import current_read_context
from evertree.core.values import json_value
from tests.support.semantics import EmptyIndex, context, semantic_world
from tests.support.tokens import offline_tokenizer  # noqa: F401 -- offline BPE fixture


@pytest.fixture
def source_graph():
    class RankedDistractors(EmptyIndex):
        async def lexical(self, nodes, queries, kinds):
            return [{"ids": ranked} for _ in queries]

        async def vector(self, nodes, queries, kinds):
            return [{"ids": ranked} for _ in queries]

    world = semantic_world(index=RankedDistractors())
    graph = world.graph
    classes = {
        name: Prototype(graph.reserve_id(), name)
        for name in (
            "Organisation",
            "Library",
            "Public library",
            "Service",
            "Streaming service",
            "Platform",
        )
    }
    identities = {
        name: Instance(graph.reserve_id(), name)
        for name in (
            "Harbor Library",
            "Other Library",
            "Community film club",
            "Paid cinema",
            "ScreenShare",
        )
    }
    relationships = [
        graph.new_fact("SUBTYPE_OF", {"type": classes[child].id, "supertype": classes[parent].id})
        for child, parent in (
            ("Library", "Organisation"),
            ("Public library", "Library"),
            ("Streaming service", "Service"),
        )
    ]
    relationships += [
        graph.new_fact(
            "IDENTITY_TYPE", {"instance": identities[name].id, "type": classes[type_].id}
        )
        for name, type_ in (
            ("Harbor Library", "Public library"),
            ("Other Library", "Library"),
            ("Community film club", "Streaming service"),
            ("Paid cinema", "Service"),
            ("ScreenShare", "Platform"),
        )
    ]
    runs = RelationType(
        graph.reserve_id(),
        "RUNS",
        signature=(Slot("organisation", "instance"), Slot("service", "instance")),
    )
    available = RelationType(
        graph.reserve_id(),
        "AVAILABLE_ON",
        signature=(Slot("service", "instance"), Slot("platform", "instance")),
    )
    distractors = [
        Node(graph.reserve_id(), f"General viewing news {i}", kind="note") for i in range(12)
    ]
    graph.apply(
        GraphDelta(
            creates=(
                *classes.values(),
                *identities.values(),
                *relationships,
                runs,
                available,
                *distractors,
            )
        ),
        provenance="fixture schema",
    )
    run = world.memory.start_run("Article", "revision", {})
    source_text = "Harbor Library runs Community film club on ScreenShare. Access costs zero per month for library members. Advertising may appear."
    event = world.memory.record(
        run, "observation", output={"title": "Library announcement", "body": source_text}
    )
    world.memory.finish_run(run)
    reference = TraceOutputRef(event.id, ("body",))
    operates = graph.new_fact(
        runs.id,
        {
            "organisation": identities["Harbor Library"].id,
            "service": identities["Community film club"].id,
        },
    )
    free = replace(
        graph.new_fact(
            available.id,
            {
                "service": identities["Community film club"].id,
                "platform": identities["ScreenShare"].id,
            },
        ),
        properties={"conditions": {"members_only": True, "monthly_fee": 0}},
    )
    world.operations.apply_delta(
        GraphDelta(creates=(operates, free)),
        task_id="task",
        revision="revision",
        source_refs=(reference,),
    )
    paid = replace(
        graph.new_fact(
            available.id,
            {"service": identities["Paid cinema"].id, "platform": identities["ScreenShare"].id},
        ),
        properties={"conditions": {"members_only": False, "monthly_fee": 9}},
    )
    graph.apply(GraphDelta(creates=(paid,)), provenance="unrelated paid service")
    ranked = [n.id for n in distractors] + [operates.id, free.id]
    token = current_read_context.set({"model": "gpt-5", "context_window": 100_000})
    try:
        yield SimpleNamespace(
            world=world,
            ctx=context(world, None),
            classes=classes,
            identities=identities,
            runs=runs,
            available=available,
            free=free,
            operates=operates,
            reference=reference,
            source_text=source_text,
            distractors=distractors,
        )
    finally:
        current_read_context.reset(token)


async def read(fixture, method, **arguments):
    return await graph_api.read(fixture.ctx, method, arguments)


async def exact_source(fixture, facts):
    sources = await graph_api.sources(fixture.ctx, facts)
    assert sources["total"] == 1 and not sources["has_more"]
    source = sources["items"][0]
    assert source["reference"] == json_value(fixture.reference)
    assert {binding["subject"] for binding in source["bindings"]} == set(facts)
    content = await memory_api.read_source(fixture.ctx, reference=source["reference"])
    assert content["status"] == "available" and not content["has_more"]
    assert content["content"] == fixture.source_text


async def test_anchor_two_predicates_reach_source_beyond_search_top_ten(source_graph):
    f = source_graph
    broad = (await search(f.ctx, ["library free streaming service for members"]))["result"]
    assert len(broad["items"]) == 10 and broad["queries"][0]["total"] == 14
    assert {item["id"] for item in broad["items"]} <= {n.id for n in f.distractors}
    anchor = (await search(f.ctx, ["Harbor Library"], kinds=["instance"]))["result"]["items"][0]
    first = await read(
        f,
        "walk",
        start=anchor["id"],
        relation=f.runs.id,
        from_slot="organisation",
        to_slot="service",
        max_depth=1,
    )
    assert not first["has_more"] and first["total"] == 1
    service = first["items"][0]["node"]
    second = await read(
        f,
        "query",
        relation=f.available.id,
        bindings=[{"slot": "service", "value": service}],
        where=[{"field": "conditions.members_only", "op": "==", "value": True}],
        select=["platform"],
        result="nodes",
    )
    assert not second["has_more"] and second["total"] == 1
    assert second["items"][0]["node"] == f.identities["ScreenShare"].id
    assert second["facts"][0]["properties"]["conditions"] == {
        "members_only": True,
        "monthly_fee": 0,
    }
    await exact_source(f, [first["facts"][0]["id"], second["facts"][0]["id"]])
    wrong_role = await read(
        f,
        "query",
        relation=f.available.id,
        bindings=[{"slot": "platform", "value": service}],
        result="exists",
    )
    assert wrong_role["exists"] is False
    wrong_condition = await read(
        f,
        "query",
        relation=f.available.id,
        bindings=[{"slot": "service", "value": service}],
        where=[{"field": "conditions.monthly_fee", "op": ">", "value": 0}],
        result="exists",
    )
    assert wrong_condition["exists"] is False


async def test_taxonomy_route_finds_subclasses_instances_and_qualified_source(source_graph):
    f = source_graph
    organisation = f.classes["Organisation"].id
    subtree = await read(
        f,
        "walk",
        start=organisation,
        relation="SUBTYPE_OF",
        from_slot="supertype",
        to_slot="type",
        max_depth=None,
    )
    assert not subtree["has_more"] and {item["depth"] for item in subtree["items"]} == {1, 2}
    classes = [organisation, *(item["node"] for item in subtree["items"])]
    organisations = await read(
        f,
        "query",
        relation="IDENTITY_TYPE",
        where=[{"field": "args.type", "op": "in", "value": classes}],
        select=["instance"],
        result="nodes",
    )
    assert not organisations["has_more"] and organisations["total"] == 2
    instances = [item["node"] for item in organisations["items"]]
    services = await read(
        f,
        "query",
        relation=f.runs.id,
        where=[{"field": "args.organisation", "op": "in", "value": instances}],
        select=["service"],
        result="nodes",
    )
    assert not services["has_more"] and services["total"] == 1
    qualified = await read(
        f,
        "query",
        relation=f.available.id,
        where=[
            {
                "field": "args.service",
                "op": "in",
                "value": [item["node"] for item in services["items"]],
            },
            {"field": "conditions.monthly_fee", "op": "==", "value": 0},
            {"field": "conditions.members_only", "op": "==", "value": True},
        ],
        result="matches",
    )
    assert not qualified["has_more"] and qualified["total"] == 1
    assert qualified["facts"][0]["id"] == f.free.id
    await exact_source(f, [qualified["facts"][0]["id"]])
