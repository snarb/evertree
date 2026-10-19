"""Regression cases found while reviewing the conscious integration boundary."""

import json
from dataclasses import asdict, replace
from datetime import timedelta

import pytest

from evertree.core.graph.types import GraphDelta
from evertree.core.memory.types import TraceOutputRef
from evertree.core.values import ContractError, json_value
from evertree.processes.semantic_processing.knowledge_integration._exec import (
    _material_for_model,
    run,
)
from tests.support.application import (
    IntegrationScriptedProvider,
    decision,
    framing,
    verification,
)
from tests.support.semantics import context, recorded_experience, semantic_world, write_action


def test_result_recording_failure_rolls_back_only_its_operation(monkeypatch):
    world = semantic_world()
    refs, metadata = recorded_experience(world, "Initial observation", "Correction")
    first = write_action(
        world,
        refs,
        metadata,
        {"action": "save_note", "name": "Insight", "source": refs[0], "sources": []},
    )
    assert "error" not in first, first
    before = (world.graph.snapshot(), world.memory.snapshot())
    original = world.memory.record

    def fail_result(run, operator, *args, **kwargs):
        if operator == "semantic_write":
            raise ValueError("Result storage failed after mutation")
        return original(run, operator, *args, **kwargs)

    action = {
        "action": "update",
        "object": first["object"],
        "changes": {"description": "Corrected"},
        "sources": refs[1:],
    }
    monkeypatch.setattr(world.memory, "record", fail_result)
    result = write_action(world, refs, metadata, action, key="correction")
    assert result["error"]
    assert (world.graph.snapshot(), world.memory.snapshot()) == before
    monkeypatch.setattr(world.memory, "record", original)
    result = write_action(world, refs, metadata, action, key="correction")
    assert result["object"] == first["object"]
    assert world.graph.get(first["object"]).description == "Corrected"


async def test_normal_integration_completion_needs_no_core_receipt(app, monkeypatch):
    task = app.tasks.create_task("Integrate experience")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Review")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    app.observe("Source", source_id="source", task_id=task.id)
    calls = []

    async def completed_program(task_id, identity, arguments):
        calls.append((identity, arguments))
        return {"result": {"writes": []}, "feedback": None}

    monkeypatch.setattr(app, "_run_program", completed_program)
    await app._integrate_step(task)
    await app._integrate_step(task)
    # Evidence assessment follows the integrated packet with the same experience.
    assert [identity for identity, _ in calls] == ["knowledge_integration", "evidence_assessment"]
    assert calls[1][1]["experience_refs"] == calls[0][1]["experience_refs"]
    assert task.status != "waiting"
    assert "last_integration_receipt" not in task.step_state


async def test_failed_integration_is_not_retried_at_every_step(app, monkeypatch):
    task = app.tasks.create_task("Integrate experience")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Review")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    app.observe("Source", source_id="source", task_id=task.id)
    calls = []

    async def failed_program(task_id, identity, arguments):
        calls.append(identity)
        raise RuntimeError("Temporary outage")

    monkeypatch.setattr(app, "_run_program", failed_program)
    await app._integrate_step(task)
    await app._integrate_step(task)
    assert calls.count("knowledge_integration") == 1
    assert task.status != "waiting"
    diagnostics = {run.program for run in app.memory.runs if run.status == "failed"}
    assert {"KnowledgeIntegrationDiagnostic", "EvidenceAssessmentDiagnostic"} <= diagnostics
    app.observe("New insight", source_id="follow-up", task_id=task.id)
    await app._integrate_step(task)
    assert calls.count("knowledge_integration") == 2


async def test_temporary_budget_clamp_does_not_overwrite_requested_step_budget(app, monkeypatch):
    monkeypatch.setattr(app, "_remaining_seconds", lambda state: 1.0)
    app.provider = IntegrationScriptedProvider([framing(), decision("Need evidence", "waiting")])
    result = await app.run("Inspect evidence")
    assert result["status"] == "waiting"
    task = app.tasks.get(result["task_id"])
    assert task.current_step["active_time_minutes"] == 1.0
    request = next(r for r in app.provider.task_requests if r.mode == "exec")
    assert request.timeout_seconds == 1.0
    assert json.loads(request.prompt)["state"]["current_step"]["active_time_minutes"] == 1 / 60


async def test_recovered_program_result_stays_in_working_context_not_user_history(app):
    task = app.tasks.create_task("Recover delegated work")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 3}, 0, reason="Resume")
    app._pending_programs[task.id] = {
        "identity": "memory_retrieval",
        "arguments": {"query": "No matching memories"},
        "run_id": "recovered-program",
        "spec": asdict(app._program("memory_retrieval")),
    }
    app.provider = IntegrationScriptedProvider([framing(), decision(), verification()])
    result = await app.run("Continue delegated work", task_id=task.id)
    assert result["status"] == "succeeded"
    assert all(item["role"] == "user" for item in app._inputs[task.id])
    request = next(r for r in app.provider.task_requests if r.mode == "exec")
    assert "recovered_program_result" in json.loads(request.prompt)
    assert task.step_state["recovered_program_ref"]["event_ref"] > 0


async def test_waiting_task_protects_working_note_until_terminal(app):
    app.provider = IntegrationScriptedProvider([framing(), decision("Need evidence", "waiting")])
    result = await app.run("Inspect evidence")
    await app._pump
    task = app.tasks.get(result["task_id"])
    refs = [task.last_step_ref]
    for ref in refs:
        event = app.memory.get_event(ref["event_ref"])
        with pytest.raises(ContractError, match="protected"):
            app.memory.delete(event.id, at=event.occurred_at + timedelta(days=90))
    await app.cancel(task.id)
    for ref in refs:
        assert "task:" + task.id not in app.memory._protections.get(ref["event_ref"], set())


def test_analytical_results_of_integrators_children_do_not_feed_automatic_integration(app):
    task = app.tasks.create_task("Integrate observations")
    parent = app.memory.start_run(
        app._program("knowledge_integration").program_id,
        app._program_revision(),
        {"task_id": task.id},
    )
    caller = app.memory.record(parent, "call_program", output="Inspect integration candidates")
    reflection = app._program("reflection")
    child = app.memory.start_run(
        reflection.program_id, reflection.revision, {}, caller_event=caller
    )
    ref = app._record_analysis(
        task.id,
        {"text": "Internal integration preparation"},
        producer=reflection.program_id,
        owner_run=child.id,
    )
    app.memory.finish_run(child)
    app.memory.finish_run(parent)
    assert TraceOutputRef(**ref) not in app._experience_refs(task)
    actual = app._record_analysis(task.id, {"text": "Actual task insight"})
    assert TraceOutputRef(**actual) in app._experience_refs(task)


def test_program_argument_cannot_assign_its_result_to_another_task(app):
    task = app.tasks.create_task("Unrelated task")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    version = app._input_version(task)
    run = app.memory.start_run(
        app._program("reflection").program_id, app._program_revision(), {"task_id": task.id}
    )
    event = app.memory.record(run, "observation", output="Untrusted Program assertion")
    app.memory.finish_run(run)
    assert app.memory.output_ref(event) not in app._experience_refs(task)
    assert app._input_version(task) == version


def test_integration_exposes_original_producer_of_a_forwarded_reference():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "A conditional insight")
    wrapper_run = world.memory.start_run("Wrapper", "other-revision", {})
    wrapper = world.memory.record(wrapper_run, "forward", output=TraceOutputRef(**refs[0]))
    world.memory.finish_run(wrapper_run)
    result = world.service.sources(
        [json_value(world.memory.output_ref(wrapper))], metadata=metadata
    )
    assert result["experience"][0]["origin"]["program"] == "experience"
    assert result["experience"][0]["origin"]["operator"] == "input"


@pytest.mark.parametrize("arguments", [None, [], {"name": 42}])
async def test_invalid_native_tool_arguments_are_repaired_with_feedback(arguments):
    world = semantic_world()
    refs, _ = recorded_experience(world, "A conditional insight")

    async def model(request, call):
        invalid = await call("create_concept", arguments)
        assert invalid["error"]
        await call("save_note", {"name": "Insight", "source": refs[0], "sources": refs})

    result = await run(context(world, model, role="exec"), refs)
    assert len(result["result"]["writes"]) == 1
    assert (
        world.graph.get(result["result"]["writes"][0]["object"]).description
        == "A conditional insight"
    )


def test_integration_context_excludes_values_and_self_knowledge(app):
    graph = app.graph
    fact = replace(
        graph.new_fact(
            "PART_WHOLE",
            {
                "part": graph.find("SelfModel").id,
                "whole": graph.find("Self").id,
            },
        ),
        properties={"conditions": {"scope": "current task"}, "status": "hypothesis"},
    )
    graph.apply(GraphDelta(creates=(fact,)), provenance="test observation")
    task = app.tasks.create_task("Examine the agent's current model")
    context = app._integration_context(task)
    assert set(context) == {"task"}
    assert context["task"]["specification"] == task.specification.to_dict()
    model_context = _material_for_model(
        {
            "context": context,
            "experience": [],
        }
    )["context"]
    assert model_context == {"task": {"objective": task.objective}}
