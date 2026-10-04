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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class BackupError(RuntimeError):
    pass


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

    def read(self, backup: Path | None = None) -> dict:
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
        return json.loads((backup / "state.json").read_text(encoding="utf-8"))

    async def restore(
        self,
        runtime,
        restore_core: Callable[[dict], None],
        *,
        backup: Path | None = None,
    ) -> dict:
        async with self._lock:
            if runtime.is_running():
                raise BackupError("Stop all workers before restoring an agent")
            if backup is None:
                choices = self.list()
                if not choices:
                    raise BackupError("No completed backup exists")
                backup = choices[0]
            backup = Path(backup).resolve()
            state = self.read(backup)
            staging = runtime.state_dir / ("restored-" + uuid.uuid4().hex)
            await asyncio.to_thread(copy_state, backup / "runs", staging)
            current = runtime.state_dir / "runs"
            old = runtime.state_dir / ("previous-runs-" + uuid.uuid4().hex)
            if current.exists():
                await asyncio.to_thread(rename_state, current, old)
            try:
                await asyncio.to_thread(rename_state, staging, current)
                result = restore_core(state["core"])
                if inspect.isawaitable(result):
                    await result
                runtime.restore(state["runtime"])
            except BaseException:
                if current.exists():
                    await asyncio.to_thread(rename_state, current, staging)
                if old.exists():
                    await asyncio.to_thread(rename_state, old, current)
                raise
            return state

    def dependency(self, backup: Path, name: str) -> Path:
        self.read(backup)
        if not name.isidentifier():
            raise ValueError("Invalid dependency name")
        path = Path(backup).resolve() / "dependencies" / name
        if not path.is_dir():
            raise BackupError(f"Backup dependency not found: {name}")
        return path
