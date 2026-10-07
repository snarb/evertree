from pathlib import Path

import pytest

from evertree.core.programs.layout import PREFIX


def test_independent_layout_gate_runs_before_candidate_evaluator(tmp_path):
    """A real candidate repository proves layout validation precedes evaluation."""
    from evertree.core.evaluation.acceptance import AcceptanceCriteria
    from evertree.core.programs.lifecycle import ProgramLifecycleRuntime, git
    from tests.support.runtime import commit_programs

    repository = tmp_path / "programs"
    path = PREFIX + "example/_exec.py"
    commit_programs(repository, {path: "def run(): return 1"})
    calls = []

    def reject(branch, revision):
        calls.append((branch.id, revision))
        raise ValueError("layout drift")

    runtime = ProgramLifecycleRuntime(
        repository, tmp_path / "lifecycle", AcceptanceCriteria(("tests",)), validate_layout=reject
    )
    branch = runtime.create_candidate(
        "program/with space", "Improve result", candidate_name="preserve inputs"
    )
    assert branch.git_ref == "codex/program/program/with%20space/preserve-inputs"
    workspace = Path(branch.workspace)
    (workspace / path).write_text("def run(): return 2")
    git(workspace, "add", ".")
    git(workspace, "commit", "-m", "Candidate")
    with pytest.raises(ValueError, match="layout drift"):
        runtime._validate_candidate(branch)
    assert calls == [(branch.id, git(workspace, "rev-parse", "HEAD"))]
    assert git(repository, "show", "main:" + path) == "def run(): return 1"
