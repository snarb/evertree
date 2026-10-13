"""Checked integration contracts, using real graph, memory and Program orchestration."""

import json

import pytest

from evertree.core.memory.store import TraceStore
from evertree.core.values import ContractError, json_value
from evertree.processes.semantic_processing.knowledge_integration._exec import run
from tests.support.semantics import EmptyIndex, context, semantic_world


def packet(world, *contents, intents=(), run_mode="live"):
    source_run = world.memory.start_run("experience", "revision", {}, run_mode=run_mode)
    refs = [
        json_value(world.memory.output_ref(world.memory.record(source_run, "input", output=value)))
        for value in contents
    ]
    world.memory.finish_run(source_run)
    metadata = {
        "task_id": "task",
        "run_id": "original-run",
        "program": {"role": "exec", "revision": "revision"},
        "knowledge_integration_authorized": True,
        "integration_operation_id": "packet",
        "integration_context": {"preservation_intents": list(intents)},
    }
    return refs, metadata


def decision(refs, disposition="trace_only", ids=(), preservation=()):
    return {
        "disposition": disposition,
        "reason": "Selected for the current task",
        "source_refs": refs,
        "affected_ids": list(ids),
        "preservation_ids": list(preservation),
    }


def commit(world, refs, metadata, *, creates=(), decisions=None):
    return world.service.commit(
        {
            "experience_refs": refs,
            "proposal": {"creates": list(creates)},
            "decisions": decisions or [decision(refs)],
        },
        metadata,
    )


def test_integration_requires_admitted_exec_and_does_not_accept_injected_context():
    world = semantic_world()
    refs, metadata = packet(world, "source")
    for bad in ({}, {"knowledge_integration_authorized": False}, {"program": {"role": "model"}}):
        with pytest.raises(PermissionError):
            commit(world, refs, {**metadata, **bad} if bad else {})
    with pytest.raises(TypeError):
        world.service.sources(refs, context={"task": "override"}, metadata=metadata)
    with pytest.raises(PermissionError, match="Public graph.apply"):
        world.operations.execute("graph.apply", {}, metadata=metadata)


def test_integration_requires_source_coverage_and_attribution_before_writing():
    world = semantic_world()
    refs, metadata = packet(world, "keep", "ordinary")
    before = world.graph.revision
    result = commit(world, refs, metadata, decisions=[decision(refs[:1])])
    assert result["status"] == "invalid" and "unreviewed" in result["error"]
    result = commit(world, refs, metadata, creates=[{"id": -1, "name": "Insight", "kind": "note"}])
    assert result["status"] == "invalid" and "attributed" in result["error"]
    assert world.graph.revision == before


def test_retention_only_pins_sources_of_materialized_candidates():
    world = semantic_world()
    refs, metadata = packet(world, "important", "ordinary")
    result = commit(
        world,
        refs,
        metadata,
        creates=[{"id": -1, "name": "Insight", "kind": "note", "description": "Important"}],
        decisions=[decision(refs[:1], "materialize", [-1]), decision(refs[1:])],
    )
    assert result["complete"]
    mutation = world.memory.get_event(world.graph._history[-1].provenance["event_ref"])
    assert [ref.event_ref for ref in mutation.dependencies] == [refs[0]["event_ref"]]
    assert refs[1]["event_ref"] not in world.memory._protections
    assert refs[1]["event_ref"] not in world.memory.retention_closure()
    assert mutation.arguments["decisions"][0]["reason"] == "Selected for the current task"
    assert world.graph.get(result["created"][0]["id"]).properties == {}


def test_receipt_survives_snapshot_and_different_run_id_without_duplicate_writes():
    world = semantic_world()
    refs, metadata = packet(world, "important")
    payload = {
        "experience_refs": refs,
        "proposal": {"creates": [{"id": -1, "name": "Insight", "kind": "note"}]},
        "decisions": [decision(refs, "materialize", [-1])],
    }
    result = world.service.commit(payload, metadata)
    revision = world.graph.revision
    restored = TraceStore.from_snapshot(world.memory.snapshot())
    world.service.memory = restored
    replay = world.service.commit(payload, {**metadata, "run_id": "after-restart"})
    assert replay == result and world.graph.revision == revision


def test_preservation_is_obligation_and_note_is_valid_fallback():
    world = semantic_world()
    refs, metadata = packet(world, "Hypothesis: reconnect may explain the error")
    metadata["integration_context"]["preservation_intents"] = [
        {"id": "insight", "text": "Preserve hypothesis and limitation", "source_ref": refs[0]}
    ]
    refused = commit(world, refs, metadata)
    assert refused["status"] == "blocked" and refused["pending_preservation_ids"] == ["insight"]
    result = commit(
        world,
        refs,
        metadata,
        creates=[
            {
                "id": -1,
                "name": "Connection hypothesis",
                "kind": "note",
                "description": "Reconnect may explain error; causality is unverified.",
            }
        ],
        decisions=[decision(refs, "materialize", [-1], ["insight"])],
    )
    assert result["complete"] and not result["pending_preservation_ids"]
    assert not world.operations.beliefs.snapshot()["targets"]


def test_identity_requires_actual_complete_search_and_world_time_is_not_invented():
    world = semantic_world()
    refs, metadata = packet(world, "Object exists")
    node = {"id": -1, "name": "Object", "kind": "concept"}
    decisions = [decision(refs, "materialize", [-1])]
    missing = commit(world, refs, metadata, creates=[node], decisions=decisions)
    assert "complete current search" in missing["error"]
    world.service.results(
        "Object", None, [], [{"channel": "vector", "error": "offline"}], 20, "task"
    )
    incomplete = commit(world, refs, metadata, creates=[node], decisions=decisions)
    assert "complete current search" in incomplete["error"]
    world.service.results("Object", None, [], [], 20, "task")
    assert commit(world, refs, metadata, creates=[node], decisions=decisions)["complete"]
    # An undated state still needs its identity link; time itself is no longer mandatory.
    with pytest.raises(ContractError, match="STATE_IDENTITY"):
        world.service._proposal({"creates": [{"id": -1, "name": "State", "kind": "facet"}]})


async def test_program_performs_search_before_identity_creation_and_sees_authoritative_context():
    searches = []

    class Index(EmptyIndex):
        async def lexical(self, nodes, query, kind):
            searches.append(query)
            return []

    world = semantic_world(index=Index())
    refs, _ = packet(world, "A useful term")
    attempts = []

    async def model(payload, call):
        state = json.loads(payload["prompt"])
        attempts.append(state)
        assert state["material"]["context"]["task"] == {"objective": "Learn terminology"}
        created = await call(
            "create_concept",
            {
                "name": "Useful term",
                "description": None,
                "sources": refs,
            },
        )
        assert created["object"] < 0
        await call("finish", {})

    result = await run(
        context(
            world,
            model,
            role="exec",
            integration_context={
                "task": {"objective": "Learn terminology"},
            },
        ),
        refs,
    )
    assert result["result"]["complete"] and len(attempts) == 1
    assert searches == ["Useful term"]
    assert result["result"]["created"][0]["name"] == "Useful term"
    assert "reason" not in result["result"]["decisions"][0]


def test_analytical_preservation_cannot_be_omitted_by_direct_program_calls():
    world = semantic_world()
    refs, metadata = packet(world, "observation")
    reference = world.operations.execute(
        "memory.note",
        {
            "text": "Unverified but useful hypothesis",
            "preserve": True,
            "source_refs": refs,
        },
        metadata=metadata,
    )
    source = world.service.sources([reference], metadata=metadata)
    intent = source["context"]["preservation_intents"][0]
    assert intent["id"] == str(reference["event_ref"]) + ":[]"
    assert commit(world, [reference], metadata)["status"] == "blocked"
    with pytest.raises(PermissionError, match="model Program"):
        world.operations.execute(
            "memory.note",
            {"text": "forbidden"},
            metadata={
                **metadata,
                "program": {"role": "model", "revision": "revision"},
            },
        )


def test_untrusted_json_does_not_create_preservation_obligations():
    world = semantic_world()
    refs, metadata = packet(world, {"text": "external document", "preserve": True})
    assert not world.service.sources(refs, metadata=metadata)["context"]["preservation_intents"]
    assert commit(world, refs, metadata)["complete"]


def test_materialized_properties_cannot_smuggle_trace_only_provenance():
    world = semantic_world()
    refs, metadata = packet(world, "keep", "trace only")
    result = commit(
        world,
        refs,
        metadata,
        creates=[{"id": -1, "name": "Insight", "kind": "note", "properties": {"source": refs[1]}}],
        decisions=[decision(refs[:1], "materialize", [-1]), decision(refs[1:])],
    )
    assert result["status"] == "invalid" and "Embedded provenance" in result["error"]


def test_operation_identity_binds_experience_and_context_but_not_remaining_budget():
    world = semantic_world()
    refs, metadata = packet(world, "first", "second")
    metadata["integration_context"]["task"] = {
        "specification": {"goal": "Investigate"},
        "remaining_active_time_minutes": 10,
    }
    original = commit(world, refs[:1], metadata)
    metadata["integration_context"]["task"]["remaining_active_time_minutes"] = 9
    assert commit(world, refs[:1], metadata) == original
    assert "different experience" in commit(world, refs[1:], metadata)["error"]
    metadata["integration_context"]["task"]["specification"]["goal"] = "Changed"
    assert "different experience" in commit(world, refs[:1], metadata)["error"]


@pytest.mark.parametrize(
    "reference",
    [
        {"event_ref": True},
        {"event_ref": 1, "output_path": [False]},
        {"event_ref": 1, "output_path": "text"},
    ],
)
def test_sources_reject_ambiguous_reference_types(reference):
    world = semantic_world()
    _, metadata = packet(world, "source")
    with pytest.raises(ContractError, match="Invalid retained"):
        world.service.sources([reference], metadata=metadata)


async def test_fabricated_search_completion_does_not_authorize_identity_creation():
    world = semantic_world()
    refs, metadata = packet(world, "candidate")
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
    result = commit(
        world,
        refs,
        metadata,
        creates=[{"id": -1, "name": "Candidate"}],
        decisions=[decision(refs, "materialize", [-1])],
    )
    assert result["status"] == "invalid"


async def test_model_projection_preserves_meaning_and_obligations_without_audit_metadata():
    world = semantic_world()
    source = {"origin": "factory", "revision": "pump-v2", "pressure": 5}
    refs, metadata = packet(world, source, run_mode="replay")
    note = world.operations.execute(
        "memory.note",
        {"text": "Pressure may vary with load; untested.", "source_refs": refs, "preserve": True},
        metadata=metadata,
    )
    refs.append(note)
    trusted = {
        "task": {
            "id": "task",
            "specification": {
                "objective": "Study pressure",
                "constraints": ["Keep hypotheses qualified"],
                "revision": 8,
                "source_ids": ["message-id"],
            },
            "self_improvement_remaining": 0,
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
        prompt = json.loads(payload["prompt"])
        material = prompt["material"]
        assert "origin" not in material["experience"][0]
        assert material["experience"][0]["content"] == source
        assert material["experience"][0]["experience_mode"] == "replay"
        analysis = material["experience"][1]
        assert analysis["source_kind"] == "analytical_note"
        assert analysis["content"]["source_refs"] == refs[:1]
        assert "preserve" not in analysis["content"]
        context_ = material["context"]
        assert context_["task"] == {
            "objective": "Study pressure",
            "constraints": ["Keep hypotheses qualified"],
        }
        assert context_["values"] == [{"name": "Accuracy", "description": "Retain uncertainty"}]
        assert [node["name"] for node in context_["self"]] == ["Sensor limitation"]
        assert "provenance" not in context_["self"][0]
        intent = context_["preservation_intents"][0]
        assert set(intent) == {"id", "source_ref"}
        await call("trace_only", {"sources": refs[:1]})
        await call("save_note", {"name": "Hypothesis", "source": note, "sources": []})
        await call("finish", {})

    result = await run(context(world, model, role="exec", integration_context=trusted), refs)
    assert result["result"]["complete"]
    original = world.service.sources(refs, metadata={**metadata, "integration_context": trusted})
    assert original["experience"][0]["origin"]["revision"] == "revision"
    assert original["context"]["task"]["specification"]["revision"] == 8


@pytest.mark.parametrize("path", [["text"], ["source_refs"], ["source_refs", 0]])
async def test_model_projection_keeps_addressed_note_fragments_verbatim(path):
    world = semantic_world()
    refs, metadata = packet(world, "Original observation")
    note = world.operations.execute(
        "memory.note",
        {
            "text": "Partial analysis",
            "source_refs": refs,
        },
        metadata=metadata,
    )
    reference = {**note, "output_path": path}
    source = world.service.sources([reference], metadata=metadata)["experience"][0]["content"]

    async def model(payload, call):
        item = json.loads(payload["prompt"])["material"]["experience"][0]
        assert item["reference"] == reference
        assert item["content"] == source
        await call("trace_only", {"sources": [reference]})
        await call("finish", {})

    assert (await run(context(world, model, role="exec"), [reference]))["result"]["complete"]


async def test_native_tools_create_undated_state_and_relation_then_replay_receipt():
    world = semantic_world()
    refs, _ = packet(world, "Pump P1 was noisy after startup; date unknown.", "Routine log")
    requests = []

    async def model(payload, call):
        requests.append(payload)
        common = {"description": None, "sources": refs[:1]}
        prototype = await call("create_prototype", {"name": "Pump", "parent": None, **common})
        instance = await call(
            "create_instance",
            {
                "name": "P1",
                "prototype": prototype["object"],
                **common,
            },
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
        await call(
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
        await call("trace_only", {"sources": refs[1:]})
        await call("finish", {})

    ctx = context(world, model, role="exec")
    result = (await run(ctx, refs))["result"]
    assert result["complete"] and len(requests) == 1
    assert len(result["created"]) == 7
    instance = world.graph.find("P1")
    (facet,) = world.graph.get_facets(instance)
    assert facet.valid_from is None and facet.valid_until is None
    assert len(world.graph.facts("HAS_NOISE")) == 1
    assert all(node["id"] > 0 for node in result["created"])
    assert refs[1]["event_ref"] not in world.memory.retention_closure()
    assert (await run(ctx, refs))["result"] == result
    assert len(requests) == 1


async def test_native_tool_repair_preserves_successful_staging_without_duplicate_note():
    world = semantic_world()
    refs, _ = packet(world, "Useful explanation", "Ordinary input")

    async def model(payload, call):
        saved = await call("save_note", {"name": "Explanation", "source": refs[0], "sources": []})
        invalid = await call("trace_only", {"sources": [{"event_ref": 9999, "output_path": []}]})
        assert invalid["error"]
        assert len(invalid["prepared"]["objects"]) == 1
        assert invalid["prepared"]["objects"][0]["id"] == saved["object"]
        await call("trace_only", {"sources": refs[1:]})
        await call("finish", {})

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert result["complete"] and len(result["created"]) == 1


async def test_search_pages_are_available_without_exposing_internal_cursors():
    from evertree.core.graph.types import GraphDelta, Node

    class Index(EmptyIndex):
        async def lexical(self, nodes, query, kind):
            return [node["id"] for node in nodes if node["name"].startswith("Candidate ")]

    world = semantic_world(index=Index())
    nodes = [Node(world.graph.reserve_id(), f"Candidate {i}") for i in range(25)]
    world.graph.apply(GraphDelta(creates=tuple(nodes)), provenance="corpus")
    refs, _ = packet(world, "Ambiguous object mention")

    async def model(payload, call):
        first = await call("search", {"query": "ambiguous", "next_page": False})
        assert first["has_more"] and "cursor" not in first
        second = await call("search", {"query": "ambiguous", "next_page": True})
        assert len(second["items"]) == 5 and not second["has_more"]
        await call(
            "unresolved",
            {
                "sources": refs,
                "reason": "The source does not identify one of these objects.",
            },
        )
        await call("finish", {})

    assert (await run(context(world, model, role="exec"), refs))["result"]["complete"]


async def test_preservation_obstacle_returns_receipt_once_without_partial_writes_then_resumes():
    world = semantic_world()
    refs, _ = packet(world, "Conditional insight", "Routine observation")
    trusted = {
        "preservation_intents": [
            {"id": "insight", "text": "Conditional insight", "source_ref": refs[0]},
        ]
    }
    obstacle = "The required condition is ambiguous; the author must clarify its meaning."
    requests = []

    async def model(payload, call):
        requests.append(payload)
        await call("save_note", {"name": "Routine note", "source": refs[1], "sources": []})
        await call("unresolved", {"sources": refs[:1], "reason": obstacle})
        await call("finish", {})
        pytest.fail("A declared preservation obstacle must return to the caller")

    before = world.graph.snapshot()
    result = (await run(context(world, model, role="exec", integration_context=trusted), refs))[
        "result"
    ]
    assert result["status"] == "blocked" and not result["complete"]
    assert result["reason"] == obstacle and result["pending_preservation_ids"] == ["insight"]
    assert world.graph.snapshot() == before and len(requests) == 1
    receipt = world.memory.get_event(result["receipt_ref"]["event_ref"])
    assert json_value(receipt.output) == {k: v for k, v in result.items() if k != "receipt_ref"}
    assert len([e for e in world.memory.events if e.operator == "semantic_commit"]) == 1

    async def resumed(payload, call):
        await call("save_note", {"name": "Insight", "source": refs[0], "sources": []})
        await call("trace_only", {"sources": refs[1:]})
        await call("finish", {})

    result = (await run(context(world, resumed, role="exec", integration_context=trusted), refs))[
        "result"
    ]
    assert result["complete"] and len(result["created"]) == 1
    assert world.graph.find("Insight").description == "Conditional insight"


async def test_unrelated_unresolved_source_does_not_prevent_repairing_missing_preservation():
    world = semantic_world()
    refs, _ = packet(world, "Keep this insight", "Unidentified object")
    trusted = {
        "preservation_intents": [
            {"id": "keep", "text": "Keep this insight", "source_ref": refs[0]},
        ]
    }

    async def model(payload, call):
        await call("trace_only", {"sources": refs[:1]})
        await call("unresolved", {"sources": refs[1:], "reason": "Identity unknown"})
        unfinished = await call("finish", {})
        assert unfinished["error"]
        await call("save_note", {"name": "Insight", "source": refs[0], "sources": []})
        await call("finish", {})

    result = (await run(context(world, model, role="exec", integration_context=trusted), refs))[
        "result"
    ]
    assert result["complete"]


async def test_relation_schema_tool_exposes_roles_without_unused_views():
    world = semantic_world()
    refs, _ = packet(world, "Inspect a relation schema")

    async def model(payload, call):
        result = await call("describe", {"subject": "IDENTITY_TYPE"})
        schema = result["schema"]
        assert schema["signature"] and "views" not in schema
        await call("trace_only", {"sources": refs})
        await call("finish", {})

    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert result["complete"]


async def test_final_model_text_without_finish_does_not_commit_staged_knowledge():
    world = semantic_world()
    refs, _ = packet(world, "Useful explanation")

    async def model(payload, call):
        await call("save_note", {"name": "Explanation", "source": refs[0], "sources": []})
        return {"text": "Integration complete"}

    before = world.graph.revision
    result = (await run(context(world, model, role="exec"), refs))["result"]
    assert result["status"] == "blocked" and not result["complete"]
    assert world.graph.revision == before
