from __future__ import annotations

import asyncio

from evertree.application import EverTree
from evertree.core.provider import ScriptedProvider
from tests.support.application import decision, framing, verification, wait_for_event
from tests.support.component import component_app


async def test_busy_agent_still_prunes_temporary_files(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from evertree import application
    from evertree._application import persistence

    agent = EverTree(tmp_path, provider=ScriptedProvider([]))
    agent._active_requests["busy"] = "request"
    prune = Mock()
    monkeypatch.setattr(persistence, "prune", prune)

    async def tick(_):
        agent._closed = True  # Execute one maintenance iteration, without a real timer.

    monkeypatch.setattr(application.asyncio, "sleep", tick)
    await agent._periodic_maintenance()
    prune.assert_called_once_with(tmp_path)


async def test_final_answer_waits_for_delivery_acknowledgement(tmp_path):
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        task = await agent.submit("Count r in strawberry")
        answer, _ = await wait_for_event(agent, "answer")
        assert not task.terminal
        assert answer.data["text"] == "3"
        await agent.acknowledge_delivery(answer.data["delivery_id"])
        finished, _ = await wait_for_event(agent, "task_completed")
        assert finished.task_id == task.id
        assert task.status == "succeeded"


async def test_clarification_continues_same_task_with_previous_context(tmp_path):
    provider = ScriptedProvider(
        [
            framing("Count a requested letter"),
            decision("Which letter?", "waiting"),
            decision("3"),
            verification(),
        ]
    )
    async with component_app(tmp_path / "agent", provider=provider) as agent:
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


async def test_incomplete_verification_returns_to_work_instead_of_success(tmp_path):
    provider = ScriptedProvider(
        [framing(), decision("2"), verification(False), decision("3"), verification(True)]
    )
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        result = await asyncio.wait_for(agent.run("Count r in strawberry"), 60)
        assert result["status"] == "succeeded", result
        assert result["answer"] == "3"
        assert len(provider.requests) == 5
        assert "Verification requires correction" in provider.requests[3].prompt


async def test_delivery_failure_leaves_task_waiting(tmp_path):
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        state = await agent.submit("Count r in strawberry")
        answer, _ = await wait_for_event(agent, "answer")
        await agent.acknowledge_delivery(answer.data["delivery_id"], delivered=False)
        await wait_for_event(agent, "task_waiting")
        assert state.status == "waiting"
        assert state.waiting_for == ["delivery"]


async def test_queue_does_not_start_second_task_before_first_delivery(tmp_path):
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
    async with component_app(tmp_path / "agent", provider=provider) as agent:
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


async def test_duplicate_input_source_does_not_create_another_task(tmp_path):
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        one = await agent.submit("Count r in strawberry", source_id="source-1")
        two = await agent.submit("Count r in strawberry", source_id="source-1")
        assert one is two
        answer, _ = await wait_for_event(agent, "answer")
        await agent.acknowledge_delivery(answer.data["delivery_id"])
        await wait_for_event(agent, "task_completed")
        assert len(agent.tasks.all()) == 1
        assert len(agent._inputs[one.id]) == 1
