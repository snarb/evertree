"""Real slot reads preserve fact semantics and budget the final model projection."""

from dataclasses import replace

import pytest

from evertree.core.graph.types import Facet, GraphDelta, Node, RelationType, Slot
from evertree.core.semantics.config import ReadConfig, SemanticConfig
from evertree.core.tokens import count_tokens, current_read_context
from evertree.core.values import ContractError, timestamp
from evertree.processes.semantic_processing.knowledge_integration._exec import run
from tests.support.semantics import (
    context,
    populated_search_world,
    recorded_experience,
    semantic_world,
)
from tests.support.tokens import offline_tokenizer  # noqa: F401 -- offline BPE fixture

CONTEXT = {"model": "gpt-5", "context_window": 1_000_000}


def read(world, method="query", *, task="task", context=CONTEXT, **args):
    return world.service.queries.read(method, {**args, "_read_context": context}, task_id=task)


def parts(count=5, description=None):
    world = semantic_world()
    g = world.graph
    parent = Node(g.reserve_id(), "Root")
    children = [Node(g.reserve_id(), f"Child {i}", description=description) for i in range(count)]
    facts = [g.new_fact("PART_WHOLE", {"part": child.id, "whole": parent.id}) for child in children]
    g.apply(GraphDelta(creates=(parent, *children, *facts)), provenance="source")
    return world, parent, children


def children_query(parent):
    return {
        "relation": "PART_WHOLE",
        "bindings": [{"slot": "whole", "value": parent.id}],
        "select": ["part"],
        "result": "nodes",
    }


def test_totals_item_limits_automatic_continuation_and_revision_scope():
    world, parent, children = parts(605)
    first = read(world, **children_query(parent))
    assert first["total"] == 605 and first["returned"] == 600 and first["has_more"]
    assert "next_cursor" not in first
    following = read(world, next_page=True)
    assert following["total"] == 605 and following["returned"] == 5 and not following["has_more"]
    with pytest.raises(ContractError, match="exhausted"):
        read(world, next_page=True)
    assert {i["node"] for i in first["items"] + following["items"]} == {n.id for n in children}
    with pytest.raises(ContractError, match="No saved selection"):
        read(world, next_page=True, task="other")
    with pytest.raises(ContractError, match="No saved selection"):
        read(world, next_page=True, fields=[])
    assert read(world, **children_query(parent)) == first
    world.graph.apply(
        GraphDelta(creates=(Node(world.graph.reserve_id(), "New"),)), provenance="later"
    )
    with pytest.raises(ContractError, match="Graph changed"):
        read(world, next_page=True)


def test_interleaved_queries_and_walks_keep_independent_pages():
    world, parent, _ = parts(5)
    children = children_query(parent)
    subject = {"subject": parent.id}
    first = read(world, **children, max_items=1)
    other = read(world, **subject, max_items=1)
    walk_args = {
        "start": parent.id,
        "relation": "PART_WHOLE",
        "from_slot": "whole",
        "to_slot": "part",
    }
    walked = read(world, "walk", **walk_args, max_items=1)
    read(world, "walk", **walk_args, max_depth=None, max_items=1)
    second = read(world, **children, next_page=True, max_items=2)
    assert second["returned"] == 2
    assert first["items"][0]["node"] not in {item["node"] for item in second["items"]}
    third = read(world, next_page=True, max_items=2)
    assert not third["has_more"]
    other_second = read(world, **subject, next_page=True, max_items=1)
    assert other_second["items"][0]["source_fact"] != other["items"][0]["source_fact"]
    walk_second = read(world, "walk", **walk_args, next_page=True, max_items=1)
    assert walked["items"][0]["node"] != walk_second["items"][0]["node"]
    all_second = read(world, "walk", **walk_args, max_depth=None, next_page=True, max_items=1)
    assert all_second["items"][0]["node"] == walk_second["items"][0]["node"]
    walk_third = read(world, "walk", next_page=True, max_items=1)
    assert walk_third["items"][0]["node"] != all_second["items"][0]["node"]
    with pytest.raises(ValueError, match="unexpected fields"):
        read(world, cursor="model-must-not-supply-cursors")


def test_real_token_budget_counts_metadata_facts_and_unicode_cards():
    world, parent, _ = parts(15, description="Насос работает исправно. " * 2)
    small = {**CONTEXT, "context_window": 1000}
    first = read(world, context=small, **children_query(parent))
    assert first["total"] == 15 and 0 < first["returned"] < 15
    assert count_tokens(first, small["model"]) <= 600
    more = read(world, next_page=True, context=small)
    assert count_tokens(more, small["model"]) <= 600
    assert not {i["node"] for i in first["items"]} & {i["node"] for i in more["items"]}
    remaining = read(world, context={**small, "remaining_tokens": 450}, **children_query(parent))
    assert count_tokens(remaining, small["model"]) <= 450
    assert remaining["returned"] <= first["returned"]


def test_oversized_item_is_explicit_and_never_loses_qualifications():
    world, parent, _ = parts(1, description="Unabridged important description. " * 500)
    result = read(world, context={**CONTEXT, "context_window": 1000}, **children_query(parent))
    assert result["total"] == 1 and result["returned"] == 0 and result["error"]
    assert result["has_more"] and "next_cursor" not in result
    minimal = read(
        world, context={**CONTEXT, "context_window": 1000}, fields=[], **children_query(parent)
    )
    assert minimal["returned"] == 1
    assert all("description" not in node for node in minimal["nodes"])


def test_partial_bindings_list_membership_scalars_and_conditions():
    world = semantic_world()
    g = world.graph
    sender, recipient, second = [
        Node(g.reserve_id(), name) for name in ("Sender", "Recipient", "Second")
    ]
    schema = RelationType(
        g.reserve_id(),
        "SUPPLY",
        signature=(
            Slot("sender"),
            Slot("recipients", "node", "list1"),
            Slot("quantity", "number"),
            Slot("unit", "string"),
            Slot("note", "string", "optional"),
        ),
    )
    g.apply(GraphDelta(creates=(sender, recipient, second, schema)), provenance="source")
    fact = replace(
        g.new_fact(
            schema.id,
            {
                "sender": sender.id,
                "recipients": [recipient.id, second.id],
                "quantity": 0,
                "unit": "kg",
            },
        ),
        properties={"conditions": {"enabled": False, "tags": []}},
        description="Only while disabled",
    )
    g.apply(GraphDelta(creates=(fact,)), provenance="source")
    result = read(
        world,
        relation=schema.id,
        bindings=[{"slot": "sender", "value": sender.id}],
        where=[
            {"field": "args.recipients", "op": "contains", "value": recipient.id},
            {"field": "conditions.enabled", "op": "==", "value": False},
        ],
        select=["recipients"],
        result="nodes",
    )
    assert result["total"] == 2
    assert {row["node"] for row in result["items"]} == {recipient.id, second.id}
    returned = result["facts"][0]
    assert returned["args"]["quantity"] == 0 and returned["properties"]["conditions"] == {
        "enabled": False,
        "tags": [],
    }
    assert returned["description"] == "Only while disabled"
    assert returned["args"]["sender"] == {"node": sender.id}
    assert len(result["facts"]) == 1
    assert read(world, subject=recipient.id)["total"] == 1
    assert (
        read(
            world,
            relation=schema.id,
            where=[{"field": "conditions.enabled", "op": "==", "value": 0}],
        )["total"]
        == 0
    )
    with pytest.raises(ContractError, match="Unknown slot"):
        read(world, relation=schema.id, bindings=[{"slot": "wrong", "value": 1}])
    with pytest.raises(ContractError, match="Unknown filter"):
        read(world, relation=schema.id, where=[{"field": "quantity", "op": "==", "value": 0}])
    assert (
        read(world, relation=schema.id, where=[{"field": "args.note", "op": "is_null"}])["total"]
        == 1
    )


def test_literal_integer_is_not_a_node_reference_and_counts_do_not_merge_facts():
    world, parent, children = parts(1)
    g = world.graph
    extra = replace(
        g.new_fact("PART_WHOLE", {"part": children[0].id, "whole": parent.id}),
        description="Another source assertion",
    )
    scalar = RelationType(g.reserve_id(), "LITERAL", signature=(Slot("value", "integer"),))
    g.apply(GraphDelta(creates=(extra, scalar)), provenance="extra")
    number = g.new_fact(scalar.id, {"value": parent.id})
    g.apply(GraphDelta(creates=(number,)), provenance="extra")
    assert read(world, subject=parent.id, result="count_matches")["total"] == 2
    assert read(world, **{**children_query(parent), "result": "count_nodes"})["total"] == 1
    assert read(world, relation=scalar.id, result="exists")["exists"] is True


def test_walk_diamond_cycle_depth_and_all_supporting_facts():
    world, root, children = parts(2)
    g = world.graph
    leaf = Node(g.reserve_id(), "Leaf", description="Shared child")
    links = [g.new_fact("PART_WHOLE", {"part": leaf.id, "whole": child.id}) for child in children]
    links.append(g.new_fact("PART_WHOLE", {"part": root.id, "whole": leaf.id}))
    g.apply(GraphDelta(creates=(leaf, *links)), provenance="links")
    args = {"start": root.id, "relation": "PART_WHOLE", "from_slot": "whole", "to_slot": "part"}
    assert read(world, "walk", **args)["total"] == 2
    full = read(world, "walk", **args, max_depth=None)
    assert full["total"] == 3
    last = next(i for i in full["items"] if i["node"] == leaf.id)
    assert last["depth"] == 2 and set(last["source_facts"]) == {f.id for f in links[:2]}
    assert next(n for n in full["nodes"] if n["id"] == leaf.id)["description"] == "Shared child"
    assert read(world, "walk", **args, max_depth=None, result="count_nodes")["total"] == 3


def test_temporal_unknown_counts_and_property_cards():
    world = populated_search_world()
    mother = world.family["daughters"][0]
    result = read(
        world,
        relation="STATE_IDENTITY",
        bindings=[{"slot": "instance", "value": mother.id}],
        select=["facet"],
        result="nodes",
        at="2026-01-01T00:00:00+00:00",
        fields=["description", "properties"],
    )
    assert result["total"] == 1 and result["unknown"] == 1 and result["applicable"] == 0
    node = next(n for n in result["nodes"] if n["id"] == world.family["facets"][0].id)
    assert node["valid_from"] is None and node["valid_until"] is None
    exists = read(
        world,
        relation="STATE_IDENTITY",
        bindings=[{"slot": "instance", "value": mother.id}],
        result="exists",
        at="2026-01-01T00:00:00+00:00",
    )
    assert exists["exists"] is None


async def test_integration_native_reads_keep_projection_and_do_not_record_writes():
    world, parent, _ = parts(3, description="Useful description")
    refs, _ = recorded_experience(world, "Inspect children")

    async def model(payload, call):
        result = await call("query", {**children_query(parent), "max_items": 1})
        assert result["total"] == 3 and result["returned"] == 1
        assert "next_cursor" not in result
        assert any(n.get("description") == "Useful description" for n in result["nodes"])
        next_result = await call("query", {"next_page": True})
        assert next_result["returned"] == 2 and not next_result["has_more"]
        walked = await call(
            "walk",
            {"start": parent.id, "relation": "PART_WHOLE", "from_slot": "whole", "to_slot": "part"},
        )
        assert walked["total"] == 3
        properties = await call("describe", {"subject": parent.id, "focus": "properties"})
        assert "relations" not in properties

    token = current_read_context.set(CONTEXT)
    try:
        result = await run(context(world, model, role="exec"), refs)
    finally:
        current_read_context.reset(token)
    assert result["result"]["writes"] == []


def test_complete_read_and_task_release_discards_result_pages():
    world, parent, _ = parts(5)
    result = read(world, **children_query(parent))
    assert result["total"] == 5 and result["returned"] == 5
    assert not result["has_more"] and "status" not in result
    read(world, **children_query(parent), max_items=1)
    world.service.release("task")
    with pytest.raises(ContractError, match="No saved selection"):
        read(world, next_page=True)


@pytest.mark.parametrize(
    ("method", "result", "expected"),
    [
        ("query", "count_matches", 10006),
        ("query", "count_nodes", 10005),
        ("walk", "count_nodes", 10005),
    ],
)
def test_large_counts_finish_without_result_pages(method, result, expected):
    world, parent, children = parts(10005)
    duplicate = world.graph.new_fact("PART_WHOLE", {"part": children[0].id, "whole": parent.id})
    world.graph.apply(GraphDelta(creates=(duplicate,)), provenance="duplicate")
    arguments = children_query(parent)
    if method == "walk":
        arguments = {
            "start": parent.id,
            "relation": "PART_WHOLE",
            "from_slot": "whole",
            "to_slot": "part",
        }
    response = read(world, method, **{**arguments, "result": result}, max_items=1)
    assert response["total"] == expected
    assert response["returned"] == 0 and response["has_more"] is False
    assert not {"status", "total_at_least", "items", "nodes", "facts"} & response.keys()
    with pytest.raises(ContractError, match="exhausted"):
        read(world, method, next_page=True)


@pytest.mark.parametrize("method", ["query", "walk"])
def test_exists_stops_reading_storage_at_first_applicable_fact(monkeypatch, method):
    world, parent, _ = parts(5)
    relation = world.graph.find("PART_WHOLE")
    first = world.graph.facts(relation.id)[0]
    visited = []

    class TrackedNodes(dict):
        def values(self):
            for node in super().values():
                visited.append(node.id)
                yield node

    monkeypatch.setattr(world.graph, "_nodes", TrackedNodes(world.graph._nodes))
    arguments = {"subject": parent.id}
    if method == "walk":
        arguments = {
            "start": parent.id,
            "relation": relation.id,
            "from_slot": "whole",
            "to_slot": "part",
            "max_depth": None,
        }
    response = read(world, method, **arguments, result="exists")
    assert response == {"exists": True, "returned": 0, "has_more": False}
    assert visited[-1] == first.id


@pytest.mark.parametrize("method", ["query", "walk"])
def test_exists_preserves_unknown_and_continues_to_a_later_definite_match(method):
    world = populated_search_world()
    instance = world.family["daughters"][0]
    arguments = {
        "relation": "STATE_IDENTITY",
        "bindings": [{"slot": "instance", "value": instance.id}],
    }
    if method == "walk":
        arguments = {
            "start": instance.id,
            "relation": "STATE_IDENTITY",
            "from_slot": "instance",
            "to_slot": "facet",
            "max_depth": None,
        }
    response = read(world, method, **arguments, result="exists", at="2026-01-01T00:00:00Z")
    assert response == {"exists": None, "returned": 0, "has_more": False}
    state = Facet(
        world.graph.reserve_id(),
        "Known state",
        valid_from=timestamp("2025-01-01T00:00:00Z"),
        valid_until=timestamp("2027-01-01T00:00:00Z"),
    )
    fact = world.graph.new_fact("STATE_IDENTITY", {"instance": instance.id, "facet": state.id})
    world.graph.apply(GraphDelta(creates=(state, fact)), provenance="known interval")
    response = read(world, method, **arguments, result="exists", at="2026-01-01T00:00:00Z")
    assert response == {"exists": True, "returned": 0, "has_more": False}


@pytest.mark.parametrize("method", ["query", "walk"])
def test_exists_returns_false_after_exhausting_nonmatches_and_self_links(method):
    world, _, children = parts(5)
    loop = world.graph.new_fact("PART_WHOLE", {"part": children[0].id, "whole": children[0].id})
    world.graph.apply(GraphDelta(creates=(loop,)), provenance="self link")
    arguments = {
        "relation": "PART_WHOLE",
        "bindings": [{"slot": "whole", "value": children[0].id}],
        "where": [{"field": "args.part", "op": "!=", "value": children[0].id}],
    }
    if method == "walk":
        arguments = {
            "start": children[0].id,
            "relation": "PART_WHOLE",
            "from_slot": "whole",
            "to_slot": "part",
            "max_depth": None,
        }
    response = read(world, method, **arguments, result="exists")
    assert response == {"exists": False, "returned": 0, "has_more": False}


def test_read_config_and_missing_model_budget(tmp_path):
    (tmp_path / "evertree.toml").write_text(
        "[semantics.read]\ncontext_fraction = 0.6\nmax_items = 600\n"
    )
    assert SemanticConfig.load(tmp_path).read == ReadConfig()
    for invalid in (0, -1, 1.1, float("nan"), True):
        with pytest.raises(ValueError):
            ReadConfig(context_fraction=invalid)
    world, parent, _ = parts()
    with pytest.raises(ContractError, match="context window"):
        read(world, context={}, **children_query(parent))
