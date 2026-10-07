import pytest

from evertree.core.codex.executor import CodexExecutor


def test_executor_runtime_cannot_be_inside_candidate(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        CodexExecutor(tmp_path, tmp_path / "runtime")
