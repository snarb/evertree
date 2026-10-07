import os
import subprocess
import sys

import pytest

from evertree.core.codex.executor import _CMD_SHIM


@pytest.mark.skipif(os.name != "nt", reason="Windows raw command-line semantics")
def test_cmd_shim_preserves_quotes_spaces_operators_and_exit_status(tmp_path):
    """Real Windows isolation/tools are required; a test process cannot prove this OS contract."""
    cmd = os.environ["COMSPEC"]
    command = (
        f'"{sys.executable}" -c "import sys; print(sys.argv[1])" "two words & punctuation"'
        f' && "{sys.executable}" -c "print(\'done\')"'
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", _CMD_SHIM, cmd, command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["two words & punctuation", "done"]
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            _CMD_SHIM,
            cmd,
            f'"{sys.executable}" -c "import sys; sys.exit(7)"',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 7, result.stderr
