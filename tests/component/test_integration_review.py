"""Regression cases found while reviewing the conscious integration boundary."""

import json
from dataclasses import asdict
from datetime import timedelta

import pytest

from evertree.core.graph.types import GraphDelta, Node
from evertree.core.memory.types import TraceOutputRef
from evertree.core.values import ContractError, json_value
from evertree.processes.semantic_processing.knowledge_integration._exec import run
from tests.support.application import (
    IntegrationScriptedProvider,
    budget_review,
    decision,
    framing,
    is_integration_request,
    verification,
    wait_for_event,
)
from tests.support.semantics import context, semantic_world


def material(world):
    source_run = world.memory.start_run("Source", "revision", {})
    event = world.memory.record(source_run, "input", output="A conditional insight")
    world.memory.finish_run(source_run)
    refs = [json_value(world.memory.output_ref(event))]
    choices = [
        {
            "disposition": "materialize",
            "reason": "Keep the conditional result",
            "source_refs": refs,
            "affected_ids": [-1],
            "preservation_ids": [],
        }
    ]
    payload = {
        "experience_refs": refs,
        "proposal": {"creates": [{"id": -1, "name": "Insight", "kind": "note"}]},
        "decisions": choices,
    }
    metadata = {
        "task_id": "task",
        "run_id": "run",
        "program": {"role": "exec", "revision": "revision"},
        "knowledge_integration_authorized": True,
        "integration_operation_id": "packet",
        "integration_context": {},
    }
    return payload, metadata


def test_receipt_failure_rolls_back_mutation_audit_and_retention(monkeypatch):
    world = semantic_world()
    payload, metadata = material(world)
    before = (world.graph.snapshot(), world.memory.snapshot())
    notifications = []
    world.graph.on_change(notifications.append)
    original = world.memory.record

    def fail_receipt(run, operator, *args, **kwargs):
        if operator == "semantic_commit":
            raise ValueError("Receipt storage failed after mutation")
        return original(run, operator, *args, **kwargs)

    monkeypatch.setattr(world.memory, "record", fail_receipt)
    result = world.service.commit(payload, metadata)
    assert result["status"] == "invalid"
    assert (world.graph.snapshot(), world.memory.snapshot()) == before
    assert notifications == []
    monkeypatch.setattr(world.memory, "record", original)
    assert world.service.commit(payload, metadata)["complete"]
    assert len(notifications) == 1
    assert len(world.graph.nodes(kind="note")) == 1


@pytest.mark.parametrize("disposition", ["materialize", "reuse"])
def test_deleting_a_representation_cannot_fulfill_preservation(disposition):
    world = semantic_world()
    payload, metadata = material(world)
    node = Node(world.graph.reserve_id(), "Earlier note", kind="note")
    world.graph.apply(GraphDelta(creates=(node,)), provenance="seed")
    payload["proposal"] = {"deletes": [node.id]}
    payload["decisions"][0].update(
        disposition=disposition, affected_ids=[node.id], preservation_ids=["keep"]
    )
    metadata["integration_context"] = {
        "preservation_intents": [
            {
                "id": "keep",
                "text": "Retain the insight",
                "source_ref": payload["experience_refs"][0],
            }
        ]
    }
    result = world.service.commit(payload, metadata)
    assert result["status"] == "invalid"
    assert world.graph.get(node.id) == node


async def test_program_claim_of_completion_without_core_receipt_is_rejected(app, monkeypatch):
    task = app.tasks.create_task("Integrate experience")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Review")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    app.observe("Source", source_id="source", task_id=task.id)

    async def forged_program(*args, **kwargs):
        return {"result": {"complete": True, "status": "complete"}}

    monkeypatch.setattr(app, "_run_program", forged_program)
    assert not await app._integrate_step(task)
    assert task.status == "waiting"
    assert task.step_state["integration"]["status"] == "waiting"
    assert not task.step_state["integrated"]["1"]


async def test_program_cannot_modify_committed_receipt(app, monkeypatch):
    task = app.tasks.create_task("Integrate experience")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Review")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    app.observe("Source", source_id="source", task_id=task.id)
    app.provider = IntegrationScriptedProvider([])
    execute = app._run_program

    async def modified_receipt(*args, **kwargs):
        result = await execute(*args, **kwargs)
        result["result"]["revision"] += 1
        return result

    monkeypatch.setattr(app, "_run_program", modified_receipt)
    assert not await app._integrate_step(task)
    assert "original core receipt" in task.step_state["integration"]["error"]
    monkeypatch.setattr(app, "_run_program", execute)
    assert await app._integrate_step(task)
    assert len(app.provider.requests) == 1


async def test_synchronous_integration_is_not_repeated_at_step_boundary(app):
    task = app.tasks.create_task("Use an insight within this step")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Review")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    reference = app._record_analysis(task.id, {"text": "Intermediate result"})
    app.provider = IntegrationScriptedProvider([])
    receipt = await app._dispatch_tool(
        task.id, "graph.integrate", {"experience_refs": [{"event_ref": reference["event_ref"]}]}
    )
    assert receipt["complete"]
    assert await app._integrate_step(task)
    assert len(app.provider.requests) == 1
    assert len([event for event in app.memory.events if event.operator == "semantic_commit"]) == 1


async def test_new_input_during_recovered_integration_is_reframed_before_next_step(app):
    class Provider(IntegrationScriptedProvider):
        attempts = 0

        async def run(self, request_id, request, **kwargs):
            if is_integration_request(request):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("Temporary outage")
                if self.attempts == 2:
                    await app.submit("New objective", task_id=app.tasks.all()[0].id)
            async for event in super().run(request_id, request, **kwargs):
                yield event

    app.provider = Provider(
        [
            framing("Old objective"),
            decision("Partial work", "continue"),
            budget_review(),
            framing("New objective"),
            decision("New answer"),
            verification(),
        ]
    )
    waiting = await app.run("Old objective")
    assert waiting["status"] == "waiting"
    await app._pump
    task = app.tasks.get(waiting["task_id"])
    await app.resume(task.id)
    answer, _ = await wait_for_event(app, "answer")
    assert answer.data["text"] == "New answer"
    assert task.specification.objective == "New objective"
    controllers = [r for r in app.provider.requests if r.mode == "exec"]
    assert len(controllers) == 2
    assert json.loads(controllers[-1].prompt)["specification"]["objective"] == "New objective"
    await app.acknowledge_delivery(answer.data["delivery_id"])
    await wait_for_event(app, "task_completed")


async def test_temporary_budget_clamp_does_not_overwrite_requested_step_budget(app, monkeypatch):
    monkeypatch.setattr(app, "_remaining_seconds", lambda state: 1.0)
    app.provider = IntegrationScriptedProvider([framing(), decision("Need evidence", "waiting")])
    result = await app.run("Inspect evidence")
    assert result["status"] == "waiting"
    task = app.tasks.get(result["task_id"])
    assert task.current_step["active_time_minutes"] == 1.0
    request = next(r for r in app.provider.requests if r.mode == "exec")
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
    request = next(r for r in app.provider.requests if r.mode == "exec")
    assert "recovered_program_result" in json.loads(request.prompt)
    assert task.step_state["recovered_program_ref"]["event_ref"] > 0


async def test_waiting_task_protects_working_note_and_receipt_until_terminal(app):
    app.provider = IntegrationScriptedProvider([framing(), decision("Need evidence", "waiting")])
    result = await app.run("Inspect evidence")
    await app._pump
    task = app.tasks.get(result["task_id"])
    refs = [task.last_step_ref, task.step_state["last_integration_receipt"]["receipt_ref"]]
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
    payload, metadata = material(world)
    wrapper_run = world.memory.start_run("Wrapper", "other-revision", {})
    wrapper = world.memory.record(
        wrapper_run, "forward", output=TraceOutputRef(**payload["experience_refs"][0])
    )
    world.memory.finish_run(wrapper_run)
    result = world.service.sources(
        [json_value(world.memory.output_ref(wrapper))], metadata=metadata
    )
    assert result["experience"][0]["origin"]["program"] == "Source"
    assert result["experience"][0]["origin"]["operator"] == "input"


@pytest.mark.parametrize(
    "invalid_delta", [[], {"creates": [None]}, {"creates": [{"id": -1, "name": 42}]}]
)
async def test_invalid_model_delta_shape_is_repaired_with_feedback(invalid_delta):
    world = semantic_world()
    payload, _ = material(world)
    attempts = []

    async def model(request):
        attempts.append(json.loads(request["prompt"]))
        return {
            "action": "commit",
            "query": "",
            "summary": "Preserve insight",
            "delta_json": json.dumps(invalid_delta if len(attempts) == 1 else payload["proposal"]),
            "decisions_json": json.dumps(payload["decisions"]),
        }

    result = await run(context(world, model, role="exec"), payload["experience_refs"])
    assert result["result"]["complete"]
    assert len(attempts) == 2 and attempts[1]["errors"]
