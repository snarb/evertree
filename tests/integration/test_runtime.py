from __future__ import annotations

import asyncio

import pytest

from evertree.core.runtime.controller import ProgramSpec, Runtime, RuntimeBusy
from evertree.core.runtime.repository import ProgramExecutionError
from tests.support.runtime import TestProcess, commit_programs


@pytest.mark.parametrize(
    "process_factory",
    [
        TestProcess,
    ],
    ids=["dbos"],
)
async def test_nested_programs_and_durable_steps(tmp_path, process_factory):
    """Use a real worker and DBOS journal to verify execution, cancellation, or recovery across process boundaries."""
    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "src/evertree/processes/__init__.py": "",
            "src/evertree/processes/calculation/__init__.py": "",
            "src/evertree/processes/calculation/parent/__init__.py": "",
            "src/evertree/processes/calculation/child/__init__.py": "",
            "src/evertree/processes/calculation/child/_exec/__init__.py": "",
            "src/evertree/processes/calculation/child/_exec/helpers.py": """
def bump(value):
    return value + 1
async def count(ctx, value):
    return await ctx.step('counter', {'value': value})
""",
            "src/evertree/processes/calculation/parent/_exec.py": """
async def run(ctx, child):
    # et:op=first_counter
    # Counts the first value.
    first = await ctx.step('counter', {'value': 1})
    result = await ctx.call(child, {'value': first})
    return {'result': result.result, 'feedback': 'nested complete'}
""",
            "src/evertree/processes/calculation/child/_exec/implementation.py": """
from .helpers import bump, count
async def run(ctx, value):
    # et:op=child_counter
    # Counts the bumped value.
    result = await count(ctx, bump(value))
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
    # The child's anchor resolves through its helper frame to the child Program line.
    assert [t["anchor"] for t in traces if t.get("operator") == "counter"] == [
        "first_counter",
        "child_counter",
    ]
    assert [t["output"] for t in traces if t.get("operator") == "counter"] == [1, 2]
    replayed = await runtime.execute("task", parent, {"child": child.program_id}, run_id="durable")
    assert replayed.result == 2
    assert calls == [1, 2]
    await runtime.close()


async def test_anchored_statements_report_each_use_with_its_value(tmp_path):
    """A real worker instruments anchored plain-Python statements; Core traces each use once."""
    repo = tmp_path / "repository"
    source = """
def run(items):
    # et:op=subtotal
    # Sums price times quantity.
    subtotal = sum(
        price * quantity for price, quantity in items
    )
    for price, _ in items:
        # et:op=check_price
        # Requires a positive price.
        if price <= 0:
            raise ValueError('price')
    # et:op=answer
    # Returns the subtotal.
    return {'result': subtotal}
"""
    revision = commit_programs(repo, {"run.py": source})
    traces = []

    async def gateway(method, payload):
        return None

    async def trace(event):
        traces.append(event)

    runtime = Runtime(tmp_path / "runtime", repo, gateway, trace, process_factory=TestProcess)
    spec = ProgramSpec(1, "run.py", revision)
    result = await runtime.execute("task", spec, {"items": [[2, 3], [1, 4]]}, run_id="ok")
    assert result.result == 10
    uses = [
        (event["anchor"], event["status"], event["output"])
        for event in traces
        if event["type"] == "operator"
    ]
    assert uses == [
        ("subtotal", "completed", 10),
        ("check_price", "completed", False),
        ("check_price", "completed", False),
        ("answer", "completed", {"result": 10}),
    ]
    first = next(event for event in traces if event["type"] == "operator")
    assert first["run_id"] == "ok" and first["source_line"] == 3 and first["seq"] == 1
    traces.clear()
    with pytest.raises(Exception, match="price"):
        await runtime.execute("task", spec, {"items": [[0, 1]]}, run_id="bad")
    assert [(e["anchor"], e["status"]) for e in traces if e["type"] == "operator"] == [
        ("subtotal", "completed"),
        ("check_price", "completed"),
    ]
    await runtime.close()


async def test_cancel_stops_gateway_before_releasing_admission(tmp_path):
    """Use a real worker and DBOS journal to verify execution, cancellation, or recovery across process boundaries."""
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
    """Use a real worker and DBOS journal to verify execution, cancellation, or recovery across process boundaries."""
    repo = tmp_path / "repository"
    source = """
async def run(ctx):
    await ctx.step('trace', {'operator': 'attempt', 'run_id': 'forged', 'task_id': 'forged',
        'program': {'program_id': 'forged'}, 'run_mode': 'forged', 'type': 'run_failed'})
    try:
        # et:op=rejected_call
        # Calls an operation Core rejects.
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
    """Use a real worker and DBOS journal to verify execution, cancellation, or recovery across process boundaries."""
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
    ],
    ids=["dbos"],
)
async def test_cancellation_stops_tree_and_blocks_task_recovery(tmp_path, process_factory):
    """Use a real worker and DBOS journal to verify execution, cancellation, or recovery across process boundaries."""
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
    """Use a real worker and DBOS journal to verify execution, cancellation, or recovery across process boundaries."""
    from evertree.core.backup import BackupManager

    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "program.py": """
async def run(ctx):
    await ctx.step('started')
    await ctx.step('peek', journal=False)
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
    await backups.restore(
        runtime, lambda _: None, snapshot_core=lambda: {"test": True}, backup=saved
    )
    second = asyncio.create_task(runtime.execute("task", spec, {}, run_id="waiting"))
    await wait_for_boundary()
    await runtime.deliver(
        "waiting", {"id": "observation-one", "value": 7}, observation_id="observation-one"
    )
    result = await asyncio.wait_for(second, 30)
    assert result.result == {"id": "observation-one", "value": 7}
    # Recovery replays the journaled step but repeats the unjournaled read.
    assert starts == ["started", "peek", "peek"]
    await runtime.close()


async def test_worker_rejects_parallel_children_and_parent_access(tmp_path):
    """Real worker ownership spans a child call, including gaps between IPC operations."""
    repository = tmp_path / "repository"
    revision = commit_programs(
        repository,
        {
            "parent.py": """
import asyncio
async def run(ctx):
    started = asyncio.Event()
    async def first():
        started.set()
        return await ctx.call("child", {})
    child = asyncio.create_task(first())
    await started.wait()
    rejected = []
    try:
        for name in ("sibling", "parent-read"):
            try:
                if name == "sibling":
                    await ctx.call("child", {})
                else:
                    await ctx.step("read_value", {})
            except RuntimeError as error:
                rejected.append(str(error))
    finally:
        result = await child
    return {"result": {"rejected": rejected, "child": result.result}}
""",
            "child.py": 'async def run(ctx): return {"result": await ctx.step("read_value", {})}\n',
        },
    )
    child = ProgramSpec("child", "child.py", revision)
    reads = []

    async def gateway(method, payload):
        if method == "resolve_program":
            return child
        reads.append(payload["_runtime"]["program"]["program_id"])
        return 7

    runtime = Runtime(tmp_path / "runtime", repository, gateway, process_factory=TestProcess)
    try:
        result = await runtime.execute("task", ProgramSpec("parent", "parent.py", revision), {})
        assert result.result["child"] == 7
        assert len(result.result["rejected"]) == 2
        assert all("sequential call chain" in message for message in result.result["rejected"])
        assert reads == ["child"]
    finally:
        await runtime.close()


@pytest.mark.parametrize("nested", [False, True])
async def test_handled_rpc_timeout_drains_core_before_continuing(tmp_path, nested):
    """Real IPC must drain a cancelled read before a Program returns to its caller."""
    repository = tmp_path / "repository"
    revision = commit_programs(
        repository,
        {
            "parent.py": """
async def run(ctx, nested):
    if nested:
        result = await ctx.call("child", {})
    else:
        result = await operation(ctx)
    return {"result": await ctx.step("after", {})}

async def operation(ctx):
    import asyncio
    try:
        await asyncio.wait_for(ctx.step("slow", {}, journal=False), 0.05)
    except TimeoutError:
        return {"result": "handled"}
    raise AssertionError("Expected timeout")
""",
            "child.py": """
import asyncio
async def run(ctx):
    try:
        await asyncio.wait_for(ctx.step("slow", {}, journal=False), 0.05)
    except TimeoutError:
        return {"result": "handled"}
    raise AssertionError("Expected timeout")
""",
        },
    )
    finished = asyncio.Event()

    async def gateway(method, payload):
        if method == "resolve_program":
            return ProgramSpec("child", "child.py", revision)
        if method == "slow":
            await asyncio.sleep(0.2)
            finished.set()
            return None
        assert method == "after" and finished.is_set()
        return "continued"

    runtime = Runtime(tmp_path / "runtime", repository, gateway, process_factory=TestProcess)
    try:
        result = await runtime.execute(
            "task", ProgramSpec("parent", "parent.py", revision), {"nested": nested}
        )
        assert result.result == "continued"
    finally:
        await runtime.close()
