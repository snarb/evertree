from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evertree.core.actions import ActionGateway, ActionOption
from evertree.core.memory.store import TraceStore
from evertree.core.memory.types import MemoryQuery
from evertree.core.values import ContractError, json_value
from evertree.processes.memory_processing.experience_compaction._exec import (
    run as propose_compaction,
)
from evertree.processes.memory_processing.replay_selection._exec import (
    run as select_replay,
)

START = datetime(2025, 1, 1, tzinfo=UTC)


REVIEW = START + timedelta(days=10)


def completed_trace(outputs):
    memory = TraceStore()
    run = memory.start_run("equipment", "revision-1", {}, at=START)
    events = [memory.record(run, "observe", output=output, at=START) for output in outputs]
    memory.finish_run(run, at=START)
    return memory, run, events


def test_mem_01_critical_incident_and_decision_survive_compaction():
    """MEM-01: explicit retention protects the actual incident and its context."""
    memory = TraceStore()
    run = memory.start_run("equipment", "revision-1", {}, at=START)
    ordinary = memory.record(run, "observe", output={"temperature": 20}, at=START)
    reading = memory.record(run, "observe", output={"temperature": 120}, at=START)
    incident = memory.record(
        run,
        "stop_equipment",
        {"reading": memory.output_ref(reading), "limit": 100},
        {"stopped": True, "reason": "dangerous temperature"},
        at=START,
    )
    memory.finish_run(run, at=START)
    memory.retain(incident.id, "supervisor: preserve incident and inputs until investigation ends")
    with pytest.raises(ContractError, match="retention"):
        memory.compact(run.id, (), at=REVIEW)
    assert memory.compact(run.id, (reading.id, incident.id), at=REVIEW).events == (
        reading.id,
        incident.id,
    )
    assert memory.get_event(incident.id) == incident
    assert memory.resolve(memory.output_ref(reading, ("temperature",))) == 120
    assert memory.get_event(ordinary.id) == ordinary
    memory.validate()


def test_mem_02_recent_experience_cannot_be_compacted_or_deleted():
    """MEM-02: a proposal does not override the initial full retention period."""
    memory, run, (event,) = completed_trace([{"expected": True, "value": 42}])
    before = memory.snapshot()
    recent = START + memory.policy.initial_full_retention_period - timedelta(seconds=1)
    with pytest.raises(ContractError, match="recent"):
        memory.compact(run.id, (), at=recent)
    with pytest.raises(ContractError, match="initial full retention"):
        memory.delete(event.id, at=recent)
    assert memory.snapshot() == before


def test_mem_03_compaction_preserves_order_identity_and_separate_deletion():
    """MEM-03: accepted retention choice [E1,E3,E5] leaves raw E2/E4 addressable."""
    memory, run, events = completed_trace([{"value": value} for value in range(5)])
    retained = tuple(event.id for event in events[::2])
    assert memory.compact(run.id, tuple(reversed(retained)), at=REVIEW).events == retained
    assert memory.events == tuple(events)
    assert all(memory.get_event(event.id) == event for event in events)
    assert memory.finalize_deletions(at=REVIEW + timedelta(days=20)) == ()


def test_mem_04_nested_result_keeps_measurement_caller_and_revision():
    """MEM-04: the protected result retains the necessary nested call provenance."""
    memory = TraceStore()
    parent = memory.start_run("parent", "parent-revision", {}, at=START)
    reading = memory.record(parent, "measure", output={"value": 12}, at=START)
    unrelated = memory.record(parent, "diagnostic", output="unrelated", at=START)
    caller = memory.record(parent, "call", output={"program": "child"}, at=START)
    child = memory.start_run(
        "child",
        "child-revision",
        {"input": memory.output_ref(reading)},
        caller_event=caller,
        at=START,
    )
    result = memory.record(child, "double", output={"value": 24}, at=START)
    memory.finish_run(child, at=START)
    memory.finish_run(parent, at=START)
    memory.retain(result.id, "result needed for explanation")
    memory.compact(parent.id, (reading.id, caller.id), at=REVIEW)
    assert {event.id for event in memory.provenance_of(memory.output_ref(result))} == {
        reading.id,
        caller.id,
        result.id,
    }
    assert memory.get_run(child.id).base_commit_sha == "child-revision"
    assert memory.get_run(child.id).caller_event == caller.id
    assert memory.resolve(memory.output_ref(reading, ("value",))) == 12
    assert unrelated.id not in memory.retention_closure()


async def test_mem_05_compaction_proposal_preserves_frequency_metadata():
    """MEM-05 partial: proposal keeps supplied counts; no frequency reducer exists."""
    memory, _run, events = completed_trace(
        [{"outcome": "ordinary"}] * 99 + [{"outcome": "exception"}]
    )
    counts = {
        "unit": "source_event",
        "window": ["2025-01-01", "2025-01-02"],
        "total": 100,
        "ordinary": 99,
        "exception": 1,
    }
    ctx = SimpleNamespace(
        step=AsyncMock(
            return_value={
                "parsed": {
                    "summary": "99 ordinary events and one exception",
                    "keep_event_ids": [events[0].id, events[-1].id],
                    "lost_details": [],
                }
            }
        )
    )
    before = memory.snapshot()
    result = (await propose_compaction(ctx, [json_value(e) for e in events], counts))["result"]
    assert result["observation_counts"] == counts
    assert result["source_event_ids"] == [event.id for event in events]
    assert result["keep_event_ids"] == [events[0].id, events[-1].id]
    assert memory.snapshot() == before


async def test_mem_06_retrieval_and_replay_selection_do_not_duplicate_source_records():
    """MEM-06 partial: read/selection keep sources; no source-event counter API exists."""
    memory, _run, events = completed_trace(
        [
            {"message": "first report", "source_event": "incident-1"},
            {"message": "second report", "source_event": "incident-1"},
        ]
    )
    ctx = SimpleNamespace(
        step=AsyncMock(
            return_value={
                "parsed": {
                    "event_ids": [event.id for event in events],
                    "objective": "Review incident",
                    "reason": "Find cause",
                }
            }
        )
    )
    before = memory.snapshot()
    for _ in range(3):
        assert len(memory.retrieve("incident")) == 2
        result = await select_replay(ctx, [json_value(e) for e in events], "Review", {"steps": 1})
        assert result["result"]["event_ids"] == [event.id for event in events]
    assert memory.snapshot() == before


def test_mem_09_structural_guards_reject_deleting_a_protected_output():
    """MEM-09: the memory boundary, not an LLM verdict, prevents dangling provenance."""
    memory, run, (event,) = completed_trace([{"value": 12}])
    reference = memory.output_ref(event, ("value",))
    memory.retain(reference, "protected semantic result")
    before = memory.snapshot()
    with pytest.raises(ContractError, match="protected"):
        memory.delete(event.id, at=REVIEW)
    with pytest.raises(ContractError, match="retention"):
        memory.compact(run.id, (), at=REVIEW)
    assert memory.snapshot() == before
    assert memory.resolve(reference) == 12
    memory.validate()


def test_mem_09_snapshot_validation_rejects_missing_protected_trace_membership():
    """MEM-09: protected events must remain in SemanticTrace, even after restore."""
    memory, run, (event,) = completed_trace([{"value": 12}])
    memory.retain(event.id, "protected semantic result")
    malformed = memory.snapshot()
    malformed["traces"][str(run.id)] = []
    with pytest.raises(ContractError, match="retention"):
        TraceStore.from_snapshot(malformed)


def test_mem_10_new_replay_obligation_restores_event_in_original_position():
    """MEM-10: new retention cancels delete before finalization, preserving seq."""
    memory, run, events = completed_trace([{"value": i} for i in range(3)])
    middle = events[1]
    memory.compact(run.id, (events[0].id, events[2].id), at=REVIEW)
    memory.delete(middle.id, at=REVIEW)
    memory.retain(middle.id, "unfinished replay")
    assert memory.semantic_trace(run.id).events == tuple(event.id for event in events)
    assert memory.finalize_deletions(at=REVIEW + timedelta(days=10)) == ()
    assert memory.get_event(middle.id) == middle


@pytest.mark.parametrize("pending_deletion", [False, True])
def test_mem_10_new_obligation_restores_the_entire_required_dependency_closure(pending_deletion):
    """MEM-10/MEM-04: revival includes compacted/deleted upstream observations."""
    memory = TraceStore()
    run = memory.start_run("equipment", "revision-1", {}, at=START)
    source = memory.record(run, "read", output={"temperature": 120}, at=START)
    result = memory.record(
        run,
        "stop",
        {"source": memory.output_ref(source)},
        {"stopped": True},
        at=START,
    )
    memory.finish_run(run, at=START)
    memory.compact(run.id, (), at=REVIEW)
    if pending_deletion:
        memory.delete(source.id, at=REVIEW)
        memory.delete(result.id, at=REVIEW)
    memory.retain(result.id, "unfinished replay")
    assert memory.semantic_trace(run.id).events == (source.id, result.id)
    assert memory.snapshot()["deleted"] == {}
    assert memory.finalize_deletions(at=REVIEW + timedelta(days=10)) == ()


@pytest.mark.parametrize("reference_location", ["run_arguments", "event_arguments", "caller_event"])
def test_mem_10_new_running_work_restores_its_compacted_inputs(reference_location):
    """MEM-10/MEM-04: execution creates retention obligations for its actual inputs."""
    memory, source_run, (source,) = completed_trace([{"value": 12}])
    memory.compact(source_run.id, (), at=REVIEW)
    memory.delete(source.id, at=REVIEW)
    if reference_location == "run_arguments":
        memory.start_run("analysis", "revision-2", {"input": memory.output_ref(source)}, at=REVIEW)
    elif reference_location == "caller_event":
        memory.start_run("analysis", "revision-2", {}, caller_event=source, at=REVIEW)
    else:
        run = memory.start_run("analysis", "revision-2", {}, at=REVIEW)
        memory.record(run, "read", {"input": memory.output_ref(source)}, 12, at=REVIEW)
    assert memory.semantic_trace(source_run.id).events == (source.id,)
    assert memory.snapshot()["deleted"] == {}


def test_mem_10_resumption_obligation_restores_compacted_run_and_inputs():
    """MEM-10/MEM-04: retaining a finished run restores its required source trace."""
    memory, source_run, (source,) = completed_trace([{"value": 12}])
    resumed = memory.start_run(
        "analysis",
        "revision-2",
        {"input": memory.output_ref(source)},
        at=START,
    )
    result = memory.record(resumed, "read", output=12, at=START)
    memory.finish_run(resumed, status="interrupted", at=START)
    memory.compact(source_run.id, (), at=REVIEW)
    memory.compact(resumed.id, (), at=REVIEW)
    memory.delete(source.id, at=REVIEW)
    memory.delete(result.id, at=REVIEW)
    memory.retain_run(resumed.id, "task continuation")
    assert memory.semantic_trace(source_run.id).events == (source.id,)
    assert memory.semantic_trace(resumed.id).events == (result.id,)
    assert memory.snapshot()["deleted"] == {}
    memory.validate()


def test_mem_11_releasing_one_consumer_preserves_another_consumers_inputs():
    """MEM-11 partial: retention reasons compose; Dataset deletion wiring is absent."""
    memory, run, (event,) = completed_trace([{"input": 2, "outcome": 4}])
    memory.retain(event.id, "dataset:A")
    memory.retain(event.id, "dataset:B")
    memory.release(event.id, "dataset:A")
    with pytest.raises(ContractError, match="protected"):
        memory.delete(event.id, at=REVIEW)
    assert memory.semantic_trace(run.id).events == (event.id,)
    assert memory.resolve(memory.output_ref(event)) == {"input": 2, "outcome": 4}
    memory.release(event.id, "dataset:B")
    memory.delete(event.id, at=REVIEW)
    assert memory.finalize_deletions(at=REVIEW + timedelta(days=10)) == (event.id,)


def test_mem_12_retrieval_deduplicates_routes_without_merging_opposite_outcomes():
    """MEM-12: direct and lexical routes return each identity once, preserve contrasts."""
    memory, _run, events = completed_trace(
        [
            {"operation": "move", "outcome": "success"},
            {"operation": "move", "outcome": "failure"},
        ]
    )
    before = memory.snapshot()
    groups = memory.retrieve(
        MemoryQuery(text="move", references=(memory.output_ref(events[0]),)), 10
    )
    assert len(groups) == 2
    found = [event for group in groups for event in group.events]
    assert len(found) == 2
    assert {event.id for event in found} == {event.id for event in events}
    assert {event.output["outcome"] for event in found} == {"success", "failure"}
    assert memory.snapshot() == before


async def test_mem_14_replay_trace_preserves_original_and_cannot_execute_live_action():
    """MEM-14 partial: trace/action contracts; ReplayTask/Episode orchestration is absent."""
    adapter = SimpleNamespace(
        list_actions=AsyncMock(return_value=[ActionOption({"move": 1})]),
        execute=AsyncMock(return_value="accepted"),
    )
    gateway = ActionGateway()
    gateway.bind("session", adapter, task_id="task", commit="adapter-revision")
    await gateway.list("session", task_id="task")
    await gateway.take("session", {"move": 1}, task_id="task", operation_id="action", approved=True)
    memory, source_run, (source,) = completed_trace([{"action": "move", "outcome": "failure"}])
    replay = memory.start_run(
        "analyze",
        "analysis-revision",
        {"source": memory.output_ref(source)},
        run_mode="replay",
        at=REVIEW,
    )
    conclusion = memory.record(replay, "conclude", output={"needs_check": True}, at=REVIEW)
    memory.finish_run(replay, at=REVIEW)
    with pytest.raises(PermissionError, match="replay"):
        await gateway.take(
            "session",
            {"move": 1},
            task_id="task",
            operation_id="replay-action",
            run_mode="replay",
            approved=True,
        )
    assert adapter.execute.await_count == 1
    assert replay.id != source_run.id
    assert memory.get_run(replay.id).run_mode == "replay"
    assert source.id in {event.id for event in memory.provenance_of(memory.output_ref(conclusion))}
    assert memory.get_event(source.id) == source


def test_int_01_protected_file_loss_lesson_is_retrievable_after_compaction():
    """INT-01 partial: memory retains the lesson; automatic planning is not exercised."""
    memory = TraceStore()
    run = memory.start_run("file_edit", "revision-1", {}, at=START)
    incident = memory.record(run, "edit", output={"file": "report", "lost": True}, at=START)
    lesson = memory.record(
        run,
        "analyze",
        {"source": memory.output_ref(incident)},
        {"lesson": "Keep a backup before overwriting a file", "scope": "file writes"},
        at=START,
    )
    ordinary = memory.record(run, "diagnostic", output="routine detail", at=START)
    memory.finish_run(run, at=START)
    memory.retain(lesson.id, "prevent repeated file loss")
    memory.compact(run.id, (incident.id, lesson.id), at=REVIEW)
    groups = memory.retrieve("backup file", 10)
    assert lesson.id in {event.id for group in groups for event in group.events}
    assert incident.id in {event.id for event in memory.provenance_of(memory.output_ref(lesson))}
    assert ordinary.id not in memory.semantic_trace(run.id).events
