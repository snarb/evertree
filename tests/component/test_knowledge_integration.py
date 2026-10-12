"""Checked integration contracts, using real graph, memory and Program orchestration."""

import json

import pytest

from evertree.core.memory.store import TraceStore
from evertree.core.values import ContractError, json_value
from evertree.processes.semantic_processing.knowledge_integration._exec import run
from tests.support.semantics import EmptyIndex, context, semantic_world


def packet(world, *contents, intents=()):
    source_run = world.memory.start_run("experience", "revision", {})
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
    with pytest.raises(ContractError, match="world-time"):
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

    async def model(payload):
        material = json.loads(payload["prompt"])
        attempts.append(material)
        assert material["material"]["context"]["task"] == {"goal": "Learn terminology"}
        return {
            "action": "commit",
            "delta_json": json.dumps({"creates": [{"id": -1, "name": "Useful term"}]}),
            "decisions_json": json.dumps([decision(refs, "materialize", [-1])]),
        }

    result = await run(
        context(
            world, model, role="exec", integration_context={"task": {"goal": "Learn terminology"}}
        ),
        refs,
    )
    assert result["result"]["complete"] and len(attempts) == 2
    assert searches == ["Useful term"]
    assert attempts[1]["reads"][0]["result"]["status"] == "complete"


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
