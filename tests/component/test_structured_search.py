"""Structured facts retain their meaning throughout retrieval and relevance filtering."""

import json

from evertree.common.semantic_search import search
from evertree.core.semantics.index import RedisSearchIndex
from evertree.core.semantics.reading import search_card
from tests.support.semantics import EmptyIndex, context, structured_fact_world


def test_projection_preserves_roles_values_and_opaque_data_without_indexing_reference_ids():
    world = structured_fact_world()
    projected = search_card(world.graph, world.target)
    fields = json.loads(RedisSearchIndex._text(projected).split("\n", 1)[1])
    assert projected["args"]["sender"] == {
        "id": world.sender.id,
        "name": "Kestrel",
        "kind": "concept",
    }
    assert "id" not in fields["args"]["sender"]
    assert fields["args"]["receivers"][0]["name"] == "Reservoir"
    assert fields["args"]["flow"] == 83.75
    assert fields["args"]["annotation"] == 99001
    assert fields["properties"]["opaque"]["id"] == 99001
    assert fields["properties"]["conditions"] == {"mode": "backup"}
    assert "provenance" not in projected and "belief" not in projected


async def test_core_index_jev_and_model_receive_actual_structured_fact_meaning():
    indexed, filtered = [], []

    class Index(EmptyIndex):
        async def lexical(self, nodes, queries, kind):
            indexed.extend(nodes)
            return [{"ids": [world.target.id]}]

    class Filter:
        async def filter(self, queries, nodes):
            filtered.extend(nodes)
            return {node["id"] for node in nodes}, []

    world = structured_fact_world(index=Index())
    world.service.jev = Filter()
    result = (await search(context(world, None), ["Kestrel backup transfer"]))["result"]
    expected = search_card(world.graph, world.target)
    assert expected in indexed and filtered == [expected]
    assert result["items"][0]["args"] == expected["args"]
    assert result["items"][0]["properties"] == expected["properties"]
    indexed.clear()
    exact = (await search(context(world, None), [world.relation.id]))["result"]
    assert exact["items"][0]["signature"] == search_card(world.graph, world.relation)["signature"]
    assert indexed == []
