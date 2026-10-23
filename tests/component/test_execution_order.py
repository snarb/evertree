"""Single execution ownership without workers; IPC and replay are covered separately."""

import asyncio
from dataclasses import asdict

import pytest

from evertree.core.graph.types import GraphDelta, Node
from evertree.core.runtime.controller import ProgramSpec, Runtime, RuntimeBusy


async def test_only_current_program_can_read_or_start_a_sibling(tmp_path):
    parent = ProgramSpec(1, "parent.py", "0" * 40)
    child = ProgramSpec(2, "child.py", "0" * 40, role="model")

    async def gateway(method, payload):
        if method == "resolve_program":
            return child
        return payload["_runtime"]["semantic_scope"]

    runtime = Runtime(tmp_path / "runtime", tmp_path / "repo", gateway)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    runtime._active = {
        "task_id": "task",
        "run_id": "parent",
        "program": parent,
        "run_mode": "live",
        "cancelled": False,
        "known_runs": {"parent": asdict(parent)},
        "calls": {"parents": {}, "finished": []},
        "run_dir": run_dir,
        "execution_stack": ["parent"],
        "execution_scopes": {"parent": ["outer"]},
        "semantic_scope": "outer",
        "requests": {},
    }

    async def dispatch(run, method, **payload):
        return await runtime._dispatch({"run_id": run, "method": method, "payload": payload})

    def enter(run):
        return {
            "run_id": run,
            "method": "run_enter",
            "program": asdict(child),
            "payload": {"parent_run_id": "parent"},
        }

    try:
        await dispatch("parent", "llm.enter", invocation_id="parent:llm:1")
        await runtime._dispatch(enter("child"))
        assert await dispatch("child", "read_value") == "parent:llm:1"
        with pytest.raises(RuntimeBusy, match="current Program"):
            await dispatch("parent", "read_value")
        with pytest.raises(RuntimeBusy, match="sequential"):
            await runtime._dispatch(enter("sibling"))
        await dispatch("child", "llm.enter", invocation_id="child:llm:1")
        assert await dispatch("child", "read_value") == "child:llm:1"
        await dispatch("child", "llm.leave", invocation_id="child:llm:1")
        await dispatch("child", "run_leave")
        assert await dispatch("parent", "read_value") == "parent:llm:1"
        await dispatch("parent", "llm.leave", invocation_id="parent:llm:1")
        assert await dispatch("parent", "read_value") == "outer"
    finally:
        runtime._active = None
        await runtime.close()


async def test_parallel_index_reads_exclude_writes_until_both_finish(tmp_path):
    entered, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []
    spec = ProgramSpec(1, "search.py", "0" * 40, role="model")

    async def gateway(method, payload):
        calls.append(method)
        entered.set()
        if len(calls) == 2:
            started.set()
        await release.wait()
        return []

    runtime = Runtime(tmp_path / "runtime", tmp_path / "repo", gateway)
    runtime._active = {
        "task_id": "task",
        "run_id": "search",
        "program": spec,
        "run_mode": "live",
        "cancelled": False,
        "known_runs": {"search": asdict(spec)},
        "execution_stack": ["search"],
        "execution_scopes": {"search": ["scope"]},
        "requests": {},
    }

    async def dispatch(method, kinds=None):
        return await runtime._dispatch(
            {"run_id": "search", "method": method, "payload": {"queries": ["pump"], "kinds": kinds}}
        )

    pending = [asyncio.create_task(dispatch("semantic.bm25", ["claim", "note"]))]
    try:
        await asyncio.wait_for(entered.wait(), 1)
        with pytest.raises(RuntimeBusy, match="paired search"):
            await dispatch("semantic.vector", ["concept"])
        pending.append(asyncio.create_task(dispatch("semantic.vector", ["NOTE", "claim", "note"])))
        await asyncio.wait_for(started.wait(), 1)
        with pytest.raises(RuntimeBusy, match="paired search"):
            await dispatch("semantic.write")
        with pytest.raises(RuntimeBusy, match="unfinished"):
            await dispatch("run_leave")
        assert set(calls) == {"semantic.bm25", "semantic.vector"}
    finally:
        release.set()
        await asyncio.gather(*pending)
        runtime._active = None
        await runtime.close()


async def test_application_rejects_outside_graph_writes_and_defers_maintenance(app, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    node = Node(app.graph.reserve_id(), "Owned change")
    maintenance = []
    monkeypatch.setattr(app.memory, "review_batch", lambda: maintenance.append("review"))
    monkeypatch.setattr(app.memory, "finalize_deletions", lambda: maintenance.append("delete"))

    async def execute():
        with app._execution.enter():
            app._current_task = "active"
            app.graph.apply(GraphDelta(creates=(node,)), provenance="owner")
            entered.set()
            await release.wait()
            app._current_task = None
            await app._run_maintenance()

    work = asyncio.create_task(execute())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        with pytest.raises(RuntimeBusy, match="execution chain"):
            app.graph.apply(GraphDelta(deletes=(node.id,)), provenance="outsider")
        with pytest.raises(RuntimeBusy):
            app.graph.reserve_id()
        app._maintenance_due = True
        await app._run_maintenance()
        assert not maintenance
    finally:
        release.set()
        await work
    assert maintenance == ["review", "delete"]
    assert app.graph.get(node.id) == node
    assert not app._execution.busy


async def test_queued_input_waits_for_idle_maintenance(app, monkeypatch):
    started, release, ran = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def maintenance():
        with app._execution.enter():
            started.set()
            await release.wait()

    async def queue():
        ran.set()

    monkeypatch.setattr(app, "_run_queue_owned", queue)
    owner = asyncio.create_task(maintenance())
    await started.wait()
    await app.submit("New task during maintenance")
    await asyncio.sleep(0)
    assert not ran.is_set()
    release.set()
    await owner
    await app._pump
    assert ran.is_set()


@pytest.mark.parametrize("reply", [{"result": 7}, {"error": "Index unavailable"}])
async def test_repeated_rpc_cancellation_waits_for_core_reply(monkeypatch, reply):
    from evertree.core.runtime import worker

    sent = asyncio.Event()
    messages = []

    def send(message):
        messages.append(message)
        sent.set()

    monkeypatch.setattr(worker, "send", send)
    monkeypatch.setattr(worker, "_pending", {})
    operation = asyncio.create_task(worker.rpc("gateway", {}))
    await sent.wait()
    for _ in range(2):
        operation.cancel()
        await asyncio.sleep(0)
        assert not operation.done()
    worker._complete({"id": messages[0]["id"], **reply})
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert not worker._pending
