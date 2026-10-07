from importlib import metadata
from pathlib import Path

import pytest

from evertree.core import environment
from evertree.core.backup import rename_state


def test_runtime_dependency_closure_includes_sdk_binary_and_transitive_extras():
    packages = environment._installed_packages()
    for name in (
        "evertree",
        "dbos",
        "msgpack",
        "pydantic",
        "openai-codex",
        "openai-codex-cli-bin",
        "websockets",
        "psycopg-binary",
        "zstandard",
    ):
        assert packages[name] == metadata.version(name)
    assert "pytest" not in packages


def test_state_rename_retries_transient_windows_lock(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    original = Path.rename
    attempts = []

    def locked_once(path, target):
        attempts.append((path, target))
        if len(attempts) == 1:
            error = PermissionError("Scanner still owns a directory handle")
            error.winerror = 5
            raise error
        return original(path, target)

    monkeypatch.setattr(Path, "rename", locked_once)
    rename_state(source, destination)
    assert len(attempts) == 2
    assert destination.is_dir()
    assert not source.exists()


def test_state_rename_retries_are_bounded(tmp_path, monkeypatch):
    from evertree.core import backup

    ticks = iter((0.0, 3.0))
    monkeypatch.setattr(backup.time, "monotonic", lambda: next(ticks))

    def locked(path, target):
        error = PermissionError("Persistent access denial")
        error.winerror = 5
        raise error

    monkeypatch.setattr(Path, "rename", locked)
    with pytest.raises(PermissionError, match="Persistent access denial"):
        rename_state(tmp_path / "source", tmp_path / "destination")
