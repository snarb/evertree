"""Exact source routes retain fragments, historical corrections and complete paged text."""

import json
from datetime import timedelta

import pytest

from evertree.core.graph import api as graph_api
from evertree.core.graph.types import GraphDelta, Node, NodeUpdate
from evertree.core.memory import api as memory_api
from evertree.core.memory.types import TraceOutputRef
from evertree.core.tokens import count_tokens
from evertree.core.values import ContractError, json_value, utcnow
from tests.support.semantics import semantic_world
from tests.support.tokens import offline_tokenizer  # noqa: F401 -- offline BPE fixture

CONTEXT = {"model": "gpt-5", "context_window": 1_000_000}


def read(world, method="graph.sources", *, task="task", context=CONTEXT, **arguments):
    return world.service.source_reads.read(
        method, {**arguments, "_read_context": context}, task_id=task
    )


def source(world, value, *, path=(), dependencies=(), arguments=None, operator="observation"):
    run = world.memory.start_run("Source", "revision", arguments or {})
    event = world.memory.record(run, operator, output=value, dependencies=dependencies)
    world.memory.finish_run(run)
    return TraceOutputRef(event.id, path)


def apply(world, delta, *references):
    return world.operations.apply_delta(
        delta, task_id="task", revision="revision", source_refs=references
    )


def test_history_preserves_original_correction_and_fragments_without_neighbor_expansion():
    world = semantic_world()
    first = source(world, {"title": "Original", "body": "Value is 10"}, path=("body",))
    title = TraceOutputRef(first.event_ref, ("title",))
    correction = source(world, "Correction: value is 20")
    renamed = source(world, "Spelling correction only")
    subject = Node(world.graph.reserve_id(), "Subject", properties={"value": 10})
    neighbor = Node(world.graph.reserve_id(), "Other")
    apply(world, GraphDelta(creates=(subject, neighbor)), first, title)
    apply(
        world,
        GraphDelta(updates=(NodeUpdate(subject.id, {"properties": {"value": 20}}),)),
        correction,
    )
    apply(world, GraphDelta(updates=(NodeUpdate(subject.id, {"name": "Renamed"}),)), renamed)
    fact = world.graph.new_fact("PART_WHOLE", {"part": subject.id, "whole": neighbor.id})
    unrelated = source(world, "Only the neighboring assertion")
    apply(world, GraphDelta(creates=(fact,)), unrelated)

    result = read(world, subjects=[subject.id, subject.id])
    refs = {json.dumps(item["reference"], sort_keys=True) for item in result["items"]}
    assert result["scope"] == "recorded_history" and result["total"] == 4
    assert json.dumps(json_value(unrelated), sort_keys=True) not in refs
    assert {tuple(item["reference"]["output_path"]) for item in result["items"]} == {
        (),
        ("title",),
        ("body",),
    }
    latest = [item for item in result["items"] if item["bindings"][0]["latest_change"]]
    assert len(latest) == 1 and latest[0]["reference"] == json_value(renamed)
    assert latest[0]["bindings"][0]["changed_fields"] == ["name"]
    assert result["items"][-1]["context_reference"] == {
        "event_ref": first.event_ref,
        "output_path": [],
    }
    shared = read(world, subjects=[subject.id, neighbor.id])
    original = next(item for item in shared["items"] if item["reference"] == json_value(first))
    assert {binding["subject"] for binding in original["bindings"]} == {subject.id, neighbor.id}

    apply(world, GraphDelta(deletes=(subject.id, fact.id)), correction)
    deleted = read(world, subjects=[subject.id])
    assert deleted["items"][0]["bindings"][0]["operation"] == "delete"


def test_explicit_evidence_dependencies_exclude_unrelated_run_context():
    world = semantic_world()
    original = source(world, {"body": "Original evidence"}, path=("body",))
    unrelated = source(world, "Unrelated input to the same task")
    analysis = source(
        world,
        {"text": "Qualified inference"},
        path=("text",),
        dependencies=(original,),
        arguments={"context": unrelated},
        operator="analytical_note",
    )
    subject = Node(world.graph.reserve_id(), "Subject")
    apply(world, GraphDelta(creates=(subject,)), analysis)
    before = world.memory.snapshot()
    result = read(world, subjects=[subject.id])
    assert [item["reference"] for item in result["items"]] == [
        json_value(analysis),
        json_value(original),
    ]
    assert result["items"][0]["origin"]["kind"] == "analytical_note"
    assert result["items"][1]["bindings"][0]["via"] == json_value(analysis)
    assert not result["items"][1]["bindings"][0]["direct"]
    assert world.memory.snapshot() == before


@pytest.mark.parametrize("value", ["Насос α🧠.\n" * 600, {"body": "Text\n" * 900, "n": 3}, ""])
def test_exact_content_pages_reconstruct_text_and_json_without_truncation(value):
    world = semantic_world()
    reference = source(world, {"source": value}, path=("source",))
    small = {**CONTEXT, "context_window": 2000}
    before = world.memory.snapshot()
    page = read(world, "memory.read_source", reference=json_value(reference), context=small)
    chunks, offset = [], 0
    while True:
        assert page["start"] == offset
        assert count_tokens(page, small["model"]) <= 1200
        assert page["reference"] == json_value(reference)
        chunks.append(page["content"])
        offset = page["end"]
        if not page["has_more"]:
            break
        page = read(world, "memory.read_source", next_page=True, context=small)
    actual = "".join(chunks)
    assert actual == value if isinstance(value, str) else json.loads(actual) == value
    assert offset == page["total_characters"]
    assert world.memory.snapshot() == before
    with pytest.raises(ContractError, match="exhausted"):
        read(world, "memory.read_source", next_page=True)


def test_source_list_continuation_is_task_and_revision_scoped():
    world = semantic_world()
    references = [source(world, f"Source {i}") for i in range(5)]
    subject = Node(world.graph.reserve_id(), "Subject")
    apply(world, GraphDelta(creates=(subject,)), *references)
    first = read(world, subjects=[subject.id], max_items=2)
    assert first["total"] == 5 and first["returned"] == 2 and first["has_more"]
    second = read(world, next_page=True, max_items=2)
    last = read(world, next_page=True, max_items=2)
    assert [item["reference"] for page in (first, second, last) for item in page["items"]] == [
        json_value(ref) for ref in references
    ]
    assert not last["has_more"]
    with pytest.raises(ContractError, match="No saved source selection"):
        read(world, task="other", next_page=True)
    read(world, subjects=[subject.id], max_items=1)
    apply(world, GraphDelta(updates=(NodeUpdate(subject.id, {"name": "New name"}),)), references[0])
    with pytest.raises(ContractError, match="Graph changed"):
        read(world, next_page=True)
    read(world, subjects=[subject.id], max_items=1)
    world.service.release("task")
    with pytest.raises(ContractError, match="No saved source selection"):
        read(world, next_page=True)


def test_forwarded_fragment_unknown_reference_and_nonaddressable_graph_provenance():
    world = semantic_world()
    original = source(world, {"body": "Exact original body"}, path=("body",))
    forwarded = source(world, json_value(original))
    result = read(world, "memory.read_source", reference=json_value(forwarded))
    assert result["content"] == "Exact original body"
    assert result["reference"] == json_value(forwarded)
    assert result["resolved_reference"] == json_value(original)
    missing = read(world, "memory.read_source", reference={"event_ref": 99999})
    assert missing["status"] == "unavailable" and not missing["has_more"]
    invalid_path = read(
        world,
        "memory.read_source",
        reference={"event_ref": original.event_ref, "output_path": ["absent"]},
    )
    assert invalid_path["status"] == "unavailable"
    status = read(world, subjects=[1, 99999])
    assert {item["status"] for item in status["items"]} == {"not_addressable", "not_found"}


def test_source_read_does_not_restore_deferred_deletion_and_invalidates_purged_content():
    world = semantic_world()
    reference = source(world, "Large original source. " * 1000)
    now = utcnow() + timedelta(days=400)
    world.memory.delete(reference.event_ref, at=now)
    before = world.memory.snapshot()
    first = read(
        world,
        "memory.read_source",
        reference=json_value(reference),
        context={**CONTEXT, "context_window": 2000},
    )
    assert first["has_more"] and world.memory.snapshot() == before
    assert world.memory.finalize_deletions(at=now + timedelta(days=8)) == (reference.event_ref,)
    with pytest.raises(ContractError, match="Source availability changed"):
        read(world, "memory.read_source", next_page=True)


@pytest.mark.parametrize(
    "arguments",
    [
        {"subjects": []},
        {"subjects": [True]},
        {"subjects": [0]},
        {"subjects": [1], "max_items": False},
        {"subjects": [1], "cursor": "foreign"},
    ],
)
def test_source_input_validation(arguments):
    with pytest.raises(ContractError):
        read(semantic_world(), **arguments)


async def test_exact_source_wrappers_and_semantic_dispatch():
    world = semantic_world()
    reference = source(world, "Original source")
    node = Node(world.graph.reserve_id(), "Subject")
    apply(world, GraphDelta(creates=(node,)), reference)

    class Context:
        async def step(self, method, payload, *, journal):
            assert journal is False
            return await world.service.execute(
                method, {**payload, "_read_context": CONTEXT}, {"task_id": "task"}
            )

    listing = await graph_api.sources(Context(), [node.id])
    content = await memory_api.read_source(Context(), listing["items"][0]["reference"])
    assert content["content"] == "Original source"
