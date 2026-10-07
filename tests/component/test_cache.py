import os
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


def test_scratch_expiration_checks_nested_files_and_both_roots(tmp_path, monkeypatch):
    now = time.time()
    for name in ("tmp", "temp"):
        root = tmp_path / name
        old = root / "old"
        old.mkdir(parents=True)
        build(old)
        (root / "old.txt").write_text("scratch")
        active = root / "active"
        active.mkdir()
        build(active)
        # Simulate a fresh nested write even though its parent directory is old.
        os.utime(active / "payload", (now + 2 * 86400, now + 2 * 86400))
    outside = tmp_path / "artifacts"
    outside.mkdir()
    build(outside)
    monkeypatch.setattr(cache.time, "time", lambda: now + 2 * 86400)
    cache.prune_scratch(tmp_path)
    for name in ("tmp", "temp"):
        assert not (tmp_path / name / "old").exists()
        assert not (tmp_path / name / "old.txt").exists()
        assert (tmp_path / name / "active/payload").exists()
    assert (outside / "payload").exists()


def test_live_version_survives_update_and_last_release_collects_it(root):
    with cache.acquire("python", "old", build) as old:
        with cache.acquire("python", "new", build) as new:
            cache.prune()
            assert old.exists() and new.exists()
        assert old.exists() and new.exists()
    assert not old.exists() and new.exists()
    with cache.acquire("python", "new", lambda _: pytest.fail("must reuse")):
        pass
    assert not list((root / ".leases").iterdir())


def test_unreadable_scratch_root_does_not_abort_other_cleanup(tmp_path, monkeypatch):
    from pathlib import Path

    for name in ("tmp", "temp"):
        (tmp_path / name).mkdir()
        build(tmp_path / name)
    now = time.time()
    monkeypatch.setattr(cache.time, "time", lambda: now + 2 * 86400)
    iterdir = Path.iterdir

    def entries(path):
        if path == tmp_path / "tmp":
            raise PermissionError("busy")
        return iterdir(path)

    monkeypatch.setattr(Path, "iterdir", entries)
    cache.prune_scratch(tmp_path)
    assert (tmp_path / "tmp/payload").exists()
    assert not (tmp_path / "temp/payload").exists()


def test_failed_build_and_temporary_files_are_removed(root):
    def fail(path):
        build(path)
        raise RuntimeError("build failed")

    with pytest.raises(RuntimeError, match="build failed"), cache.acquire("python", "bad", fail):
        pass
    assert not list((root / "python").iterdir())
    with pytest.raises(RuntimeError), cache.temporary_directory() as temporary:
        build(temporary)
        raise RuntimeError("cancelled")
    assert not temporary.exists()


def test_abandoned_publication_is_removed(root):
    with cache.acquire("python", "current", build):
        pass
    staging = root / "python/stale.pending-build"
    staging.mkdir()
    build(staging)
    cache.prune()
    assert not staging.exists()
