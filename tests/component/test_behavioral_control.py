import pytest

from evertree.core.actions import ActionGateway, ActionOption
from evertree.core.cognition import AttentionRuntime, TaskStore
from evertree.core.graph import (
    json_value,
)


class ActionFixture:
    def __init__(self, *, outcome="accepted", command=None):
        self.calls = []
        self.outcome = outcome
        self.command = command or {"type": "raise", "to": 100}

    async def list_actions(self):
        return [ActionOption(self.command)]

    async def execute(self, command):
        self.calls.append(command)
        if self.outcome == "unknown":
            raise OSError("Response lost after send")
        return self.outcome


def test_cog_03_switch_suspends_then_resumes_original_task_without_erasing_usage():
    tasks = TaskStore()
    first, second = tasks.create_task("A"), tasks.create_task("B")
    for task in (first, second):
        tasks.assign_budget(task.id, {"active_time_minutes": 10}, 0, reason="Fixture scope")
    attention = AttentionRuntime(tasks)
    attention.admit(first.id)
    first.progress = "First step completed"
    tasks.record_usage(first.id, "active_time_minutes", 2, operation_id="first-step")
    with pytest.raises(RuntimeError, match="confirmed stopped"):
        attention.admit(second.id, stop_current=lambda _: False)
    assert attention.running_task == first.id
    attention.admit(second.id, stop_current=lambda _: True)
    assert first.status == "suspended" and first.execution_stopped
    attention.admit(first.id, stop_current=lambda _: True)
    assert second.status == "suspended" and second.execution_stopped
    assert attention.focus == attention.running_task == first.id
    assert first.progress == "First step completed"
    assert first.remaining("active_time_minutes") == 8
    assert sum(task.status == "running" for task in tasks.all()) == 1


def test_cog_04_improvement_is_inside_total_budget_and_does_not_stop_main_work():
    tasks = TaskStore()
    task = tasks.create_task("Report")
    tasks.assign_budget(task.id, {"active_time_minutes": 100}, 20, reason="Requested report")
    tasks.record_usage(task.id, "active_time_minutes", 40, operation_id="main-work")
    tasks.record_usage(
        task.id, "active_time_minutes", 20, operation_id="improvement", self_improvement=True
    )
    assert task.spent == {"active_time_minutes": 60}
    assert task.remaining("active_time_minutes", self_improvement=True) == 0
    assert task.remaining("active_time_minutes") == 40
    AttentionRuntime(tasks).admit(task.id)
    assert task.status == "running"


async def test_act_04_changed_command_and_old_list_in_new_session_are_rejected():
    gateway, adapter = ActionGateway(), ActionFixture()
    gateway.bind("S1", adapter, task_id="task", commit="revision")
    await gateway.list("S1", task_id="task")
    with pytest.raises(ValueError, match="unchanged"):
        await gateway.take(
            "S1",
            {"type": "raise", "to": 200},
            task_id="task",
            operation_id="changed",
            approved=True,
        )
    gateway.bind("S2", adapter, task_id="task", commit="revision")
    with pytest.raises(ValueError, match="unchanged"):
        await gateway.take(
            "S2",
            {"type": "raise", "to": 100},
            task_id="task",
            operation_id="old-list",
            approved=True,
        )
    assert adapter.calls == []


async def test_act_06_unknown_operation_waits_for_reconciliation_across_restore():
    gateway, adapter = ActionGateway(), ActionFixture(outcome="unknown")
    gateway.bind("S1", adapter, task_id="task", commit="revision")
    issued = (await gateway.list("S1", task_id="task"))[0]["command"]
    assert (
        await gateway.take("S1", issued, task_id="task", operation_id="send", approved=True)
        == "unknown"
    )
    restored = ActionGateway.from_snapshot(gateway.snapshot())
    restored.bind("S1", adapter, task_id="task", commit="revision")
    assert (
        await restored.take("S1", issued, task_id="task", operation_id="send", approved=True)
        == "unknown"
    )
    assert len(adapter.calls) == 1
    assert restored.pending("task")
    restored.reconcile("send", "accepted", evidence="Source confirmed receipt")
    assert (
        await restored.take("S1", issued, task_id="task", operation_id="send", approved=True)
        == "accepted"
    )
    assert len(adapter.calls) == 1
    assert restored.pending("task") == []


async def test_act_05_command_acceptance_does_not_observe_effect_or_complete_task(app):
    async def approve(_):
        return True

    app.approval_handler = approve
    task = app.tasks.create_task("Move the object")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 5}, 0, reason="Move fixture")
    command = {"type": "move", "object": "box", "to": "shelf"}
    adapter = ActionFixture(command=command)
    app.actions.bind("S1", adapter, task_id=task.id, commit="revision")
    await app.actions.list("S1", task_id=task.id)
    observations = set(app._observations)
    result = await app._gateway(
        "actions.take",
        {
            "session": "S1",
            "command": command,
            "operation_id": "move",
            "_runtime": {"task_id": task.id, "run_mode": "live", "program": {"role": "exec"}},
        },
    )
    assert result == "accepted"
    assert len(adapter.calls) == 1
    assert app._observations == observations
    assert not task.terminal


@pytest.mark.parametrize("claimed_backing", [False, True])
async def test_bel_08_recorded_observation_does_not_validate_program_likelihood_model(
    app, claimed_backing
):
    """BEL-08 integration: provenance proves an observation, not model calibration."""
    task = app.tasks.create_task("Assess a sensor")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 5}, 0, reason="Evidence fixture")
    for index in range(2):
        source = app.observe("light", source_id=f"observation-{index}", task_id=task.id)
        await app._gateway(
            "evidence.assess",
            {
                "target": "lamp-on",
                "source_ref": json_value(source),
                "likelihoods": {"false": 0.2, "true": 0.8},
                "backed": claimed_backing,
                "_runtime": {
                    "task_id": task.id,
                    "run_id": "evidence-fixture",
                    "run_mode": "live",
                    "program": {"role": "exec", "revision": "fixture"},
                },
            },
        )
    reading = app.beliefs.read("lamp-on")
    assert reading.strength == pytest.approx(0.75)
    assert reading.prior_support == 0
