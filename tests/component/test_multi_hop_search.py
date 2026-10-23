"""Adaptive-read bookkeeping; scripted decisions do not establish model judgment."""

import pytest

from evertree.core.graph.types import GraphDelta, Node
from tests.support.search_session import SearchSession
from tests.support.semantics import context, semantic_world


async def test_dependent_search_and_reads_preserve_discovered_identifiers_and_evidence():
    world = semantic_world()
    anchor = Node(world.graph.reserve_id(), "Beacon Q7", description="Fallback route: RX-843921")
    route = Node(world.graph.reserve_id(), "RX-843921", description="Archive service: SE-7752")
    destination = Node(world.graph.reserve_id(), "SE-7752", description="Retention: 17 days")
    world.graph.apply(GraphDelta(creates=[anchor, route, destination]), provenance="fixture")
    session = SearchSession(context(world, None))
    first = await session.call("graph.search", {"queries": [anchor.name]})
    route_name = first["items"][0]["description"].split(": ")[1]
    second = await session.call("graph.describe", {"subject": route_name})
    service_name = second["subject"]["description"].split(": ")[1]
    third = await session.call("graph.search", {"queries": [service_name]})
    assert third["items"][0]["id"] == destination.id
    assert set(session.visible) == {anchor.id, route.id, destination.id}
    assert session.check_evidence([{"object_id": destination.id, "supports": "retention"}]) == {
        destination.id
    }
    with pytest.raises(ValueError, match="never read"):
        session.check_evidence([{"object_id": 99999, "supports": "invented"}])


async def test_adaptive_budgets_do_not_reset_between_hops_or_infer_absence():
    world = semantic_world()
    session = SearchSession(context(world, None), searches=2, queries=2, reads=1)
    first = await session.call("graph.search", {"queries": ["not present"]})
    assert first["status"] == "complete" and first["items"] == []
    second = await session.call("graph.search", {"queries": ["different", "unrelated"]})
    assert "1 query entries remain" in second["error"]
    assert session.searches == 1 and session.queries == 1
    assert (await session.call("graph.search", {"queries": ["Process"]}))["exact"]
    assert (
        "budget exhausted"
        in (await session.call("graph.search", {"queries": ["Process"]}))["error"]
    )
    assert (await session.call("graph.describe", {"subject": "Process"}))["subject"][
        "name"
    ] == "Process"
    assert (
        "budget exhausted"
        in (await session.call("graph.describe", {"subject": "Process"}))["error"]
    )
