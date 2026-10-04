from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evertree.core.runtime import ProgramExecutionError, ProgramSpec, Runtime, RuntimeBusy
from evertree.core.sandbox import SandboxedProcess, WindowsProcessTree, prepare_python


def test_private_cache_publication_retries_sharing_violation(tmp_path, monkeypatch):
    from evertree.core.backup import _extended
    from evertree.core.sandbox import _publish_cache

    target = tmp_path / "cache-key"
    staging = _extended(tmp_path / "cache-key.preparing-test")
    staging.mkdir()
    (staging / ".complete").write_text("verified-cache")
    rename = Path.rename
    attempts = 0

    def temporarily_locked(path, destination):
        nonlocal attempts
        if path == staging:
            attempts += 1
            if attempts == 1:
                error = OSError("Transient scanner file lock")
                error.winerror = 32
                raise error
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", temporarily_locked)
    _publish_cache(staging, target)
    assert attempts == 2 and (target / ".complete").read_text() == "verified-cache"


class TestProcess:
    """Explicit test injection: exercise DBOS separately from native isolation."""

    __test__ = False

    def __init__(self, executable, arguments, *, workdir, **_):
        self.process = subprocess.Popen(
            [str(executable), *arguments],
            cwd=workdir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.stdin, self.stdout, self.stderr = (
            self.process.stdin,
            self.process.stdout,
            self.process.stderr,
        )

    def poll(self):
        return self.process.poll()

    def terminate(self):
        self.process.terminate()
        self.process.wait(timeout=10)

    def close(self):
        if self.poll() is None:
            self.terminate()
        self.stdin.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows SDK process-tree ownership")
def test_sdk_process_tree_stops_all_children():
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


def commit_programs(root: Path, files: dict[str, str]) -> str:
    root.mkdir(parents=True)
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for arguments in (
        ("init", "-b", "main"),
        ("config", "user.name", "Test"),
        ("config", "user.email", "test@localhost"),
        ("add", "."),
        ("commit", "-m", "Fixture"),
    ):
        subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows AppContainer smoke test")
def test_appcontainer_denies_core_files_and_owns_process(tmp_path):
    executable = prepare_python(Path(__file__).resolve().parents[1] / ".state" / "test-python")
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
        executable,
        ["-I", "-c", code],
        workdir=scratch,
        readable=(executable.parent,),
        writable=(scratch,),
    ) as process:
        assert process.wait(timeout=30) == 0, process.stderr.read().decode(errors="replace")
        assert json.loads(process.stdout.read()) == {"read_denied": True, "write_denied": True}
    assert secret.read_text(encoding="utf-8") == "must remain outside worker"
    assert (scratch / "allowed.txt").read_text(encoding="utf-8") == "allowed"


@pytest.mark.parametrize(
    "process_factory",
    [
        TestProcess,
        pytest.param(
            None, marks=pytest.mark.skipif(os.name != "nt", reason="Native Windows runtime")
        ),
    ],
    ids=["dbos", "native"],
)
async def test_nested_programs_and_durable_steps(tmp_path, process_factory):
    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "src/evertree/processes/__init__.py": "",
            "src/evertree/processes/calculation.py": "def bump(value): return value + 1\n",
            "src/evertree/processes/parent.py": """
async def run(ctx, child):
    # et:op=first_counter
    first = await ctx.step('counter', {'value': 1})
    result = await ctx.call(child, {'value': first})
    return {'result': result.result, 'feedback': 'nested complete'}
""",
            "src/evertree/processes/child.py": """
from .calculation import bump
async def run(ctx, value):
    result = await ctx.step('counter', {'value': bump(value)})
    return {'result': result}
""",
        },
    )
    parent = ProgramSpec("parent", "src/evertree/processes/parent.py", revision)
    child = ProgramSpec(2, "src/evertree/processes/child.py", revision)
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
    assert calls == [1, 2]
    assert len([t for t in traces if t["type"] == "run_started"]) == 2
    assert next(t for t in traces if t.get("operator") == "counter")["anchor"] == "first_counter"
    assert [t["output"] for t in traces if t.get("operator") == "counter"] == [1, 2]
    replayed = await runtime.execute("task", parent, {"child": child.program_id}, run_id="durable")
    assert replayed.result == 2
    assert calls == [1, 2]
    await runtime.close()


async def test_cancel_stops_gateway_before_releasing_admission(tmp_path):
    repo = tmp_path / "repository"
    revision = commit_programs(
        repo, {"run.py": "async def run(ctx): return {'result': await ctx.step('long_call')}\n"}
    )
    started, stopped = asyncio.Event(), asyncio.Event()

    async def gateway(method, payload):
        started.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    runtime = Runtime(tmp_path / "runtime", repo, gateway, process_factory=TestProcess)
    execution = asyncio.create_task(runtime.execute("task", ProgramSpec(1, "run.py", revision), {}))
    await asyncio.wait_for(started.wait(), 30)
    await asyncio.wait_for(runtime.cancel("task"), 10)
    assert stopped.is_set() and not runtime.is_running()
    with pytest.raises(ProgramExecutionError):
        await execution
    await runtime.close()


async def test_trace_cannot_forge_runtime_identity_and_records_failed_operation(tmp_path):
    repo = tmp_path / "repository"
    source = """
async def run(ctx):
    await ctx.step('trace', {'operator': 'attempt', 'run_id': 'forged', 'task_id': 'forged',
        'program': {'program_id': 'forged'}, 'run_mode': 'forged', 'type': 'run_failed'})
    try:
        # et:op=rejected_call
        await ctx.step('reject', {'input': 1})
    except RuntimeError:
        pass
    return {'result': 1}
"""
    revision = commit_programs(repo, {"run.py": source})
    traces = []

    async def gateway(method, payload):
        payload["input"] = 2
        raise ValueError("rejected")

    async def trace(event):
        traces.append(event)

    runtime = Runtime(tmp_path / "runtime", repo, gateway, trace, process_factory=TestProcess)
    await runtime.execute("task", ProgramSpec(1, "run.py", revision), {}, run_id="real")
    attempt = next(event for event in traces if event.get("operator") == "attempt")
    assert (
        attempt["type"] == "trace" and attempt["run_id"] == "real" and attempt["task_id"] == "task"
    )
    assert attempt["program"]["program_id"] == 1 and attempt["run_mode"] == "live"
    failed = next(event for event in traces if event.get("operator") == "reject")
    assert failed["arguments"] == {"input": 1}
    assert failed["status"] == "failed" and failed["anchor"] == "rejected_call"
    await runtime.close()


async def test_cancelled_startup_acquires_handles_and_stops_late_process(tmp_path):
    import threading

    repo = tmp_path / "repository"
    revision = commit_programs(repo, {"run.py": "async def run(): return {'result': 1}\n"})
    started, release = threading.Event(), threading.Event()
    processes = []

    def delayed_process(*args, **kwargs):
        started.set()
        assert release.wait(10)
        process = TestProcess(*args, **kwargs)
        processes.append(process)
        return process

    async def gateway(method, payload):
        return None

    runtime = Runtime(tmp_path / "runtime", repo, gateway, process_factory=delayed_process)
    execution = asyncio.create_task(runtime.execute("task", ProgramSpec(1, "run.py", revision), {}))
    assert await asyncio.to_thread(started.wait, 10)
    execution.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await execution
    assert len(processes) == 1 and processes[0].poll() is not None
    assert not runtime.is_running()
    await runtime.close()


@pytest.mark.parametrize(
    "process_factory",
    [
        TestProcess,
        pytest.param(
            None, marks=pytest.mark.skipif(os.name != "nt", reason="Native Windows runtime")
        ),
    ],
    ids=["dbos", "native"],
)
async def test_cancellation_stops_tree_and_blocks_task_recovery(tmp_path, process_factory):
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


async def test_waiting_run_backup_and_recovery_preserve_observation_identity(tmp_path):
    from evertree.core.backup import BackupManager

    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "program.py": """
async def run(ctx):
    await ctx.step('started')
    observation = await ctx.next_observation(timeout_seconds=120)
    return {'result': observation}
"""
        },
    )
    starts = []

    async def gateway(method, payload):
        starts.append(method)

    runtime = Runtime(tmp_path / "runtime", repository, gateway, process_factory=TestProcess)
    spec = ProgramSpec("observe", "program.py", revision)

    async def wait_for_boundary():
        async with asyncio.timeout(30):
            while not runtime._active or not runtime._active.get("waiting"):
                await asyncio.sleep(0.01)

    first = asyncio.create_task(runtime.execute("task", spec, {}, run_id="waiting"))
    await wait_for_boundary()
    backups = BackupManager(tmp_path / "backups")
    saved = await backups.create(runtime, lambda: {"test": True})
    await runtime.cancel("task", finalize=False)
    with pytest.raises(ProgramExecutionError):
        await first
    await backups.restore(runtime, lambda _: None, backup=saved)
    second = asyncio.create_task(runtime.execute("task", spec, {}, run_id="waiting"))
    await wait_for_boundary()
    await runtime.deliver(
        "waiting", {"id": "observation-one", "value": 7}, observation_id="observation-one"
    )
    result = await asyncio.wait_for(second, 30)
    assert result.result == {"id": "observation-one", "value": 7}
    assert starts == ["started"]
    await runtime.close()
