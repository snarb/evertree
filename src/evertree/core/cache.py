"""Shared, rebuildable tools. OS locks protect live users, including across processes."""

from __future__ import annotations

import errno
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .backup import rename_state, safe_remove_tree

_log = logging.getLogger(__name__)


def cache_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "EverTree" / "cache"


@contextmanager
def _lock(path: Path, *, wait: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if not path.stat().st_size:
            stream.write(b"0")
            stream.flush()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if not wait or error.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                time.sleep(0.05)
        # Closing the descriptor also releases the lock after an exception or crash.
        yield


def _collect(root: Path) -> None:
    """Called under the cache lock; never follows a link or deletes a live lease."""
    for group in root.iterdir():
        if (
            group.name.startswith(".")
            or not group.is_dir()
            or group.is_symlink()
            or group.is_junction()
        ):
            continue
        current = group / ".current"
        keep = current.read_text() if current.exists() else None
        for entry in group.iterdir():
            if not entry.is_dir() or entry.is_symlink() or entry.is_junction():
                continue
            busy = False
            for lease in (root / ".leases").glob(f"{group.name}-{entry.name}-*.lock"):
                try:
                    with _lock(lease, wait=False):
                        pass
                    lease.unlink()
                except OSError:
                    busy = True
            if entry.name != keep and not busy:
                try:
                    safe_remove_tree(entry, group)
                except OSError as error:
                    _log.warning("Cache cleanup will retry %s: %s", entry, error)


def prune(directory: Path | None = None) -> None:
    root = cache_root()
    with _lock(root / ".lock"):
        _collect(root)
    if directory is not None:
        prune_scratch(directory)


def prune_scratch(directory: Path) -> None:
    """Expire disposable scratch entries after 24 hours without changes."""
    directory = directory.resolve()
    cutoff = time.time() - 24 * 60 * 60

    def stale(path):
        # Refuse linked trees, including junctions nested below an ordinary directory.
        if path.is_symlink() or path.is_junction():
            return False
        modified = path.stat()
        if max(modified.st_mtime, modified.st_ctime) >= cutoff:
            return False
        return not path.is_dir() or all(stale(child) for child in path.iterdir())

    for name in ("tmp", "temp"):
        root = directory / name
        try:
            if not root.is_dir() or root.is_symlink() or root.is_junction():
                continue
            entries = list(root.iterdir())
        except OSError as error:
            _log.warning("Scratch cleanup will retry %s: %s", root, error)
            continue
        for entry in entries:
            try:
                if stale(entry):
                    if entry.is_dir():
                        safe_remove_tree(entry, root)
                    else:
                        entry.unlink()
            except OSError as error:
                _log.warning("Scratch cleanup will retry %s: %s", entry, error)


@contextmanager
def acquire(kind: str, key: str, build, *, temporary: bool = False):
    """Publish once; retain the latest version and every version in active use."""
    root = cache_root()
    group = root / kind
    target = group / key
    lease_path = root / ".leases" / f"{kind}-{key}-{uuid4().hex}.lock"
    with _lock(root / ".lock"):
        group.mkdir(parents=True, exist_ok=True)
        _collect(root)
        if not target.exists():
            staging = group / (key + ".pending-" + uuid4().hex)
            staging.mkdir()
            try:
                build(staging)
                rename_state(staging, target)
            finally:
                if staging.exists():
                    safe_remove_tree(staging, group)
        lease = _lock(lease_path)
        lease.__enter__()
        try:
            if not temporary:
                current = group / ".current.pending"
                current.write_text(key)
                current.replace(group / ".current")
        except BaseException:
            lease.__exit__(None, None, None)
            lease_path.unlink()
            raise
    try:
        yield target
    finally:
        with _lock(root / ".lock"):
            lease.__exit__(None, None, None)
            lease_path.unlink()
            _collect(root)


def temporary_directory():
    return acquire("temporary", uuid4().hex, lambda path: None, temporary=True)
