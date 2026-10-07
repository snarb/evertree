import os
import subprocess
import sys
import time

import pytest

from evertree.core import cache


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    monkeypatch.setattr(cache, "cache_root", lambda: root)
    return root


def build(path):
    (path / "payload").write_text("rebuildable")


def test_scratch_skips_linked_trees_and_retries_locked_files(tmp_path, monkeypatch):
    """Use real OS locks and child processes to verify cache ownership and publication."""
    from pathlib import Path

    scratch = tmp_path / "tmp"
    scratch.mkdir()
    for name in ("locked", "expired"):
        (scratch / name).write_text("scratch")
    outside = tmp_path / "artifacts"
    outside.mkdir()
    build(outside)
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(outside), str(scratch / "linked"))
    else:
        (scratch / "linked").symlink_to(outside, target_is_directory=True)
    now = time.time()
    monkeypatch.setattr(cache.time, "time", lambda: now + 2 * 86400)
    unlink = Path.unlink

    def remove(path, *args, **kwargs):
        if path.name == "locked":
            raise PermissionError("busy")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", remove)
    cache.prune_scratch(tmp_path)
    assert (scratch / "linked").exists()
    assert (outside / "payload").read_text() == "rebuildable"
    assert (scratch / "locked").exists()
    assert not (scratch / "expired").exists()
    monkeypatch.setattr(Path, "unlink", unlink)
    cache.prune_scratch(tmp_path)
    assert not (scratch / "locked").exists()


def test_crashed_owner_releases_versions_and_temporary_files(root):
    """Use real OS locks and child processes to verify cache ownership and publication."""
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
import os, sys
from pathlib import Path
from evertree.core import cache
cache.cache_root = lambda: Path(sys.argv[1])
with cache.acquire('python', 'old', lambda p: (p / 'payload').write_text('old')):
    with cache.temporary_directory() as temporary:
        print(temporary, flush=True)
        sys.stdin.readline()
        os._exit(0)  # Bypass context cleanup in the real interpreter, not its venv launcher.
""",
            str(root),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        temporary = child.stdout.readline().decode().strip()
        assert temporary, child.stderr.read().decode()
        with cache.acquire("python", "new", build):
            cache.prune()
            assert (root / "python/old").exists()
            assert list((root / "temporary").iterdir())
            child.stdin.write(b"crash\n")
            child.stdin.flush()
            child.wait(timeout=10)
            cache.prune()
            assert not (root / "python/old").exists()
            assert not list((root / "temporary").iterdir())
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)


def test_concurrent_processes_publish_once(root):
    """Use real OS locks and child processes to verify cache ownership and publication."""
    code = """
import sys, time
from pathlib import Path
from evertree.core import cache
cache.cache_root = lambda: Path(sys.argv[1])
def build(path):
    with (path.parent / 'builds').open('a') as log:
        log.write('built\\n')
    time.sleep(0.2)
    (path / 'payload').write_text('complete')
with cache.acquire('python', 'same', build) as path:
    print((path / 'payload').read_text(), flush=True)
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(2)
    ]
    try:
        for child in children:
            out, error = child.communicate(timeout=20)
            assert child.returncode == 0, error.decode()
            assert out.strip() == b"complete"
        assert (root / "python/builds").read_text().splitlines() == ["built"]
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)
