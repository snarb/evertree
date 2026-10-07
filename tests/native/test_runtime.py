from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest

from evertree.core.runtime import ProgramExecutionError, ProgramSpec, Runtime, RuntimeBusy
from evertree.core.sandbox import SandboxedProcess, WindowsProcessTree
from tests.support.runtime import commit_programs


@pytest.mark.skipif(os.name != "nt", reason="Windows SDK process-tree ownership")
def test_sdk_process_tree_stops_all_children():
    """Real Windows isolation/tools are required; a test process cannot prove this OS contract."""
    code = """
import subprocess, sys, time
sys.stdin.readline()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(100)'],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(child.pid, flush=True)
time.sleep(100)
"""
    parent = subprocess.Popen(
        [sys.executable, "-I", "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    tree = None
    try:
        tree = WindowsProcessTree(parent.pid)
        parent.stdin.write(b"start\n")
        parent.stdin.flush()
        assert int(parent.stdout.readline()) > 0
        tree.close()
        assert parent.wait(timeout=10) != 0
    finally:
        if tree:
            tree.close()
        if parent.poll() is None:
            parent.terminate()
            parent.wait(timeout=10)
        parent.stdin.close()
        parent.stdout.close()
        parent.stderr.close()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows AppContainer smoke test")
def test_appcontainer_denies_core_files_and_owns_process(tmp_path):
    """Real Windows isolation/tools are required; a test process cannot prove this OS contract."""
    secret = tmp_path / "protected-secret.txt"
    secret.write_text("must remain outside worker", encoding="utf-8")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    code = f"""
from pathlib import Path
import json
checks = {{}}
try:
    Path({str(secret)!r}).read_text()
    checks['read_denied'] = False
except PermissionError:
    checks['read_denied'] = True
try:
    Path({str(secret)!r}).write_text('changed')
    checks['write_denied'] = False
except PermissionError:
    checks['write_denied'] = True
Path('allowed.txt').write_text('allowed')
print(json.dumps(checks), flush=True)
"""
    with SandboxedProcess(
        None,
        ["-I", "-c", code],
        workdir=scratch,
        readable=(),
        writable=(scratch,),
    ) as process:
        assert process.wait(timeout=30) == 0, process.stderr.read().decode(errors="replace")
        assert json.loads(process.stdout.read()) == {"read_denied": True, "write_denied": True}
    assert secret.read_text(encoding="utf-8") == "must remain outside worker"
    assert (scratch / "allowed.txt").read_text(encoding="utf-8") == "allowed"


@pytest.mark.parametrize(
    "process_factory",
    [
        pytest.param(
            None, marks=pytest.mark.skipif(os.name != "nt", reason="Native Windows runtime")
        ),
    ],
    ids=["native"],
)
async def test_nested_programs_and_durable_steps(tmp_path, process_factory):
    """Real Windows isolation/tools are required; a test process cannot prove this OS contract."""
    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "src/evertree/processes/__init__.py": "",
            "src/evertree/processes/calculation/__init__.py": "",
            "src/evertree/processes/calculation/parent/__init__.py": "",
            "src/evertree/processes/calculation/child/__init__.py": "",
            "src/evertree/processes/calculation/child/_exec/__init__.py": "",
            "src/evertree/processes/calculation/child/_exec/helpers.py": "def bump(value): return value + 1\n",
            "src/evertree/processes/calculation/parent/_exec.py": """
async def run(ctx, child):
    # et:op=first_counter
    first = await ctx.step('counter', {'value': 1})
    result = await ctx.call(child, {'value': first})
    return {'result': result.result, 'feedback': 'nested complete'}
""",
            "src/evertree/processes/calculation/child/_exec/implementation.py": """
from .helpers import bump
async def run(ctx, value):
    result = await ctx.step('counter', {'value': bump(value)})
    return {'result': result}
""",
        },
    )
    parent = ProgramSpec("parent", "src/evertree/processes/calculation/parent/_exec.py", revision)
    child = ProgramSpec(
        2, "src/evertree/processes/calculation/child/_exec/implementation.py", revision
    )
    calls, traces = [], []

    async def gateway(method, payload):
        if method == "resolve_program":
            return child
        calls.append(payload["value"])
        assert payload["_runtime"]["task_id"] == "task"
        return payload["value"]

    async def trace(event):
        traces.append(event)

    runtime = Runtime(
        tmp_path / "runtime", repository, gateway, trace, process_factory=process_factory
    )
    result = await runtime.execute("task", parent, {"child": child.program_id}, run_id="durable")
    assert result.result == 2
    assert not list((runtime.state_dir / "runs").iterdir())
    assert (runtime.state_dir / "journals/durable/dbos/dbos.sqlite").exists()
    assert calls == [1, 2]
    assert len([t for t in traces if t["type"] == "run_started"]) == 2
    assert next(t for t in traces if t.get("operator") == "counter")["anchor"] == "first_counter"
    assert [t["output"] for t in traces if t.get("operator") == "counter"] == [1, 2]
    replayed = await runtime.execute("task", parent, {"child": child.program_id}, run_id="durable")
    assert replayed.result == 2
    assert calls == [1, 2]
    await runtime.close()


@pytest.mark.parametrize(
    "process_factory",
    [
        pytest.param(
            None, marks=pytest.mark.skipif(os.name != "nt", reason="Native Windows runtime")
        ),
    ],
    ids=["native"],
)
async def test_cancellation_stops_tree_and_blocks_task_recovery(tmp_path, process_factory):
    """Real Windows isolation/tools are required; a test process cannot prove this OS contract."""
    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "program.py": """
import asyncio
import subprocess
import sys
async def run(ctx, spawn_child=False):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(100)'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) if spawn_child else None
    await ctx.step('started', {'child_pid': child.pid if child else None})
    await asyncio.sleep(100)
    return {'result': 1}
"""
        },
    )
    started = asyncio.Event()
    child_pid = None

    async def gateway(method, payload):
        nonlocal child_pid
        child_pid = payload.get("child_pid")
        started.set()

    runtime = Runtime(tmp_path / "runtime", repository, gateway, process_factory=process_factory)
    spec = ProgramSpec("wait", "program.py", revision)
    execution = asyncio.create_task(
        runtime.execute("task", spec, {"spawn_child": process_factory is None}, timeout=120)
    )
    await asyncio.wait_for(started.wait(), 60)
    with pytest.raises(RuntimeBusy):
        await runtime.execute("another", spec, {})
    await runtime.cancel("task")
    assert not runtime.is_running("task")
    if child_pid:
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, child_pid)
        if handle:
            try:
                status = wintypes.DWORD()
                assert kernel.GetExitCodeProcess(handle, ctypes.byref(status))
                assert status.value != 259
            finally:
                kernel.CloseHandle(handle)
    with pytest.raises(ProgramExecutionError):
        await execution
    with pytest.raises(ProgramExecutionError, match="finalized"):
        await runtime.execute("task", spec, {})
    await runtime.close()


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native isolation")
