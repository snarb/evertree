"""End-to-end offline-provider tests through the real native DBOS worker.

These tests never call a paid model. They still execute committed bootstrap
Programs in the Windows AppContainer and exercise the actual app coordinator.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from evertree.application import EverTree
from evertree.core.provider import AgentEvent, ScriptedProvider

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="EverTree v1 requires Windows native workers"
)


def completed(data):
    return [AgentEvent("completed", {"text": json.dumps(data), "parsed": data})]


def framing(objective="Count r in strawberry", minutes=3, improvement=0):
    return completed(
        {
            "objective": objective,
            "success_criteria": ["Use the supplied sources"],
            "constraints": [],
            "preferences": [],
            "execution_budget": {"active_time_minutes": minutes},
            "self_improvement_budget": improvement,
            "budget_reason": "Small task with a precise check",
        }
    )


def decision(answer="3", status="completed"):
    return completed({"status": status, "answer": answer, "progress": "Selected work complete"})


def verification(verified=True):
    return completed(
        {
            "verified": verified,
            "reason": "Source and calculation checked" if verified else "Recheck calculation",
        }
    )


@pytest.fixture
def native_python_cache(monkeypatch):
    """Reuse only the interpreter copy, keeping actual OS isolation for every run."""
    from evertree.core import runtime, sandbox

    root = Path(__file__).resolve().parents[1] / ".state" / "test-application-python"
    monkeypatch.setattr(runtime, "prepare_python", lambda _: sandbox.prepare_python(root))


async def wait_for_event(agent, kind, *, timeout=45):
    seen = []
    async with asyncio.timeout(timeout):
        while True:
            event = await agent._events.get()
            seen.append(event)
            if event.kind in {"task_failed", "task_cancelled"} and event.kind != kind:
                pytest.fail(f"Task ended before {kind}: {event.data}")
            if event.kind == kind:
                return event, seen


async def test_native_framing_verification_delivery_and_budget(tmp_path, native_python_cache):
    provider = ScriptedProvider([framing(minutes=4, improvement=15), decision(), verification()])
    async with EverTree(tmp_path / "agent", provider=provider) as agent:
        result = await asyncio.wait_for(agent.run("Count the r characters in strawberry"), 60)
        assert result["status"] == "succeeded", result
        assert result["answer"] == "3"
        task = agent.tasks.get(result["task_id"])
        assert task.execution_budget.resources == {"active_time_minutes": 4}
        assert task.self_improvement_budget == 15
        assert len(provider.requests) == 3
        assert provider.requests[0].mode == "model"
        assert provider.requests[1].mode == "exec"
        assert provider.requests[2].mode == "model"
        assert task.specification.revision == 2
        assert not agent.runtime.is_running()
        assert any(event.operator == "provider_request" for event in agent.memory.events)
        assert any(event.operator == "run_finished" for event in agent.memory.events)


async def test_final_answer_waits_for_delivery_acknowledgement(tmp_path, native_python_cache):
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with EverTree(tmp_path / "agent", provider=provider) as agent:
        task = await agent.submit("Count r in strawberry")
        answer, _ = await wait_for_event(agent, "answer")
        assert not task.terminal
        assert answer.data["text"] == "3"
        await agent.acknowledge_delivery(answer.data["delivery_id"])
        finished, _ = await wait_for_event(agent, "task_completed")
        assert finished.task_id == task.id
        assert task.status == "succeeded"


async def test_clarification_continues_same_task_with_previous_context(
    tmp_path, native_python_cache
):
    provider = ScriptedProvider(
        [
            framing("Count a requested letter"),
            decision("Which letter?", "waiting"),
            decision("3"),
            verification(),
        ]
    )
    async with EverTree(tmp_path / "agent", provider=provider) as agent:
        first = await asyncio.wait_for(agent.run("Count a letter in strawberry"), 60)
        assert first["status"] == "waiting", first
        identity = first["task_id"]
        usage_before = dict(agent.tasks.get(identity).spent)
        second = await asyncio.wait_for(agent.run("The letter r", task_id=identity), 60)
        assert second["status"] == "succeeded", second
        assert second["task_id"] == identity
        assert len(agent.tasks.all()) == 1
        assert (
            agent.tasks.get(identity).spent["active_time_minutes"]
            >= usage_before["active_time_minutes"]
        )
        assert "The letter r" in provider.requests[2].prompt
        assert "strawberry" in provider.requests[2].prompt


async def test_incomplete_verification_returns_to_work_instead_of_success(
    tmp_path, native_python_cache
):
    provider = ScriptedProvider(
        [framing(), decision("2"), verification(False), decision("3"), verification(True)]
    )
    async with EverTree(tmp_path / "agent", provider=provider) as agent:
        result = await asyncio.wait_for(agent.run("Count r in strawberry"), 60)
        assert result["status"] == "succeeded", result
        assert result["answer"] == "3"
        assert len(provider.requests) == 5
        assert "Verification requires correction" in provider.requests[3].prompt


async def test_delivery_failure_leaves_task_waiting(tmp_path, native_python_cache):
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with EverTree(tmp_path / "agent", provider=provider) as agent:
        state = await agent.submit("Count r in strawberry")
        answer, _ = await wait_for_event(agent, "answer")
        await agent.acknowledge_delivery(answer.data["delivery_id"], delivered=False)
        await wait_for_event(agent, "task_waiting")
        assert state.status == "waiting"
        assert state.waiting_for == ["delivery"]


async def test_queue_does_not_start_second_task_before_first_delivery(
    tmp_path, native_python_cache
):
    provider = ScriptedProvider(
        [
            framing("First"),
            decision("one"),
            verification(),
            framing("Second"),
            decision("two"),
            verification(),
        ]
    )
    async with EverTree(tmp_path / "agent", provider=provider) as agent:
        first = await agent.submit("First")
        first_answer, _ = await wait_for_event(agent, "answer")
        second = await agent.submit("Second")
        await asyncio.sleep(0.05)
        assert len(provider.requests) == 3
        assert agent.attention.running_task == first.id
        assert second.status == "queued"
        await agent.acknowledge_delivery(first_answer.data["delivery_id"])
        second_answer, seen = await wait_for_event(agent, "answer")
        assert second_answer.task_id == second.id
        assert any(event.kind == "task_completed" and event.task_id == first.id for event in seen)
        await agent.acknowledge_delivery(second_answer.data["delivery_id"])
        await wait_for_event(agent, "task_completed")
        assert first.status == second.status == "succeeded"


async def test_backup_restart_preserves_waiting_task_and_original_budget(
    tmp_path, native_python_cache
):
    home = tmp_path / "agent"
    first_provider = ScriptedProvider(
        [
            framing("Count a requested letter", minutes=8, improvement=5),
            decision("Which letter?", "waiting"),
        ]
    )
    async with EverTree(home, provider=first_provider) as first:
        waiting = await asyncio.wait_for(first.run("Count a letter in strawberry"), 60)
        assert waiting["status"] == "waiting", waiting
        identity = waiting["task_id"]
        # The completed backup is made at the queue's next safe boundary.
        await first._pump
        saved_usage = dict(first.tasks.get(identity).spent)
        assert first.backups.list()
    second_provider = ScriptedProvider([decision("3"), verification()])
    async with EverTree(home, provider=second_provider) as restored:
        task = restored.tasks.get(identity)
        assert task.status == "waiting"
        assert task.execution_budget.resources["active_time_minutes"] == 8
        assert task.self_improvement_budget == 5
        assert task.spent == saved_usage
        result = await asyncio.wait_for(restored.run("r", task_id=identity), 60)
        assert result["status"] == "succeeded", result
        assert result["task_id"] == identity
        assert len(second_provider.requests) == 2  # No reset or repeated framing.


async def test_duplicate_input_source_does_not_create_another_task(tmp_path, native_python_cache):
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with EverTree(tmp_path / "agent", provider=provider) as agent:
        one = await agent.submit("Count r in strawberry", source_id="source-1")
        two = await agent.submit("Count r in strawberry", source_id="source-1")
        assert one is two
        answer, _ = await wait_for_event(agent, "answer")
        await agent.acknowledge_delivery(answer.data["delivery_id"])
        await wait_for_event(agent, "task_completed")
        assert len(agent.tasks.all()) == 1
        assert len(agent._inputs[one.id]) == 1
