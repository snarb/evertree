"""Typed search scopes preserve retrieval intent without authorizing duplicate identities."""

import pytest

from evertree.common.semantic_search import search
from evertree.core.graph.types import GraphDelta, Node
from evertree.core.memory.store import TraceStore
from evertree.core.semantics.searching import search_kinds
from evertree.core.values import ContractError
from evertree.processes.self_semantic_processing.self_knowledge_integration._exec import run
from tests.support.semantics import (
    EmptyIndex,
    context,
    recorded_experience,
    semantic_world,
    write_action,
)


@pytest.mark.parametrize("kinds", [[], "concept", [""], [" "], [True], [None], ["concepts"]])
def test_invalid_kind_filters_are_correctable(kinds):
    with pytest.raises(ContractError):
        search_kinds(kinds)


async def test_exact_search_unions_kinds_without_hiding_same_named_assertions():
    class NoIndex(EmptyIndex):
        async def lexical(self, *args):
            pytest.fail("Exact queries must bypass indexes")

        async def vector(self, *args):
            pytest.fail("Exact queries must bypass indexes")

    world = semantic_world(index=NoIndex())
    nodes = [
        Node(world.graph.reserve_id(), "Shared meaning", kind=kind)
        for kind in ("concept", "claim", "note")
    ]
    world.graph.apply(GraphDelta(creates=nodes), provenance="test")
    ctx = context(world, None)
    broad = (await search(ctx, ["shared meaning"]))["result"]
    assert [item["id"] for item in broad["items"]] == [nodes[0].id]
    filtered = (await search(ctx, ["SHARED meaning"], kinds=[" CLAIM ", "Concept", "claim"]))[
        "result"
    ]
    assert [item["id"] for item in filtered["items"]] == [n.id for n in nodes[:2]]
    assert filtered["exact"]
    assert (await search(ctx, [nodes[2].id], kinds=["claim", "concept"]))["result"]["items"] == []


async def test_filter_is_normalized_once_for_both_batched_channels():
    calls = []

    class Index(EmptyIndex):
        async def lexical(self, nodes, queries, kinds):
            calls.append(("bm25", queries, kinds))
            return [{"ids": [claim.id]} for _ in queries]

        async def vector(self, nodes, queries, kinds):
            calls.append(("vector", queries, kinds))
            return [{"ids": [note.id]} for _ in queries]

    world = semantic_world(index=Index())
    claim = Node(world.graph.reserve_id(), "First fact", kind="claim")
    note = Node(world.graph.reserve_id(), "Saved detail", kind="note")
    world.graph.apply(GraphDelta(creates=(claim, note)), provenance="test")
    result = (
        await search(context(world, None), ["first", "second"], kinds=["NOTE", "claim", "note"])
    )["result"]
    assert sorted(calls) == [
        ("bm25", ["first", "second"], ["claim", "note"]),
        ("vector", ["first", "second"], ["claim", "note"]),
    ]
    assert {item["id"] for item in result["items"]} == {claim.id, note.id}
    assert all(item["query_indices"] == [0, 1] for item in result["items"])


@pytest.mark.parametrize(
    ("broad", "filtered", "allowed"),
    [(None, True, False), (False, True, False), (True, False, True)],
)
def test_creation_confirmation_is_scoped_by_filter_after_restore(broad, filtered, allowed):
    world = semantic_world()
    refs, metadata = recorded_experience(world, "A new useful meaning")
    service = world.service

    def record(kinds, complete):
        service.results(
            "New meaning",
            kinds,
            [],
            [] if complete else [{"channel": "vector", "error": "offline"}],
            10,
            "task",
            scope="packet",
        )

    if broad is not None:
        record(None, broad)
    record(["note", "CLAIM", "note"], filtered)
    record(["claim", "note"], filtered)
    filtered_reviews = [
        run
        for run in world.memory.runs
        if run.program == "SemanticSearchReview" and run.arguments["key"][-1]
    ]
    assert len(filtered_reviews) == 1
    service.memory = TraceStore.from_snapshot(world.memory.snapshot())
    action = {
        "action": "create_concept",
        "name": "New meaning",
        "description": None,
        "sources": refs,
    }
    result = write_action(world, refs, metadata, action, searched=False)
    assert ("object" in result) is allowed
    if not allowed:
        assert "complete search" in result["error"]


async def test_integration_filtered_search_does_not_replace_creation_review():
    calls = []

    class Index(EmptyIndex):
        async def lexical(self, nodes, queries, kinds):
            calls.append((queries, kinds))
            return [{"ids": [existing.id] if kinds is None else []} for _ in queries]

    world = semantic_world(index=Index())
    existing = Node(world.graph.reserve_id(), "Related concept")
    world.graph.apply(GraphDelta(creates=(existing,)), provenance="test")
    refs, _ = recorded_experience(world, "Distinct meaning needs its own identity.")

    async def model(_payload, call):
        assert not (await call("search", {"queries": ["Distinct meaning"], "kinds": ["note"]}))[
            "items"
        ]
        fields = {"name": "Distinct meaning", "description": None, "sources": refs}
        first = await call("create_concept", fields)
        assert "Review search candidates" in first["error"]
        assert first["reads"][0]["kinds"] is None
        assert "object" in await call("create_concept", fields)

    await run(context(world, model, role="exec"), refs)
    assert calls == [(["Distinct meaning"], ["note"]), (["Distinct meaning"], None)]


@pytest.mark.parametrize("limit", [1, 2])
async def test_integration_search_passes_explicit_result_limit(limit):
    world = semantic_world()
    nodes = [
        Node(world.graph.reserve_id(), "Shared detail", kind=kind) for kind in ("claim", "note")
    ]
    world.graph.apply(GraphDelta(creates=nodes), provenance="test")
    refs, _ = recorded_experience(world, "Read saved details.")
    results = []

    async def model(_payload, call):
        results.append(
            await call(
                "search", {"queries": ["Shared detail"], "kinds": ["claim", "note"], "limit": limit}
            )
        )

    await run(context(world, model, role="exec"), refs)
    assert len(results) == 1
    assert [item["id"] for item in results[0]["items"]] == [node.id for node in nodes[:limit]]
