"""Checked immediate writes and autonomous integration with real semantic stores."""

import json

import pytest

from evertree.core.memory.store import TraceStore
from evertree.core.values import ContractError
from evertree.processes.semantic_processing.knowledge_integration._exec import run
from tests.support.semantics import (
    EmptyIndex,
    context,
    recorded_experience,
    semantic_world,
    write_action,
)


def note(ref, name="Insight"):
    return {"action": "save_note", "name": name, "source": ref, "sources": []}


def test_writes_require_admitted_exec_and_reject_injected_context():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "source")
    for bad in ({}, {"knowledge_integration_authorized": False}, {"program": {"role": "model"}}):
        with pytest.raises(PermissionError):
            write_action(world, refs, {**metadata, **bad} if bad else {}, note(refs[0]))
    with pytest.raises(TypeError):
        world.service.sources(refs, context={"task": "override"}, metadata=metadata)
    with pytest.raises(PermissionError, match="Public graph.apply"):
        world.operations.execute("graph.apply", {}, metadata=metadata)


def test_sources_need_no_decisions_or_obligations_and_only_written_sources_are_retained():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "Important", "Routine")
    source = world.service.sources(refs, metadata=metadata)
    assert set(source) <= {"experience", "context", "focus"}
    assert "preservation_intents" not in source["context"]
    result = write_action(world, refs, metadata, note(refs[0]))
    assert "error" not in result, result
    mutation = world.memory.get_event(world.graph._history[-1].provenance["event_ref"])
    assert [ref.event_ref for ref in mutation.dependencies] == [refs[0]["event_ref"]]
    assert refs[1]["event_ref"] not in world.memory.retention_closure()
    assert "decisions" not in mutation.arguments


def test_each_write_requires_sources_in_supplied_experience():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "Allowed", "Outside the packet")
    before = (world.graph.snapshot(), world.memory.snapshot())
    invalid = write_action(world, refs[:1], metadata, note(refs[1]))
    assert invalid["error"]
    assert (world.graph.snapshot(), world.memory.snapshot()) == before
    missing = {"action": "create_concept", "name": "Ungrounded", "description": None, "sources": []}
    assert write_action(world, refs, metadata, missing)["error"]
    assert world.graph.snapshot() == before[0]


def test_write_replay_survives_restart_and_expanded_experience_without_duplicate_effects():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "Important", "Correction")
    action = note(refs[0])
    result = write_action(world, refs[:1], metadata, action)
    assert "error" not in result, result
    before = world.graph.snapshot()
    restored = TraceStore.from_snapshot(world.memory.snapshot())
    world.service.memory = restored
    world.operations.memory = restored
    before_trace = restored.snapshot()
    replay = write_action(world, refs, {**metadata, "run_id": "after-restart"}, action)
    assert replay == result and world.graph.snapshot() == before
    assert restored.snapshot() == before_trace
    assert len(world.graph.nodes(kind="note")) == 1
    changed_action = {**action, "source": refs[1]}
    assert write_action(world, refs, metadata, changed_action)["error"]
    assert write_action(world, refs[1:], metadata, note(refs[1]))["error"]
    assert world.graph.snapshot() == before
    next_write = write_action(world, refs, metadata, note(refs[1], "Correction"), key="next")
    assert next_write["object"] != result["object"]


async def test_search_pagination_refreshes_after_a_successful_graph_write():
    from evertree.core.graph.types import GraphDelta, Node

    searches = []

    class Index(EmptyIndex):
        async def lexical(self, nodes, query, kind):
            searches.append(query)
            return [node["id"] for node in nodes if node["name"].startswith("Candidate ")]

    world = semantic_world(index=Index())
    nodes = [Node(world.graph.reserve_id(), f"Candidate {index}") for index in range(25)]
    world.graph.apply(GraphDelta(creates=tuple(nodes)), provenance="corpus")
    refs, _ = recorded_experience(world, "An explanation worth retaining")

    async def model(payload, call):
        first = await call("search", {"query": "ambiguous", "next_page": False})
        assert len(first["items"]) == 20 and first["has_more"]
        saved = await call("save_note", {"name": "Explanation", "source": refs[0], "sources": []})
        assert "error" not in saved, saved
        refreshed = await call("search", {"query": "ambiguous", "next_page": True})
        assert refreshed["items"] == first["items"] and refreshed["has_more"]
        remaining = await call("search", {"query": "ambiguous", "next_page": True})
        assert len(remaining["items"]) == 5 and not remaining["has_more"]
        assert {item["id"] for item in refreshed["items"] + remaining["items"]} == {
            node.id for node in nodes
        }

    result = await run(context(world, model, role="exec"), refs)
    assert len(result["result"]["writes"]) == 1
    assert searches == ["ambiguous", "ambiguous"]


def test_identity_creation_requires_complete_fresh_search():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "Object exists")
    action = {"action": "create_concept", "name": "Object", "description": None, "sources": refs}
    assert (
        "complete current search"
        in write_action(world, refs, metadata, action, searched=False)["error"]
    )
    world.service.results(
        "Object", None, [], [{"channel": "vector", "error": "offline"}], 20, "task"
    )
    assert (
        "complete current search"
        in write_action(world, refs, metadata, action, searched=False)["error"]
    )
    world.service.results("Object", None, [], [], 20, "task")
    assert "error" not in write_action(world, refs, metadata, note(refs[0]), key="intervening")
    assert (
        "complete current search"
        in write_action(world, refs, metadata, action, searched=False)["error"]
    )
    result = write_action(world, refs, metadata, action)
    assert result["object"] > 0


@pytest.mark.parametrize(
    "reference",
    [
        {"event_ref": True},
        {"event_ref": 1, "output_path": [False]},
        {"event_ref": 1, "output_path": "text"},
        {"event_ref": 1, "output_path": [-1]},
    ],
)
def test_sources_reject_ambiguous_reference_types(reference):
    world = semantic_world()
    _, metadata = recorded_experience(world, "source")
    with pytest.raises(ContractError, match="Invalid retained"):
        world.service.sources([reference], metadata=metadata)


async def test_fabricated_search_completion_cannot_authorize_creation():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "candidate")
    result = await world.service.execute(
        "semantic.results",
        {
            "query": "Candidate",
            "kind": None,
            "revision": world.graph.revision,
            "items": [],
            "errors": [],
            "limit": 20,
        },
        metadata,
    )
    assert result["status"] == "incomplete"
    action = {"action": "create_concept", "name": "Candidate", "description": None, "sources": refs}
    assert write_action(world, refs, metadata, action, searched=False)["error"]


async def test_program_searches_before_creation_and_refreshes_after_intervening_write():
    searches = []

    class Index(EmptyIndex):
        async def lexical(self, nodes, query, kind):
            searches.append(query)
            return []

    world = semantic_world(index=Index())
    refs, _ = recorded_experience(world, "A useful term")

    async def model(payload, call):
        state = json.loads(payload["prompt"])
        assert state["material"]["context"]["task"] == {"objective": "Learn terminology"}
        await call("search", {"query": "Useful term", "next_page": False})
        saved = await call("save_note", {"name": "Explanation", "source": refs[0], "sources": []})
        assert world.graph.get(saved["object"]).description == "A useful term"
        created = await call(
            "create_concept", {"name": "Useful term", "description": None, "sources": refs}
        )
        assert created["object"] > 0

    result = await run(
        context(
            world,
            model,
            role="exec",
            integration_context={"task": {"objective": "Learn terminology"}},
        ),
        refs,
    )
    assert result["feedback"] is None
    assert len(result["result"]["writes"]) == 2
    assert searches == ["Useful term", "Useful term"]


async def test_model_projection_preserves_meaning_without_audit_or_obligation_metadata():
    world = semantic_world()
    source = {"origin": "factory", "revision": "pump-v2", "pressure": 5}
    refs, metadata = recorded_experience(world, source, run_mode="replay")
    analysis_ref = world.operations.execute(
        "memory.note",
        {"text": "Important: pressure may vary with load; untested.", "source_refs": refs},
        metadata=metadata,
    )
    refs.append(analysis_ref)
    trusted = {
        "task": {
            "id": "task",
            "specification": {
                "objective": "Study pressure",
                "constraints": ["Keep hypotheses qualified"],
                "revision": 8,
                "source_ids": ["message-id"],
            },
        },
        "values": [
            {
                "id": 100,
                "name": "Accuracy",
                "description": "Retain uncertainty",
                "provenance": {"revision": "value-revision"},
            }
        ],
        "self": [
            {"id": 101, "name": "Self", "kind": "concept", "properties": {}},
            {
                "id": 102,
                "name": "Sensor limitation",
                "kind": "note",
                "description": "Cannot observe load",
                "provenance": "bootstrap",
            },
        ],
    }

    async def model(payload, call):
        material = json.loads(payload["prompt"])["material"]
        assert "origin" not in material["experience"][0]
        assert material["experience"][0]["content"] == source
        assert material["experience"][0]["experience_mode"] == "replay"
        analysis = material["experience"][1]
        assert analysis["source_kind"] == "analytical_note"
        assert analysis["content"]["source_refs"] == refs[:1]
        assert set(analysis["content"]) <= {"text", "kind", "source_refs"}
        context_ = material["context"]
        assert context_["task"] == {
            "objective": "Study pressure",
            "constraints": ["Keep hypotheses qualified"],
        }
        assert context_["values"] == [{"name": "Accuracy", "description": "Retain uncertainty"}]
        assert [node["name"] for node in context_["self"]] == ["Sensor limitation"]
        assert "provenance" not in context_["self"][0]
        assert "preservation_intents" not in context_
        await call("save_note", {"name": "Hypothesis", "source": analysis_ref, "sources": []})

    result = await run(context(world, model, role="exec", integration_context=trusted), refs)
    assert len(result["result"]["writes"]) == 1
    assert not world.operations.beliefs.snapshot()["targets"]
    original = world.service.sources(refs, metadata={**metadata, "integration_context": trusted})
    assert original["experience"][0]["origin"]["revision"] == "revision"
    assert original["context"]["task"]["specification"]["revision"] == 8


@pytest.mark.parametrize("path", [["text"], ["source_refs"], ["source_refs", 0]])
async def test_model_projection_keeps_addressed_note_fragments_verbatim(path):
    world = semantic_world()
    refs, metadata = recorded_experience(world, "Original observation")
    analysis_ref = world.operations.execute(
        "memory.note", {"text": "Partial analysis", "source_refs": refs}, metadata=metadata
    )
    reference = {**analysis_ref, "output_path": path}
    source = world.service.sources([reference], metadata=metadata)["experience"][0]["content"]

    async def model(payload, call):
        item = json.loads(payload["prompt"])["material"]["experience"][0]
        assert item["reference"] == reference
        assert item["content"] == source

    assert (await run(context(world, model, role="exec"), [reference])) == {
        "result": {"writes": []},
        "feedback": None,
    }


async def test_native_tools_create_undated_state_and_relation_with_permanent_ids():
    world = semantic_world()
    refs, _ = recorded_experience(
        world, "Pump P1 was noisy after startup; date unknown.", "Routine log"
    )

    async def model(payload, call):
        common = {"description": None, "sources": refs[:1]}
        prototype = await call("create_prototype", {"name": "Pump", "parent": None, **common})
        instance = await call(
            "create_instance", {"name": "P1", "prototype": prototype["object"], **common}
        )
        state = await call(
            "create_facet",
            {
                "name": "P1 after startup",
                "instance": instance["object"],
                "valid_from": None,
                "valid_until": None,
                **common,
            },
        )
        relation = await call(
            "define_relation",
            {
                "name": "HAS_NOISE",
                "roles": [
                    {"label": "state", "value_type": "facet", "arity": "one"},
                    {"label": "sound", "value_type": "string", "arity": "one"},
                ],
                **common,
            },
        )
        result = await call(
            "relate",
            {
                "relation": relation["object"],
                "arguments": [
                    {"role": "state", "value": state["object"]},
                    {"role": "sound", "value": "noisy"},
                ],
                "conditions": [],
                **common,
            },
        )
        assert "error" not in result, result

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert len(result["writes"]) == 5
    assert sum(len(write["created"]) for write in result["writes"]) == 7
    instance = world.graph.find("P1")
    (facet,) = world.graph.get_facets(instance)
    assert facet.valid_from is None and facet.valid_until is None
    assert len(world.graph.facts("HAS_NOISE")) == 1
    assert refs[1]["event_ref"] not in world.memory.retention_closure()


async def test_invalid_later_tool_preserves_previous_write_and_allows_repair():
    world = semantic_world()
    refs, _ = recorded_experience(world, "Useful explanation")

    async def model(payload, call):
        saved = await call("save_note", {"name": "Explanation", "source": refs[0], "sources": []})
        invalid = await call(
            "update", {"object": saved["object"], "changes": {"id": -1}, "sources": refs}
        )
        assert invalid["error"]
        assert "prepared" not in invalid
        assert world.graph.get(saved["object"]).description == "Useful explanation"
        corrected = await call(
            "update",
            {
                "object": saved["object"],
                "changes": {"description": "Qualified explanation"},
                "sources": refs,
            },
        )
        assert corrected["object"] == saved["object"]

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert len(result["writes"]) == 2
    assert len(world.graph.nodes(kind="note")) == 1


async def test_model_failure_does_not_undo_completed_writes():
    world = semantic_world()
    refs, _ = recorded_experience(world, "Useful explanation")

    async def model(payload, call):
        await call("save_note", {"name": "Explanation", "source": refs[0], "sources": []})
        raise RuntimeError("Provider disconnected")

    with pytest.raises(RuntimeError, match="Provider disconnected"):
        await run(context(world, model, role="exec"), refs)
    assert world.graph.find("Explanation").description == "Useful explanation"


async def test_search_pages_and_relation_schemas_need_no_status_calls():
    from evertree.core.graph.types import GraphDelta, Node

    class Index(EmptyIndex):
        async def lexical(self, nodes, query, kind):
            return [node["id"] for node in nodes if node["name"].startswith("Candidate ")]

    world = semantic_world(index=Index())
    nodes = [Node(world.graph.reserve_id(), f"Candidate {i}") for i in range(25)]
    world.graph.apply(GraphDelta(creates=tuple(nodes)), provenance="corpus")
    refs, _ = recorded_experience(world, "Ambiguous object mention")

    async def model(payload, call):
        first = await call("search", {"query": "ambiguous", "next_page": False})
        assert first["has_more"] and "cursor" not in first
        second = await call("search", {"query": "ambiguous", "next_page": True})
        assert len(second["items"]) == 5 and not second["has_more"]
        schema = (await call("describe", {"subject": "IDENTITY_TYPE"}))["schema"]
        assert schema["signature"] and "views" not in schema

    assert (await run(context(world, model, role="exec"), refs))["result"] == {"writes": []}


async def test_normal_model_completion_needs_no_finish_call():
    world = semantic_world()
    refs, _ = recorded_experience(world, "Useful explanation")

    async def model(payload, call):
        await call("save_note", {"name": "Explanation", "source": refs[0], "sources": []})
        return {"text": "Integration complete"}

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert len(result["writes"]) == 1
    assert world.graph.find("Explanation").description == "Useful explanation"
