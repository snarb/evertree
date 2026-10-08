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
from evertree.core.semantics.config import SemanticConfig
from evertree.core.semantics.index import RedisSearchIndex
from evertree.core.semantics.reading import card
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
        replace(SemanticConfig(), embedding_dimensions=3),
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
            index.lexical(cards, "feline"), index.vector(cards, "cat")
        )
        assert len(lexical) == 7 and len(vector) == 12
        assert set(lexical) <= {n.id for n in nodes}
        assert await index.lexical(cards, "feline", "facet") == []
        index.attach(g)
        await index._refresh_task
        async with index._generation_lease(cards) as old_generation:
            g.apply(
                GraphDelta(
                    updates=(
                        NodeUpdate(
                            nodes[0].id, {"name": "Unique sentinel", "description": "renamed"}
                        ),
                    ),
                    deletes=(nodes[1].id,),
                ),
                provenance="mutation",
            )
            await index._refresh_task
            assert index.indexed_revision["revision"] == g.revision
            new_cards = [card(n) for n in g.nodes()]
            assert await index.lexical(new_cards, "sentinel") == [nodes[0].id]
            assert await client.execute_command("FT.INFO", old_generation)
        owned = [
            name.decode()
            for name in await client.execute_command("FT._LIST")
            if name.decode().startswith(index.namespace + ":")
        ]
        assert owned == [index._generation(new_cards)]
        from evertree.core.graph.store import GraphStore

        restored = GraphStore.from_snapshot(snapshot)
        index.attach(restored)
        await index._refresh_task
        assert await index.lexical([card(n) for n in restored.nodes()], "sentinel") == []
        # Losing Redis data is recoverable without touching authoritative graph data.
        generation = index._generation(cards)
        await client.execute_command("FT.DROPINDEX", generation, "DD")
        assert len(await index.lexical(cards, "feline")) == 7
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
        RedisSearchIndex._text(card(n)): position
        for position, n in enumerate(world.targets.values())
    }

    class KnownVectors:
        async def embed(self, texts_to_embed):
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
        replace(SemanticConfig(), embedding_dimensions=len(kinds) + 1),
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
    ids = await index.lexical(cards, query, kind)
    assert world.targets[kind].id in ids
    assert all(world.graph.get(identity).kind == kind for identity in ids)
    assert len(ids) <= 7
    assert await index.lexical(cards, "несуществующеесловоцщ", kind) == []


@pytest.mark.parametrize(
    "kind", ["concept", "prototype", "facet", "instance", "relation_type", "relation_instance"]
)
async def test_real_knn_ranks_known_vectors_per_kind(corpus_index, kind):
    world, cards, index = corpus_index
    ids = await index.vector(cards, "vector-query:" + kind, kind)
    assert ids and world.targets[kind].id in ids[:2]
    assert all(world.graph.get(identity).kind == kind for identity in ids)
    assert len(ids) <= 12
