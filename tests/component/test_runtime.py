from __future__ import annotations

from pathlib import Path

import pytest

from evertree.core.runtime import ProgramSpec, Runtime


def test_private_cache_publication_retries_sharing_violation(tmp_path, monkeypatch):
    from evertree.core.backup import _extended, rename_state

    target = tmp_path / "cache-key"
    staging = _extended(tmp_path / "cache-key.preparing-test")
    staging.mkdir()
    (staging / ".complete").write_text("verified-cache")
    rename = Path.rename
    attempts = 0

    def temporarily_locked(path, destination):
        nonlocal attempts
        if path == staging:
            attempts += 1
            if attempts == 1:
                error = OSError("Transient scanner file lock")
                error.winerror = 32
                raise error
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", temporarily_locked)
    rename_state(staging, target)
    assert attempts == 2 and (target / ".complete").read_text() == "verified-cache"


async def test_gateway_uses_registered_metadata_and_rejects_later_program_fields(tmp_path):
    from dataclasses import asdict

    spec = ProgramSpec("program", "program.py", "0" * 40, role="model")

    async def gateway(method, payload):
        assert payload["_runtime"]["program"] == asdict(spec)
        assert payload["_runtime"]["task_id"] == "task"
        return 7

    runtime = Runtime(tmp_path / "runtime", tmp_path / "repo", gateway)
    runtime._active = {
        "task_id": "task",
        "program": spec,
        "run_id": "root",
        "run_mode": "evaluation",
        "cancelled": False,
        "known_runs": {"root": asdict(spec)},
    }
    try:
        assert await runtime._dispatch({"run_id": "root", "method": "read_value"}) == 7
        with pytest.raises(PermissionError, match="only accepted when registering"):
            await runtime._dispatch(
                {
                    "run_id": "root",
                    "method": "read_value",
                    "program": {**asdict(spec), "role": "exec"},
                }
            )
        with pytest.raises(PermissionError, match="not admitted"):
            await runtime._dispatch({"run_id": "unregistered", "method": "read_value"})
    finally:
        runtime._active = None
        await runtime.close()
