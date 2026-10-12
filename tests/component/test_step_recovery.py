"""Required integration survives interruption without inventing or repeating knowledge."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from evertree.core.provider import AgentEvent
from tests.support.application import (
    IntegrationScriptedProvider,
    budget_review,
    completed,
    decision,
    framing,
    is_integration_request,
    verification,
    wait_for_event,
)
from tests.support.component import component_app


def request_kind(request):
    if is_integration_request(request):
        return "integration"
    if request.mode == "exec":
        return "controller"
    data = json.loads(request.prompt)
    if "task_state" in data:
        return "budget_review"
    return "verification" if "answer" in data else "framing"


@pytest.mark.parametrize("failure", ["provider", "budget"])
async def test_pending_result_waits_for_required_integration_before_resume_continues(
    tmp_path, failure
):
    """Real task checkpoints retain a partial result when the provider or allowance fails."""

    class RecoverableProvider(IntegrationScriptedProvider):
        def __init__(self):
            super().__init__(
                [
                    framing(),
                    decision("First experiment narrowed the hypothesis", "continue"),
                    budget_review(minutes=6),
                    decision("Checked explanation"),
                    verification(),
                ]
            )
            self.stages = []
            self.injected = False

        async def run(self, request_id, request, **kwargs):
            kind = request_kind(request)
            self.stages.append(kind)
            if failure == "provider" and kind == "integration" and not self.injected:
                self.injected = True
                self.requests.append(request)
                raise RuntimeError("Temporary integration provider outage")
            async for event in super().run(request_id, request, **kwargs):
                if (
                    failure == "budget"
                    and kind == "controller"
                    and event.kind == "completed"
                    and not self.injected
                ):
                    self.injected = True
                    task = app.tasks.all()[0]
                    app.tasks.record_usage(
                        task.id,
                        "active_time_minutes",
                        task.remaining("active_time_minutes"),
                        operation_id="measured-first-iteration-cost",
                    )
                yield event

    provider = RecoverableProvider()
    async with component_app(tmp_path / "agent", provider=provider) as app:
        waiting = await app.run("Investigate the error")
        assert waiting["status"] == "waiting"
        await app._pump
        task = app.tasks.get(waiting["task_id"])
        assert task.waiting_for == ["knowledge_integration"]
        assert task.step_state["status"] == "result_ready"
        saved = deepcopy(task.step_state["pending_result"])
        packet = deepcopy(task.step_state["integration"])
        assert saved["disposition"] == "continue"
        assert task.last_step_ref is not None
        assert len([request for request in provider.requests if request.mode == "exec"]) == 1
        original_inputs = deepcopy(app._inputs[task.id])
        original_version = app._input_version(task)
        original_revision = task.specification.revision
        marker = len(provider.stages)

        await app.resume(task.id)
        answer, _ = await wait_for_event(app, "answer")
        assert answer.data["text"] == "Checked explanation"
        assert provider.stages[marker : marker + 3] == [
            "budget_review",
            "integration",
            "controller",
        ]
        controller = [request for request in provider.requests if request.mode == "exec"][1]
        controller_context = json.loads(controller.prompt)
        assert controller_context["last_step_result"] == saved
        assert (
            controller_context["state"]["step_state"]["last_integration_receipt"]["operation_id"]
            == packet["operation_id"]
        )
        assert app._inputs[task.id] == original_inputs
        assert app._input_version(task) == original_version
        assert task.specification.revision == original_revision
        await app.acknowledge_delivery(answer.data["delivery_id"])
        await wait_for_event(app, "task_completed")
        assert task.status == "succeeded"


async def test_resume_replays_committed_receipt_after_transport_loss_without_second_mutation(
    tmp_path, monkeypatch
):
    """Lose the completed Program reply; retry uses its committed receipt under a new run ID."""

    class MaterializingProvider(IntegrationScriptedProvider):
        def __init__(self):
            super().__init__(
                [framing(), decision("Checked explanation"), budget_review(), verification()]
            )
            self.materialization_requests = 0

        async def run(self, request_id, request, **kwargs):
            if not is_integration_request(request):
                async for event in super().run(request_id, request, **kwargs):
                    yield event
                return
            self.requests.append(request)
            self.materialization_requests += 1
            refs = [
                item["reference"] for item in json.loads(request.prompt)["material"]["experience"]
            ]
            proposal = {"creates": [{"id": -1, "name": "Retained explanation", "kind": "note"}]}
            choices = [
                {
                    "disposition": "materialize" if index == 0 else "trace_only",
                    "reason": "Preserve the explanation once",
                    "source_refs": [reference],
                    "affected_ids": [-1] if index == 0 else [],
                    "preservation_ids": [],
                }
                for index, reference in enumerate(refs)
            ]
            for event in completed(
                {
                    "action": "commit",
                    "query": "",
                    "summary": "Explanation saved",
                    "delta_json": json.dumps(proposal),
                    "decisions_json": json.dumps(choices),
                }
            ):
                yield event

    provider = MaterializingProvider()
    async with component_app(tmp_path / "agent", provider=provider) as app:
        run_program = app._run_program
        lost_reply = False
        integration_runs = []

        async def lose_committed_reply(task_id, identity, arguments, **kwargs):
            nonlocal lost_reply
            output = await run_program(task_id, identity, arguments, **kwargs)
            if identity == "knowledge_integration":
                integration_runs.append(output["run_id"])
                if not lost_reply:
                    lost_reply = True
                    assert output["result"]["complete"]
                    raise RuntimeError("Worker reply lost after semantic commit")
            return output

        monkeypatch.setattr(app, "_run_program", lose_committed_reply)
        waiting = await app.run("Explain and retain the observed failure")
        assert waiting["status"] == "waiting"
        await app._pump
        task = app.tasks.get(waiting["task_id"])
        packet_id = task.step_state["integration"]["operation_id"]
        saved_result = deepcopy(task.step_state["pending_result"])
        assert saved_result["disposition"] == "propose_completion"
        assert len([node for node in app.graph.nodes() if node.name == "Retained explanation"]) == 1
        graph_revision = app.graph.revision
        receipt_events = [
            event for event in app.memory.events if event.operator == "semantic_commit"
        ]
        assert len(receipt_events) == 1

        await app.resume(task.id)
        answer, _ = await wait_for_event(app, "answer")
        assert answer.data["text"] == "Checked explanation"
        assert len(integration_runs) == 2 and integration_runs[0] != integration_runs[1]
        assert provider.materialization_requests == 1
        assert len([request for request in provider.requests if request.mode == "exec"]) == 1
        assert app.graph.revision == graph_revision
        assert (
            len([event for event in app.memory.events if event.operator == "semantic_commit"]) == 1
        )
        assert task.step_state["last_integration_receipt"]["operation_id"] == packet_id
        await app.acknowledge_delivery(answer.data["delivery_id"])
        await wait_for_event(app, "task_completed")


async def test_interrupted_iteration_keeps_actual_tool_trace_without_fabricated_analysis(tmp_path):
    """A provider timeout preserves real partial events but produces no completed analytic Note."""

    class InterruptedProvider(IntegrationScriptedProvider):
        async def run(self, request_id, request, **kwargs):
            async for event in super().run(request_id, request, **kwargs):
                yield event
            if request.mode == "exec":
                raise TimeoutError("Iteration allowance reached")

    provider = InterruptedProvider(
        [
            framing(),
            [
                AgentEvent(
                    "tool_call", {"name": "graph.describe", "arguments": {"subject": "Self"}}
                ),
                AgentEvent("message", {"text": "Still comparing the observations"}),
            ],
        ]
    )
    async with component_app(tmp_path / "agent", provider=provider) as app:
        waiting = await app.run("Inspect available knowledge and investigate")
        assert waiting["status"] == "waiting"
        await app._pump
        task = app.tasks.get(waiting["task_id"])
        assert task.step_state["status"] == "interrupted"
        assert task.step_state["interruption_reason"] == "Iteration allowance reached"
        assert task.last_step_ref is None
        assert "pending_result" not in task.step_state
        assert not any(
            event.operator in {"analytical_note", "conscious_step_result"}
            for event in app.memory.events
        )
        assert any(
            event.operator == "provider_event" and event.output.get("kind") == "tool_result"
            for event in app.memory.events
        )
        assert any(
            run.program == "Consciousness" and run.status == "interrupted"
            for run in app.memory.runs
        )
        assert task.step_state["last_integration_receipt"]["complete"]
        assert provider.cancelled
