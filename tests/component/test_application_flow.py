import asyncio
import json

import pytest

from evertree.core.provider import AgentEvent, AgentRequest, ScriptedProvider
from tests.support.application import decision, framing, verification


async def until(stream, kind):
    async with asyncio.timeout(30):
        async for event in stream:
            if event.kind == kind:
                return event
            if event.kind in {"task_failed", "task_cancelled"}:
                pytest.fail(str(event.data))
    raise AssertionError("Event stream ended early")


async def test_run_does_not_leave_an_unconsumed_copy_of_streaming_events(app):
    """Streaming subscribers must not leave duplicate in-memory event queues after delivery."""
    streamed = [AgentEvent("message", {"text": str(number)}) for number in range(100)]
    app.provider = ScriptedProvider(
        [
            framing(),
            [*streamed, *decision()],
            verification(),
            framing(),
            [*streamed, *decision()],
            verification(),
        ]
    )
    for _ in range(2):
        result = await app.run("Count r in strawberry")
        assert result["status"] == "succeeded"
        assert len(app._subscribers) == 0
    assert not hasattr(app, "_events")
    assert not hasattr(app, "_task_events")
    assert (
        sum(
            event.operator == "provider_event" and event.output["kind"] == "message"
            for event in app.memory.events
        )
        == 200
    )


async def test_subscribers_receive_independent_delivery_and_close_without_leaks(app):
    """Two subscribers observe the same delivery; acknowledgement finishes the real Task."""
    app.provider = ScriptedProvider([framing(), decision(), verification()])
    async with app.events() as first, app.events() as second:
        task = await app.submit("Count r in strawberry")
        answer = await until(first, "answer")
        mirror = await until(second, "answer")
        assert answer == mirror
        assert task.status == "running"
        await app.acknowledge_delivery(answer.data["delivery_id"])
        assert (await until(first, "task_completed")).task_id == task.id
        assert (await until(second, "task_completed")).task_id == task.id
        assert len(app._subscribers) == 2
    assert len(app._subscribers) == 0


async def test_late_subscription_receives_pending_answer_but_no_old_progress(app):
    """Pending delivery is replayed to a late subscriber without replaying progress."""
    app.provider = ScriptedProvider([framing(), decision(), verification()])
    task = await app.submit("Count r in strawberry")
    async with asyncio.timeout(30):
        while not app._delivery:
            await asyncio.sleep(0.01)
    assert task.status == "running"
    assert not app._subscribers
    async with app.events() as stream:
        first = await anext(stream)
        assert first.kind == "answer"
        assert first.data["text"] == "3"
        await app.acknowledge_delivery(first.data["delivery_id"])
        await until(stream, "task_completed")
    assert task.status == "succeeded"


async def test_cancelled_event_consumer_releases_subscription(app):
    """Cancelling a consumer releases its subscription without starting an agent process."""
    stream = app.events()
    waiter = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not app._subscribers


async def test_controller_uses_self_contained_context_without_resuming_session(app):
    """Controller prompts include retained tool evidence without reusing SDK session history."""
    node = app.graph.find("Self")
    app.provider = ScriptedProvider(
        [
            framing(),
            [
                AgentEvent("tool_call", {"name": "read_graph", "arguments": {"id": node.id}}),
                *decision("Continue from the retained result", "continue"),
            ],
            decision(),
            verification(),
        ]
    )
    result = await app.run("Count r in strawberry")
    assert result["status"] == "succeeded"
    controllers = [request for request in app.provider.requests if request.mode == "exec"]
    assert len(controllers) == 2
    assert all(request.session is None for request in app.provider.requests)
    context = json.loads(controllers[1].prompt)
    assert any(
        event["output"].get("kind") == "tool_result"
        for event in context["recent_results"]
        if isinstance(event["output"], dict)
    )
    assert "Count r in strawberry" in controllers[1].prompt
    assert app._sessions[result["task_id"]]["provider"] == "scripted"  # Audit only.


async def test_initial_framing_assigns_only_the_models_budget_and_honors_hard_guard(app):
    """Call the real framing Program directly to verify budget assignment and hard limits."""
    inspected = []

    class InspectingProvider(ScriptedProvider):
        async def run(self, request_id, request, **kwargs):
            if not self.requests:
                task = app.tasks.all()[0]
                inspected.append(
                    (task.execution_budget, list(task.budget_history), request.timeout_seconds)
                )
            async for event in super().run(request_id, request, **kwargs):
                yield event

    app.provider = InspectingProvider([framing(minutes=0.15), decision(), verification()])
    result = await app.run("Count r in strawberry", hard_limits={"active_time_minutes": 0.2})
    assert result["status"] == "succeeded"
    task = app.tasks.get(result["task_id"])
    assert inspected[0][:2] == (None, [])
    assert 0 < inspected[0][2] <= 12
    assert len(task.budget_history) == 1
    assert task.execution_budget.resources["active_time_minutes"] == 0.15
    assert len(app.provider.requests) == 3


async def test_explicit_reassessment_uses_resource_control_and_preserves_spending(app):
    """Real ResourceControl revises a budget while accumulated usage remains intact."""
    app.provider = ScriptedProvider(
        [
            framing(minutes=3),
            decision("Which input?", "waiting"),
            framing(minutes=4),
            decision(),
            verification(),
        ]
    )
    initial = await app.run("Count a requested letter")
    task = app.tasks.get(initial["task_id"])
    spent = task.spent["active_time_minutes"]
    async with app.events() as stream:
        await app.resume(task.id, "r in strawberry")
        answer = await until(stream, "answer")
        await app.acknowledge_delivery(answer.data["delivery_id"])
        await until(stream, "task_completed")
    assert len(task.budget_history) == 2
    assert task.execution_budget.resources["active_time_minutes"] == 4
    assert task.spent["active_time_minutes"] >= spent
    resource_control = app.graph.find("ResourceControl.exec")
    assert any(run.program == resource_control.id for run in app.memory.runs)
    assert "task_state" in json.loads(app.provider.requests[2].prompt)


async def test_exhausted_hard_limit_does_not_run_initial_framing(app):
    """A prepared exhausted Task must not request model framing."""
    task = app.tasks.create_task("No remaining allowance", hard_limits={"active_time_minutes": 1})
    app.tasks.record_usage(task.id, "active_time_minutes", 1, operation_id="previous")
    result = await app.run("Continue", task_id=task.id)
    assert result["status"] == "waiting"
    assert task.execution_budget is None
    assert task.budget_history == []
    assert app.provider.requests == []


async def test_budget_review_cannot_reexecute_a_pending_nonpolicy_program(app):
    """A prepared pending Program blocks incompatible budget-policy execution."""
    task = app.tasks.create_task("Review the budget")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Initial decision")
    task.review_required = True
    app._inputs[task.id] = [{"role": "user", "content": "Continue"}]
    app._pending_programs[task.id] = {
        "identity": "MemoryRetrieval",
        "arguments": {"query": "retained facts"},
    }
    with pytest.raises(RuntimeError, match="Resume the pending ProgramRun"):
        await app._ensure_budget(task)
    assert app.provider.requests == []
    assert not app.runtime.is_running(task.id)
    app._pending_programs.clear()


@pytest.mark.parametrize("token_limit", [None, 100])
async def test_unavailable_usage_is_retained_and_cannot_satisfy_an_explicit_token_limit(
    app, token_limit
):
    """Missing SDK usage stays unknown and cannot satisfy an explicit token allowance."""
    task = app.tasks.create_task(
        "Observe usage", hard_limits={"tokens": token_limit} if token_limit else {}
    )
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Short check")
    app.provider = ScriptedProvider(
        [
            [
                AgentEvent("usage", {"available": False, "total_tokens": None}),
                AgentEvent("completed", {"text": "done", "parsed": None}),
            ]
        ]
    )
    request = AgentRequest("Observe usage", app._workspace(task.id))
    if token_limit:
        with pytest.raises(RuntimeError, match="usage is unknown"):
            await app._invoke(task.id, request)
    else:
        assert (await app._invoke(task.id, request))["text"] == "done"
    assert "tokens" not in task.spent
    assert any(
        event.operator == "provider_event"
        and event.output["kind"] == "usage"
        and event.output["data"]["available"] is False
        for event in app.memory.events
    )
