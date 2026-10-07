import pytest

from evertree.core.actions import ActionGateway
from tests.support.actions import Adapter


@pytest.mark.asyncio
async def test_unchanged_issued_action_session_and_exactly_once():
    gateway, adapter = ActionGateway(), Adapter()
    gateway.bind("session", adapter, task_id="task", commit="abc")
    await gateway.list("session", task_id="task")
    with pytest.raises(ValueError):
        await gateway.take("session", {"move": 3}, task_id="task", operation_id="x", approved=True)
    with pytest.raises(PermissionError):
        await gateway.take("session", {"move": 2}, task_id="task", operation_id="x")
    for _ in range(2):
        assert (
            await gateway.take(
                "session", {"move": 2}, task_id="task", operation_id="x", approved=True
            )
            == "accepted"
        )
    assert adapter.calls == 1
    with pytest.raises(PermissionError):
        await gateway.list("session", task_id="task", run_mode="replay")


@pytest.mark.asyncio
async def test_unknown_never_blindly_retried_after_restore():
    gateway, adapter = ActionGateway(), Adapter(fail=True)
    gateway.bind("session", adapter, task_id="task", commit="abc")
    await gateway.list("session", task_id="task")
    assert (
        await gateway.take("session", {"move": 2}, task_id="task", operation_id="x", approved=True)
        == "unknown"
    )
    restored = ActionGateway.from_snapshot(gateway.snapshot())
    restored.bind("session", adapter, task_id="task", commit="abc")
    assert (
        await restored.take("session", {"move": 2}, task_id="task", operation_id="x", approved=True)
        == "unknown"
    )
    assert adapter.calls == 1
