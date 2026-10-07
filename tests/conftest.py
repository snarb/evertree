"""Test infrastructure is opt-in; fast tests cannot start child processes."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ["tests.support.fixtures"]


def pytest_xdist_auto_num_workers(config):
    return min(4, os.process_cpu_count() or 1)


@pytest.fixture(scope="session", autouse=True)
def isolated_tool_cache(tmp_path_factory):
    # A worker may reuse its immutable tools, but never another session's mutable state.
    from evertree.core import cache

    with pytest.MonkeyPatch.context() as patch:
        root = tmp_path_factory.mktemp("tools")
        patch.setattr(cache, "cache_root", lambda: root)
        yield root


_fast_test_active = False


def _reject_fast_process(event, args):
    if _fast_test_active and event in {
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.fork",
        "os.exec",
        "os.spawn",
    }:
        raise AssertionError("Fast tests must not launch processes; use an integration test")


sys.addaudithook(_reject_fast_process)


@pytest.fixture(autouse=True)
def no_fast_subprocesses(request):
    global _fast_test_active
    relative = Path(request.node.path).relative_to(request.config.rootpath / "tests")
    if relative.parts[0] not in {"unit", "component"}:
        yield
        return
    _fast_test_active = True
    try:
        with pytest.MonkeyPatch.context() as patch:
            from evertree.core.sandbox import SandboxedProcess

            def forbidden(*args, **kwargs):
                raise AssertionError("Fast tests must not create an OS sandbox")

            patch.setattr(SandboxedProcess, "__init__", forbidden)
            yield
    finally:
        _fast_test_active = False


@pytest.fixture
def program_remote(tmp_path):
    remote = tmp_path / "programs.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    return str(remote)


@pytest.fixture
def offline_application(monkeypatch, program_remote):
    """Only real application integration tests need publication and provenance I/O."""
    from evertree import application

    monkeypatch.setenv("EVERTREE_PROGRAM_REMOTE", program_remote)
    monkeypatch.setattr(application, "require_committed_runtime", lambda _: None)
