from __future__ import annotations

import os

import pytest

from evertree.core.backup import _extended
from evertree.core.programs.lifecycle import (
    git,
)


@pytest.mark.skipif(os.name != "nt", reason="Windows Git long paths")
def test_managed_git_reads_revision_paths_under_long_temporary_root(tmp_path):
    """Real Windows isolation/tools are required; a test process cannot prove this OS contract."""
    root = tmp_path / ("nested-" + "a" * 100)
    _extended(root).mkdir(parents=True)
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@localhost")
    relative = "src/evertree/processes/task_management/example_process_with_long_name/_exec.py"
    target = _extended(root / relative)
    target.parent.mkdir(parents=True)
    target.write_text("value = 3\n")
    assert len(str(root / relative)) > 260
    git(root, "add", ".")
    git(root, "commit", "-m", "Long path fixture")
    revision = git(root, "rev-parse", "HEAD")
    assert git(root, "show", f"{revision}:{relative}") == "value = 3"


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native isolation")
