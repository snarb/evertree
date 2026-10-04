"""Consistent whole-agent backups at durable-operation boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import shutil
import sqlite3
import stat
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedBackup:
    """A manifest verified once while the caller owns the recovery boundary."""

    path: Path
    state: dict

    def dependency(self, name: str) -> Path:
        if not name.isidentifier():
            raise ValueError("Invalid dependency name")
        path = self.path / "dependencies" / name
        if not path.is_dir():
            raise BackupError(f"Backup dependency not found: {name}")
        return path


def _extended(path: Path) -> Path:
    """CopyFile2 and directory APIs still need extended paths on some hosts."""
    path = Path(path).absolute()
    text = str(path)
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        return Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)
    return path


def safe_remove_tree(target: Path, root: Path) -> None:
    """Remove an owned subtree, including Git's read-only objects on Windows."""
    root, target = Path(root).resolve(), Path(target).resolve()
    if target == root or not target.is_relative_to(root):
        raise BackupError("Refusing to remove a path outside the owned subtree")
    if not target.exists():
        return

    def remove_readonly(function, path, error):
        if not isinstance(error, PermissionError):
            raise error
        os.chmod(path, stat.S_IWRITE)
        function(path)

    shutil.rmtree(_extended(target), onexc=remove_readonly)


def rename_state(source: Path, destination: Path) -> None:
    """Retry transient Windows sharing/access locks without changing the target."""
    source, destination = _extended(source), _extended(destination)
    deadline = time.monotonic() + 2
    while True:
        try:
            source.rename(destination)
            return
        except OSError as error:
            if getattr(error, "winerror", None) not in {5, 32} or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with _extended(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def copy_state(source: Path, destination: Path) -> None:
    """Copy an owned state tree, preserving SQLite and Windows long-path semantics."""
    source, destination = _extended(source), _extended(destination)
    if not source.exists():
        destination.mkdir(parents=True, exist_ok=True)
        return
    if source.is_symlink() or source.is_junction():
        raise BackupError("Backup dependencies may not be symbolic links or junctions")
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise BackupError("Backup dependencies may not be symbolic links or junctions")
        target = destination / path.relative_to(source)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.name.endswith(("-wal", "-shm", "-journal")):
            continue
        elif path.suffix == ".sqlite":
            target.parent.mkdir(parents=True, exist_ok=True)
            with (
                closing(sqlite3.connect(source_file_uri(path), uri=True)) as original,
                closing(sqlite3.connect(target)) as backup,
            ):
                original.backup(backup)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def source_file_uri(path: Path) -> str:
    text = str(path)
    if text.startswith("\\\\?\\UNC\\"):
        text = "\\\\" + text[8:]
    elif text.startswith("\\\\?\\"):
        text = text[4:]
    return Path(text).as_uri() + "?mode=ro"


async def _restore_io(function, *arguments):
    # A cancelled to_thread call keeps running. Own its completion before
    # rollback can inspect or move the same directories.
    operation = asyncio.create_task(asyncio.to_thread(function, *arguments))
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        await operation
        raise


class BackupManager:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def create(
        self,
        runtime,
        snapshot: Callable[[], Mapping[str, Any]],
        *,
        dependencies: Mapping[str, Path] | None = None,
        timeout: float = 10,
    ) -> Path:
        """Save JSON core state, run journals/code and explicit immutable dependencies.

        The caller pauses external input while producing its snapshot. A failure
        leaves the previous complete backup intact and the new one unselectable.
        """
        async with self._lock:
            name = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
            pending = self.root / (name + ".pending")
            final = self.root / name
            pending.mkdir()
            async with runtime.quiesce(timeout=timeout):
                state = snapshot()
                if inspect.isawaitable(state):
                    state = await state
                payload = {"core": state, "runtime": runtime.snapshot()}
                (pending / "state.json").write_text(
                    json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8"
                )
                await asyncio.to_thread(copy_state, runtime.state_dir / "runs", pending / "runs")
                for key, source in (dependencies or {}).items():
                    if not key.isidentifier():
                        raise ValueError("Backup dependency names must be identifiers")
                    await asyncio.to_thread(
                        copy_state, Path(source), pending / "dependencies" / key
                    )
                extended_pending = _extended(pending)
                checksums = {
                    path.relative_to(extended_pending).as_posix(): _checksum(path)
                    for path in extended_pending.rglob("*")
                    if path.is_file()
                }
                manifest = {
                    "format": 1,
                    "complete": True,
                    "files": checksums,
                    "created_at": datetime.now(UTC).isoformat(),
                }
                (pending / "manifest.json").write_text(
                    json.dumps(manifest, indent=2), encoding="utf-8"
                )
                await asyncio.to_thread(rename_state, pending, final)
            return final

    def list(self) -> list[Path]:
        return sorted(
            (
                p
                for p in self.root.iterdir()
                if p.is_dir()
                and not p.name.endswith(".pending")
                and (p / "manifest.json").is_file()
            ),
            reverse=True,
        )

    def verify(self, backup: Path | None = None) -> VerifiedBackup:
        if backup is None:
            available = self.list()
            if not available:
                raise BackupError("No completed backup exists")
            backup = available[0]
        backup = Path(backup).resolve()
        if not backup.is_relative_to(self.root) or backup.name.endswith(".pending"):
            raise BackupError("Backup must be a completed entry in this backup store")
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("format") != 1 or manifest.get("complete") is not True:
            raise BackupError("Unsupported or incomplete backup")
        extended_backup = _extended(backup)
        actual = {
            p.relative_to(extended_backup).as_posix()
            for p in extended_backup.rglob("*")
            if p.is_file() and p.relative_to(extended_backup).as_posix() != "manifest.json"
        }
        if actual != set(manifest["files"]):
            raise BackupError("Backup contains missing or unexpected files")
        for relative, digest in manifest["files"].items():
            path = (backup / relative).resolve()
            if (
                not path.is_relative_to(backup)
                or not _extended(path).is_file()
                or _checksum(path) != digest
            ):
                raise BackupError(f"Backup dependency is missing or changed: {relative}")
        return VerifiedBackup(
            backup, json.loads((backup / "state.json").read_text(encoding="utf-8"))
        )

    def read(self, backup: Path | None = None) -> dict:
        return self.verify(backup).state

    async def restore(
        self,
        runtime,
        restore_core: Callable[[dict], None],
        *,
        snapshot_core: Callable[[], Mapping[str, Any]],
        backup: Path | None = None,
        dependencies: Mapping[str, Path] | None = None,
        validate: Callable[[VerifiedBackup], Any] | None = None,
    ) -> dict:
        """Restore all roots and both state owners as one rollback transaction.

        The application holds its admission lock throughout this call. Validation
        and all staging finish before the first live directory is replaced.
        """
        async with self._lock:
            if runtime.is_running():
                raise BackupError("Stop all workers before restoring an agent")
            verified = await asyncio.to_thread(self.verify, backup)
            if validate:
                validation = validate(verified)
                if inspect.isawaitable(validation):
                    await validation
            roots = [(verified.path / "runs", runtime.state_dir / "runs")]
            roots.extend(
                (verified.dependency(name), Path(path).resolve())
                for name, path in (dependencies or {}).items()
            )
            destinations = [destination.resolve() for _, destination in roots]
            for index, destination in enumerate(destinations):
                if verified.path.is_relative_to(destination) or destination.is_relative_to(
                    verified.path
                ):
                    raise BackupError("Restore destination overlaps its backup")
                if any(
                    destination.is_relative_to(other) or other.is_relative_to(destination)
                    for other in destinations[:index]
                ):
                    raise BackupError("Restore destinations overlap")
            previous_core = snapshot_core()
            if inspect.isawaitable(previous_core):
                previous_core = await previous_core
            previous_core = json.loads(json.dumps(previous_core, allow_nan=False))
            previous_runtime = runtime.snapshot()
            prepared, swapped = [], []
            try:
                for source, destination in roots:
                    destination = Path(destination).resolve()
                    staging = destination.with_name(
                        destination.name + ".restoring-" + uuid.uuid4().hex
                    )
                    previous = destination.with_name(
                        destination.name + ".previous-" + uuid.uuid4().hex
                    )
                    prepared.append((destination, previous, staging))
                    await _restore_io(copy_state, source, staging)
                for destination, previous, staging in prepared:
                    # Register before I/O: cancellation can arrive after the
                    # rename's OS operation completed but before its await returns.
                    swapped.append((destination, previous, staging))
                    if destination.exists():
                        await _restore_io(rename_state, destination, previous)
                    await _restore_io(rename_state, staging, destination)
                result = restore_core(verified.state["core"])
                if inspect.isawaitable(result):
                    await result
                runtime.restore(verified.state["runtime"])
            except BaseException as error:
                failures = []
                for destination, previous, staging in reversed(swapped):
                    try:
                        if previous.exists():
                            if destination.exists():
                                await _restore_io(rename_state, destination, staging)
                            await _restore_io(rename_state, previous, destination)
                        elif not staging.exists() and destination.exists():
                            await _restore_io(rename_state, destination, staging)
                    except BaseException as failure:  # noqa: BLE001 -- continue every rollback
                        failures.append(failure)
                if swapped:
                    try:
                        result = restore_core(previous_core)
                        if inspect.isawaitable(result):
                            await result
                    except BaseException as failure:  # noqa: BLE001 -- preserve rollback evidence
                        failures.append(failure)
                    try:
                        runtime.restore(previous_runtime)
                    except BaseException as failure:  # noqa: BLE001 -- attempt each state owner
                        failures.append(failure)
                if failures:
                    raise BaseExceptionGroup(
                        "Restore failed and rollback is incomplete", [error, *failures]
                    ) from error
                raise
            finally:
                # Only private staging trees are removed after failure. Previous
                # directories remain recoverable if any rollback was incomplete.
                for destination, previous, staging in prepared:
                    if staging.exists():
                        await _restore_io(safe_remove_tree, staging, staging.parent)
            for destination, previous, staging in prepared:
                if previous.exists():
                    await _restore_io(safe_remove_tree, previous, previous.parent)
            return verified.state

    def dependency(self, backup: Path, name: str) -> Path:
        return self.verify(backup).dependency(name)
