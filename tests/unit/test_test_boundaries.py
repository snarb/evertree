"""Fast-suite process guards must reject real launch APIs before side effects."""

import asyncio
import os
import subprocess
import sys

import pytest

from evertree.core.sandbox import SandboxedProcess


@pytest.mark.parametrize(
    "launch",
    [
        lambda: subprocess.run([sys.executable, "-c", "pass"], check=True),
        lambda: os.system("echo unexpected-process"),
    ],
)
def test_fast_suite_rejects_child_process_launch(launch):
    with pytest.raises(AssertionError, match="must not launch processes"):
        launch()


async def test_fast_suite_rejects_async_child_process_launch():
    with pytest.raises(AssertionError, match="must not launch processes"):
        await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")


def test_fast_suite_rejects_native_sandbox_construction(tmp_path):
    with pytest.raises(AssertionError, match="must not create an OS sandbox"):
        SandboxedProcess(None, [], workdir=tmp_path, readable=(), writable=())
