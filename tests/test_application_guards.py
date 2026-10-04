"""Application authority and recovery tests with an explicit DBOS test subprocess."""

from __future__ import annotations

import asyncio
import contextvars
import json
import time
from functools import partial
from types import SimpleNamespace

import pytest
from test_application import decision, framing, verification, wait_for_event
from test_runtime import TestProcess

from evertree.application import EverTree
from evertree.core.actions import ActionOption
from evertree.core.datasets import EvaluationCase
from evertree.core.evaluation import AcceptanceCriteria, MetricGuardrail, evaluate_prediction
from evertree.core.graph import GraphDelta
from evertree.core.learning import LearningCredit, LearningObjective, LearningSignal
from evertree.core.provider import AgentEvent, AgentRequest, ScriptedProvider
from evertree.core.runtime import Runtime

TEST_RUNTIME = partial(Runtime, process_factory=TestProcess)


@pytest.fixture
async def agent(tmp_path):
    async with EverTree(
        tmp_path / "agent", provider=ScriptedProvider([]), runtime_factory=TEST_RUNTIME
    ) as app:
        yield app


def prepared_task(agent):
    task = agent.tasks.create_task("Develop a reusable skill")
    agent.tasks.assign_budget(
        task.id, {"active_time_minutes": 3}, 0, reason="Requested primary work"
    )
    return task


async def test_developer_binds_prediction_criteria_without_weakening_core_checks(agent):
    proposal = agent.propose_program(
        "Probability",
        role="model",
        claim="Learn a binary rate",
        description="Predict a binary probability",
    )
    program = proposal["program"]["id"]
    dataset = agent.datasets.create(
        "Independent probabilities",
        [EvaluationCase("case", {}, True, "prediction", ("heldout-episode",))],
        target_metrics=("brier", "log_loss"),
    )
    with pytest.raises(ValueError, match="mandatory core checks"):
        agent.bind_evaluation(
            program,
            dataset.revision,
            criteria=AcceptanceCriteria(("holdout",), "brier", "minimize", 0.2),
        )
    policy = AcceptanceCriteria(
        ("contracts", "tests", "holdout"),
        "brier",
        "minimize",
        0.2,
        guardrails=(MetricGuardrail("log_loss", "minimize", 1.0),),
    )
    agent.bind_evaluation(program, dataset.revision, criteria=policy)
    candidate = agent.lifecycle.candidate(proposal["candidate"]["id"])
    assert agent._acceptance_criteria(candidate) == policy
    # Graph writes cannot replace the private, developer-owned binding.
    assert "bind_evaluation" not in {tool.name for tool in agent._tools()}
    saved = json.loads(json.dumps(agent.snapshot()))
    agent._evaluation_bindings.clear()
    agent._restore_core(saved)
    assert agent._acceptance_criteria(candidate) == policy


async def test_verification_retains_tool_evidence_after_long_stream(agent):
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
    async def collect():
        return [event.kind async for event in agent.events()]

    reader = asyncio.create_task(collect())
    await asyncio.sleep(0)
    assert not reader.done()
    await agent.close()
    assert await asyncio.wait_for(reader, timeout=2) == ["closed"]


def runtime_payload(task, **data):
    return {
        **data,
        "_runtime": {"task_id": task.id, "run_mode": "live", "program": {"role": "exec"}},
    }


@pytest.mark.parametrize(
    "method", ["learning.learn", "learning.credit", "learning.coordinate", "learning.prepare"]
)
async def test_programs_cannot_rewrite_runtime_verification_estimator(agent, method):
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
    task = prepared_task(agent)
    process = agent.graph.find("TaskFraming")
    assert process.kind == "prototype"
    assert process.properties["process"] is True
    before = agent.graph.snapshot()
    with pytest.raises(PermissionError, match="cannot be removed"):
        agent._apply_delta(task.id, GraphDelta(deletes=(process.id,)))
    assert agent.graph.snapshot() == before


async def test_primary_skill_work_uses_primary_budget_and_extra_work_requires_allowance(agent):
    task = prepared_task(agent)
    program = agent._program("TaskFraming")
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


async def test_cancel_joins_blocked_sdk_callback_before_publishing_terminal_state(tmp_path):
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

    async with EverTree(
        tmp_path / "agent",
        provider=provider,
        runtime_factory=TEST_RUNTIME,
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


class BlockingModelProvider(ScriptedProvider):
    def __init__(self, *, scripts=(), block_after=0):
        super().__init__(list(scripts))
        self.block_after = block_after
        self.entered, self.release, self.unwound = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def run(self, request_id, request, *, tool_handler=None, approval_handler=None):
        if len(self.requests) == self.block_after:
            self.requests.append(request)
            yield AgentEvent("session", {"provider": self.name, "id": request_id})
            self.entered.set()
            try:
                await self.release.wait()
                raise AssertionError("A stopped model callback resumed")
            finally:
                self.unwound.set()
        else:
            async for event in super().run(
                request_id, request, tool_handler=tool_handler, approval_handler=approval_handler
            ):
                yield event


async def test_cancel_stops_real_worker_waiting_inside_provider_gateway(tmp_path):
    provider = BlockingModelProvider()
    async with EverTree(tmp_path / "agent", provider=provider, runtime_factory=TEST_RUNTIME) as app:
        task = await app.submit("Wait inside the framing Program")
        await asyncio.wait_for(provider.entered.wait(), 30)
        assert app.runtime.is_running(task.id)
        await asyncio.wait_for(app.cancel(task.id), 10)
        assert provider.unwound.is_set()
        assert not app.runtime.is_running()
        assert task.status == "cancelled"
        assert task.execution_stopped
        assert app.learning.statistics("verified_task_rate")["observed_count"] == 0
        provider.release.set()
        await asyncio.sleep(0)
        assert len(provider.requests) == 1


async def test_switching_provider_does_not_resume_another_providers_session(tmp_path):
    old = ScriptedProvider([framing(), decision("Which letter?", "waiting")])
    async with EverTree(tmp_path / "agent", provider=old, runtime_factory=TEST_RUNTIME) as app:
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


async def test_restart_resumes_pending_program_with_original_run_identity(tmp_path):
    home = tmp_path / "agent"
    blocked = BlockingModelProvider()
    first = EverTree(home, provider=blocked, runtime_factory=TEST_RUNTIME)
    try:
        await first.start()
        task = await first.submit("Count r in strawberry")
        await asyncio.wait_for(blocked.entered.wait(), 30)
        saved = dict(first._pending_programs[task.id])
    finally:
        await asyncio.wait_for(first.close(), 15)
    assert blocked.unwound.is_set()
    assert first.backups.list()
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with EverTree(home, provider=provider, runtime_factory=TEST_RUNTIME) as restored:
        assert restored._pending_programs[task.id] == saved
        result = await asyncio.wait_for(restored.run("Continue", task_id=task.id), 45)
        assert result["status"] == "succeeded", result
        assert result["answer"] == "3"
        assert restored.tasks.get(task.id).program_run_ids.count(saved["run_id"]) == 1
        assert task.id not in restored._pending_programs
        assert provider.requests[0].mode == "model"
        assert len(provider.requests) == 3


@pytest.mark.parametrize("pause_at", [1, 2], ids=["controller", "verifier"])
async def test_input_accepted_during_turn_reaches_controller_before_delivery(tmp_path, pause_at):
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
    async with EverTree(tmp_path / "agent", provider=provider, runtime_factory=TEST_RUNTIME) as app:
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


class VirtualClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.mark.parametrize("purpose", ["task", "self_improvement"])
async def test_nested_sdk_approval_wait_is_excluded_once_from_both_budget_buckets(
    agent, monkeypatch, purpose
):
    from evertree import application

    clock = VirtualClock()
    monkeypatch.setattr(
        application, "time", SimpleNamespace(monotonic=clock.monotonic, time=time.time)
    )
    task = prepared_task(agent)
    agent.tasks.assign_budget(
        task.id, {"active_time_minutes": 3}, 50, reason="Explicit optional allowance"
    )
    program = agent._program("TaskFraming")
    candidate = agent.lifecycle.create_candidate(
        program.program_id, "Measure a candidate development call"
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
                    "develop_candidate",
                    {
                        "candidate": candidate.id,
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
    from evertree import application

    clock = VirtualClock()
    monkeypatch.setattr(
        application, "time", SimpleNamespace(monotonic=clock.monotonic, time=time.time)
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
    from evertree import application

    clock = VirtualClock()
    monkeypatch.setattr(
        application, "time", SimpleNamespace(monotonic=clock.monotonic, time=time.time)
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


async def test_failed_boundary_backup_does_not_stop_the_next_queued_task(agent, monkeypatch):
    agent.provider = ScriptedProvider(
        [
            framing("First"),
            decision("one"),
            verification(),
            framing("Second"),
            decision("two"),
            verification(),
        ]
    )
    create = agent.backups.create
    attempts = 0

    async def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("Simulated backup disk failure")
        return await create(*args, **kwargs)

    monkeypatch.setattr(agent.backups, "create", fail_once)
    first = await agent.submit("First")
    answer, _ = await wait_for_event(agent, "answer")
    second = await agent.submit("Second")
    await agent.acknowledge_delivery(answer.data["delivery_id"])
    answer, seen = await wait_for_event(agent, "answer")
    assert answer.task_id == second.id
    assert answer.data["text"] == "two"
    assert any(
        event.kind == "maintenance_error" and "backup disk failure" in event.data["message"]
        for event in seen
    )
    await agent.acknowledge_delivery(answer.data["delivery_id"])
    await wait_for_event(agent, "task_completed")
    await agent._pump
    assert first.status == second.status == "succeeded"
    assert agent.backups.list()


async def test_restore_copies_long_dependency_paths_through_backup_helper(agent):
    from evertree.core.backup import _extended

    asset = agent.repository / "assets" / ("a" * 80) / ("b" * 80) / "saved-state.txt"
    extended = _extended(asset)
    extended.parent.mkdir(parents=True)
    extended.write_text("saved content", encoding="utf-8")
    backup = await agent.backup()
    extended.write_text("changed later", encoding="utf-8")
    await agent.restore(backup)
    assert _extended(asset).read_text(encoding="utf-8") == "saved content"


async def test_shutdown_backup_failure_still_closes_provider_and_releases_home_lock(
    tmp_path, monkeypatch
):
    class ClosingProvider(ScriptedProvider):
        closed = False

        async def close(self):
            self.closed = True

    async def fail(*args, **kwargs):
        raise OSError("Simulated shutdown backup failure")

    home = tmp_path / "agent"
    provider = ClosingProvider([])
    app = EverTree(home, provider=provider, runtime_factory=TEST_RUNTIME)
    await app.start()
    monkeypatch.setattr(app.backups, "create", fail)
    with pytest.raises(OSError, match="shutdown backup failure"):
        await app.close()
    assert provider.closed
    assert app._lock_file is None
    async with EverTree(
        home, provider=ScriptedProvider([]), runtime_factory=TEST_RUNTIME
    ) as reopened:
        assert reopened._started


async def test_backup_runtime_bundle_rejects_incompatible_restore_before_swaps(agent, monkeypatch):
    from evertree.core import environment
    from evertree.core.environment import RuntimeEnvironmentError

    backup = await agent.backup()
    saved = agent.backups.read(backup)["core"]["environment"]
    bundle = agent.backups.dependency(backup, "core_runtime")
    assert (bundle / "src/evertree/core/environment.py").is_file()
    assert (bundle / "requirements.txt").is_file()
    assert "websockets" in saved["packages"]
    assert saved["fingerprint"] == agent._environment["fingerprint"]
    changed = dict(saved["packages"])
    changed["websockets"] = "0.0.0"
    monkeypatch.setattr(environment, "_installed_packages", lambda: changed)
    graph_before = agent.graph.snapshot()
    head_before = (agent.repository / ".git/HEAD").read_bytes()
    with pytest.raises(RuntimeEnvironmentError, match="Runtime mismatch.*packages"):
        await agent.restore(backup)
    assert agent.graph.snapshot() == graph_before
    assert (agent.repository / ".git/HEAD").read_bytes() == head_before
