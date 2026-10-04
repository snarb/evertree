"""Opt-in checks against the signed-in Codex account, never part of offline CI."""

import json
import os
from uuid import uuid4

import pytest

from evertree.core.codex_provider import CodexProvider
from evertree.core.provider import AgentRequest, SessionRef, ToolDefinition

pytestmark = pytest.mark.skipif(
    os.environ.get("EVERTREE_CODEX_INTEGRATION") != "1",
    reason="Set EVERTREE_CODEX_INTEGRATION=1 to use the current Codex account",
)


async def collect(provider, request, **kwargs):
    events = [event async for event in provider.run(uuid4().hex, request, **kwargs)]
    errors = [event.data for event in events if event.kind == "error"]
    assert not errors, errors
    completed = [event for event in events if event.kind == "completed"]
    assert len(completed) == 1
    usage = [event.data for event in events if event.kind == "usage"]
    assert usage and all(item["available"] and type(item["total_tokens"]) is int for item in usage)
    totals = [item["total_tokens"] for item in usage]
    assert totals == sorted(totals) and totals[-1] > 0
    for event in events:
        if event.kind == "tool_call":
            assert set(event.data) == {"call_id", "name", "arguments"}
        elif event.kind == "tool_result":
            assert set(event.data) == {"call_id", "name", "status", "result", "error"}
    return events, completed[0].data


async def test_live_model_dynamic_tool_and_session_resume(tmp_path):
    provider = CodexProvider()
    schema = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    calls = []

    async def lookup(name, arguments):
        assert name == "read_test_value"
        calls.append(arguments)
        return {"value": 17}

    try:
        _, model = await collect(
            provider, AgentRequest("Return the integer value 3.", tmp_path, output_schema=schema)
        )
        assert model["parsed"] == {"value": 3}
        events, result = await collect(
            provider,
            AgentRequest(
                "Call read_test_value exactly once and return its value.",
                tmp_path,
                mode="exec",
                output_schema=schema,
                tools=(
                    ToolDefinition(
                        "read_test_value",
                        "Read the supplied test value",
                        {"type": "object", "properties": {}, "additionalProperties": False},
                    ),
                ),
            ),
            tool_handler=lookup,
        )
        assert calls == [{}]
        assert result["parsed"] == {"value": 17}
        session = next(event.data for event in events if event.kind == "session")
        assert session["requested_model"] == "gpt-6-luna"
        assert session["requested_effort"] == "high"
        _, resumed = await collect(
            provider,
            AgentRequest(
                "Return the value from the previous tool result plus one.",
                tmp_path,
                output_schema=schema,
                session=SessionRef("codex", session["id"]),
            ),
        )
        assert resumed["parsed"] == {"value": 18}
    finally:
        await provider.close()


async def test_live_native_coding_tools(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    canary = tmp_path / "private-canary.txt"
    canary.write_text("integration canary", encoding="utf-8")
    schema = {
        "type": "object",
        "properties": {
            "tested": {"type": "boolean"},
            "read_denied": {"type": "boolean"},
            "write_denied": {"type": "boolean"},
        },
        "required": ["tested", "read_denied", "write_denied"],
        "additionalProperties": False,
    }
    provider = CodexProvider()
    try:
        events, result = await collect(
            provider,
            AgentRequest(
                f"Create add.py with add(a,b) and test_add.py using unittest. "
                "Run tests using the isolated Python interpreter on PATH. "
                f"Using a shell command, attempt to read and write this sibling canary: {canary}. "
                "These attempts must be denied. Do not retry with elevated permissions. "
                "Report only observed outcomes; tested is true only if tests passed.",
                workspace,
                mode="exec",
                native_coding=True,
                output_schema=schema,
                timeout_seconds=300,
            ),
        )
        outcomes = [
            event.data for event in events if event.kind in {"tool_result", "file_change", "error"}
        ]
        (tmp_path / "tool-events.json").write_text(json.dumps(outcomes, indent=2), encoding="utf-8")
        assert result["parsed"] == {"tested": True, "read_denied": True, "write_denied": True}, (
            outcomes
        )
        assert (workspace / "add.py").is_file()
        assert (workspace / "test_add.py").is_file()
        assert canary.read_text(encoding="utf-8") == "integration canary"
        assert any(
            event.kind == "tool_result" and event.data["name"] == "shell" for event in events
        )
    finally:
        await provider.close()
