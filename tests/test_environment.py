from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

import pytest

from evertree.core import environment
from evertree.core.backup import rename_state
from evertree.core.environment import (
    RuntimeEnvironmentError,
    prepare_runtime_bundle,
    validate_runtime_bundle,
)


@pytest.fixture
def sources(tmp_path, monkeypatch):
    root = tmp_path / "evertree"
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
    return root


def test_bundle_captures_only_source_and_frozen_runtime_and_reuses_fingerprint(sources, tmp_path):
    manifest, bundle = prepare_runtime_bundle(sources, tmp_path / "cache")
    assert bundle.name == manifest["fingerprint"]
    assert set(manifest["source_files"]) == {
        "src/evertree/__init__.py",
        "src/evertree/core/trusted.py",
    }
    assert json.loads((bundle / "environment.json").read_text()) == manifest
    assert (bundle / ".python-version").read_text().strip() == manifest["python"]["version"]
    assert "dependency==1.2.3" in (bundle / "requirements.txt").read_text()
    assert not any("secret" in path.read_text() for path in bundle.rglob("*") if path.is_file())
    assert prepare_runtime_bundle(sources, tmp_path / "cache") == (manifest, bundle)
    validate_runtime_bundle(bundle, manifest, sources)


@pytest.mark.parametrize("change", ["source", "packages", "python"])
def test_restore_rejects_different_installed_runtime_without_overwriting_it(
    sources, tmp_path, monkeypatch, change
):
    manifest, bundle = prepare_runtime_bundle(sources, tmp_path / "cache")
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
        validate_runtime_bundle(bundle, manifest, sources)
    assert source.read_bytes() == before


def test_bundle_tampering_is_rejected(sources, tmp_path):
    manifest, bundle = prepare_runtime_bundle(sources, tmp_path / "cache")
    (bundle / "src/evertree/core/trusted.py").write_text("VERSION = 999\n", encoding="utf-8")
    with pytest.raises(RuntimeEnvironmentError, match="hash mismatch"):
        validate_runtime_bundle(bundle, manifest, sources)
    with pytest.raises(RuntimeEnvironmentError, match="hash mismatch"):
        prepare_runtime_bundle(sources, tmp_path / "cache")


def test_runtime_dependency_closure_includes_sdk_binary_and_transitive_extras():
    packages = environment._installed_packages()
    for name in (
        "evertree",
        "dbos",
        "pydantic",
        "openai-codex",
        "openai-codex-cli-bin",
        "websockets",
        "psycopg-binary",
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
