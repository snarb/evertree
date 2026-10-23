"""Exact acquisition sections survive replay without widening source authority."""

import json
from datetime import timedelta

import pytest

from evertree.core.memory.store import TraceStore
from evertree.core.memory.types import TraceOutputRef
from evertree.core.operations import authorize_operation
from evertree.core.semantics import api
from evertree.core.values import ContractError, json_value
from tests.support.semantics import recorded_experience, semantic_world, write_action
from tests.support.tokens import offline_tokenizer  # noqa: F401 -- offline BPE fixture


def prepared(world, refs, metadata, *sections):
    return world.service.prepare_sources(refs, list(sections), metadata=metadata)["experience"]


def note(reference):
    return {"action": "save_note", "name": "Exact source", "source": reference, "sources": []}


def test_exact_unicode_section_and_context_are_separately_readable_after_graph_write():
    world = semantic_world()
    body = "First α fact. Second β fact. Third γ fact."
    refs, metadata = recorded_experience(world, {"title": "Source title", "body": body})
    start, end = body.index("Second"), body.index("Third")
    section = {"source": 0, "path": ["body"], "start": start, "end": end}
    item = prepared(world, refs, metadata, section)[0]
    assert item["content"] == body[start:end]
    assert item["reference"]["output_path"] == ["text"]
    assert item["source_reference"] == refs[0]
    assert item["location"] == {key: value for key, value in section.items() if key != "source"}
    assert any(entry.get("values") == {"title": "Source title"} for entry in item["source_context"])
    event = world.memory.get_event(item["reference"]["event_ref"])
    assert event.dependencies == (TraceOutputRef(**refs[0]),)

    result = write_action(world, refs, metadata, note(item["reference"]))
    assert "error" not in result, result
    assert world.graph.get(result["object"]).description == body[start:end]
    context = {"model": "gpt-5", "context_window": 100000}
    listing = world.service.source_reads.read(
        "graph.sources", {"subjects": [result["object"]], "_read_context": context}, task_id="task"
    )
    assert {json.dumps(row["reference"], sort_keys=True) for row in listing["items"]} == {
        json.dumps(item["reference"], sort_keys=True),
        json.dumps(refs[0], sort_keys=True),
    }
    read = world.service.source_reads.read
    exact = read(
        "memory.read_source",
        {"reference": item["reference"], "_read_context": context},
        task_id="task",
    )
    assert exact["content"] == body[start:end] and not exact["has_more"]
    envelope = read(
        "memory.read_source",
        {"reference": exact["context_reference"], "_read_context": context},
        task_id="task",
    )
    stored = json.loads(envelope["content"])
    assert stored["source_ref"] == refs[0] and stored["location"] == item["location"]


def test_preparation_replay_and_snapshot_restore_keep_reference_and_make_no_new_events():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "First fact. Second fact.")
    section = {"source": 0, "path": [], "start": 0, "end": 12}
    first = prepared(world, refs, metadata, section, section)
    assert first[0] == first[1]
    saved = world.memory.snapshot()
    world.service.memory = TraceStore.from_snapshot(saved)
    second = prepared(world, refs, {**metadata, "run_id": "resumed"}, section)
    assert second == first[:1]
    assert world.service.memory.snapshot() == saved


def test_prepared_fragment_survives_compaction_before_first_write_until_task_release():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "First fact. Second fact.")
    item = prepared(world, refs, metadata, {"source": 0, "path": [], "start": 0, "end": 12})[0]
    restored = TraceStore.from_snapshot(world.memory.snapshot())
    event = restored.get_event(item["reference"]["event_ref"])
    assert {event.id, refs[0]["event_ref"]} <= restored.retention_closure()
    later = event.occurred_at + timedelta(days=30)
    with pytest.raises(ContractError, match="retention closure"):
        restored.compact(event.program_run, (), at=later)
    restored.release(event.id, "task:" + metadata["task_id"])
    assert event.id not in restored.retention_closure()
    restored.compact(event.program_run, (), at=later)


def test_adaptive_children_refer_to_their_own_exact_original_ranges():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "First fact. Second fact.")
    parent = prepared(world, refs, metadata, {"source": 0, "path": [], "start": 0, "end": 23})[0]
    children = prepared(
        world,
        refs,
        metadata,
        {"source": 0, "path": [], "start": 0, "end": 12},
        {"source": 0, "path": [], "start": 12, "end": 23},
    )
    assert "".join(child["content"] for child in children) == parent["content"]
    assert len({child["reference"]["event_ref"] for child in [parent, *children]}) == 3
    assert all(child["source_reference"] == refs[0] for child in children)


def test_structured_keys_and_list_ranges_preserve_exact_values_and_paths():
    world = semantic_world()
    refs, metadata = recorded_experience(
        world, {"article": {"title": "Title", "body": "Body", "tags": ["a", "b", "c"]}}
    )
    items = prepared(
        world,
        refs,
        metadata,
        {"source": 0, "path": ["article"], "keys": ["title", "tags"]},
        {"source": 0, "path": ["article", "tags"], "start": 1, "end": 3},
    )
    assert items[0]["content"] == {"title": "Title", "tags": ["a", "b", "c"]}
    assert items[1]["content"] == ["b", "c"]
    for item in items:
        assert item["reference"]["output_path"] == ["value"]
        assert (
            json_value(world.memory.resolve(TraceOutputRef(**item["reference"]))) == item["content"]
        )


def test_whole_and_nested_values_reuse_existing_source_without_recording_fragments():
    world = semantic_world()
    refs, metadata = recorded_experience(world, {"body": "Complete body"})
    before = world.memory.snapshot()
    whole, nested = prepared(
        world, refs, metadata, {"source": 0, "path": []}, {"source": 0, "path": ["body"]}
    )
    assert whole["reference"] == refs[0]
    assert nested["reference"] == {**refs[0], "output_path": ["body"]}
    assert nested["context_reference"] == refs[0]
    assert world.memory.snapshot() == before


def forwarded(world, reference):
    run = world.memory.start_run("Forwarder", "revision", {})
    event = world.memory.record(run, "forward", output=TraceOutputRef(**reference))
    world.memory.finish_run(run)
    return {"event_ref": event.id, "output_path": []}


def test_forwarded_input_keeps_nested_whole_selection_addressable_and_writable():
    world = semantic_world()
    refs, metadata = recorded_experience(world, {"body": "Complete original text"})
    alias = forwarded(world, refs[0])
    item = prepared(world, [alias], metadata, {"source": 0, "path": ["body"]})[0]
    assert world.memory.resolve(TraceOutputRef(**item["reference"])) == item["content"]
    result = write_action(world, [alias], metadata, note(item["reference"]))
    assert "error" not in result, result
    assert world.graph.get(result["object"]).description == "Complete original text"


def test_forwarded_automatic_fragment_unwraps_to_an_addressable_data_reference():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "Complete original text")
    run = world.memory.start_run("ExperienceFragments", "revision", {"task_id": "task"})
    event = world.memory.record(
        run,
        "experience_fragment",
        output={
            "source_ref": refs[0],
            "encoding": "structured",
            "location": {"path": [], "start": 0, "end": 8},
            "context": [],
            "text": "Complete",
        },
    )
    world.memory.finish_run(run)
    alias = forwarded(world, json_value(world.memory.output_ref(event)))
    item = prepared(world, [alias], metadata, {"source": 0, "path": []})[0]
    assert item["content"] == "Complete"
    assert world.memory.resolve(TraceOutputRef(**item["reference"])) == "Complete"
    result = write_action(world, [alias], metadata, note(item["reference"]))
    assert "error" not in result, result


@pytest.mark.parametrize("field", ["text", "value"])
def test_existing_automatic_fragment_unwraps_only_data_and_preserves_context(field):
    world = semantic_world()
    value = "First fact. Second fact." if field == "text" else {"fact": 12}
    refs, metadata = recorded_experience(world, value)
    run = world.memory.start_run("ExperienceFragments", "revision", {"task_id": "task"})
    output = {
        "source_ref": refs[0],
        "encoding": "structured",
        "location": {"path": [], "start": 0, "end": 12},
        "context": [{"preceding_text": "Title"}],
        field: value,
    }
    event = world.memory.record(run, "experience_fragment", output=output)
    world.memory.finish_run(run)
    fragment = json_value(world.memory.output_ref(event))
    before = len(world.memory.events)
    item = prepared(world, [fragment], metadata, {"source": 0, "path": []})[0]
    assert item["content"] == value
    assert item["reference"] == {**fragment, "output_path": [field]}
    assert item["source_reference"] == refs[0]
    assert item["context_reference"] == fragment
    assert item["source_context"] == output["context"]
    assert item["location"] == output["location"]
    assert len(world.memory.events) == before
    assert event.id in world.memory.retention_closure()
    if field == "text":
        child = prepared(
            world, [fragment], metadata, {"source": 0, "path": [], "start": 0, "end": 12}
        )[0]
        result = write_action(world, [fragment], metadata, note(child["reference"]))
        assert "error" not in result, result


@pytest.mark.parametrize(
    "changes",
    [{"integration_operation_id": "other"}, {"task_id": "other"}],
)
def test_prepared_fragment_cannot_authorize_a_different_integration_or_task(changes):
    world = semantic_world()
    refs, metadata = recorded_experience(world, "First fact. Second fact.")
    item = prepared(world, refs, metadata, {"source": 0, "path": [], "start": 0, "end": 12})[0]
    result = write_action(world, refs, {**metadata, **changes}, note(item["reference"]))
    assert "outside supplied experience" in result["error"]


def test_fragment_envelope_and_unrelated_original_are_not_authorized_for_writes():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "First fact. Second fact.", "Other source")
    item = prepared(world, refs, metadata, {"source": 0, "path": [], "start": 0, "end": 12})[0]
    for sources, reference in ((refs, item["context_reference"]), (refs[1:], item["reference"])):
        result = write_action(world, sources, metadata, note(reference))
        assert "outside supplied experience" in result["error"]


@pytest.mark.parametrize(
    "section",
    [
        {"source": True, "path": []},
        {"source": 2, "path": []},
        {"source": 0, "path": ["missing"]},
        {"source": 0, "path": ["body"], "start": 0, "end": 100},
        {"source": 0, "path": ["body"], "start": 0},
        {"source": 0, "path": ["body"], "start": -1, "end": 3},
        {"source": 0, "path": [], "keys": ["body", "body"]},
        {"source": 0, "path": [], "keys": ["body"], "start": 0, "end": 1},
    ],
)
def test_bad_sections_reject_entire_batch_without_retaining_partial_preparation(section):
    world = semantic_world()
    refs, metadata = recorded_experience(world, {"body": "First fact. Second fact."})
    before = world.memory.snapshot()
    with pytest.raises(ContractError):
        prepared(
            world, refs, metadata, {"source": 0, "path": ["body"], "start": 0, "end": 12}, section
        )
    assert world.memory.snapshot() == before


async def test_prepare_wrapper_is_journaled_and_excluded_from_model_program_authority():
    calls = []

    class Context:
        async def step(self, method, payload, *, journal=True):
            calls.append((method, payload, journal))
            return {"experience": []}

    refs, sections = [{"event_ref": 1}], [{"source": 0, "path": []}]
    assert await api.prepare_sources(Context(), refs, sections, focus="Focus") == {"experience": []}
    assert calls == [
        (
            "semantic.prepare_sources",
            {"experience_refs": refs, "sections": sections, "focus": "Focus"},
            True,
        )
    ]
    with pytest.raises(PermissionError):
        authorize_operation("semantic.prepare_sources", "model")
