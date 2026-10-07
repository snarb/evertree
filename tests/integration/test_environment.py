from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from evertree.core import environment
from evertree.core.environment import (
    RuntimeEnvironmentError,
    capture_runtime,
    require_committed_runtime,
    validate_runtime,
)


@pytest.fixture
def sources(tmp_path, monkeypatch, program_remote):
    repository = tmp_path / "runtime-repository"
    root = repository / "evertree"
    (root / "core").mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "core" / "trusted.py").write_text("VERSION = 1\n", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "ignored.py").write_text("cached content", encoding="utf-8")
    (root / ".env").write_text("secret=do-not-copy", encoding="utf-8")
    (root / "auth.json").write_text('{"token":"do-not-copy"}', encoding="utf-8")
    monkeypatch.setattr(
        environment, "_installed_packages", lambda: {"evertree": "0.1.0", "dependency": "1.2.3"}
    )
    from evertree.core.programs.lifecycle import git

    git(repository, "init", "-b", "main")
    git(repository, "config", "user.name", "Test")
    git(repository, "config", "user.email", "test@localhost")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "Runtime fixture")
    git(repository, "remote", "add", "origin", program_remote)
    git(
        repository,
        "push",
        "-u",
        "origin",
        "HEAD:refs/heads/fixtures/" + uuid4().hex,
    )
    return root


def test_runtime_records_fingerprint_without_copying_source(sources, tmp_path):
    """Use committed repositories to verify runtime provenance and publication checks."""
    manifest = capture_runtime(sources)
    assert set(manifest["source_files"]) == {
        "src/evertree/__init__.py",
        "src/evertree/core/trusted.py",
    }
    assert len(manifest["revision"]) == 40
    assert "secret" not in json.dumps(manifest)
    assert capture_runtime(sources) == manifest
    validate_runtime(manifest, sources)
    assert not (tmp_path / "cache").exists()
    require_committed_runtime(sources)


@pytest.mark.parametrize("change", ["source", "packages", "python"])
def test_restore_rejects_different_installed_runtime_without_overwriting_it(
    sources, tmp_path, monkeypatch, change
):
    """Use committed repositories to verify runtime provenance and publication checks."""
    manifest = capture_runtime(sources)
    source = sources / "core" / "trusted.py"
    if change == "source":
        source.write_text("VERSION = 2\n", encoding="utf-8")
    elif change == "packages":
        monkeypatch.setattr(
            environment, "_installed_packages", lambda: {"evertree": "0.1.0", "dependency": "2.0.0"}
        )
    else:
        monkeypatch.setattr(environment.platform, "python_version", lambda: "3.13.99")
    before = source.read_bytes()
    with pytest.raises(RuntimeEnvironmentError, match="Runtime mismatch"):
        validate_runtime(manifest, sources)
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "relative, staged",
    [
        ("evertree/core/trusted.py", False),
        ("evertree/core/new.py", False),
        ("pyproject.toml", True),
        ("uv.lock", False),
        (".python-version", False),
    ],
)
def test_uncommitted_runtime_is_rejected(sources, relative, staged):
    """Use committed repositories to verify runtime provenance and publication checks."""
    from evertree.core.programs.lifecycle import git

    (sources.parent / relative).write_text("changed\n", encoding="utf-8")
    if staged:
        git(sources.parent, "add", relative)
    with pytest.raises(RuntimeEnvironmentError, match="Commit runtime"):
        require_committed_runtime(sources)


def test_deleted_remote_branch_cannot_pass_via_stale_local_refs(sources, program_remote):
    """Use committed repositories to verify runtime provenance and publication checks."""
    from evertree.core.programs.lifecycle import git, remote_git

    branch = git(sources.parent, "config", "--get", "branch.main.merge")
    remote_git(Path(program_remote), "update-ref", "-d", branch)
    assert git(sources.parent, "branch", "--remotes", "--contains", "HEAD")
    with pytest.raises(RuntimeEnvironmentError, match="Push the runtime commit"):
        require_committed_runtime(sources)


async def test_application_rejects_dirty_runtime_before_creating_program_repository(
    sources, tmp_path, monkeypatch
):
    """Use committed repositories to verify runtime provenance and publication checks."""
    from evertree import application
    from evertree.core.provider import ScriptedProvider

    (sources / "core/trusted.py").write_text("VERSION = 999\n", encoding="utf-8")
    monkeypatch.setattr(application, "__file__", str(sources / "application.py"))
    monkeypatch.setattr(application, "require_committed_runtime", require_committed_runtime)
    app = application.EverTree(tmp_path / "agent", provider=ScriptedProvider([]))
    with pytest.raises(RuntimeEnvironmentError, match="Commit runtime"):
        await app.start()
    assert not app.repository.exists()
    assert app.runtime is None
    assert app._lock_file is None


def test_local_only_runtime_commit_is_rejected(sources):
    """Use committed repositories to verify runtime provenance and publication checks."""
    from evertree.core.programs.lifecycle import git

    (sources / "core/trusted.py").write_text("VERSION = 2\n")
    git(sources.parent, "add", ".")
    git(sources.parent, "commit", "-m", "Not published")
    with pytest.raises(RuntimeEnvironmentError, match="Push the runtime commit"):
        require_committed_runtime(sources)
