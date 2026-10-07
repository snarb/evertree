import json

import pytest

from evertree.core.actions import ActionGateway
from tests.support.actions import Adapter


@pytest.mark.asyncio
async def test_crash_after_send_recovers_intent_over_stale_snapshot(tmp_path):
    """Real journal writes and reads verify durable action receipts and recovery."""

    class Crash(BaseException):
        pass

    journal = tmp_path / "actions.jsonl"

    class CrashingAdapter(Adapter):
        async def execute(self, command):
            self.calls += 1
            durable = json.loads(journal.read_text().splitlines()[-1])
            assert durable["operation"]["status"] == "unknown"
            raise Crash()

    gateway, adapter = ActionGateway(journal=journal), CrashingAdapter()
    stale = gateway.snapshot()
    gateway.bind("session", adapter, task_id="task", commit="abc")
    await gateway.list("session", task_id="task")
    with pytest.raises(Crash):
        await gateway.take("session", {"move": 2}, task_id="task", operation_id="x", approved=True)
    recovered = ActionGateway.from_snapshot(stale, journal=journal)
    assert recovered.pending("task") == [
        {"operation_id": "x", "session": "session", "status": "unknown"}
    ]
    assert recovered.pending("other-task") == []
    with pytest.raises(ValueError, match="new identity"):
        recovered.bind("session", adapter, task_id="other-task", commit="abc")
    recovered.bind("session", adapter, task_id="task", commit="abc")
    assert (
        await recovered.take(
            "session", {"move": 2}, task_id="task", operation_id="x", approved=True
        )
        == "unknown"
    )
    assert adapter.calls == 1
    recovered.reconcile("x", "accepted", evidence="host-confirmed receipt")
    again = ActionGateway.from_snapshot(stale, journal=journal)
    again.bind("session", adapter, task_id="task", commit="abc")
    assert (
        await again.take("session", {"move": 2}, task_id="task", operation_id="x", approved=True)
        == "accepted"
    )
    assert again.pending("task") == []
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_torn_outcome_keeps_unknown_and_allows_durable_reconciliation(tmp_path):
    """Real journal writes and reads verify durable action receipts and recovery."""
    journal = tmp_path / "actions.jsonl"
    gateway, adapter = ActionGateway(journal=journal), Adapter(fail=True)
    gateway.bind("session", adapter, task_id="task", commit="abc")
    await gateway.list("session", task_id="task")
    await gateway.take("session", {"move": 2}, task_id="task", operation_id="x", approved=True)
    with journal.open("ab") as stream:
        stream.write(b'{"operation_id": "x", "operation":')
    recovered = ActionGateway(journal=journal)
    assert recovered.pending("task")
    recovered.reconcile("x", "rejected", evidence="host confirmed command was not accepted")
    assert not ActionGateway(journal=journal).pending("task")


@pytest.mark.asyncio
async def test_action_is_not_sent_if_intent_cannot_be_synced(tmp_path, monkeypatch):
    """Real journal writes and reads verify durable action receipts and recovery."""
    gateway, adapter = ActionGateway(journal=tmp_path / "actions.jsonl"), Adapter()
    gateway.bind("session", adapter, task_id="task", commit="abc")
    await gateway.list("session", task_id="task")

    def failed_fsync(_):
        raise OSError("disk unavailable")

    monkeypatch.setattr("evertree.core.actions.os.fsync", failed_fsync)
    with pytest.raises(OSError):
        await gateway.take("session", {"move": 2}, task_id="task", operation_id="x", approved=True)
    assert adapter.calls == 0


@pytest.mark.asyncio
async def test_journal_rejects_operation_identity_collision(tmp_path):
    """Real journal writes and reads verify durable action receipts and recovery."""
    journal = tmp_path / "actions.jsonl"
    gateway, adapter = ActionGateway(journal=journal), Adapter()
    gateway.bind("session", adapter, task_id="task", commit="abc")
    await gateway.list("session", task_id="task")
    await gateway.take("session", {"move": 2}, task_id="task", operation_id="x", approved=True)
    snapshot = gateway.snapshot()
    snapshot["operations"]["x"]["fingerprint"] = json.dumps(["session", {"move": 9}])
    with pytest.raises(ValueError, match="identity reused"):
        ActionGateway.from_snapshot(snapshot, journal=journal)
