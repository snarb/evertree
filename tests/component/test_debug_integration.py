"""Debug harness configuration and provider forwarding without external services."""

import json

import pytest

from evertree.core.provider import AgentEvent
from evertree.core.semantics.config import SemanticConfig
from evertree.core.semantics.index import RedisSearchIndex
from evertree.debug_integration import DebugSession, load_debug_environment


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
    assert json.loads((tmp_path / "receipt.json").read_text()) is None
    assert (tmp_path / "graph.json").is_file()
    assert (tmp_path / "trace.json").is_file()


async def test_model_forwards_program_request_and_returns_provider_output(tmp_path):
    session = DebugSession(tmp_path)
    requests = []
    provider_output = {"action": "search", "query": "new query from provider"}

    class RecordingProvider:
        async def run(self, run_id, request):
            requests.append(request)
            yield AgentEvent("completed", {"parsed": provider_output})

    session.provider = RecordingProvider()
    payload = {
        "prompt": "experience selected by the Program",
        "instructions": "instructions selected by the Program",
        "output_schema": {"type": "object"},
    }
    result = await session.step("agent.run", payload)
    assert result["parsed"] is provider_output
    assert len(requests) == 1
    request = requests[0]
    assert request.prompt == payload["prompt"]
    assert request.instructions == payload["instructions"]
    assert request.output_schema == payload["output_schema"]
    assert request.model == session.config.remember.model
    assert request.effort == session.config.remember.effort
    assert session.calls[0]["result"] == result
