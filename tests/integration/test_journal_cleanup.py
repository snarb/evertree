"""Journal retention across published backups and complete task trees."""

import json
import sqlite3

import pytest

from evertree.core import backup as backup_module
from evertree.core.backup import BackupManager
from evertree.core.cognition.tasks import TaskSpecification, TaskStore
from evertree.core.runtime.controller import Runtime


async def test_completed_tree_journals_are_removed_only_after_publication(tmp_path, monkeypatch):
    """Real SQLite backups prove failed publication retains recoverable execution history."""
    tasks = TaskStore()
    parent = tasks.create_task(TaskSpecification("Parent"))
    child = tasks.create_task(TaskSpecification("Child"), parent_task_id=parent.id)
    grandchild = tasks.create_task(TaskSpecification("Grandchild"), parent_task_id=child.id)
    unrelated = tasks.create_task(TaskSpecification("Unfinished"))
    runtime = Runtime(tmp_path / "runtime", tmp_path, None)
    manager = BackupManager(tmp_path / "backups")
    for state in (parent, child, grandchild, unrelated):
        directory = runtime.state_dir / "journals" / state.id
        (directory / "dbos").mkdir(parents=True)
        (directory / "worker.json").write_text(
            json.dumps({"run_id": state.id, "task_id": state.id}), encoding="utf-8"
        )
        with sqlite3.connect(directory / "dbos/dbos.sqlite") as connection:
            connection.execute("CREATE TABLE evidence (value TEXT)")
            connection.execute("INSERT INTO evidence VALUES ('retained')")

    async def save():
        return await manager.create(
            runtime, tasks.snapshot, completed_task_ids=tasks.completed_tree_ids()
        )

    for state in (parent, child):
        tasks.finish(state.id, "cancelled", reason="Done", execution_stopped=True)
        await runtime.finish_task(state.id)
    assert not tasks.completed_tree_ids()
    previous = await save()
    assert len(list((previous / "journals").iterdir())) == 4

    tasks.finish(grandchild.id, "failed", reason="Done", execution_stopped=True)
    await runtime.finish_task(grandchild.id)
    assert tasks.completed_tree_ids() == {parent.id, child.id, grandchild.id}
    rename = backup_module.rename_state

    def fail_publish(*args):
        raise OSError("Publication failed")

    monkeypatch.setattr(backup_module, "rename_state", fail_publish)
    with pytest.raises(OSError, match="Publication failed"):
        await save()
    assert len(list((runtime.state_dir / "journals").iterdir())) == 4
    assert manager.list() == [previous]

    monkeypatch.setattr(backup_module, "rename_state", rename)
    saved = await save()
    for root in (saved / "journals", runtime.state_dir / "journals"):
        assert {path.name for path in root.iterdir()} == {unrelated.id}
    assert len(list((previous / "journals").iterdir())) == 4
    verified = manager.verify(saved)
    assert {row["id"] for row in verified.state["core"]["tasks"]} == {
        parent.id,
        child.id,
        grandchild.id,
        unrelated.id,
    }
    await manager.restore(runtime, lambda state: None, snapshot_core=tasks.snapshot, backup=saved)
    assert {path.name for path in (runtime.state_dir / "journals").iterdir()} == {unrelated.id}


async def test_open_parent_and_unstopped_execution_keep_journals(tmp_path):
    """Task ancestry and runtime admission independently protect execution journals."""
    tasks = TaskStore()
    parent = tasks.create_task(TaskSpecification("Parent"))
    child = tasks.create_task(TaskSpecification("Child"), parent_task_id=parent.id)
    tasks.finish(child.id, "cancelled", reason="Done", execution_stopped=True)
    assert not tasks.completed_tree_ids()
    tasks.finish(parent.id, "cancelled", reason="Done", execution_stopped=True)
    parent.execution_stopped = False
    assert not tasks.completed_tree_ids()
    parent.execution_stopped = True
    runtime = Runtime(tmp_path / "runtime", tmp_path, None)
    directory = runtime.state_dir / "journals" / "run"
    directory.mkdir(parents=True)
    (directory / "worker.json").write_text(
        json.dumps({"run_id": "run", "task_id": parent.id}), encoding="utf-8"
    )
    assert not runtime.obsolete_journals(tasks.completed_tree_ids())
    await runtime.finish_task(parent.id)
    runtime._active = {"task_id": parent.id}
    assert not runtime.obsolete_journals(tasks.completed_tree_ids())
    runtime._active = None
    assert runtime.obsolete_journals(tasks.completed_tree_ids()) == {"run"}
