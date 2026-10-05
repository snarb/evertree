import subprocess

import pytest

from evertree.core.cache import prune_scratch


def pytest_sessionstart(session):
    prune_scratch(session.config.rootpath)


@pytest.fixture
def program_remote(tmp_path):
    remote = tmp_path / "programs.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    return str(remote)


@pytest.fixture(autouse=True)
def offline_development_runtime(monkeypatch, program_remote):
    # Tests exercise uncommitted changes and real Git publication without network access.
    from evertree import application

    monkeypatch.setenv("EVERTREE_PROGRAM_REMOTE", program_remote)
    monkeypatch.setattr(application, "require_committed_runtime", lambda _: None)
