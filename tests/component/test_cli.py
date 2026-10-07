from __future__ import annotations

import io
import json
import sys

import pytest

from evertree import cli
from evertree.application import EverTree, EverTreeEvent
from evertree.core.cognition.tasks import TaskStore
from evertree.core.provider import AgentEvent, AgentRequest, ScriptedProvider


class TransportAgent:
    """A transport fixture that completes only after its answer was delivered."""

    def __init__(self, home, approval_handler=None):
        self.home, self.approval_handler = home, approval_handler
        self.tasks = TaskStore()
        self.received = None
        self.delivered = []
        self.resumed = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def submit(self, prompt, **kwargs):
        self.received = (prompt, kwargs)
        self.state = self.tasks.create_task(prompt, task_id="task-one")
        return self.state

    async def resume(self, task_id, text=None, **kwargs):
        self.resumed = (task_id, text, kwargs)
        self.state = self.tasks.create_task("Saved objective", task_id=task_id)
        return self.state

    async def events(self):
        yield EverTreeEvent(
            "answer", self.state.id, {"text": "Exact answer", "delivery_id": "delivery"}
        )
        assert self.delivered == [("delivery", True)], "CLI must acknowledge actual output"
        self.state.status = "succeeded"
        yield EverTreeEvent("task_completed", self.state.id, {"reason": "Verified"})

    async def acknowledge_delivery(self, delivery_id, *, delivered=True):
        self.delivered.append((delivery_id, delivered))


@pytest.fixture
def transport(monkeypatch):
    created = []

    def factory(*args, **kwargs):
        instance = TransportAgent(*args, **kwargs)
        created.append(instance)
        return instance

    monkeypatch.setattr(cli, "EverTree", factory)
    return created


def test_run_outputs_then_acknowledges_and_passes_explicit_user_limit(transport, capsys, tmp_path):
    status = cli.main(["--home", str(tmp_path), "run", "Compute the answer", "--max-minutes", "17"])
    assert status == 0
    out = capsys.readouterr()
    assert "Exact answer" in out.out
    assert "task-one: succeeded" in out.err
    assert transport[0].received == (
        "Compute the answer",
        {"task_id": None, "hard_limits": {"active_time_minutes": 17.0}},
    )
    assert transport[0].approval_handler is cli.approve


def test_run_reads_complete_stdin_without_assuming_approval(transport, monkeypatch, capsys):
    text = "First line\nSecond line\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    assert cli.main(["run"]) == 0
    assert transport[0].received[0] == text
    capsys.readouterr()


def test_tasks_resume_preserves_identity_and_new_input(transport, capsys):
    assert cli.main(["tasks", "resume", "saved-task", "The letter r"]) == 0
    assert transport[0].resumed == ("saved-task", "The letter r", {"hard_limits": None})
    assert "saved-task: succeeded" in capsys.readouterr().err


def test_run_existing_task_applies_explicit_new_limit(transport, capsys):
    assert cli.main(["run", "Continue", "--task", "saved", "--max-minutes", "40"]) == 0
    assert transport[0].resumed == (
        "saved",
        "Continue",
        {"hard_limits": {"active_time_minutes": 40}},
    )
    capsys.readouterr()


def test_run_json_emits_delivered_answer_then_terminal_event(transport, capsys):
    assert cli.main(["run", "Compute", "--json"]) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[0]["event"] == "answer"
    assert records[0]["answer"] == "Exact answer"
    assert records[1]["status"] == "succeeded"


async def test_noninteractive_boundary_approval_is_denied(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(
        "builtins.input", lambda _: pytest.fail("No noninteractive approval prompt")
    )
    assert await cli.approve({"action": "external write"}) is False


async def test_interactive_boundary_approval_requires_explicit_yes(monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert not await cli.approve({"action": "external write"})
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert await cli.approve({"action": "external write"})


def test_missing_prompt_and_invalid_hard_limit_return_failure(transport, monkeypatch, capsys):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Terminal())
    assert cli.main(["run"]) == 1
    assert "Supply a request" in capsys.readouterr().err
    assert cli.main(["run", "hello", "--max-minutes", "nan"]) == 1
    assert "finite and positive" in capsys.readouterr().err


def test_doctor_reports_exact_provider_or_sandbox_failure(monkeypatch, capsys):
    class Provider:
        def __init__(self, **_kwargs):
            pass

        async def doctor(self):
            return {"available": True, "authenticated": True, "model": "luna"}

        async def close(self):
            pass

    monkeypatch.setattr(cli, "CodexProvider", Provider)
    monkeypatch.setattr(cli, "check_sandbox", lambda: {"app_container": True, "read_denied": False})
    assert cli.main(["doctor"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["provider"]["available"] is True
    assert data["sandbox"]["available"] is False
    assert data["ready"] is False


def test_cli_exposes_inspection_commands_without_model_calls():
    for args in (
        ["init"],
        ["doctor"],
        ["tasks", "list"],
        ["tasks", "show", "task"],
        ["tasks", "cancel", "task"],
        ["graph", "Self"],
        ["memory", "experiment"],
        ["traces", "1"],
        ["programs"],
        ["backup", "--list"],
        ["restore"],
    ):
        assert cli.parser().parse_args(args).command == args[0]


def test_cli_uses_application_and_provider_definitions():
    assert EverTree.__module__ == "evertree.application"
    assert AgentRequest.__module__ == "evertree.core.provider"
    assert AgentEvent.__module__ == "evertree.core.provider"
    assert ScriptedProvider.name == "scripted"
