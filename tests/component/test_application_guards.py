import asyncio
import contextvars
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evertree.core.actions import ActionOption
from evertree.core.evaluation.scoring import evaluate_prediction
from evertree.core.graph.types import GraphDelta
from evertree.core.learning.contracts import LearningCredit, LearningObjective, LearningSignal
from evertree.core.programs.lifecycle import ProgramBranch
from evertree.core.provider import AgentEvent, AgentRequest, ScriptedProvider
from tests.support.application import decision, framing, verification, wait_for_event
from tests.support.component import component_app


def prepared_task(agent):
    task = agent.tasks.create_task("Develop a reusable skill")
    agent.tasks.assign_budget(
        task.id, {"active_time_minutes": 3}, 0, reason="Requested primary work"
    )
    return task


def runtime_payload(task, **data):
    return {
        **data,
        "_runtime": {
            "task_id": task.id,
            "run_id": "run",
            "run_mode": "live",
            "program": {"role": "exec", "revision": "commit"},
        },
    }


class DetachedToolsProvider(ScriptedProvider):
    """Model cancellation alone does not stop a separately scheduled SDK callback."""

    async def run(self, request_id, request, *, tool_handler=None, approval_handler=None):
        async def detached(name, arguments):
            callback = asyncio.create_task(tool_handler(name, arguments))
            return await asyncio.shield(callback)

        async for event in super().run(
            request_id, request, tool_handler=detached, approval_handler=approval_handler
        ):
            yield event


class CountingAction:
    def __init__(self):
        self.calls = []

    async def list_actions(self):
        return [ActionOption("send")]

    async def execute(self, command):
        self.calls.append(command)
        return "accepted"


class VirtualClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


async def test_verification_retains_tool_evidence_after_long_stream(agent):
    """Prepare traces directly to verify evidence selection independently of worker transport."""
    task = prepared_task(agent)
    run = agent.memory.start_run("Consciousness", "commit", {"task_id": task.id})
    result = agent.memory.record(
        run,
        "provider_event",
        output={"kind": "tool_result", "data": {"name": "run_program", "result": [1, 3, 3]}},
    )
    for _ in range(80):
        agent.memory.record(
            run,
            "provider_event",
            output={"kind": "message", "data": {"text": "delta", "delta": True}},
        )
    agent.memory.finish_run(run)
    trace = agent._recent_trace(task.id)
    assert any(event["id"] == result.id for event in trace)
    assert not any(event["output"].get("kind") == "message" for event in trace)


async def test_close_wakes_a_waiting_event_consumer(agent):
    """Coordinator shutdown wakes a subscriber without needing a worker or Git repository."""

    async def collect():
        return [event.kind async for event in agent.events()]

    reader = asyncio.create_task(collect())
    await asyncio.sleep(0)
    assert not reader.done()
    await agent.close()
    assert await asyncio.wait_for(reader, timeout=2) == ["closed"]


@pytest.mark.parametrize(
    "method", ["learning.learn", "learning.credit", "learning.coordinate", "learning.prepare"]
)
async def test_programs_cannot_rewrite_runtime_verification_estimator(agent, method):
    """Gateway authorization protects the real learning state from Program-owned updates."""
    task = prepared_task(agent)
    evaluation = agent.evaluations.add(
        evaluate_prediction(
            0.5,
            True,
            metrics=("brier",),
            outcome_ids=("claimed_success",),
            provenance=(str(agent.memory.events[0].id),),
            subject="verified_task_rate",
        )
    )
    objective = LearningObjective(("brier",), "minimize")
    signal = LearningSignal(evaluation, objective, {"claimed_success": True})
    data = {
        "target": "verified_task_rate",
        "signal": signal.to_dict(),
        "evaluation_id": evaluation.id,
        "objective": objective.to_dict(),
        "outcome_values": {"claimed_success": True},
    }
    if method == "learning.prepare":
        data = {"credit": LearningCredit("verified_task_rate", signal).to_dict()}
    before = agent.learning.snapshot()
    with pytest.raises(PermissionError, match="core task outcomes"):
        await agent._gateway(method, runtime_payload(task, **data))
    assert agent.learning.snapshot() == before
    assert (
        await agent._gateway(
            "learning.predict", runtime_payload(task, state_id="verified_task_rate")
        )
        == 0.5
    )


async def test_process_prototype_cannot_be_deleted_by_semantic_edit(agent):
    """Apply a real semantic edit against a seeded graph and retain its protected prototype."""
    task = prepared_task(agent)
    process = agent.graph.find("TaskFraming")
    assert process.kind == "prototype"
    assert process.properties["process"] is True
    before = agent.graph.snapshot()
    with pytest.raises(PermissionError, match="cannot be removed"):
        agent._apply_delta(task.id, GraphDelta(deletes=(process.id,)))
    assert agent.graph.snapshot() == before


async def test_cancel_joins_blocked_sdk_callback_before_publishing_terminal_state(tmp_path):
    """Coordinator cancellation joins a detached SDK callback before declaring the Task terminal."""
    entered, release, unwound = asyncio.Event(), asyncio.Event(), asyncio.Event()
    terminal_during_cleanup = []
    provider = DetachedToolsProvider(
        [
            framing(),
            [
                AgentEvent("tool_call", {"name": "list_actions", "arguments": {"session": "test"}}),
                AgentEvent(
                    "tool_call",
                    {
                        "name": "take_action",
                        "arguments": {
                            "session": "test",
                            "command": "send",
                            "operation_id": "send-once",
                        },
                    },
                ),
                *decision(),
            ],
        ]
    )

    async def approve(data):
        entered.set()
        try:
            await release.wait()
            return True
        finally:
            terminal_during_cleanup.append(app.tasks.get(data["task_id"]).terminal)
            unwound.set()

    async with component_app(
        tmp_path / "agent",
        provider=provider,
        approval_handler=approve,
    ) as app:
        task = await app.submit("Send one approved command")
        adapter = CountingAction()
        app.actions.bind("test", adapter, task_id=task.id, commit="test-adapter-v1")
        await asyncio.wait_for(entered.wait(), 30)
        assert not task.terminal
        await asyncio.wait_for(app.cancel(task.id), 10)
        assert unwound.is_set()
        assert terminal_during_cleanup == [False]
        assert task.status == "cancelled"
        assert task.execution_stopped
        assert not app.runtime.is_running()
        assert app.learning.statistics("verified_task_rate")["observed_count"] == 0
        assert not app._tool_tasks.get(task.id)
        release.set()
        await asyncio.sleep(0)
        assert adapter.calls == []
        with pytest.raises(PermissionError, match="stopped"):
            await app._tool(
                task.id,
                "take_action",
                {"session": "test", "command": "send", "operation_id": "after-stop"},
            )
        assert adapter.calls == []


async def test_switching_provider_does_not_resume_another_providers_session(tmp_path):
    """Switching fake providers exercises real session ownership without SDK processes."""
    old = ScriptedProvider([framing(), decision("Which letter?", "waiting")])
    async with component_app(
        tmp_path / "agent",
        provider=old,
    ) as app:
        first = await app.run("Count a letter")
        assert first["status"] == "waiting"
        await app._pump
        identity = first["task_id"]
        assert app._sessions[identity]["provider"] == "scripted"
        replacement = ScriptedProvider([decision(), verification()])
        replacement.name = "other-provider"
        app.provider = replacement
        result = await app.run("r in strawberry", task_id=identity)
        assert result["status"] == "succeeded"
        assert replacement.requests[0].session is None
        assert app._sessions[identity]["provider"] == "other-provider"


@pytest.mark.parametrize("pause_at", [1, 2], ids=["controller", "verifier"])
async def test_input_accepted_during_turn_reaches_controller_before_delivery(tmp_path, pause_at):
    """Events control a paused turn so new input must reach the controller before delivery."""

    class PausingProvider(ScriptedProvider):
        def __init__(self, scripts):
            super().__init__(scripts)
            self.entered, self.release = asyncio.Event(), asyncio.Event()

        async def run(self, request_id, request, **kwargs):
            if len(self.requests) == pause_at:
                self.entered.set()
                await self.release.wait()
            async for event in super().run(request_id, request, **kwargs):
                yield event

    scripts = [framing(), decision("stale")]
    if pause_at == 2:
        scripts.append(verification())
    scripts.extend([decision("updated"), verification()])
    provider = PausingProvider(scripts)
    async with component_app(
        tmp_path / "agent",
        provider=provider,
    ) as app:
        task = await app.submit("Answer the initial request")
        await asyncio.wait_for(provider.entered.wait(), 30)
        await app.submit("New accepted constraint: use the updated answer", task_id=task.id)
        provider.release.set()
        answer, seen = await wait_for_event(app, "answer")
        assert answer.data["text"] == "updated"
        assert [event.data["text"] for event in seen if event.kind == "answer"] == ["updated"]
        revised_controller = provider.requests[-2]
        assert revised_controller.mode == "exec"
        assert "New accepted constraint" in revised_controller.prompt
        await app.acknowledge_delivery(answer.data["delivery_id"])
        await wait_for_event(app, "task_completed")
        assert task.status == "succeeded"


@pytest.mark.parametrize("purpose", ["task", "self_improvement"])
async def test_nested_sdk_approval_wait_is_excluded_once_from_both_budget_buckets(
    agent, monkeypatch, purpose
):
    """A controlled clock tests nested approval accounting without candidate Git work."""
    from evertree._application import execution

    clock = VirtualClock()
    monkeypatch.setattr(
        execution, "time", SimpleNamespace(monotonic=clock.monotonic, time=time.time)
    )
    task = prepared_task(agent)
    agent.tasks.assign_budget(
        task.id, {"active_time_minutes": 3}, 50, reason="Explicit optional allowance"
    )

    async def approve(_):
        clock.advance(20)
        await asyncio.sleep(0)
        return True

    class TimedProvider(ScriptedProvider):
        async def run(self, request_id, request, *, tool_handler=None, approval_handler=None):
            self.requests.append(request)
            yield AgentEvent("session", {"provider": self.name, "id": request_id})
            if request.native_coding:
                clock.advance(3)
                # SDK callbacks can originate in an independent reader task.
                approved = await asyncio.create_task(
                    approval_handler({"operation": "test"}), context=contextvars.Context()
                )
                assert approved
                clock.advance(2)
            else:
                clock.advance(1)
                await tool_handler(
                    "work_on_code",
                    {
                        "instruction": "Inspect this candidate",
                        "purpose": purpose,
                    },
                )
                clock.advance(1)
            yield AgentEvent("completed", {"text": "done", "parsed": None})

    agent.provider = TimedProvider([])
    agent.approval_handler = approve
    await agent._invoke(
        task.id,
        AgentRequest("Develop", agent._workspace(task.id), mode="exec", tools=agent._tools()),
    )
    assert task.spent["active_time_minutes"] * 60 == pytest.approx(7)
    assert task.self_improvement_spent.get("active_time_minutes", 0) * 60 == pytest.approx(
        5 if purpose == "self_improvement" else 0
    )


async def test_program_gateway_approval_wait_is_excluded_from_parent_run_meter(agent, monkeypatch):
    """A direct framing Program call proves approval time is excluded by the shared meter."""
    from evertree._application import execution

    clock = VirtualClock()
    monkeypatch.setattr(
        execution, "time", SimpleNamespace(monotonic=clock.monotonic, time=time.time)
    )
    task = prepared_task(agent)

    async def approve(_):
        clock.advance(20)
        await asyncio.sleep(0)
        return True

    class TimedFramingProvider(ScriptedProvider):
        async def run(self, request_id, request, *, tool_handler=None, approval_handler=None):
            clock.advance(3)
            assert await approval_handler({"operation": "test"})
            clock.advance(2)
            for event in framing():
                yield event

    agent.provider = TimedFramingProvider([])
    agent.approval_handler = approve
    result = await agent._run_program(task.id, "TaskFraming", {"request": "Count r"})
    assert result["result"]["objective"] == "Count r in strawberry"
    assert task.spent["active_time_minutes"] * 60 == pytest.approx(5)


async def test_technical_timeout_during_approval_does_not_consume_task_budget(agent, monkeypatch):
    """A timed approval callback must not charge waiting time to the Task."""
    from evertree._application import execution

    clock = VirtualClock()
    monkeypatch.setattr(
        execution, "time", SimpleNamespace(monotonic=clock.monotonic, time=time.time)
    )
    task = prepared_task(agent)

    async def timed_out_approval(_):
        clock.advance(600)
        await asyncio.sleep(0)
        raise TimeoutError("Technical approval deadline")

    class TimedOutProvider(ScriptedProvider):
        async def run(self, request_id, request, *, tool_handler=None, approval_handler=None):
            clock.advance(3)
            await approval_handler({"operation": "test"})
            yield AgentEvent("completed", {"text": "unreachable", "parsed": None})

    agent.provider = TimedOutProvider([])
    agent.approval_handler = timed_out_approval
    with pytest.raises(TimeoutError, match="Technical approval deadline"):
        await agent._invoke(task.id, AgentRequest("Request permission", agent._workspace(task.id)))
    assert task.spent["active_time_minutes"] * 60 == pytest.approx(3)
    assert not task.budget_exhausted


@pytest.mark.parametrize(
    ("name", "role", "parent"),
    [
        ("Planning", "exec", None),
        ("Planning", "model", "Learning"),
        ("NewProcess", "exec", "Process"),
        ("NewProcess", "exec", "Self"),
        ("NewProcess", "exec", "MissingParent"),
    ],
)
async def test_invalid_program_proposals_do_not_change_graph(agent, name, role, parent):
    """Reject invalid proposals from seeded in-memory state before any candidate I/O."""
    identities = {node.id for node in agent.graph.nodes()}
    with pytest.raises(ValueError):
        agent.propose_program(name, role=role, parent=parent, claim="Improve behavior")
    assert {node.id for node in agent.graph.nodes()} == identities


async def test_primary_skill_work_uses_primary_budget_and_extra_work_requires_allowance(
    agent, monkeypatch
):
    """Test real budget gates with branch creation supplied as an external boundary."""
    task = prepared_task(agent)
    program = agent._program("TaskFraming")
    # Only budget accounting is under test; branch creation has real Git tests.
    create = Mock(
        return_value=ProgramBranch(
            "candidate",
            program.program_id,
            "candidate",
            str(agent.state_dir / "candidate"),
            program.revision,
            "Improve requested skill",
        )
    )
    monkeypatch.setattr(agent.lifecycle, "create_candidate", create)
    candidate = await agent._tool(
        task.id,
        "create_candidate",
        {"program": program.program_id, "claim": "Improve requested skill"},
    )
    assert candidate["program_id"] == program.program_id
    assert task.self_improvement_budget == 0
    assert task.self_improvement_spent == {}
    with pytest.raises(PermissionError, match="self-improvement allowance"):
        await agent._tool(
            task.id,
            "create_candidate",
            {
                "program": program.program_id,
                "claim": "Optional future work",
                "purpose": "self_improvement",
            },
        )
    assert not agent._tool_tasks.get(task.id)
