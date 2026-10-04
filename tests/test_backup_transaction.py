"""One restore transaction owns dependencies, run journals and core state."""

import asyncio
import json
import threading
from contextlib import asynccontextmanager

import pytest

from evertree.core import backup as module
from evertree.core.backup import BackupManager


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
    dependencies = {name: tmp_path / name for name in ("repository", "workspaces")}
    roots = [runtime.state_dir / "runs", *dependencies.values()]
    for root in roots:
        root.mkdir(parents=True)
        (root / "value.txt").write_text("saved", encoding="utf-8")
    core = {"value": "saved"}
    manager = BackupManager(tmp_path / "backups")
    saved = await manager.create(runtime, lambda: dict(core), dependencies=dependencies)
    for root in roots:
        (root / "value.txt").write_text("current", encoding="utf-8")
    core["value"] = runtime.marker = "current"
    return manager, saved, runtime, dependencies, roots, core


async def test_restore_verifies_once_and_swaps_all_owned_state(tmp_path, monkeypatch):
    manager, saved, runtime, dependencies, roots, core = await setup(tmp_path)
    checks = []
    checksum = module._checksum

    def count(path):
        checks.append(path)
        return checksum(path)

    monkeypatch.setattr(module, "_checksum", count)
    manifest = json.loads((saved / "manifest.json").read_text())

    def validate(verified):
        assert verified.state["core"] == {"value": "saved"}
        assert verified.dependency("repository").is_dir()
        assert verified.dependency("workspaces").is_dir()

    await manager.restore(
        runtime,
        core.update,
        snapshot_core=lambda: dict(core),
        backup=saved,
        dependencies=dependencies,
        validate=validate,
    )
    assert len(checks) == len(manifest["files"])
    assert core == {"value": "saved"} and runtime.marker == "saved"
    assert all((root / "value.txt").read_text() == "saved" for root in roots)
    assert not list(tmp_path.rglob("*.previous-*"))
    assert not list(tmp_path.rglob("*.restoring-*"))


@pytest.mark.parametrize("failure", ["stage", "rename", "core", "runtime"])
async def test_restore_failure_rolls_back_every_directory_and_state_owner(
    tmp_path, monkeypatch, failure
):
    manager, saved, runtime, dependencies, roots, core = await setup(tmp_path)
    copy, rename = module.copy_state, module.rename_state

    def copy_or_fail(source, destination):
        if failure == "stage" and destination.name.startswith("workspaces.restoring-"):
            raise RuntimeError("stage failed")
        copy(source, destination)

    def rename_or_fail(source, destination):
        if failure == "rename" and source.name.startswith("workspaces.restoring-"):
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
            dependencies=dependencies,
        )
    assert core == {"value": "current"} and runtime.marker == "current"
    assert all((root / "value.txt").read_text() == "current" for root in roots)
    assert not list(tmp_path.rglob("*.previous-*"))
    assert not list(tmp_path.rglob("*.restoring-*"))


async def test_cancelled_restore_waits_for_staging_copy_before_cleanup(tmp_path, monkeypatch):
    manager, saved, runtime, dependencies, roots, core = await setup(tmp_path)
    copying, release = threading.Event(), threading.Event()
    copy = module.copy_state

    def slow_copy(source, destination):
        if destination.name.startswith("workspaces.restoring-"):
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
            dependencies=dependencies,
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
    assert all((root / "value.txt").read_text() == "current" for root in roots)
    assert not list(tmp_path.rglob("*.restoring-*"))


async def test_failed_core_rollback_still_restores_runtime(tmp_path):
    manager, saved, runtime, dependencies, roots, core = await setup(tmp_path)
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
            dependencies=dependencies,
        )
    assert [str(error) for error in caught.value.exceptions] == [
        "runtime restore failed",
        "core rollback failed",
    ]
    assert runtime.marker == "current"
    assert all((root / "value.txt").read_text() == "current" for root in roots)


async def test_cancellation_after_os_rename_restores_original_directory(tmp_path, monkeypatch):
    manager, saved, runtime, dependencies, roots, core = await setup(tmp_path)
    renamed, release = threading.Event(), threading.Event()
    rename = module.rename_state

    def pause_after_rename(source, destination):
        rename(source, destination)
        if destination.name.startswith("runs.previous-"):
            renamed.set()
            assert release.wait(10)

    monkeypatch.setattr(module, "rename_state", pause_after_rename)
    restore = asyncio.create_task(
        manager.restore(
            runtime,
            core.update,
            snapshot_core=lambda: dict(core),
            backup=saved,
            dependencies=dependencies,
        )
    )
    assert await asyncio.to_thread(renamed.wait, 10)
    restore.cancel()
    await asyncio.sleep(0.01)
    assert not restore.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await restore
    assert all((root / "value.txt").read_text() == "current" for root in roots)
    assert core == {"value": "current"} and runtime.marker == "current"
    assert not list(tmp_path.rglob("*.previous-*"))
