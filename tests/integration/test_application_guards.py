from __future__ import annotations

import asyncio
import json
from functools import partial

import pytest

from evertree.application import EverTree
from evertree.core.datasets import EvaluationCase
from evertree.core.evaluation import AcceptanceCriteria, MetricGuardrail
from evertree.core.provider import AgentEvent, ScriptedProvider
from evertree.core.runtime import Runtime
from tests.support.application import decision, framing, verification, wait_for_event
from tests.support.runtime import TestProcess

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


async def test_developer_binds_prediction_criteria_without_weakening_core_checks(agent):
    """Exercise the application lifecycle with private Git publication and real state owners."""
    proposal = agent.propose_program(
        "Probability",
        role="model",
        claim="Learn a binary rate",
        description="Predict a binary probability",
    )
    program = proposal["program"]["id"]
    assert (
        proposal["candidate"]["git_ref"]
        == "codex/program/Self/Process/Probability/model/learn-a-binary"
    )
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


@pytest.mark.parametrize("parent_by_id", [False, True])
async def test_program_proposal_uses_selected_taxonomy_parent(agent, parent_by_id):
    """Exercise the application lifecycle with private Git publication and real state owners."""
    parent = agent.graph.find("Planning")
    proposal = agent.propose_program(
        "BudgetPlanning",
        parent=parent.id if parent_by_id else parent.name,
        role="exec",
        claim="Plan within the available budget",
        candidate_name="respect budget",
    )
    program = proposal["program"]
    assert program["properties"]["git_path"] == (
        "src/evertree/processes/task_management/planning/budget_planning/_exec.py"
    )
    assert agent.graph.ancestors(program["properties"]["process"])[0].id == parent.id
    assert proposal["candidate"]["git_ref"] == (
        "codex/program/Self/Process/TaskManagement/Planning/BudgetPlanning/exec/respect-budget"
    )


async def test_program_proposal_adds_missing_role_without_replacing_process(agent):
    """Exercise the application lifecycle with private Git publication and real state owners."""
    process = agent.graph.find("Planning")
    active_exec = process.properties["active_exec"]
    ancestors = agent.graph.ancestors(process.id)
    proposal = agent.propose_program(
        "Planning", role="model", claim="Predict plan cost", candidate_name="predict cost"
    )
    props = proposal["program"]["properties"]
    assert props["process"] == process.id
    assert props["git_path"] == "src/evertree/processes/task_management/planning/_model.py"
    assert props["active"] is False
    assert agent.graph.ancestors(process.id) == ancestors
    assert agent.graph.get(process.id).properties["active_exec"] == active_exec
    assert agent.graph.get(process.id).properties.get("active_model") is None
    assert proposal["candidate"]["git_ref"] == (
        "codex/program/Self/Process/TaskManagement/Planning/model/predict-cost"
    )
    # An inactive proposal reserves its role too; improve it through a candidate.
    with pytest.raises(ValueError, match="already has this Program role"):
        agent.propose_program("Planning", role="model", claim="Another model")


async def test_cancel_stops_real_worker_waiting_inside_provider_gateway(tmp_path):
    """Exercise the application lifecycle with private Git publication and real state owners."""
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


async def test_restart_discards_pending_program_and_starts_a_new_run(tmp_path):
    """Exercise the application lifecycle with private Git publication and real state owners."""
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
        assert task.id not in restored._pending_programs
        result = await asyncio.wait_for(restored.run("Continue", task_id=task.id), 45)
        assert result["status"] == "succeeded", result
        assert result["answer"] == "3"
        assert restored.tasks.get(task.id).program_run_ids.count(saved["run_id"]) == 1
        assert len(restored.tasks.get(task.id).program_run_ids) > 1
        assert task.id not in restored._pending_programs
        assert provider.requests[0].mode == "model"
        assert len(provider.requests) == 3


async def test_failed_boundary_backup_does_not_stop_the_next_queued_task(agent, monkeypatch):
    """Exercise the application lifecycle with private Git publication and real state owners."""
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


async def test_backup_does_not_copy_uncommitted_repository_files(agent):
    """Exercise the application lifecycle with private Git publication and real state owners."""
    from evertree.core.backup import _extended

    asset = agent.repository / "assets" / ("a" * 80) / ("b" * 80) / "saved-state.txt"
    extended = _extended(asset)
    extended.parent.mkdir(parents=True)
    extended.write_text("saved content", encoding="utf-8")
    backup = await agent.backup()
    extended.write_text("changed later", encoding="utf-8")
    await agent.restore(backup)
    assert _extended(asset).read_text(encoding="utf-8") == "changed later"
    assert not (backup / "dependencies").exists()


async def test_shutdown_backup_failure_still_closes_provider_and_releases_home_lock(
    tmp_path, monkeypatch
):
    """Exercise the application lifecycle with private Git publication and real state owners."""

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
    """Exercise the application lifecycle with private Git publication and real state owners."""
    from evertree.core import environment
    from evertree.core.environment import RuntimeEnvironmentError

    backup = await agent.backup()
    saved = agent.backups.read(backup)["core"]["environment"]
    assert not (backup / "dependencies").exists()
    assert not (agent.state_dir / "core-runtime").exists()
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


pytestmark = pytest.mark.usefixtures("offline_application")
