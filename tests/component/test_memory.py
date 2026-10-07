import json
from datetime import UTC, datetime, timedelta

import pytest

from evertree.core.graph import ContractError
from evertree.core.memory import MemoryQuery, RetentionPolicy, TraceOutputRef, TraceStore

START = datetime(2025, 1, 1, tzinfo=UTC)


def completed_memory():
    memory = TraceStore()
    run = memory.start_run("program", "abc123", {}, at=START)
    first = memory.record(run, "observe", {}, {"value": 3}, at=START)
    second = memory.record(
        run, "compute", {"source": TraceOutputRef(first.id, ("value",))}, {"value": 6}, at=START
    )
    memory.finish_run(run, at=START)
    return memory, run, first, second


def test_trace_nested_provenance_and_forwarding_identity():
    memory = TraceStore()
    root = memory.start_run("root", "commit", {})
    source = memory.record(root, "observe", {}, {"value": [1, 2]})
    call = memory.record(root, "call", {"source": TraceOutputRef(source.id)}, {"program": "child"})
    child = memory.start_run(
        "child", "commit", {"source": TraceOutputRef(source.id)}, caller_event=call.id
    )
    returned = memory.record(child, "return", {}, {"result": TraceOutputRef(source.id, ("value",))})
    reference = memory.output_ref(returned, ("result",))
    assert reference == TraceOutputRef(source.id, ("value",))
    assert memory.resolve(reference) == (1, 2)
    assert {event.id for event in memory.provenance_of(TraceOutputRef(returned.id))} == {
        source.id,
        call.id,
        returned.id,
    }
    with pytest.raises(TypeError):
        memory.get_event(source.id).output["new"] = 2
    memory.finish_run(child)
    memory.finish_run(root)
    memory.validate()


def test_retention_closure_prevents_compaction_and_deletion():
    memory, run, first, second = completed_memory()
    memory.retain(TraceOutputRef(second.id), "active belief")
    assert memory.retention_closure() == {first.id, second.id}
    with pytest.raises(ContractError, match="retention"):
        memory.compact(run.id, (second.id,), at=START + timedelta(days=10))
    with pytest.raises(ContractError, match="protected"):
        memory.delete(first.id, at=START + timedelta(days=10))
    memory.release(second.id, "active belief")
    memory.compact(run.id, (second.id,), at=START + timedelta(days=10))
    assert memory.resolve(TraceOutputRef(first.id)) == {"value": 3}


def test_delete_waits_for_grace_and_cancels_on_new_dependency():
    memory, run, first, second = completed_memory()
    deletion_time = START + timedelta(days=10)
    memory.delete(first.id, at=deletion_time)
    assert memory.finalize_deletions(at=deletion_time + timedelta(days=6)) == ()
    # second still requires first, so finalization restores first membership.
    assert memory.finalize_deletions(at=deletion_time + timedelta(days=8)) == ()
    assert first.id in memory.semantic_trace(run.id).events
    memory.delete(first.id, at=deletion_time)
    memory.delete(second.id, at=deletion_time)
    assert memory.finalize_deletions(at=deletion_time + timedelta(days=8)) == (first.id, second.id)
    with pytest.raises(ContractError, match="dangling"):
        memory.resolve(TraceOutputRef(first.id))


def test_running_and_resumable_runs_are_protected():
    memory = TraceStore()
    run = memory.start_run("program", "commit", {}, at=START)
    event = memory.record(run, "observe", {}, 1, at=START)
    with pytest.raises(ContractError):
        memory.delete(event.id, at=START + timedelta(days=10))
    memory.finish_run(run, status="interrupted", at=START)
    memory.retain_run(run.id, "continuation")
    assert event.id in memory.retention_closure()


def test_mandatory_reviews_keep_original_age_and_pending_work():
    memory, _run, first, second = completed_memory()
    assert memory.review_batch(at=START + timedelta(days=6)) == ()
    batch = memory.review_batch(at=START + timedelta(days=7))
    assert {event.id for event in batch} == {first.id, second.id}
    memory.complete_review(first.id, at=START + timedelta(days=7))
    assert [event.id for event in memory.review_batch(at=START + timedelta(days=8))] == [second.id]
    memory.complete_review(second.id, at=START + timedelta(days=8))
    memory.request_review(first.id, "changed evidence", at=START + timedelta(days=9))
    memory.complete_review(first.id, at=START + timedelta(days=9))
    assert memory.review_batch(at=START + timedelta(days=29)) == ()
    assert len(memory.review_batch(at=START + timedelta(days=30))) == 2


def test_retrieval_grouping_constraints_and_snapshot():
    memory, _run, _first, second = completed_memory()
    later = memory.start_run("program", "abc123", {}, run_mode="replay", at=START)
    memory.record(later, "observe", {}, {"value": 3}, at=START)
    memory.finish_run(later, at=START)
    groups = memory.retrieve("observe")
    assert len(groups) == 1
    assert len(groups[0].events) == 2
    assert len(memory.retrieve(MemoryQuery(text="observe", run_mode="live"))[0].events) == 1
    memory.retain(TraceOutputRef(second.id), "dataset")
    restored = TraceStore.from_snapshot(json.loads(json.dumps(memory.snapshot())))
    assert restored.retention_closure() == memory.retention_closure()
    assert restored.resolve(TraceOutputRef(second.id, ("value",))) == 6
    assert restored.snapshot() == memory.snapshot()


def test_unknown_output_path_and_full_initial_retention_are_errors():
    memory, run, first, _second = completed_memory()
    with pytest.raises(ContractError):
        memory.resolve(TraceOutputRef(first.id, ("missing",)))
    with pytest.raises(ContractError, match="recent"):
        memory.compact(run.id, (), at=START + timedelta(days=1))
    with pytest.raises(ContractError):
        RetentionPolicy(memory_compaction_ladder=(timedelta(days=3), timedelta(days=2)))


def test_retrieval_accepts_json_query_and_preserves_marker_shaped_content():
    memory = TraceStore()
    run = memory.start_run("program", "commit", {})
    event = memory.record(run, "observe", output={"$datetime": "literal content"})
    memory.finish_run(run)
    restored = TraceStore.from_snapshot(json.loads(json.dumps(memory.snapshot())))
    assert restored.resolve(TraceOutputRef(event.id)) == {"$datetime": "literal content"}
    assert len(restored.retrieve({"text": "literal", "program": "program"})) == 1
