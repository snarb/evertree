"""Checked immediate writes and autonomous integration with real semantic stores."""

import json

import pytest

from evertree.core.cognition.steps import trace_reference
from evertree.core.graph.store import GraphStore
from evertree.core.memory.store import TraceStore
from evertree.core.values import ContractError
from evertree.processes.self_semantic_processing.self_knowledge_integration._exec import run
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
    for action in ("create_concept", "create_claim"):
        fields = {"action": action, "name": "Ungrounded", "description": "A possible cause"}
        assert write_action(world, refs, metadata, {**fields, "sources": []})["error"]
        assert write_action(world, refs[:1], metadata, {**fields, "sources": refs[1:]})["error"]
        assert world.graph.snapshot() == before[0]


@pytest.mark.parametrize("kind", ["note", "claim"])
def test_write_replay_survives_restart_and_expanded_experience_without_duplicate_effects(kind):
    world = semantic_world()
    refs, metadata = recorded_experience(world, "Important", "Correction")
    action = (
        note(refs[0])
        if kind == "note"
        else {
            "action": "create_claim",
            "name": "Possible cause",
            "description": "Reconnect may cause failure under load.",
            "sources": refs[:1],
        }
    )
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
    assert len(world.graph.nodes(kind=kind)) == 1
    changed_action = {**action, "name": "Different assertion"}
    assert write_action(world, refs, metadata, changed_action)["error"]
    assert write_action(world, refs[1:], metadata, note(refs[1]))["error"]
    assert world.graph.snapshot() == before
    next_write = write_action(world, refs, metadata, note(refs[1], "Correction"), key="next")
    assert next_write["object"] != result["object"]


async def test_search_is_bounded_and_refreshes_after_a_successful_graph_write():
    from evertree.core.graph.types import GraphDelta, Node

    searches = []

    class Index(EmptyIndex):
        async def lexical(self, nodes, query, kind):
            searches.extend(query)
            return [
                {"ids": [node["id"] for node in nodes if node["name"].startswith("Candidate ")]}
                for _ in query
            ]

    world = semantic_world(index=Index())
    nodes = [Node(world.graph.reserve_id(), f"Candidate {index}") for index in range(25)]
    world.graph.apply(GraphDelta(creates=tuple(nodes)), provenance="corpus")
    refs, _ = recorded_experience(world, "An explanation worth retaining")

    async def model(payload, call):
        first = await call("search", {"queries": ["ambiguous"]})
        assert len(first["items"]) == 10 and "has_more" not in first
        saved = await call("save_note", {"name": "Explanation", "source": refs[0], "sources": []})
        assert "error" not in saved, saved
        refreshed = await call("search", {"queries": ["ambiguous"]})
        assert refreshed["items"] == first["items"]
        assert "cursor" not in refreshed and "has_more" not in refreshed

    result = await run(context(world, model, role="exec"), refs)
    assert len(result["result"]["writes"]) == 1
    assert searches == ["ambiguous", "ambiguous"]


@pytest.mark.parametrize("action_name", ["create_concept", "create_claim"])
def test_identity_creation_keeps_complete_search_after_own_write(action_name):
    world = semantic_world()
    refs, metadata = recorded_experience(world, "Object exists")
    action = {
        "action": action_name,
        "name": "Object",
        "description": "The object may be a new kind of pump.",
        "sources": refs,
    }
    assert "complete search" in write_action(world, refs, metadata, action, searched=False)["error"]
    world.service.results(
        "Object", None, [], [{"channel": "vector", "error": "offline"}], 10, "task", scope="packet"
    )
    assert "complete search" in write_action(world, refs, metadata, action, searched=False)["error"]
    world.service.results("Object", None, [], [], 10, "task", scope="packet")
    assert "error" not in write_action(world, refs, metadata, note(refs[0]), key="intervening")
    result = write_action(world, refs, metadata, action, searched=False)
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
            "queries": ["Candidate"],
            "kinds": None,
            "rankings": [{"items": [], "errors": []}],
            "limit": 10,
        },
        metadata,
    )
    assert result["status"] == "incomplete"
    action = {"action": "create_concept", "name": "Candidate", "description": None, "sources": refs}
    assert write_action(world, refs, metadata, action, searched=False)["error"]


@pytest.mark.parametrize("action_name", ["create_concept", "create_claim"])
async def test_program_reuses_search_after_own_write(action_name):
    searches = []

    class Index(EmptyIndex):
        async def lexical(self, nodes, query, kind):
            searches.extend(query)
            return [{"ids": []} for _ in query]

    world = semantic_world(index=Index())
    refs, _ = recorded_experience(world, "A useful term")

    async def model(payload, call):
        state = json.loads(payload["prompt"])
        assert state["material"]["context"]["task"] == {"objective": "Learn terminology"}
        await call("search", {"queries": ["Useful term"]})
        saved = await call("save_note", {"name": "Explanation", "source": refs[0], "sources": []})
        assert world.graph.get(saved["object"]).description == "A useful term"
        created = await call(
            action_name,
            {"name": "Useful term", "description": "A useful conditional meaning", "sources": refs},
        )
        assert created["object"] > 0
        assert world.graph.get(created["object"]).kind == action_name.removeprefix("create_")

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
    assert searches == ["Useful term"]


async def test_model_projection_preserves_meaning_without_audit_or_obligation_metadata():
    world = semantic_world()
    source = {
        "origin": "factory",
        "revision": "pump-v2",
        "pressure": 5,
        "self": "The sensor reports its own pressure.",
        "values": [4, 5],
    }
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
                "success_criteria": ["Retain the sensor readings"],
                "constraints": ["Keep hypotheses qualified"],
                "preferences": ["Prefer compact representations"],
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
        assert material["focus"] == "Pressure under load"
        assert "origin" not in material["experience"][0]
        assert material["experience"][0]["content"] == source
        assert material["experience"][0]["experience_mode"] == "replay"
        analysis = material["experience"][1]
        assert analysis["source_kind"] == "analytical_note"
        assert analysis["content"]["source_refs"] == refs[:1]
        assert set(analysis["content"]) <= {"text", "kind", "source_refs"}
        context_ = material["context"]
        assert context_ == {
            "task": {
                "objective": "Study pressure",
                "success_criteria": ["Retain the sensor readings"],
                "constraints": ["Keep hypotheses qualified"],
                "preferences": ["Prefer compact representations"],
            }
        }
        await call("save_note", {"name": "Hypothesis", "source": analysis_ref, "sources": []})

    result = await run(
        context(world, model, role="exec", integration_context=trusted),
        refs,
        focus="Pressure under load",
    )
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
        assert trace_reference(item["reference"]) == world.memory.producer_of(
            trace_reference(reference)
        )
        assert item["content"] == source

    result = await run(context(world, model, role="exec"), [reference])
    assert result["result"]["writes"] == []
    assert result["result"]["processing"]["status"] == "processed"
    assert result["feedback"] is None


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
                    {
                        "label": "state",
                        "value_type": "facet",
                        "arity": "one",
                        "description": "State in which the sound was reported.",
                    },
                    {
                        "label": "sound",
                        "value_type": "string",
                        "arity": "one",
                        "description": "Reported sound of that state.",
                    },
                ],
                **common,
            },
        )
        assert "error" not in relation, relation
        described = await call("describe", {"subject": relation["object"]})
        assert described["schema"]["signature"][0]["description"] == (
            "State in which the sound was reported."
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
    restored = GraphStore.from_snapshot(world.graph.snapshot())
    assert restored.find("HAS_NOISE").signature[1].description == "Reported sound of that state."
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

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert len(result["writes"]) == 1
    assert result["processing"]["status"] == "incomplete"
    assert "Provider disconnected" in result["processing"]["failed"][0]["error"]
    assert world.graph.find("Explanation").description == "Useful explanation"


async def test_search_ceiling_and_relation_schemas_need_no_status_calls():
    from evertree.core.graph.types import GraphDelta, Node

    class Index(EmptyIndex):
        async def lexical(self, nodes, query, kind):
            return [
                {"ids": [node["id"] for node in nodes if node["name"].startswith("Candidate ")]}
                for _ in query
            ]

    world = semantic_world(index=Index())
    nodes = [Node(world.graph.reserve_id(), f"Candidate {i}") for i in range(25)]
    world.graph.apply(GraphDelta(creates=tuple(nodes)), provenance="corpus")
    refs, _ = recorded_experience(world, "Ambiguous object mention")

    async def model(payload, call):
        first = await call("search", {"queries": ["ambiguous"]})
        assert len(first["items"]) == 10
        assert "has_more" not in first and "cursor" not in first
        rejected = await call("search", {"queries": ["ambiguous"], "next_page": True})
        assert "error" in rejected
        schema = (await call("describe", {"subject": "IDENTITY_TYPE"}))["schema"]
        assert schema["signature"] and "views" not in schema

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert result["writes"] == [] and result["processing"]["status"] == "processed"


async def test_tool_projection_preserves_empty_reads_and_nested_review_results():
    from evertree.core.graph.types import GraphDelta, Prototype

    world = semantic_world()
    root = Prototype(world.graph.reserve_id(), "Equipment")
    world.graph.apply(GraphDelta(creates=(root,)), provenance="test")
    refs, _ = recorded_experience(world, "Equipment is useful")

    async def model(payload, call):
        # Creation's automatic search must expose the same candidates as direct search.
        rejected = await call(
            "create_prototype",
            {"name": root.name, "description": None, "parent": None, "sources": refs},
        )
        assert rejected["error"]
        nested = rejected["reads"][0]
        assert nested["tool"] == "search"
        found = await call("search", {"queries": [root.name]})
        assert nested["result"] == found
        assert found == {
            "status": "complete",
            "items": [{"id": root.id, "name": root.name, "kind": "prototype"}],
            "queries": [
                {
                    "query": root.name,
                    "status": "complete",
                    "exact": True,
                    "total": 1,
                    "ids": [root.id],
                }
            ],
        }

        described = await call("describe", {"subject": root.id})
        assert described["parent"] is None
        assert described["children"] == described["properties"] == described["relations"] == []
        focused = await call("describe", {"subject": root.id, "focus": "properties"})
        assert focused["properties"] == []
        assert "relations" not in focused and "parent" not in focused

        missing = await call("describe", {"subject": "Absent object"})
        assert missing["error"]
        assert missing["reads"][0]["result"] == {"status": "not_found", "candidates": []}

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert result["writes"] == [] and result["processing"]["status"] == "processed"


@pytest.mark.parametrize("text", ["Integration complete", "Extraction is incomplete", ""])
async def test_final_text_without_finish_keeps_writes_but_records_gap(text):
    world = semantic_world()
    refs, _ = recorded_experience(world, "Useful explanation")

    async def model(payload, call):
        await call("save_note", {"name": "Explanation", "source": refs[0], "sources": []})
        return {"text": text}

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert len(result["writes"]) == 1
    assert world.graph.find("Explanation").description == "Useful explanation"
    assert result["processing"]["status"] == "incomplete"
    assert result["processing"]["completed"] == []
    assert "without finish_section" in result["processing"]["failed"][0]["error"]


def test_character_citations_cannot_ground_graph_writes():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "UPS-1 returned to mains at 10:07 UTC")
    action = {
        "action": "create_claim",
        "name": "Power restored",
        "description": "UPS-1 returned to mains at 10:07 UTC",
        "sources": [{**refs[0], "output_path": [0]}],
    }
    world.service.results("Power restored", None, [], [], 10, "task", scope="packet")
    before = world.graph.snapshot(), world.memory.snapshot()
    result = write_action(world, refs, metadata, action)
    assert "not text characters" in result["error"]
    assert (world.graph.snapshot(), world.memory.snapshot()) == before
    corrected = write_action(world, refs, metadata, {**action, "sources": refs})
    assert "error" not in corrected
    world.memory.validate()


async def test_new_names_search_without_reviewing_own_known_updates():
    from evertree.core.graph.types import GraphDelta, Node

    searches = []

    class Index(EmptyIndex):
        async def vector(self, nodes, query, kind):
            searches.extend(query)
            return [{"ids": [existing.id]} for _ in query]

    world = semantic_world(index=Index())
    existing = Node(world.graph.reserve_id(), "Existing", description="An unrelated meaning")
    world.graph.apply(GraphDelta(creates=(existing,)), provenance="test")
    refs, _ = recorded_experience(world, "Three useful new meanings")

    async def model(payload, call):
        fields = {"description": "A new meaning", "sources": refs}
        first = await call("create_concept", {**fields, "name": "First"})
        assert "Review search candidates" in first["error"]
        # A different proposed name still refreshes search, but the same card was just shown.
        saved = await call("create_concept", {**fields, "name": "Second"})
        assert "object" in saved
        updated = await call(
            "update",
            {"object": existing.id, "changes": {"description": "Changed meaning"}, "sources": refs},
        )
        assert "error" not in updated
        assert "object" in await call("create_concept", {**fields, "name": "Third"})

    await run(context(world, model, role="exec"), refs)
    assert searches == ["First", "Second", "Third"]
    assert world.graph.find("First") is None
    assert world.graph.find("Second") is not None
    assert world.graph.find("Third") is not None


async def test_explicit_search_exposes_candidates_before_new_name_preflight():
    from evertree.core.graph.types import GraphDelta, Node

    class Index(EmptyIndex):
        async def vector(self, *args):
            return [{"ids": [existing.id]} for _ in args[1]]

    world = semantic_world(index=Index())
    existing = Node(world.graph.reserve_id(), "Existing", description="Other meaning")
    world.graph.apply(GraphDelta(creates=(existing,)), provenance="test")
    refs, _ = recorded_experience(world, "New useful concept")

    async def model(payload, call):
        await call("search", {"queries": ["Related meaning"]})
        result = await call(
            "create_concept", {"name": "New", "description": "Useful", "sources": refs}
        )
        assert "object" in result

    await run(context(world, model, role="exec"), refs)


def test_search_review_is_owned_by_one_model_invocation():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "A pump")
    action = {"action": "create_concept", "name": "Pump", "description": None, "sources": refs}
    world.service.results("Pump", None, [], [], 10, "task", scope="parent")
    world.service.results(
        "Pump", None, [], [{"channel": "vector", "error": "offline"}], 10, "task", scope="child"
    )
    for scope in ("child", "next-turn"):
        result = write_action(
            world, refs, {**metadata, "semantic_scope": scope}, action, key=scope, searched=False
        )
        assert "complete search" in result["error"]
    result = write_action(
        world, refs, {**metadata, "semantic_scope": "parent"}, action, searched=False
    )
    assert result["object"] > 0


async def test_completed_channels_cannot_be_reused_for_a_second_search():
    world = semantic_world()
    _, metadata = recorded_experience(world, "A pump")
    for method in ("semantic.bm25", "semantic.vector"):
        await world.service.execute(method, {"queries": ["pump"], "kinds": None}, metadata)
    payload = {
        "queries": ["pump"],
        "kinds": None,
        "rankings": [{"items": [], "errors": []}],
        "limit": 10,
    }
    assert (await world.service.execute("semantic.results", payload, metadata))[
        "status"
    ] == "complete"
    assert (await world.service.execute("semantic.results", payload, metadata))[
        "status"
    ] == "incomplete"


def test_program_completion_cannot_authorize_creation():
    from evertree.core.graph.types import GraphDelta, Node

    world = semantic_world()
    refs, metadata = recorded_experience(world, "A pump")
    program = Node(
        world.graph.reserve_id(),
        "SelfSemanticSearch.model",
        kind="program",
        properties={"slug": "semantic_search"},
    )
    world.graph.apply(GraphDelta(creates=(program,)), provenance="registered")
    run = world.memory.start_run(program.id, "revision", {"query": "Pump"})
    world.memory.record(
        run,
        "run_finished",
        output={
            "type": "run_finished",
            "task_id": "task",
            "semantic_scope": "packet",
            "result": {"result": {"status": "complete", "items": []}},
        },
    )
    world.memory.finish_run(run)
    world.service.release("task")
    action = {"action": "create_concept", "name": "Pump", "description": None, "sources": refs}
    assert "error" in write_action(
        world, refs, {**metadata, "semantic_scope": "other"}, action, key="other", searched=False
    )
    assert "error" in write_action(world, refs, metadata, action, searched=False)


@pytest.mark.parametrize("complete", [True, False])
def test_core_search_confirmation_survives_restore(complete):
    world = semantic_world()
    refs, metadata = recorded_experience(world, "A pump")
    world.service.results("Pump", None, [], [], 10, "task", scope="packet")
    if not complete:
        world.service.results("Pump", None, [], [{"channel": "vector"}], 10, "task", scope="packet")
    world.memory = TraceStore.from_snapshot(world.memory.snapshot())
    world.service.memory = world.memory
    world.operations.memory = world.memory
    world.service.release("task")
    action = {"action": "create_concept", "name": "Pump", "description": None, "sources": refs}
    assert "error" in write_action(
        world, refs, {**metadata, "semantic_scope": "other"}, action, key="other", searched=False
    )
    result = write_action(world, refs, metadata, action, searched=False)
    assert ("object" in result) is complete


@pytest.mark.parametrize("focus", [None, "Preserve the failure conditions"])
async def test_default_integration_prioritizes_connected_facts_and_explicit_focus_is_preserved(
    focus,
):
    from evertree.processes.self_semantic_processing.self_knowledge_integration._exec import (
        DEFAULT_FOCUS,
    )

    world = semantic_world()
    refs, _ = recorded_experience(world, "A transfers coolant to B at 12 l/min.")

    async def model(payload, call):
        material = json.loads(payload["prompt"])["material"]
        assert material["focus"] == (DEFAULT_FOCUS if focus is None else focus)

    await run(context(world, model, role="exec"), refs, focus=focus)


@pytest.mark.parametrize("automatic_fragment", [False, True])
async def test_tool_limit_refines_sections_with_fresh_review_and_distinct_write_keys(
    automatic_fragment,
):
    from evertree.core.runtime.llm import ToolCallLimitError

    world = semantic_world()
    text = "The pump supplies water.\n\nThe valve controls the pump."
    refs, _ = recorded_experience(world, text)
    if automatic_fragment:
        producer = world.memory.start_run("ExperienceFragments", "revision", {"task_id": "task"})
        event = world.memory.record(
            producer,
            "experience_fragment",
            output={
                "source_ref": refs[0],
                "encoding": "structured",
                "location": {"path": [], "start": 0, "end": len(text)},
                "context": [{"preceding_text": "Pump system"}],
                "text": text,
            },
        )
        world.memory.finish_run(producer)
        refs = [{"event_ref": event.id, "output_path": []}]
    parent = {**refs[0], "output_path": ["text"]} if automatic_fragment else refs[0]
    invocations = 0

    async def model(payload, call):
        nonlocal invocations
        invocations += 1
        source = json.loads(payload["prompt"])["material"]["experience"][0]
        if invocations == 1:
            result = await call(
                "create_concept",
                {"name": "Water supply", "description": "A useful function", "sources": refs},
            )
            assert "error" not in result
            raise ToolCallLimitError("LLM dialogue exhausted its tool-call limit")
        assert source["reference"] != refs[0]
        assert source["source_reference"] == parent
        assert world.memory.resolve(trace_reference(source["reference"])) == source["content"]
        if invocations == 2:
            rejected = await call(
                "create_concept",
                {
                    "name": "Water supply",
                    "description": "A useful function",
                    "sources": [source["reference"]],
                },
            )
            assert "Review search candidates" in rejected["error"]
        result = await call(
            "create_concept",
            {
                "name": f"Section {invocations}",
                "description": "Supported meaning",
                "sources": [source["reference"]],
            },
        )
        assert "error" not in result

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert invocations == 3
    assert len(result["writes"]) == 3
    assert len(result["processing"]["completed"]) == 2
    assert result["processing"]["status"] == "processed"
    events = [event for event in world.memory.events if event.operator == "semantic_write"]
    assert len({tuple(event.arguments["key"]) for event in events}) == 3
    assert len(world.graph.changes_of(world.graph.find("Water supply").id)) == 1


async def test_indivisible_tool_limit_records_gap():
    from evertree.core.runtime.llm import ToolCallLimitError

    world = semantic_world()
    refs, _ = recorded_experience(world, "An indivisible assertion")

    async def limited(payload, call):
        raise ToolCallLimitError("LLM dialogue exhausted its tool-call limit")

    result = (await run(context(world, limited, role="exec"), refs))["result"]
    assert result["processing"]["status"] == "incomplete"
    assert result["processing"]["completed"] == result["processing"]["pending"] == []
    assert len(result["processing"]["failed"]) == 1


async def test_direct_integration_partitions_full_source_and_resumes_only_remaining_units():
    world = semantic_world()
    source = "First fact.\n\n" * 700 + "Last distinct fact."
    refs, _ = recorded_experience(world, source)
    seen = []

    async def interrupted(payload, call):
        item = json.loads(payload["prompt"])["material"]["experience"][0]
        seen.append(item["content"])
        if len(seen) == 2:
            raise RuntimeError("Provider temporarily unavailable")

    result = (await run(context(world, interrupted, role="exec"), refs))["result"]
    progress = result["processing"]
    assert len(progress["completed"]) == 1 and len(progress["failed"]) == 1
    progress["pending"] = [entry["unit"] for entry in progress["failed"]] + progress["pending"]
    progress["failed"] = []
    resumed = []

    async def complete(payload, call):
        resumed.append(json.loads(payload["prompt"])["material"]["experience"][0]["content"])

    result = (await run(context(world, complete, role="exec"), refs, processing=progress))["result"]
    assert result["processing"]["status"] == "processed"
    assert "".join([seen[0], *resumed]) == source


async def test_declared_incomplete_section_splits_and_keeps_prior_writes():
    world = semantic_world()
    refs, _ = recorded_experience(world, "First fact. Second fact.")
    sections = []

    async def model(payload, call):
        material = json.loads(payload["prompt"])["material"]
        item = material["experience"][0]
        sections.append(item["content"])
        if len(sections) > 1:
            assert material["previous_attempt_remaining_work"] == ["Second assertion not yet saved"]
        if len(sections) == 1:
            await call(
                "create_claim",
                {"name": "First fact", "description": "First fact.", "sources": refs},
            )
            await call(
                "finish_section", {"complete": False, "remaining": "Second assertion not yet saved"}
            )
        if "Second" in item["content"]:
            await call(
                "create_claim",
                {
                    "name": "Second fact",
                    "description": "Second fact.",
                    "sources": [item["reference"]],
                },
            )
        await call("finish_section", {"complete": True, "remaining": ""})

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert sections == ["First fact. Second fact.", "First fact. ", "Second fact."]
    assert len(result["writes"]) == len(world.graph.nodes(kind="claim")) == 2
    assert result["processing"]["status"] == "processed"
    assert len(result["processing"]["completed"]) == 2
    assert result["processing"]["failed"] == result["processing"]["pending"] == []


async def test_declared_indivisible_gap_is_not_retried_forever():
    world = semantic_world()
    refs, _ = recorded_experience(world, "One indivisible assertion")
    invocations = 0

    async def model(payload, call):
        nonlocal invocations
        invocations += 1
        await call(
            "finish_section", {"complete": False, "remaining": "Missing participant identity"}
        )

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert invocations == 1
    assert result["processing"]["completed"] == result["processing"]["pending"] == []
    assert result["processing"]["status"] == "incomplete"
    assert "Missing participant identity" in result["processing"]["failed"][0]["error"]
    assert result["processing"]["failed"][0]["unit"]["remaining_work"] == [
        "Missing participant identity"
    ]


async def test_completion_decision_cannot_hide_a_known_remainder():
    world = semantic_world()
    refs, _ = recorded_experience(world, "One fact")

    async def model(payload, call):
        with pytest.raises(ValueError, match="Completed sections"):
            await call("finish_section", {"complete": True, "remaining": "Still missing a fact"})
        with pytest.raises(ValueError, match="Completed sections"):
            await call("finish_section", {"complete": False, "remaining": ""})
        await call("finish_section", {"complete": True, "remaining": ""})

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert result["processing"]["status"] == "processed"


async def test_explicit_retry_preserves_unresolved_repair_report():
    world = semantic_world()
    refs, _ = recorded_experience(world, "A participant has a property")

    async def incomplete(payload, call):
        await call(
            "finish_section",
            {"complete": False, "remaining": "Check a duplicate participant identity"},
        )

    progress = (await run(context(world, incomplete, role="exec"), refs))["result"]["processing"]
    progress = json.loads(json.dumps(progress))
    progress["pending"] = [row["unit"] for row in progress["failed"]]
    progress["failed"] = []

    async def resumed(payload, call):
        material = json.loads(payload["prompt"])["material"]
        assert material["previous_attempt_remaining_work"] == [
            "Check a duplicate participant identity"
        ]
        await call("finish_section", {"complete": True, "remaining": ""})

    result = (await run(context(world, resumed, role="exec"), refs, processing=progress))["result"]
    assert result["processing"]["status"] == "processed"
