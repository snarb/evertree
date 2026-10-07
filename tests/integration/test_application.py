import asyncio
from functools import partial

import pytest

from evertree.application import EverTree
from evertree.core.provider import ScriptedProvider
from evertree.core.runtime.controller import Runtime
from tests.support.application import decision, framing, verification
from tests.support.runtime import TestProcess


async def test_backup_restart_preserves_waiting_task_and_original_budget(tmp_path):
    """Restart must restore task state and budgets from real application persistence."""
    home = tmp_path / "agent"
    first_provider = ScriptedProvider(
        [
            framing("Count a requested letter", minutes=8, improvement=5),
            decision("Which letter?", "waiting"),
        ]
    )
    async with EverTree(
        home, provider=first_provider, runtime_factory=partial(Runtime, process_factory=TestProcess)
    ) as first:
        waiting = await asyncio.wait_for(first.run("Count a letter in strawberry"), 60)
        assert waiting["status"] == "waiting", waiting
        identity = waiting["task_id"]
        # The completed backup is made at the queue's next safe boundary.
        await first._pump
        saved_usage = dict(first.tasks.get(identity).spent)
        assert first.backups.list()
    second_provider = ScriptedProvider([decision("3"), verification()])
    async with EverTree(
        home,
        provider=second_provider,
        runtime_factory=partial(Runtime, process_factory=TestProcess),
    ) as restored:
        task = restored.tasks.get(identity)
        assert task.status == "waiting"
        assert task.execution_budget.resources["active_time_minutes"] == 8
        assert task.self_improvement_budget == 5
        assert task.spent == saved_usage
        result = await asyncio.wait_for(restored.run("r", task_id=identity), 60)
        assert result["status"] == "succeeded", result
        assert result["task_id"] == identity
        assert len(second_provider.requests) == 2  # No reset or repeated framing.


pytestmark = pytest.mark.usefixtures("offline_application")
