import asyncio
import json
import os
import subprocess
from functools import partial
from pathlib import Path

import pytest

from evertree.application import EverTree
from evertree.core.backup import _extended, safe_remove_tree
from evertree.core.provider import AgentEvent, ScriptedProvider
from evertree.core.runtime import Runtime
from tests.support.runtime import TestProcess


class WorkspaceProvider(ScriptedProvider):
    async def run(self, request_id, request, **kwargs):
        assert request.native_coding and request.mode == "exec"
        self.requests.append(request)
        for relative, contents in json.loads(request.prompt).items():
            target = _extended(request.workspace / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
            yield AgentEvent("file_change", {"path": str(target)})
        yield AgentEvent("completed", {"text": "Workspace files written"})


@pytest.fixture
async def agent(tmp_path):
    async with EverTree(
        tmp_path / "agent",
        provider=WorkspaceProvider([]),
        runtime_factory=partial(Runtime, process_factory=TestProcess),
    ) as app:
        yield app


def task_for(agent):
    task = agent.tasks.create_task("Create a local coding artifact")
    agent.tasks.assign_budget(task.id, {"active_time_minutes": 3}, 0, reason="Small coding task")
    return task


async def write_code(agent, task, files):
    return await agent._tool(task.id, "work_on_code", {"instruction": json.dumps(files)})


@pytest.mark.parametrize("current_missing", [False, True])
async def test_work_on_code_files_and_long_paths_restore_with_task_state(agent, current_missing):
    """Use real workspace, repository, and backup operations to verify restoration or failure cleanup."""
    task = task_for(agent)
    deep = Path("generated") / ("a" * 80) / ("b" * 80) / "saved.py"
    await write_code(agent, task, {"answer.py": "answer = 42\n", deep.as_posix(): "version = 1\n"})
    workspace = agent.state_dir / "workspaces" / task.id
    assert len(str(workspace / deep)) > 260
    saved = await agent.backup()
    assert not (saved / "dependencies").exists()
    assert not list(saved.rglob("*.py"))
    await write_code(agent, task, {"answer.py": "answer = 0\n", deep.as_posix(): "version = 2\n"})
    later = task_for(agent)
    await write_code(agent, later, {"later.txt": "not in this backup"})
    if current_missing:
        safe_remove_tree(agent.state_dir / "workspaces", agent.state_dir)
    await agent.restore(saved)
    assert not workspace.exists()
    assert any("Temporary files" in item["content"] for item in agent._inputs[task.id])
    assert not (agent.state_dir / "workspaces" / later.id).exists()
    assert [state.id for state in agent.tasks.all()] == [task.id]


async def test_restore_backup_before_any_workspace_removes_later_outputs(agent):
    """Use real workspace, repository, and backup operations to verify restoration or failure cleanup."""
    root = agent.state_dir / "workspaces"
    assert not root.exists()
    saved = await agent.backup()
    task = task_for(agent)
    await write_code(agent, task, {"later.py": "created after backup\n"})
    assert (root / task.id / "later.py").exists()
    await agent.restore(saved)
    assert not root.exists()
    assert not agent.tasks.all()


async def test_failed_journal_restore_rolls_back_workspace_swap(agent, monkeypatch):
    """Use real workspace, repository, and backup operations to verify restoration or failure cleanup."""
    task = task_for(agent)
    await write_code(agent, task, {"artifact.txt": "saved"})
    saved = await agent.backup()
    await write_code(agent, task, {"artifact.txt": "current"})
    current_core = agent.snapshot()

    async def fail(*args, **kwargs):
        raise OSError("Journal restore failed")

    monkeypatch.setattr(agent.backups, "restore", fail)
    with pytest.raises(OSError, match="Journal restore failed"):
        await agent.restore(saved)
    assert (agent.state_dir / "workspaces" / task.id / "artifact.txt").read_text() == "current"
    assert agent.graph.snapshot() == current_core["graph"]
    assert agent.tasks.snapshot() == current_core["tasks"]


async def test_workspace_links_cannot_make_backup_read_outside_content(agent, tmp_path):
    """Use real workspace, repository, and backup operations to verify restoration or failure cleanup."""
    task = task_for(agent)
    await write_code(agent, task, {"artifact.txt": "safe"})
    saved = await agent.backup()
    external = tmp_path / "private"
    external.mkdir()
    (external / "canary.txt").write_text("must not enter backup", encoding="utf-8")
    link = agent.state_dir / "workspaces" / task.id / "linked-content"
    if os.name == "nt":
        await asyncio.to_thread(
            subprocess.run,
            ["cmd", "/d", "/c", "mklink", "/J", str(link), str(external)],
            capture_output=True,
            check=True,
        )
    else:
        link.symlink_to(external, target_is_directory=True)
    try:
        newer = await agent.backup()
        assert agent.backups.list() == [newer, saved]
        assert not any(
            path.name == "canary.txt" for path in _extended(agent.backups.root).rglob("*")
        )
    finally:
        link.rmdir() if os.name == "nt" else link.unlink()


async def test_restore_fetches_committed_artifact_after_local_repository_is_lost(agent):
    """Use real workspace, repository, and backup operations to verify restoration or failure cleanup."""
    from evertree.core.programs.lifecycle import git, remote_git

    artifact = agent.repository / "artifacts/result.txt"
    artifact.parent.mkdir()
    artifact.write_text("saved in Git")
    git(agent.repository, "add", "artifacts")
    git(agent.repository, "commit", "-m", "Keep useful result")
    revision = git(agent.repository, "rev-parse", "HEAD")
    await agent.close()
    remote = agent._program_remote
    assert remote_git(Path(remote), "rev-parse", "refs/heads/evertree/programs") == revision
    saved = agent.backups.list()[0]
    assert not list(saved.rglob("result.txt"))
    safe_remove_tree(agent.repository, agent.state_dir)
    async with EverTree(
        agent.directory,
        provider=WorkspaceProvider([]),
        runtime_factory=partial(Runtime, process_factory=TestProcess),
    ) as restored:
        assert git(restored.repository, "rev-parse", "main") == revision
        assert (restored.repository / "artifacts/result.txt").read_text() == "saved in Git"


async def test_failed_git_publication_keeps_previous_completed_backup(agent, tmp_path):
    """Use real workspace, repository, and backup operations to verify restoration or failure cleanup."""
    from evertree.core.programs.lifecycle import LifecycleError

    saved = await agent.backup()
    remote = agent._program_remote
    agent._program_remote = str(tmp_path / "missing-remote")
    try:
        with pytest.raises(LifecycleError):
            await agent.backup()
        assert agent.backups.list() == [saved]
        assert agent.backups.read(saved)["core"]["program_remote"] == remote
    finally:
        agent._program_remote = remote


async def test_restore_discards_candidate_ownership_from_later_work(agent):
    """Use real workspace, repository, and backup operations to verify restoration or failure cleanup."""
    task = task_for(agent)
    saved = await agent.backup()
    candidate = agent.lifecycle.create_candidate(
        agent._program("TaskFraming").program_id, "Disposable experiment"
    )
    agent._candidate_owners[candidate.id] = task.id
    await agent.restore(saved)
    assert not agent._candidate_owners
    assert not Path(candidate.workspace).exists()
    await agent._stop_task(agent.tasks.get(task.id), "cancelled", "No longer needed")


pytestmark = pytest.mark.usefixtures("offline_application")
