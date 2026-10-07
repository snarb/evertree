import json

import pytest

from evertree.core.backup import _extended
from evertree.core.provider import AgentEvent, ScriptedProvider


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


def task_for(agent):
    task = agent.tasks.create_task("Create a local coding artifact")
    agent.tasks.assign_budget(task.id, {"active_time_minutes": 3}, 0, reason="Small coding task")
    return task


async def write_code(agent, task, files):
    return await agent._tool(task.id, "work_on_code", {"instruction": json.dumps(files)})


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
async def test_terminal_task_discards_its_workspace(agent, status):
    """Terminal state cleanup removes real temporary files without creating a Git candidate."""
    from evertree.core.evaluation.acceptance import VerificationResult

    agent.provider = WorkspaceProvider([])
    task = task_for(agent)
    await write_code(agent, task, {"temporary.txt": "discard me"})
    workspace = agent.state_dir / "workspaces" / task.id
    await agent._stop_task(task, status, "finished", VerificationResult("verified"))
    assert not workspace.exists()
    assert agent.tasks.get(task.id).status == status


async def test_provider_close_failure_still_discards_workspaces(agent, monkeypatch):
    """Provider failure must still clean real workspace and candidate directories."""
    agent.provider = WorkspaceProvider([])
    task = task_for(agent)
    await write_code(agent, task, {"temporary.txt": "discard me"})
    candidate_dir = agent.state_dir / "lifecycle" / "candidates" / "temporary"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "draft.py").write_text("temporary")

    async def fail():
        raise RuntimeError("Provider close failed")

    monkeypatch.setattr(agent.provider, "close", fail)
    with pytest.raises(RuntimeError, match="Provider close failed"):
        await agent.close()
    assert not (agent.state_dir / "workspaces").exists()
    assert not candidate_dir.exists()
    assert agent._lock_file is None
