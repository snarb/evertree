"""Integration remains bounded, recoverable and independent of conscious completion."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest

from evertree.core.provider import LLMEvent
from tests.support.application import (
    IntegrationScriptedProvider,
    decision,
    framing,
    is_integration_request,
    tool_events,
    verification,
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


async def test_integration_failure_records_gap_without_retrying_or_blocking_answer(tmp_path):
    """A provider failure does not send integration bookkeeping back to consciousness."""

    class FailingProvider(IntegrationScriptedProvider):
        injected = False

        async def run(self, request_id, request, **kwargs):
            if is_integration_request(request) and not self.injected:
                self.injected = True
                self.requests.append(request)
                self.failed_refs = [
                    item["reference"]
                    for item in json.loads(request.prompt)["material"]["experience"]
                ]
                raise RuntimeError("Temporary integration provider outage")
            async for event in super().run(request_id, request, **kwargs):
                yield event

    provider = FailingProvider(
        [
            framing(),
            decision("First experiment", "continue"),
            decision("Checked explanation"),
            verification(),
        ]
    )
    async with component_app(tmp_path / "agent", provider=provider) as app:
        result = await app.run("Investigate the error")
        assert result["status"] == "succeeded"
        task = app.tasks.get(result["task_id"])
        assert not task.step_state.get("integration")
        assert all(ref not in task.step_state["integrated"]["2"] for ref in provider.failed_refs)
        assert all(
            ref in task.step_state["integration_failed"]["2"] for ref in provider.failed_refs
        )
        diagnostics = [
            event for event in app.memory.events if event.operator == "integration_error"
        ]
        assert len(diagnostics) == 1
        assert "Temporary integration provider outage" in diagnostics[0].output["error"]
        controller = [request for request in provider.task_requests if request.mode == "exec"][1]
        context = json.loads(controller.prompt)
        assert "integration" not in context
        assert "Temporary integration provider outage" not in controller.prompt
        attempted = [
            item["reference"]
            for request in provider.requests
            if is_integration_request(request)
            for item in json.loads(request.prompt)["material"]["experience"]
        ]
        assert all(attempted.count(ref) == 1 for ref in provider.failed_refs)


async def test_exhausted_budget_leaves_packet_pending_without_an_integration_wait_state(app):
    task = app.tasks.create_task("Review observations when allowance permits")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Review")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    source = app._record_analysis(task.id, {"text": "Important, but not a completion gate"})
    app.tasks.record_usage(task.id, "active_time_minutes", 1, operation_id="exhaust")
    await app._integrate_step(task)
    assert task.step_state["integration"]["experience_refs"] == [source]
    assert task.step_state["integration"]["status"] == "pending"
    assert task.waiting_for != ["knowledge_integration"]
    assert not app.provider.requests


async def test_successful_write_survives_lost_program_reply_without_blocking_answer(
    tmp_path, monkeypatch
):
    """The graph operation is durable even if the enclosing integration invocation fails."""

    class MaterializingProvider(IntegrationScriptedProvider):
        async def run(self, request_id, request, **kwargs):
            if not is_integration_request(request):
                async for event in super().run(request_id, request, **kwargs):
                    yield event
                return
            self.requests.append(request)
            experience = json.loads(request.prompt)["material"]["experience"]
            explanation = next(
                item["reference"] for item in experience if item["source_kind"] == "analytical_note"
            )
            calls = [
                (
                    "save_note",
                    {"name": "Retained explanation", "source": explanation, "sources": []},
                )
            ]
            async for event in tool_events(request_id, request, kwargs["tool_handler"], calls):
                yield event

    provider = MaterializingProvider([framing(), decision("Checked explanation"), verification()])
    async with component_app(tmp_path / "agent", provider=provider) as app:
        run_program = app._run_program

        async def lose_reply(task_id, identity, arguments, **kwargs):
            output = await run_program(task_id, identity, arguments, **kwargs)
            if identity == "knowledge_integration":
                assert output["result"]["writes"]
                raise RuntimeError("Worker reply lost after graph write")
            return output

        monkeypatch.setattr(app, "_run_program", lose_reply)
        result = await app.run("Explain and retain the observed failure")
        assert result["status"] == "succeeded"
        note = app.graph.find("Retained explanation")
        assert note.description == "Current result: Checked explanation"
        assert len(app.graph.changes_of(note.id)) == 1
        assert (
            len([request for request in provider.requests if is_integration_request(request)]) == 1
        )
        assert (
            len([event for event in app.memory.events if event.operator == "integration_error"])
            == 1
        )


async def test_cancelled_integration_keeps_the_packet_for_resume(app, monkeypatch):
    task = app.tasks.create_task("Continue interrupted integration")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Review")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    source = app._record_analysis(task.id, {"text": "A useful observation"})
    original = app._run_program

    async def interrupt(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(app, "_run_program", interrupt)
    with pytest.raises(asyncio.CancelledError):
        await app._integrate_step(task)
    packet = deepcopy(task.step_state["integration"])
    assert packet["status"] == "interrupted"
    assert packet["experience_refs"] == [source]
    monkeypatch.setattr(app, "_run_program", original)
    await app._integrate_step(task)
    assert source in task.step_state["integrated"][str(task.specification.revision)]
    assert not task.step_state.get("integration")


async def test_interrupted_iteration_keeps_actual_tool_trace_without_fabricated_analysis(tmp_path):
    """A provider timeout preserves real partial events but produces no completed analytic Note."""

    class InterruptedProvider(IntegrationScriptedProvider):
        async def run(self, request_id, request, **kwargs):
            async for event in super().run(request_id, request, **kwargs):
                yield event
            if request.mode == "exec" and not is_integration_request(request):
                raise TimeoutError("Iteration allowance reached")

    provider = InterruptedProvider(
        [
            framing(),
            [
                LLMEvent("tool_call", {"name": "graph.describe", "arguments": {"subject": "Self"}}),
                LLMEvent("message", {"text": "Still comparing the observations"}),
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
        assert task.step_state["integrated"]
        assert "last_integration_receipt" not in task.step_state
        assert provider.cancelled


async def test_explicit_retry_resumes_failed_and_pending_sections_without_replaying_completed(app):
    class Provider(IntegrationScriptedProvider):
        failed = False

        async def run(self, request_id, request, **kwargs):
            if is_integration_request(request):
                self.requests.append(request)
                count = len(self.requests)
                if count == 2 and not self.failed:
                    self.failed = True
                    raise RuntimeError("Transient section failure")
                async for event in tool_events(request_id, request, kwargs["tool_handler"], []):
                    yield event
                return
            async for event in super().run(request_id, request, **kwargs):
                yield event

    task = app.tasks.create_task("Review full retained source")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 5}, 0, reason="Review")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    ref = app._record_analysis(task.id, {"text": "First independently useful fact.\n\n" * 500})
    app.provider = Provider([])
    args = {"experience_refs": [ref]}
    first = (await app._run_integration(task.id, args))["result"]["processing"]
    assert len(first["completed"]) == 1 and first["pending"] and first["failed"]
    prefix = app.provider.requests[0].prompt
    second = (await app._run_integration(task.id, args))["result"]["processing"]
    assert second["status"] == "processed"
    assert sum(request.prompt == prefix for request in app.provider.requests) == 1
    assert ref in task.step_state["integrated"][str(task.specification.revision)]


async def test_finalization_drains_all_sections_and_budget_stop_retains_real_tail(app):
    task = app.tasks.create_task("Process all source sections")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 5}, 0, reason="Review")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    ref = app._record_analysis(task.id, {"text": "Another independently useful fact.\n\n" * 1800})
    app.provider = IntegrationScriptedProvider([])
    await app._drain_integration(task)
    fragments = task.step_state["fragments"][json.dumps(ref, sort_keys=True)]
    assert len(fragments) > 8
    assert all(
        item in task.step_state["integrated"][str(task.specification.revision)]
        for item in fragments
    )
    assert not task.step_state.get("integration")

    pending = app._record_analysis(task.id, {"text": "New unprocessed source"})
    app.tasks.record_usage(task.id, "active_time_minutes", 5, operation_id="limit")
    await app._drain_integration(task)
    from evertree.core.evaluation.acceptance import VerificationResult

    await app._stop_task(task, "succeeded", "Answer delivered", VerificationResult("verified"))
    assert pending["event_ref"] in app.memory.retention_closure()
    assert pending not in task.step_state["integrated"][str(task.specification.revision)]


async def test_retry_after_norm_refresh_failure_reuses_processed_sections(app, monkeypatch):
    from evertree.core.semantics import api as semantics

    task = app.tasks.create_task("Retain processed source after norm refresh failure")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 5}, 0, reason="Review")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    ref = app._record_analysis(task.id, {"text": "An independently useful fact."})
    original = semantics.refresh_property_norms

    async def fail(ctx):
        raise RuntimeError("Temporary norm refresh failure")

    monkeypatch.setattr(semantics, "refresh_property_norms", fail)
    args = {"experience_refs": [ref]}
    with pytest.raises(RuntimeError, match="Temporary norm refresh failure"):
        await app._run_integration(task.id, args)
    assert len(app.provider.requests) == 1
    # Component transport does not emit the real worker's run_failed lifecycle event.
    pending_run = app._pending_programs[task.id]["run_id"]
    app.memory.finish_run(app._run_map[pending_run], status="failed")
    monkeypatch.setattr(semantics, "refresh_property_norms", original)
    result = await app._run_integration(task.id, args)
    assert result["result"]["processing"]["status"] == "processed"
    assert len(app.provider.requests) == 1
