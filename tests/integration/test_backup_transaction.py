import asyncio
import json
import threading
from contextlib import asynccontextmanager

import pytest

from evertree.core import backup as module
from evertree.core.backup import BackupError, BackupManager
from evertree.core.serialization import decode_snapshot, encode_snapshot


class StoppedRuntime:
    def __init__(self, root):
        self.state_dir = root
        self.marker = "saved"
        self.fail_restore = False

    def is_running(self):
        return False

    def snapshot(self):
        return {"marker": self.marker}

    def restore(self, snapshot):
        self.marker = snapshot["marker"]
        if self.fail_restore:
            self.fail_restore = False
            raise RuntimeError("runtime restore failed")

    @asynccontextmanager
    async def quiesce(self, **kwargs):
        yield


async def setup(tmp_path):
    runtime = StoppedRuntime(tmp_path / "runtime")
    roots = [runtime.state_dir / "journals" / "test"]
    for root in roots:
        root.mkdir(parents=True)
        (root / "core_runs.json").write_text("saved", encoding="utf-8")
    core = {"value": "saved"}
    manager = BackupManager(tmp_path / "backups")
    saved = await manager.create(runtime, lambda: dict(core))
    for root in roots:
        (root / "core_runs.json").write_text("current", encoding="utf-8")
    core["value"] = runtime.marker = "current"
    return manager, saved, runtime, roots, core


async def test_restore_verifies_once_and_swaps_all_owned_state(tmp_path, monkeypatch):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, saved, runtime, roots, core = await setup(tmp_path)
    checks = []
    checksum = module._checksum

    def count(path):
        checks.append(path)
        return checksum(path)

    monkeypatch.setattr(module, "_checksum", count)
    manifest = json.loads((saved / "manifest.json").read_text())

    def validate(verified):
        assert verified.state["core"] == {"value": "saved"}
        assert (verified.path / "journals/test").is_dir()
        assert not (verified.path / "dependencies").exists()

    await manager.restore(
        runtime,
        core.update,
        snapshot_core=lambda: dict(core),
        backup=saved,
        validate=validate,
    )
    assert len(checks) == len(manifest["files"])
    assert core == {"value": "saved"} and runtime.marker == "saved"
    assert all((root / "core_runs.json").read_text() == "saved" for root in roots)
    assert not list(tmp_path.rglob("*.previous-*"))
    assert not list(tmp_path.rglob("*.restoring-*"))


@pytest.mark.parametrize("failure", ["stage", "rename", "core", "runtime"])
async def test_restore_failure_rolls_back_every_directory_and_state_owner(
    tmp_path, monkeypatch, failure
):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, saved, runtime, roots, core = await setup(tmp_path)
    copy, rename = module.copy_state, module.rename_state

    def copy_or_fail(source, destination):
        if failure == "stage" and destination.name.startswith("journals.restoring-"):
            raise RuntimeError("stage failed")
        copy(source, destination)

    def rename_or_fail(source, destination):
        if failure == "rename" and source.name.startswith("journals.restoring-"):
            raise RuntimeError("rename failed")
        rename(source, destination)

    def restore_core(snapshot):
        core.update(snapshot)
        if failure == "core" and core["value"] == "saved":
            raise RuntimeError("core failed")

    monkeypatch.setattr(module, "copy_state", copy_or_fail)
    monkeypatch.setattr(module, "rename_state", rename_or_fail)
    runtime.fail_restore = failure == "runtime"
    with pytest.raises(RuntimeError, match="failed"):
        await manager.restore(
            runtime,
            restore_core,
            snapshot_core=lambda: dict(core),
            backup=saved,
        )
    assert core == {"value": "current"} and runtime.marker == "current"
    assert all((root / "core_runs.json").read_text() == "current" for root in roots)
    assert not list(tmp_path.rglob("*.previous-*"))
    assert not list(tmp_path.rglob("*.restoring-*"))


async def test_cancelled_restore_waits_for_staging_copy_before_cleanup(tmp_path, monkeypatch):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, saved, runtime, roots, core = await setup(tmp_path)
    copying, release = threading.Event(), threading.Event()
    copy = module.copy_state

    def slow_copy(source, destination):
        if destination.name.startswith("journals.restoring-"):
            copying.set()
            assert release.wait(10)
        copy(source, destination)

    monkeypatch.setattr(module, "copy_state", slow_copy)
    restore = asyncio.create_task(
        manager.restore(
            runtime,
            core.update,
            snapshot_core=lambda: dict(core),
            backup=saved,
        )
    )
    assert await asyncio.to_thread(copying.wait, 10)
    restore.cancel()
    await asyncio.sleep(0.01)
    assert not restore.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await restore
    assert core == {"value": "current"} and runtime.marker == "current"
    assert all((root / "core_runs.json").read_text() == "current" for root in roots)
    assert not list(tmp_path.rglob("*.restoring-*"))


async def test_failed_core_rollback_still_restores_runtime(tmp_path):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, saved, runtime, roots, core = await setup(tmp_path)
    runtime.fail_restore = True

    def restore_core(snapshot):
        if snapshot["value"] == "current":
            raise RuntimeError("core rollback failed")
        core.update(snapshot)

    with pytest.raises(ExceptionGroup, match="rollback is incomplete") as caught:
        await manager.restore(
            runtime,
            restore_core,
            snapshot_core=lambda: dict(core),
            backup=saved,
        )
    assert [str(error) for error in caught.value.exceptions] == [
        "runtime restore failed",
        "core rollback failed",
    ]
    assert runtime.marker == "current"
    assert all((root / "core_runs.json").read_text() == "current" for root in roots)


async def test_cancellation_after_os_rename_restores_original_directory(tmp_path, monkeypatch):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, saved, runtime, roots, core = await setup(tmp_path)
    renamed, release = threading.Event(), threading.Event()
    rename = module.rename_state

    def pause_after_rename(source, destination):
        rename(source, destination)
        if destination.name.startswith("journals.previous-"):
            renamed.set()
            assert release.wait(10)

    monkeypatch.setattr(module, "rename_state", pause_after_rename)
    restore = asyncio.create_task(
        manager.restore(
            runtime,
            core.update,
            snapshot_core=lambda: dict(core),
            backup=saved,
        )
    )
    assert await asyncio.to_thread(renamed.wait, 10)
    restore.cancel()
    await asyncio.sleep(0.01)
    assert not restore.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await restore
    assert all((root / "core_runs.json").read_text() == "current" for root in roots)
    assert core == {"value": "current"} and runtime.marker == "current"
    assert not list(tmp_path.rglob("*.previous-*"))


async def test_next_backup_removes_abandoned_copy_and_preserves_completed_backup(tmp_path):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, saved, runtime, _roots, core = await setup(tmp_path)
    abandoned = manager.root / "interrupted.pending"
    abandoned.mkdir()
    (abandoned / "partial").write_text("incomplete")
    newer = await manager.create(runtime, lambda: dict(core))
    assert not abandoned.exists()
    assert manager.read(saved)["core"] == {"value": "saved"}
    assert manager.read(newer)["core"] == {"value": "current"}


async def test_backup_writes_compressed_state_covered_by_manifest(tmp_path):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, _saved, runtime, _roots, _core = await setup(tmp_path)
    state = {"text": "Повторяющийся опыт 🌳" * 10000, "number": 2**100, "flag": True}
    saved = await manager.create(runtime, lambda: state)
    path = saved / "state.msgpack.zst"
    assert path.stat().st_size < 10000
    assert not (saved / "state.json").exists()
    assert decode_snapshot(path.read_bytes()) == {"core": state, "runtime": runtime.snapshot()}
    manifest = json.loads((saved / "manifest.json").read_text())
    assert manifest["format"] == 3
    assert manifest["files"][path.name] == module._checksum(path)
    assert manager.read(saved)["core"] == state


async def test_backup_ignores_working_files_even_inside_journal_directories(tmp_path):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, _saved, runtime, _roots, core = await setup(tmp_path)
    for relative in (
        "runs/source.py",
        "journals/test/scratch.py",
        "journals/test/dbos/extra.sqlite",
    ):
        path = runtime.state_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not durable state")
    saved = await manager.create(runtime, lambda: core)
    files = {path.relative_to(saved).as_posix() for path in saved.rglob("*") if path.is_file()}
    assert files == {"state.msgpack.zst", "manifest.json", "journals/test/core_runs.json"}


@pytest.mark.parametrize("payload", [b"damaged", encode_snapshot({"core": []})])
async def test_invalid_compressed_state_is_rejected_before_restore_swaps(tmp_path, payload):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, saved, runtime, roots, core = await setup(tmp_path)
    path = saved / "state.msgpack.zst"
    path.write_bytes(payload)
    manifest_path = saved / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][path.name] = module._checksum(path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(BackupError, match="Invalid backup state"):
        await manager.restore(
            runtime,
            core.update,
            snapshot_core=lambda: dict(core),
            backup=saved,
        )
    assert core == {"value": "current"} and runtime.marker == "current"
    assert all((root / "core_runs.json").read_text() == "current" for root in roots)
    assert not list(tmp_path.rglob("*.restoring-*"))


async def test_previous_backup_format_is_explicitly_rejected(tmp_path):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, saved, _runtime, _roots, _core = await setup(tmp_path)
    path = saved / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["format"] = 1
    path.write_text(json.dumps(manifest))
    with pytest.raises(BackupError, match="Unsupported or incomplete backup"):
        manager.read(saved)


async def test_encoding_failure_keeps_previous_backup_readable(tmp_path):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, saved, runtime, _roots, _core = await setup(tmp_path)
    with pytest.raises(ValueError, match="Non-finite"):
        await manager.create(runtime, lambda: {"nested": [float("nan")]})
    assert manager.list() == [saved]
    assert manager.read(saved)["core"] == {"value": "saved"}
    newer = await manager.create(runtime, lambda: {"value": "new"})
    assert manager.read(newer)["core"] == {"value": "new"}
    assert not list(manager.root.glob("*.pending"))


async def test_failed_restore_keeps_arbitrary_precision_current_state(tmp_path):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, saved, runtime, roots, core = await setup(tmp_path)
    core["value"] = 2**20000
    runtime.fail_restore = True
    with pytest.raises(RuntimeError, match="runtime restore failed"):
        await manager.restore(
            runtime,
            core.update,
            snapshot_core=lambda: dict(core),
            backup=saved,
        )
    assert core["value"] == 2**20000 and runtime.marker == "current"
    assert all((root / "core_runs.json").read_text() == "current" for root in roots)


async def test_cancelled_backup_waits_for_encoding_before_leaving_boundary(tmp_path, monkeypatch):
    """Exercise real filesystem staging and swaps to verify atomic persistence and rollback."""
    manager, saved, runtime, _roots, core = await setup(tmp_path)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    boundary_left = threading.Event()
    encode = module.encode_snapshot

    def slow_encode(value):
        entered.set()
        assert release.wait(3)
        encoded = encode(value)
        finished.set()
        return encoded

    @asynccontextmanager
    async def boundary(**kwargs):
        try:
            yield
        finally:
            boundary_left.set()

    monkeypatch.setattr(module, "encode_snapshot", slow_encode)
    monkeypatch.setattr(runtime, "quiesce", boundary)
    creation = asyncio.create_task(manager.create(runtime, lambda: dict(core)))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert not creation.done()
        creation.cancel()
        await asyncio.sleep(0.01)
        assert not creation.done()
        assert not boundary_left.is_set()
    finally:
        release.set()
        await asyncio.gather(creation, return_exceptions=True)
    assert creation.cancelled()
    assert finished.is_set() and boundary_left.is_set()
    assert manager.list() == [saved]
    assert manager.read(saved)["core"] == {"value": "saved"}
