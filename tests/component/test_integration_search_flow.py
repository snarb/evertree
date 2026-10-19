"""Graph navigation after retrieval uses real structural links and projected reads."""

from evertree.processes.semantic_processing.knowledge_integration._exec import _describe_for_model
from tests.support.pump_search import seed_pump_history
from tests.support.semantics import context, semantic_world


async def test_class_parent_remains_visible_beyond_the_relation_preview():
    from evertree.core.graph.types import GraphDelta, Instance, Prototype

    world = semantic_world()
    graph = world.graph
    parent = Prototype(graph.reserve_id(), "Equipment")
    child = Prototype(graph.reserve_id(), "Pump")
    instances = [Instance(graph.reserve_id(), f"P-{i}") for i in range(21)]
    facts = [
        graph.new_fact("IDENTITY_TYPE", {"instance": n.id, "type": child.id}) for n in instances
    ]
    graph.apply(GraphDelta(creates=(parent, child, *instances, *facts)), provenance="test")
    ctx = context(world, None, role="model")
    unlinked = _describe_for_model(await ctx.step("graph.describe", {"subject": child.id}))
    assert unlinked["parent"] is None
    link = graph.new_fact("SUBTYPE_OF", {"type": child.id, "supertype": parent.id})
    graph.apply(GraphDelta(creates=(link,)), provenance="classification")
    linked = _describe_for_model(await ctx.step("graph.describe", {"subject": child.id}))
    assert linked["relations_total"] == 22
    assert len(linked["relations"]) == 7
    assert not any(r["relation"] == "SUBTYPE_OF" for r in linked["relations"])
    assert linked["parent"]["id"] == parent.id
    assert linked["children"] == []
    assert "children_total" not in linked

    descendants = [
        Prototype(graph.reserve_id(), f"Pump subtype {i}", description="Omit this description")
        for i in range(9)
    ]
    links = [
        graph.new_fact("SUBTYPE_OF", {"type": descendant.id, "supertype": child.id})
        for descendant in descendants
    ]
    graph.apply(GraphDelta(creates=(*descendants, *links)), provenance="classification")
    for focus in (None, "relations"):
        raw = await ctx.step("graph.describe", {"subject": child.id, "focus": focus})
        for result in (raw, _describe_for_model(raw)):
            assert result["children_total"] == 9
            assert result["children"] == [node.name for node in descendants[:7]]
            assert list(result).index("children_total") < list(result).index("children")
    parent_result = _describe_for_model(await ctx.step("graph.describe", {"subject": parent.id}))
    assert parent_result["children"] == [child.name]
    assert "children_total" not in parent_result


async def test_found_facet_leads_to_identity_class_and_other_states_without_search():
    world = semantic_world()
    targets = seed_pump_history(world.graph)
    ctx = context(world, None, role="model")
    found = await ctx.call("semantic_search", {"query": "Н-1 выключен"})
    assert [item["id"] for item in found.result["items"]] == [targets["off"].id]
    facet = _describe_for_model(await ctx.step("graph.describe", {"subject": targets["off"].id}))
    link = next(fact for fact in facet["relations"] if fact["relation"] == "STATE_IDENTITY")
    identity = link["args"]["instance"]
    assert identity["id"] == targets["pump"].id
    described = _describe_for_model(await ctx.step("graph.describe", {"subject": identity["id"]}))
    class_link = next(
        fact for fact in described["relations"] if fact["relation"] == "IDENTITY_TYPE"
    )
    assert class_link["args"]["type"]["id"] == targets["prototype"].id
    states = [
        fact["args"]["facet"]
        for fact in described["relations"]
        if fact["relation"] == "STATE_IDENTITY"
    ]
    assert [state["id"] for state in states] == [targets["off"].id]
    assert states[0]["valid_until"] == targets["off"].valid_until.isoformat()


async def test_reviewed_creation_reuses_search_and_links_missing_parent():
    from evertree.common.integration_actions import SemanticTools
    from tests.support.semantics import EmptyIndex, recorded_experience

    class Neighbors(EmptyIndex):
        async def vector(self, nodes, query, kind):
            return [nodes[0]["id"]]

    world = semantic_world(index=Neighbors())
    refs, _ = recorded_experience(world, "Pump P1 is equipment used to move water.")
    ctx = context(world, None, role="exec")
    searches = []

    async def search(query):
        searches.append(query)
        return (await ctx.call("semantic_search", {"query": query})).result

    async def describe(subject):
        return await ctx.step("graph.describe", {"subject": subject})

    async def write(action, operation_key):
        return await ctx.step(
            "semantic.write",
            {"action": action, "operation_key": operation_key, "experience_refs": refs},
        )

    handler = SemanticTools(search=search, describe=describe, write=write)
    parent = None
    for name in ("Equipment", "Pump"):
        args = {"name": name, "description": None, "parent": parent, "sources": refs}
        created = await handler.handle("create_prototype", args)
        if parent is None:
            assert "error" in created and created["reads"][0]["result"]["items"]
            before = len(searches)
            created = await handler.handle("create_prototype", args)
            assert len(searches) == before
        # The child's fresh search returns the same already exposed Process candidate.
        assert "error" not in created
        child = created["object"]
        if parent is not None:
            assert any(
                fact.args == {"type": child, "supertype": parent}
                for fact in world.graph.facts("SUBTYPE_OF")
            )
        parent = child
    assert searches == ["Equipment", "Pump"]
