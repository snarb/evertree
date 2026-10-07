from __future__ import annotations

from pathlib import Path

from evertree.core.programs.lifecycle import (
    git,
    initialize_seed_repository,
)


def seed_repository(tmp_path):
    source = tmp_path / "seed"
    program = source / "src" / "evertree" / "processes" / "example.py"
    program.parent.mkdir(parents=True)
    program.write_text("def run(): return {'result': 1}\n", encoding="utf-8")
    repo = tmp_path / "repository"
    initialize_seed_repository(source, repo)
    return repo


def change(
    candidate,
    relative="src/evertree/processes/example.py",
    text="def run(): return {'result': 2}\n",
):
    workspace = Path(candidate.workspace)
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(workspace, "add", ".")
    git(workspace, "commit", "-m", "Candidate")
    return git(workspace, "rev-parse", "HEAD")
