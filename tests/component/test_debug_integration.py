"""Debug harness configuration and provider forwarding without external services."""

import json

import pytest

from evertree.core.provider import LLMEvent, ScriptedProvider
from evertree.core.semantics.config import SemanticConfig
from evertree.core.semantics.index import RedisSearchIndex
from evertree.debug_integration import CONSCIOUS_ANALYSIS, DebugSession, load_debug_environment
from evertree.processes.semantic_processing.knowledge_integration._exec import run


def test_load_local_secrets_preserves_environment_and_accepts_test_redis(tmp_path, monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "EVERTREE_REDIS_URL",
        "EVERTREE_TEST_REDIS_URL",
        "UNRELATED_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "from-pycharm")
    (tmp_path / ".env").write_text(
        'OPENAI_API_KEY="from-file"\nEVERTREE_TEST_REDIS_URL="redis://test/$literal"\n'
        'UNRELATED_KEY="do-not-load"\n',
        encoding="utf-8",
    )
    load_debug_environment(tmp_path, SemanticConfig())
    import os

    assert os.environ["OPENAI_API_KEY"] == "from-pycharm"
    assert os.environ["EVERTREE_REDIS_URL"] == "redis://test/$literal"
    assert "UNRELATED_KEY" not in os.environ


async def test_missing_search_configuration_stops_before_model_usage(tmp_path, monkeypatch):
    session = DebugSession(tmp_path)
    for name in (session.config.redis_url_env, session.config.openai_key_env):
        monkeypatch.delenv(name, raising=False)
    assert isinstance(session.index, RedisSearchIndex)
    with pytest.raises(RuntimeError, match="PyCharm"):
        await session.run()
    assert session.calls == []
    assert json.loads((tmp_path / "result.json").read_text()) is None
    assert (tmp_path / "graph.json").is_file()
    assert (tmp_path / "trace.json").is_file()


@pytest.mark.parametrize("timeout_seconds", [None, 120])
async def test_model_forwards_program_request_and_returns_provider_output(
    tmp_path, timeout_seconds
):
    session = DebugSession(tmp_path, timeout_seconds=timeout_seconds)
    requests = []
    provider_output = {"query": "new query from provider"}

    class RecordingProvider:
        async def run(self, run_id, request, *, tool_handler=None):
            assert tool_handler is None
            requests.append(request)
            yield LLMEvent("completed", {"parsed": provider_output})

    session.provider = RecordingProvider()
    payload = {
        "prompt": "experience selected by the Program",
        "instructions": "instructions selected by the Program",
        "output_schema": {"type": "object"},
    }
    result = await session.step("llm.run", payload)
    assert result["parsed"] is provider_output
    assert len(requests) == 1
    request = requests[0]
    assert request.prompt == payload["prompt"]
    assert request.instructions == payload["instructions"]
    assert request.output_schema == payload["output_schema"]
    assert request.model == session.config.remember.model
    assert request.effort == session.config.remember.effort
    assert request.timeout_seconds == timeout_seconds
    assert session.calls[0]["result"] == result


async def test_debug_integration_forwards_native_tools_and_records_direct_writes(tmp_path):
    session = DebugSession(tmp_path)
    assert session.timeout_seconds is None
    assert set(session.metadata["integration_context"]) == {"task"}
    session.record_experience()
    refs = session.experience_refs

    class Provider(ScriptedProvider):
        async def run(self, request_id, request, **kwargs):
            if not self.scripts:
                self.scripts.append([LLMEvent("completed", {"text": ""})])
            self.scripts[0].insert(
                next(
                    (
                        i
                        for i, event in enumerate(self.scripts[0])
                        if event.kind in {"usage", "completed"}
                    ),
                    len(self.scripts[0]),
                ),
                LLMEvent(
                    "tool_call",
                    {"name": "finish_section", "arguments": {"complete": True, "remaining": ""}},
                ),
            )
            async for event in super().run(request_id, request, **kwargs):
                yield event

    session.provider = Provider(
        [
            [
                LLMEvent(
                    "tool_call",
                    {
                        "name": "save_note",
                        "arguments": {
                            "name": "Retained analysis",
                            "source": refs[-1],
                            "sources": [],
                        },
                    },
                ),
                LLMEvent("usage", {"available": True, "total_tokens": 17}),
                LLMEvent("completed", {"text": ""}),
            ],
            [LLMEvent("completed", {"text": ""})],
        ]
    )
    try:
        result = (await run(session, refs))["result"]
        assert len(result["writes"]) == 1
        assert session.graph.find("Retained analysis").description == CONSCIOUS_ANALYSIS
        request = session.provider.requests[0]
        assert set(json.loads(request.prompt)["material"]["context"]) == {"task"}
        assert request.mode == "exec" and not request.native_coding
        assert request.output_schema is None
        assert {"save_note", "update", "delete"} <= {tool.name for tool in request.tools}
        (saved,) = [call for call in session.tool_calls() if call["name"] != "finish_section"]
        assert saved["name"] == "save_note" and saved["result"] == result["writes"][0]
        assert [
            call["method"]
            for call in session.calls
            if call["method"] not in {"trace", "semantic.prepare_sources", "tool:finish_section"}
        ] == [
            "semantic.sources",
            "tool:save_note",
            "semantic.write",
            "attribution.refresh_norms",
        ]
        assert sum(call["method"] == "semantic.prepare_sources" for call in session.calls) == len(
            session.provider.requests
        )
        progress = [
            event.output
            for event in session.memory.events
            if event.operator == "integration_processing"
        ]
        assert progress[0]["status"] == "incomplete"
        assert progress[-1]["status"] == "processed"
        transcripts = [json.loads(path.read_text()) for path in tmp_path.glob("model-*.json")]
        assert len(transcripts) == len(session.provider.requests)
        events = next(
            events for events in transcripts if any(row["kind"] == "usage" for row in events)
        )
        assert events[-1]["kind"] == "completed"
        assert events[-2] == {"kind": "usage", "data": {"available": True, "total_tokens": 17}}
        assert not session.provider.cancelled
    finally:
        await session.provider.close()
        await session.index.close()


async def test_live_evaluation_native_bridge_accepts_no_writes_and_records_final_usage(tmp_path):
    from evertree.core.values import json_value
    from tests.live.test_knowledge_integration import _native_context
    from tests.support.semantics import semantic_world

    world = semantic_world()
    source_run = world.memory.start_run("observation", "evaluation", {})
    event = world.memory.record(source_run, "input", output="Routine measurement")
    refs = [json_value(world.memory.output_ref(event))]
    world.memory.finish_run(source_run)
    provider = ScriptedProvider(
        [
            [
                LLMEvent(
                    "tool_call",
                    {"name": "finish_section", "arguments": {"complete": True, "remaining": ""}},
                ),
                LLMEvent("usage", {"available": True, "total_tokens": 23}),
                LLMEvent("completed", {"text": ""}),
            ],
        ]
    )
    transcript = []
    try:
        async with _native_context(world, provider, tmp_path, transcript, {}, "test") as ctx:
            result = (await run(ctx, refs))["result"]
        assert result["writes"] == []
        assert result["processing"]["status"] == "processed"
        (request,) = provider.requests
        assert request.tools and request.output_schema is None
        (history,) = [entry["tool_history"] for entry in transcript if "tool_history" in entry]
        assert [call["name"] for call in history] == ["finish_section"]
        (events,) = [entry["events"] for entry in transcript if "events" in entry]
        assert events[-1]["kind"] == "completed"
        assert events[-2] == {"kind": "usage", "data": {"available": True, "total_tokens": 23}}
        assert not provider.cancelled
    finally:
        await provider.close()


@pytest.mark.parametrize("failure", [KeyError("bug"), None])
async def test_llm_dialogue_fails_like_runtime_on_handler_bug_or_limit(tmp_path, failure):
    """Only ValueError, TypeError and PermissionError reach the model; other failures end the run."""
    session = DebugSession(tmp_path)
    call = LLMEvent("tool_call", {"name": "read", "arguments": {}})
    session.provider = ScriptedProvider([[call, call, LLMEvent("completed", {"text": ""})]])
    tool = {
        "name": "read",
        "description": "Read.",
        "input_schema": {"type": "object"},
        "read_only": True,
    }

    async def handler(name, arguments):
        if failure:
            raise failure
        return {}

    try:
        with pytest.raises(Exception, match="bug" if failure else "tool-call limit"):
            await session.llm(
                {"prompt": "x", "instructions": ""},
                tools=[tool],
                tool_handler=handler,
                max_tool_calls=1,
            )
        assert session.tool_calls()[0]["name"] == "read"
    finally:
        await session.provider.close()
        await session.index.close()
