"""Real Redis Search; set EVERTREE_TEST_REDIS_URL to an isolated Redis 8.4+ server."""

import asyncio
import os
from contextlib import suppress
from dataclasses import replace
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from evertree.core.graph.types import GraphDelta, Node, NodeUpdate
from evertree.core.semantics.config import SearchConfig, SemanticConfig
from evertree.core.semantics.index import RedisSearchIndex
from evertree.core.semantics.reading import card, search_card
from tests.support.semantics import semantic_world

pytestmark = pytest.mark.skipif(
    not os.environ.get("EVERTREE_TEST_REDIS_URL"), reason="Real Redis Search URL required"
)


class Embeddings:
    async def embed(self, texts):
        return [[1.0, float(len(t) % 7 + 1), 0.25] for t in texts]


async def test_real_redis_quotas_mutations_rebuild_and_restore():
    """Real FT commands verify dialect, scoring, vector encoding and restored generations."""
    client = Redis.from_url(os.environ["EVERTREE_TEST_REDIS_URL"])
    index = RedisSearchIndex(
        replace(
            SemanticConfig(),
            embedding_dimensions=3,
            search=SearchConfig(bm25_candidates=7, vector_candidates=12),
        ),
        uuid4().hex,
        client=client,
        embeddings=Embeddings(),
    )
    world = semantic_world(index=index)
    g = world.graph
    nodes = [Node(g.reserve_id(), f"Cat {i}", description="feline animal") for i in range(20)]
    g.apply(GraphDelta(creates=tuple(nodes)), provenance="test")
    snapshot = g.snapshot()
    try:
        cards = [card(n) for n in g.nodes()]
        lexical, vector = await asyncio.gather(
            index.lexical(cards, ["feline"]), index.vector(cards, ["cat"])
        )
        lexical, vector = lexical[0]["ids"], vector[0]["ids"]
        assert len(lexical) == 7 and len(vector) == 12
        assert set(lexical) <= {n.id for n in nodes}
        assert (await index.lexical(cards, ["feline"], ["facet"]))[0]["ids"] == []
        old_generation = index._current
        g.apply(
            GraphDelta(
                updates=(
                    NodeUpdate(nodes[0].id, {"name": "Unique sentinel", "description": "renamed"}),
                ),
                deletes=(nodes[1].id,),
            ),
            provenance="mutation",
        )
        # A commit does no Redis work. The next search replaces the derived index.
        assert index._current == old_generation
        assert await client.execute_command("FT.INFO", old_generation)
        new_cards = [card(n) for n in g.nodes()]
        assert (await index.lexical(new_cards, ["sentinel"]))[0]["ids"] == [nodes[0].id]
        owned = [
            name.decode()
            for name in await client.execute_command("FT._LIST")
            if name.decode().startswith(index.namespace + ":")
        ]
        assert owned == [index._generation(new_cards)]
        from evertree.core.graph.store import GraphStore

        restored = GraphStore.from_snapshot(snapshot)
        assert (await index.lexical([card(n) for n in restored.nodes()], ["sentinel"]))[0][
            "ids"
        ] == []
        # Losing Redis data is recoverable without touching authoritative graph data.
        generation = index._generation(cards)
        await client.execute_command("FT.DROPINDEX", generation, "DD")
        assert len((await index.lexical(cards, ["feline"]))[0]["ids"]) == 7
    finally:
        for name in index._ready:
            with suppress(ResponseError):
                await client.execute_command("FT.DROPINDEX", name, "DD")
        keys = [key async for key in client.scan_iter(index.namespace + ":*")]
        if keys:
            await client.delete(*keys)
        await index.close()


@pytest.fixture
async def corpus_index():
    from tests.support.semantics import populated_search_world

    world = populated_search_world()
    cards = [card(n) for n in world.graph.nodes()]
    kinds = list(world.targets)
    texts = {
        RedisSearchIndex._text(project): position
        for position, n in enumerate(world.targets.values())
        for project in (card(n), search_card(world.graph, n))
    }

    class KnownVectors:
        def __init__(self):
            self.calls = []

        async def embed(self, texts_to_embed):
            self.calls.append(list(texts_to_embed))
            result = []
            for text in texts_to_embed:
                position = (
                    kinds.index(text.removeprefix("vector-query:"))
                    if text.startswith("vector-query:")
                    else texts.get(text, len(kinds))
                )
                result.append([float(i == position) for i in range(len(kinds) + 1)])
            return result

    client = Redis.from_url(os.environ["EVERTREE_TEST_REDIS_URL"])
    index = RedisSearchIndex(
        replace(
            SemanticConfig(),
            embedding_dimensions=len(kinds) + 1,
            search=SearchConfig(bm25_candidates=7, vector_candidates=12),
        ),
        uuid4().hex,
        client=client,
        embeddings=KnownVectors(),
    )
    try:
        yield world, cards, index
    finally:
        for name in tuple(index._ready):
            with suppress(ResponseError):
                await client.execute_command("FT.DROPINDEX", name, "DD")
        keys = [key async for key in client.scan_iter(index.namespace + ":*")]
        if keys:
            await client.delete(*keys)
        await index.close()


@pytest.mark.parametrize(
    ("kind", "name_term", "description_term"),
    [
        ("concept", "МУРЛЫКАНЬЕ", "вибрирующий"),
        ("prototype", "КОШКА", "мышей"),
        ("facet", "МУРКИ", "подоконнике"),
        ("instance", "МУРКА", "питомец"),
        ("relation_type", "ДОЧЬ", "участник"),
        ("relation_instance", "ДОЧЬ", "родство"),
    ],
)
@pytest.mark.parametrize("field", ["name", "description"])
async def test_real_fulltext_bm25_by_kind_and_field(
    corpus_index, kind, name_term, description_term, field
):
    world, cards, index = corpus_index
    query = name_term if field == "name" else description_term
    ids = (await index.lexical(cards, [query], [kind]))[0]["ids"]
    variant = " \t " + "   ".join(query.upper().split()) + "  "
    assert (await index.lexical(cards, [variant], [kind.upper()]))[0]["ids"] == ids
    assert world.targets[kind].id in ids
    assert all(world.graph.get(identity).kind == kind for identity in ids)
    assert len(ids) <= 7
    assert (await index.lexical(cards, ["несуществующеесловоцщ"], [kind]))[0]["ids"] == []


@pytest.mark.parametrize(
    "kind", ["concept", "prototype", "facet", "instance", "relation_type", "relation_instance"]
)
async def test_real_knn_ranks_known_vectors_per_kind(corpus_index, kind):
    world, cards, index = corpus_index
    ids = (await index.vector(cards, ["vector-query:" + kind], [kind]))[0]["ids"]
    assert ids and world.targets[kind].id in ids[:2]
    assert all(world.graph.get(identity).kind == kind for identity in ids)
    assert len(ids) <= 12


async def test_kind_union_filters_before_both_channel_quotas(corpus_index):
    """Real Redis tag unions must exclude competing kinds before lexical and KNN ceilings."""
    world, _cards, index = corpus_index
    index.config = replace(
        index.config, search=SearchConfig(bm25_candidates=2, vector_candidates=2)
    )
    nodes = [
        Node(world.graph.reserve_id(), f"Distractor {i}", description="needle") for i in range(20)
    ]
    targets = [
        Node(world.graph.reserve_id(), f"Saved {kind}", kind=kind, description="needle detail")
        for kind in ("claim", "note")
    ]
    world.graph.apply(GraphDelta(creates=(*nodes, *targets)), provenance="test")
    cards = [card(n) for n in world.graph.nodes()]
    expected = {node.id for node in targets}
    for channel in (index.lexical, index.vector):
        rows = await channel(cards, ["needle", "needle detail"], [" NOTE ", "claim", "note"])
        assert all(set(row["ids"]) == expected for row in rows)
        assert not any(row.get("error") for row in rows)


async def test_real_batch_reuses_generation_and_embeds_queries_together(corpus_index):
    """Real Redis pipelines must preserve query order and match warmed singleton retrieval."""
    _world, cards, index = corpus_index
    queries = ["vector-query:concept", "vector-query:instance", "vector-query:facet"]
    singles = [(await index.vector(cards, [query]))[0] for query in queries]
    generation = index._current
    index.embeddings.calls.clear()
    assert await index.vector(cards, queries) == singles
    assert index.embeddings.calls == [queries]
    assert index._current == generation
    lexical = ["МУРКА", "ДОЧЬ", "несуществующеесловоцщ"]
    expected = [(await index.lexical(cards, [query]))[0] for query in lexical]
    assert await index.lexical(cards, lexical) == expected
    assert expected[-1] == {"ids": []}


async def test_vector_population_does_not_rewrite_lexical_statistics(corpus_index):
    """Separate Redis records keep first-search BM25 scores equal to warmed search scores."""
    _world, cards, index = corpus_index
    generation = await index._ensure(cards)
    command = (
        "FT.SEARCH",
        generation,
        "@text:(мурка|питомец|кошка)",
        "WITHSCORES",
        "SCORER",
        "BM25STD",
        "RETURN",
        1,
        "identity",
        "LIMIT",
        0,
        100,
        "DIALECT",
        2,
    )
    before = await index.client.execute_command(*command)
    await index.vector(cards, ["vector-query:instance"])
    assert await index.client.execute_command(*command) == before
    vector_index = generation + ":vectors"
    assert vector_index in index._ready
    await index.client.execute_command("FT.DROPINDEX", vector_index, "DD")
    assert (await index.vector(cards, ["vector-query:instance"]))[0]["ids"]
    assert await index.client.execute_command(*command) == before


@pytest.mark.parametrize("algorithm", ["FLAT", "HNSW"])
async def test_long_objects_retrieve_tail_and_cannot_fill_quotas_with_their_passages(
    corpus_index, algorithm, monkeypatch
):
    """Real Redis must collapse passage hits before applying each channel's object quota."""
    world, _cards, index = corpus_index
    monkeypatch.setattr(index, "_algorithm", lambda _count: algorithm)
    index.config = replace(index.config, search=SearchConfig(2, 2, 64, 16))

    class PassageVectors:
        async def embed(self, texts):
            return [
                [float("sentinel" in text), float("sentinel" not in text)]
                + [0.0] * (index.config.embedding_dimensions - 2)
                for text in texts
            ]

    index.embeddings = PassageVectors()
    nodes = [
        Node(world.graph.reserve_id(), "Long source", description="sentinel other " * 600),
        Node(
            world.graph.reserve_id(),
            "Tail source",
            description="unrelated filler " * 600 + " sentinel",
        ),
        Node(world.graph.reserve_id(), "Distractor", description="unrelated content"),
    ]
    world.graph.apply(GraphDelta(creates=nodes), provenance="passage-test")
    cards = [card(n) for n in nodes]
    lexical, vector = await asyncio.gather(
        index.lexical(cards, ["sentinel"]), index.vector(cards, ["sentinel"])
    )
    expected = {nodes[0].id, nodes[1].id}
    assert set(lexical[0]["ids"]) == expected
    assert set(vector[0]["ids"]) == expected
    assert len(index._documents(cards)) > 20


async def test_description_free_facts_are_retrieved_by_roles_values_and_renamed_participants():
    """Real Redis proves structured retrieval beyond the candidate quota and generation refresh."""
    from evertree.core.semantics.reading import search_card
    from tests.support.semantics import structured_fact_world

    class RoleVectors:
        async def embed(self, texts):
            return [
                [float("kestrel" in text.lower() or "heron" in text.lower()), 0.1, 0.2]
                for text in texts
            ]

    client = Redis.from_url(os.environ["EVERTREE_TEST_REDIS_URL"])
    index = RedisSearchIndex(
        replace(SemanticConfig(), embedding_dimensions=3),
        uuid4().hex,
        client=client,
        embeddings=RoleVectors(),
    )
    world = structured_fact_world(index=index)
    graph = world.graph
    try:
        cards = [search_card(graph, node) for node in graph.nodes()]
        lexical, vector = await asyncio.gather(
            index.lexical(cards, ["Kestrel 83.75 backup"], ["relation_instance"]),
            index.vector(cards, ["Kestrel transfer"], ["relation_instance"]),
        )
        assert lexical[0]["ids"][0] == vector[0]["ids"][0] == world.target.id
        previous = index._current
        graph.apply(
            GraphDelta(updates=[NodeUpdate(world.sender.id, {"name": "Heron"})]),
            provenance="rename",
        )
        cards = [search_card(graph, node) for node in graph.nodes()]
        assert (await index.lexical(cards, ["Heron"], ["relation_instance"]))[0]["ids"] == [
            world.target.id
        ]
        assert index._current != previous
        assert (await index.lexical(cards, ["Kestrel"], ["relation_instance"]))[0]["ids"] == []
    finally:
        for name in tuple(index._ready):
            with suppress(ResponseError):
                await client.execute_command("FT.DROPINDEX", name, "DD")
        keys = [key async for key in client.scan_iter(index.namespace + ":*")]
        if keys:
            await client.delete(*keys)
        await index.close()
