import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evertree.core.codex import CodexProvider
from evertree.core.provider import (
    AgentEvent,
    AgentRequest,
    ProviderError,
    ScriptedProvider,
    ToolDefinition,
)


@pytest.fixture(autouse=True)
def model_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    codex_home = tmp_path / "login"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    cache = codex_home / "models_cache.json"
    cache.write_text(
        json.dumps(
            {
                "account_id": "must-not-copy-account",
                "models": [
                    {
                        "slug": "gpt-6-luna",
                        "display_name": "Luna",
                        "description": "Exact public model metadata",
                        "supported_reasoning_levels": [{"effort": "high", "description": "High"}],
                        "default_reasoning_level": "medium",
                        "model_messages": {"instructions_template": "original instructions"},
                        "context_window": 196000,
                        "shell_type": "unified_exec",
                        "apply_patch_tool_type": "freeform",
                        "tool_mode": "code_mode_only",
                        "multi_agent_version": "v2",
                        "experimental_supported_tools": ["clock", "send_user_message_async"],
                        "unknown_secret_field": "must-not-copy-secret",
                    },
                    {"slug": "another-model", "unknown_secret_field": "must-not-copy-other"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return cache


class FakeClient:
    def __init__(self, config, approval_handler):
        self.config = config
        self.handler = approval_handler
        self.events = []
        self.closed = False

    def start(self):
        pass

    def initialize(self):
        return {"userAgent": "test"}

    def request(self, method, params, response_model):
        if method == "environment/add":
            self.environment_connection = params
            return response_model.model_validate({})
        if method == "thread/start":
            return response_model.model_validate(self.thread_start(params))
        assert method == "config/read"
        return response_model.model_validate(
            {
                "config": {
                    "mcp_servers": {"inherited": {"command": "must not run", "enabled": True}},
                    "shell_environment_policy": {"set": {"SECRET_TOKEN": "not for commands"}},
                }
            }
        )

    def thread_start(self, params):
        self.params = params
        return {
            "thread": {"id": "thread1"},
            "model": params["model"],
            "activePermissionProfile": {"id": params["permissions"]},
        }

    def turn_start(self, thread_id, prompt, params):
        self.turn_params = params
        self.events = [
            SimpleNamespace(method="item/agentMessage/delta", payload={"delta": '{"ok": true}'}),
            SimpleNamespace(
                method="item/completed",
                payload={"item": {"type": "agentMessage", "text": '{"ok": true}'}},
            ),
            SimpleNamespace(method="turn/completed", payload={"turn": {"status": "completed"}}),
        ]
        return {"turn": {"id": "turn1"}}

    def next_turn_notification(self, turn_id):
        return self.events.pop(0)

    def close(self):
        self.closed = True


class FakeExecutor:
    def __init__(self, workspace, state_dir):
        self.command_environment = {"PATH": "isolated-python-and-git"}
        self.environment = {
            "environmentId": "isolated",
            "cwd": str(workspace),
            "runtimeWorkspaceRoots": [str(workspace)],
        }
        self.closed = False

    async def start(self):
        return {
            "environmentId": "isolated",
            "execServerUrl": "ws://127.0.0.1:1234/",
            "authBearerToken": "test-only",
        }

    async def close(self):
        self.closed = True


def token_notification(total, *, last=None):
    def counters(number):
        return {
            "totalTokens": number,
            "inputTokens": number - 2,
            "outputTokens": 2,
            "cachedInputTokens": 0,
            "reasoningOutputTokens": 1,
        }

    return SimpleNamespace(
        method="thread/tokenUsage/updated",
        payload={"tokenUsage": {"total": counters(total), "last": counters(last or total)}},
    )


@pytest.mark.asyncio
async def test_sdk_model_effort_and_no_permissive_default(tmp_path):
    clients = []

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        clients.append(client)
        return client

    provider = CodexProvider(client_factory=factory)
    events = [
        event
        async for event in provider.run(
            "one", AgentRequest("Return ok", tmp_path, output_schema={"type": "object"})
        )
    ]
    assert events[-1].kind == "completed"
    assert events[-1].data["parsed"] == {"ok": True}
    assert clients[0].params["model"] == "gpt-6-luna"
    assert clients[0].turn_params["effort"] == "high"
    assert "sandbox" not in clients[0].params
    assert clients[0].params["permissions"].startswith("evertree_")
    assert clients[0].params["approvalPolicy"] == "never"
    assert clients[0].params["environments"] == []
    assert clients[0].params["dynamicTools"] == []
    assert clients[0].turn_params["environments"] == []
    assert clients[0].params["config"]["mcp_servers"]["inherited"]["enabled"] is False
    assert clients[0].params["config"]["shell_environment_policy"]["set"]["SECRET_TOKEN"] == ""
    assert "features.shell_tool=false" in clients[0].config.config_overrides
    assert "features.code_mode_only=false" in clients[0].config.config_overrides
    assert "tools.update_plan.enabled=false" in clients[0].config.config_overrides
    import tomllib

    profile = next(
        item for item in clients[0].config.config_overrides if item.startswith("permissions.")
    )
    rules = next(iter(tomllib.loads(profile)["permissions"].values()))
    assert rules["filesystem"][str(tmp_path.resolve())] == "deny"
    assert clients[0].closed


@pytest.mark.asyncio
async def test_model_cannot_expose_tools(tmp_path):
    provider = CodexProvider()
    with pytest.raises(ProviderError, match="cannot expose"):
        [
            event
            async for event in provider.run(
                "one", AgentRequest("x", tmp_path, tools=(ToolDefinition("write", "write", {}),))
            )
        ]


@pytest.mark.asyncio
async def test_scripted_tool_requires_declaration(tmp_path):
    provider = ScriptedProvider([[AgentEvent("tool_call", {"name": "unlisted"})]])

    async def handle(name, arguments):
        raise AssertionError("Must not execute")

    with pytest.raises(ProviderError, match="not declared"):
        [
            event
            async for event in provider.run(
                "one", AgentRequest("x", tmp_path, mode="exec"), tool_handler=handle
            )
        ]


@pytest.mark.asyncio
async def test_unknown_approval_is_denied(tmp_path):
    clients = []

    class ToolClient(FakeClient):
        def turn_start(self, *args):
            self.decision = self.handler(
                "item/commandExecution/requestApproval", {"command": "outside"}
            )
            return super().turn_start(*args)

    def factory(**kwargs):
        c = ToolClient(**kwargs)
        clients.append(c)
        return c

    provider = CodexProvider(client_factory=factory)
    [event async for event in provider.run("one", AgentRequest("x", tmp_path, mode="exec"))]
    assert clients[0].decision == {"decision": "decline"}


@pytest.mark.asyncio
async def test_dynamic_tool_request_dispatch(tmp_path):
    clients = []

    class ToolClient(FakeClient):
        def turn_start(self, *args):
            self.response = self.handler(
                "item/tool/call", {"tool": "lookup", "arguments": {"id": 2}}
            )
            return super().turn_start(*args)

    def factory(**kwargs):
        c = ToolClient(**kwargs)
        clients.append(c)
        return c

    async def lookup(name, arguments):
        assert name == "lookup"
        return {"found": arguments["id"]}

    request = AgentRequest(
        "x", tmp_path, mode="exec", tools=(ToolDefinition("lookup", "lookup", {"type": "object"}),)
    )
    events = [
        event
        async for event in CodexProvider(client_factory=factory).run(
            "one", request, tool_handler=lookup
        )
    ]
    assert clients[0].response["success"]
    assert [e.kind for e in events].count("tool_result") == 1
    assert clients[0].params["dynamicTools"][0]["name"] == "lookup"
    assert "features.shell_tool=false" in clients[0].config.config_overrides


@pytest.mark.asyncio
async def test_native_coding_has_scoped_profile_and_never_escalates(tmp_path):
    clients = []

    class ToolClient(FakeClient):
        def turn_start(self, *args):
            self.decision = self.handler(
                "item/commandExecution/requestApproval", {"command": "outside"}
            )
            return super().turn_start(*args)

    def factory(**kwargs):
        client = ToolClient(**kwargs)
        clients.append(client)
        return client

    async def approve(_):
        raise AssertionError("Native tool escape must not reach approval callback")

    events = [
        event
        async for event in CodexProvider(client_factory=factory, executor_factory=FakeExecutor).run(
            "one",
            AgentRequest("code", tmp_path, mode="exec", native_coding=True),
            approval_handler=approve,
        )
    ]
    assert events[-1].kind == "completed"
    client = clients[0]
    assert client.decision == {"decision": "decline"}
    assert "features.shell_tool=true" in client.config.config_overrides
    assert client.params["environments"][0]["environmentId"] == "isolated"
    assert client.turn_params["environments"] == client.params["environments"]
    assert client.environment_connection["authBearerToken"] == "test-only"
    import tomllib

    profile = next(
        item for item in client.config.config_overrides if item.startswith("permissions.")
    )
    rules = next(iter(tomllib.loads(profile)["permissions"].values()))
    assert rules["filesystem"][str(tmp_path.resolve())] == "write"
    assert rules["filesystem"][":root"] == "deny"
    assert rules["network"]["enabled"] is False


@pytest.mark.asyncio
async def test_missing_permission_profile_fails_before_turn(tmp_path):
    class UnsafeClient(FakeClient):
        def thread_start(self, params):
            return {"thread": {"id": "thread1"}, "model": params["model"]}

        def turn_start(self, *args):
            raise AssertionError("Must not bill a turn without permissions")

    events = [
        event
        async for event in CodexProvider(client_factory=UnsafeClient).run(
            "one", AgentRequest("x", tmp_path)
        )
    ]
    assert events[-1].kind == "error"
    assert "permissions" in events[-1].data["message"]


def test_model_cannot_enable_native_coding(tmp_path):
    with pytest.raises(ValueError, match="exec"):
        AgentRequest("x", tmp_path, native_coding=True)


@pytest.mark.asyncio
async def test_native_coding_requires_isolated_executor(tmp_path):
    class UnreadyClient(FakeClient):
        def thread_start(self, params):
            raise AssertionError("Do not create a coding thread without its sandbox")

    class UnreadyExecutor(FakeExecutor):
        async def start(self):
            raise RuntimeError("Isolated executor unavailable")

    events = [
        event
        async for event in CodexProvider(
            client_factory=UnreadyClient, executor_factory=UnreadyExecutor
        ).run("one", AgentRequest("x", tmp_path, mode="exec", native_coding=True))
    ]
    assert events[-1].kind == "error"
    assert "Isolated executor unavailable" in events[-1].data["message"]


async def test_cancel_waits_for_sdk_callback_to_stop(tmp_path):
    entered, stopped = asyncio.Event(), asyncio.Event()
    clients = []

    class WaitingClient(FakeClient):
        def turn_start(self, *args):
            self.handler("item/tool/call", {"tool": "wait", "arguments": {}})
            return super().turn_start(*args)

    def factory(**kwargs):
        client = WaitingClient(**kwargs)
        clients.append(client)
        return client

    async def tool_handler(_name, _arguments):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    provider = CodexProvider(client_factory=factory)

    async def consume():
        return [
            event
            async for event in provider.run(
                "one",
                AgentRequest(
                    "wait", tmp_path, mode="exec", tools=(ToolDefinition("wait", "wait", {}),)
                ),
                tool_handler=tool_handler,
            )
        ]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), 5)
    await asyncio.wait_for(provider.cancel("one"), 5)
    assert stopped.is_set()
    assert clients[0].closed
    assert any(event.kind == "cancelled" for event in await task)


@pytest.mark.asyncio
@pytest.mark.parametrize("resume", [False, True])
async def test_native_start_and_resume_bind_only_current_executor(tmp_path, resume):
    from evertree.core.provider import SessionRef

    clients, executors = [], []

    class RecordingClient(FakeClient):
        def request(self, method, params, response_model):
            if method == "thread/resume":
                assert params["threadId"] == "previous-session"
                return response_model.model_validate(self.thread_start(params))
            return super().request(method, params, response_model)

    def client_factory(**kwargs):
        client = RecordingClient(**kwargs)
        clients.append(client)
        return client

    def executor_factory(workspace, state_dir):
        executor = FakeExecutor(workspace, state_dir)
        executors.append(executor)
        return executor

    provider = CodexProvider(client_factory=client_factory, executor_factory=executor_factory)
    events = [
        event
        async for event in provider.run(
            "one",
            AgentRequest(
                "code",
                tmp_path,
                mode="exec",
                native_coding=True,
                session=SessionRef("codex", "previous-session") if resume else None,
            ),
        )
    ]
    assert events[-1].kind == "completed"
    assert clients[0].params["environments"] == [executors[0].environment]
    assert clients[0].turn_params["environments"] == [executors[0].environment]
    assert clients[0].turn_params["sandboxPolicy"] == {
        "type": "externalSandbox",
        "networkAccess": "restricted",
    }
    shell_policy = clients[0].params["config"]["shell_environment_policy"]
    assert shell_policy["inherit"] == "none"
    assert shell_policy["set"]["PATH"] == executors[0].command_environment["PATH"]
    assert shell_policy["set"]["SECRET_TOKEN"] == ""
    assert executors[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase", ["environment/add", "turn"])
async def test_executor_failure_never_retries_with_local_environment(tmp_path, failure_phase):
    clients, executors = [], []

    class FailingClient(FakeClient):
        def request(self, method, params, response_model):
            if method == "environment/add" and failure_phase == method:
                raise ConnectionError("Executor connection lost")
            return super().request(method, params, response_model)

        def next_turn_notification(self, turn_id):
            raise ConnectionError("Executor connection lost")

    def client_factory(**kwargs):
        client = FailingClient(**kwargs)
        clients.append(client)
        return client

    def executor_factory(workspace, state_dir):
        executor = FakeExecutor(workspace, state_dir)
        executors.append(executor)
        return executor

    provider = CodexProvider(client_factory=client_factory, executor_factory=executor_factory)
    events = [
        event
        async for event in provider.run(
            "one",
            AgentRequest("code", tmp_path, mode="exec", native_coding=True),
        )
    ]
    assert events[-1].kind == "error"
    assert "Executor connection lost" in events[-1].data["message"]
    assert not any(event.kind == "completed" for event in events)
    assert len(clients) == len(executors) == 1
    assert clients[0].closed and executors[0].closed
    if failure_phase == "environment/add":
        assert not hasattr(clients[0], "turn_params")
    else:
        assert clients[0].turn_params["environments"] == [executors[0].environment]


@pytest.mark.asyncio
async def test_computation_catalog_preserves_identity_and_only_restricts_capabilities(
    tmp_path, model_cache
):
    source = model_cache.read_bytes()
    clients = []

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        clients.append(client)
        return client

    provider = CodexProvider(state_dir=tmp_path / "state", client_factory=factory)
    events = [e async for e in provider.run("catalog", AgentRequest("compute", tmp_path))]
    assert events[-1].kind == "completed"
    assert model_cache.read_bytes() == source
    override = next(
        entry
        for entry in clients[0].config.config_overrides
        if entry.startswith("model_catalog_json=")
    )
    path = Path(json.loads(override.split("=", 1)[1]))
    assert path.is_relative_to(provider.state_dir)
    text = path.read_text(encoding="utf-8")
    assert "must-not-copy" not in text
    catalog = json.loads(text)
    assert len(catalog["models"]) == 1
    model = catalog["models"][0]
    original = json.loads(source)["models"][0]
    for field in (
        "slug",
        "display_name",
        "description",
        "default_reasoning_level",
        "supported_reasoning_levels",
        "model_messages",
        "context_window",
    ):
        assert model[field] == original[field]
    assert model["tool_mode"] == "direct"
    assert model["shell_type"] == "disabled"
    assert model["apply_patch_tool_type"] is None
    assert model["experimental_supported_tools"] == []
    assert clients[0].params["model"] == "gpt-6-luna"
    assert clients[0].turn_params["effort"] == "high"
    session = next(e.data for e in events if e.kind == "session")
    assert session["capability_restrictions"]["catalog_sha256"] == path.stem
    assert session["capability_restrictions"]["dynamic_tools"] == []
    assert session["provider_internal_requests"] == "not_exposed"


@pytest.mark.asyncio
async def test_native_catalog_is_unchanged_and_not_required(tmp_path, model_cache):
    model_cache.unlink()
    clients = []

    def factory(**kwargs):
        client = FakeClient(**kwargs)
        clients.append(client)
        return client

    provider = CodexProvider(client_factory=factory, executor_factory=FakeExecutor)
    events = [
        e
        async for e in provider.run(
            "native", AgentRequest("code", tmp_path, mode="exec", native_coding=True)
        )
    ]
    assert events[-1].kind == "completed"
    assert not any(c.startswith("model_catalog_json=") for c in clients[0].config.config_overrides)
    assert not model_cache.exists()
    assert not (provider.state_dir / "model-catalogs").exists()
    session = next(e.data for e in events if e.kind == "session")
    assert session["capability_restrictions"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["model", "effort"])
async def test_missing_exact_model_metadata_fails_without_a_turn(tmp_path, model_cache, missing):
    data = json.loads(model_cache.read_text(encoding="utf-8"))
    if missing == "model":
        data["models"] = []
    else:
        data["models"][0]["supported_reasoning_levels"] = [{"effort": "low"}]
    model_cache.write_text(json.dumps(data), encoding="utf-8")

    def forbidden_client(**kwargs):
        raise AssertionError("Cannot create a turn using fallback model metadata")

    events = [
        e
        async for e in CodexProvider(client_factory=forbidden_client).run(
            "missing", AgentRequest("compute", tmp_path)
        )
    ]
    assert events[-1].kind == "error"
    assert "Exact Luna metadata" in events[-1].data["message"]
    assert not any(e.kind == "session" for e in events)


@pytest.mark.asyncio
async def test_absent_catalog_bootstrap_is_nonbilled_and_owns_process_tree(
    tmp_path, model_cache, monkeypatch
):
    contents = model_cache.read_bytes()
    model_cache.unlink()
    clients, trees = [], []

    class BootstrapClient(FakeClient):
        def model_list(self, include_hidden):
            assert include_hidden is True
            assert not hasattr(self, "turn_params")
            model_cache.write_bytes(contents)
            return {"data": []}

    def factory(**kwargs):
        cls = BootstrapClient if not clients else FakeClient
        client = cls(**kwargs)
        clients.append(client)
        return client

    def attach(client):
        tree = SimpleNamespace(closed=False)
        tree.close = lambda: setattr(tree, "closed", True)
        trees.append(tree)
        return tree

    monkeypatch.setattr("evertree.core.codex.configuration._attach_process_tree", attach)
    events = [
        e
        async for e in CodexProvider(client_factory=factory).run(
            "bootstrap", AgentRequest("compute", tmp_path)
        )
    ]
    assert events[-1].kind == "completed"
    assert len(clients) == len(trees) == 2
    assert all(c.closed for c in clients)
    assert all(t.closed for t in trees)
    assert not hasattr(clients[0], "params")
    assert not any(c.startswith("model_catalog_json=") for c in clients[0].config.config_overrides)
    assert any(c.startswith("model_catalog_json=") for c in clients[1].config.config_overrides)


@pytest.mark.asyncio
async def test_absent_catalog_bootstrap_cannot_silently_fallback(tmp_path, model_cache):
    model_cache.unlink()
    clients = []

    class EmptyClient(FakeClient):
        def model_list(self, include_hidden):
            return {"data": []}

    def factory(**kwargs):
        client = EmptyClient(**kwargs)
        clients.append(client)
        return client

    events = [
        e
        async for e in CodexProvider(client_factory=factory).run(
            "bootstrap", AgentRequest("compute", tmp_path)
        )
    ]
    assert events[-1].kind == "error"
    assert "Exact Luna metadata" in events[-1].data["message"]
    assert len(clients) == 1 and clients[0].closed
    assert not hasattr(clients[0], "turn_params")


@pytest.mark.asyncio
async def test_model_resume_explicitly_clears_previous_dynamic_tools(tmp_path):
    from evertree.core.provider import SessionRef

    clients = []

    class ResumeClient(FakeClient):
        def request(self, method, params, response_model):
            if method == "thread/resume":
                assert params["dynamicTools"] == []
                assert params["environments"] == []
                return response_model.model_validate(self.thread_start(params))
            return super().request(method, params, response_model)

    def factory(**kwargs):
        client = ResumeClient(**kwargs)
        clients.append(client)
        return client

    events = [
        e
        async for e in CodexProvider(client_factory=factory).run(
            "resume",
            AgentRequest("compute", tmp_path, session=SessionRef("codex", "previous-exec")),
        )
    ]
    assert events[-1].kind == "completed"
    assert clients[0].turn_params["effort"] == "high"


async def test_usage_counts_all_responses_and_excludes_known_resumed_history(tmp_path):
    from evertree.core.provider import SessionRef

    totals = iter(((12, 12, 32), (42, 42, 72)))

    class UsageClient(FakeClient):
        def request(self, method, params, response_model):
            if method == "thread/resume":
                return response_model.model_validate(self.thread_start(params))
            return super().request(method, params, response_model)

        def turn_start(self, *args):
            result = super().turn_start(*args)
            self.events = [
                token_notification(total, last=12) for total in next(totals)
            ] + self.events
            return result

    provider = CodexProvider(client_factory=UsageClient)
    first = [e async for e in provider.run("first", AgentRequest("first", tmp_path))]
    second = [
        e
        async for e in provider.run(
            "second", AgentRequest("second", tmp_path, session=SessionRef("codex", "thread1"))
        )
    ]
    assert [e.data["total_tokens"] for e in first if e.kind == "usage"] == [12, 12, 32]
    assert [e.data["total_tokens"] for e in second if e.kind == "usage"] == [10, 10, 40]
    assert all(e.data["available"] for e in first + second if e.kind == "usage")
    assert first[-1].kind == second[-1].kind == "completed"


@pytest.mark.parametrize("reported", [True, False])
async def test_unknown_resume_baseline_or_missing_usage_is_explicitly_unavailable(
    tmp_path, reported
):
    from evertree.core.provider import SessionRef

    class UsageClient(FakeClient):
        def request(self, method, params, response_model):
            if method == "thread/resume":
                return response_model.model_validate(self.thread_start(params))
            return super().request(method, params, response_model)

        def turn_start(self, *args):
            result = super().turn_start(*args)
            if reported:
                self.events.insert(0, token_notification(9000, last=20))
            return result

    events = [
        e
        async for e in CodexProvider(client_factory=UsageClient).run(
            "unknown",
            AgentRequest(
                "resume", tmp_path, session=SessionRef("codex", "old") if reported else None
            ),
        )
    ]
    usage = [e.data for e in events if e.kind == "usage"]
    assert len(usage) == 1
    assert usage[0]["available"] is False
    assert all(value is None for key, value in usage[0].items() if key != "available")
    assert events[-1].kind == "completed"


async def test_native_and_dynamic_tools_share_event_contract_and_raw_audit(tmp_path):
    class EventClient(FakeClient):
        def turn_start(self, *args):
            result = super().turn_start(*args)
            self.handler(
                "item/tool/call", {"tool": "lookup", "callId": "dynamic1", "arguments": {"id": 2}}
            )
            shell = {
                "id": "shell1",
                "type": "commandExecution",
                "command": "python script.py",
                "cwd": str(tmp_path),
                "status": "inProgress",
            }
            patch = {
                "id": "patch1",
                "type": "fileChange",
                "status": "inProgress",
                "changes": [
                    {
                        "path": "script.py",
                        "kind": {"type": "update", "move_path": "renamed.py"},
                        "diff": "example diff",
                    }
                ],
            }
            self.events = [
                SimpleNamespace(method="item/started", payload={"item": shell}),
                SimpleNamespace(
                    method="item/completed",
                    payload={
                        "item": {
                            **shell,
                            "status": "failed",
                            "exitCode": 1,
                            "aggregatedOutput": "test failure",
                        }
                    },
                ),
                SimpleNamespace(method="item/started", payload={"item": patch}),
                SimpleNamespace(
                    method="item/completed", payload={"item": {**patch, "status": "completed"}}
                ),
                # Callback owns normalized dynamic events; SDK echoes stay audit-only.
                SimpleNamespace(
                    method="item/completed",
                    payload={
                        "item": {"type": "dynamicToolCall", "id": "dynamic1", "tool": "lookup"}
                    },
                ),
            ] + self.events
            return result

    async def lookup(_name, arguments):
        return {"found": arguments["id"]}

    request = AgentRequest(
        "code",
        tmp_path,
        mode="exec",
        native_coding=True,
        tools=(ToolDefinition("lookup", "lookup", {}),),
    )
    events = [
        e
        async for e in CodexProvider(client_factory=EventClient, executor_factory=FakeExecutor).run(
            "tools", request, tool_handler=lookup
        )
    ]
    calls = [e.data for e in events if e.kind == "tool_call"]
    results = [e.data for e in events if e.kind == "tool_result"]
    assert len(calls) == len(results) == 3
    assert all(set(call) == {"call_id", "name", "arguments"} for call in calls)
    assert all(
        set(result) == {"call_id", "name", "status", "result", "error"} for result in results
    )
    assert [call["call_id"] for call in calls] == [result["call_id"] for result in results]
    shell = next(result for result in results if result["call_id"] == "shell1")
    assert shell["status"] == "failed"
    assert shell["result"] == {"output": "test failure", "exit_code": 1}
    assert next(result for result in results if result["call_id"] == "dynamic1")["result"] == {
        "found": 2
    }
    changed = next(e.data for e in events if e.kind == "file_change")
    assert changed == {
        "call_id": "patch1",
        "path": "script.py",
        "operation": "update",
        "status": "completed",
        "diff": "example diff",
        "moved_to": "renamed.py",
    }
    assert any(
        e.kind == "provider_event" and e.data["payload"].get("item", {}).get("exitCode") == 1
        for e in events
    )


async def test_failed_dynamic_tool_result_keeps_call_identity(tmp_path):
    class ToolClient(FakeClient):
        def turn_start(self, *args):
            self.handler(
                "item/tool/call", {"tool": "lookup", "callId": "failure1", "arguments": {}}
            )
            return super().turn_start(*args)

    async def failure(*_):
        raise ValueError("Missing observation")

    request = AgentRequest(
        "call", tmp_path, mode="exec", tools=(ToolDefinition("lookup", "lookup", {}),)
    )
    events = [
        e
        async for e in CodexProvider(client_factory=ToolClient).run(
            "failure", request, tool_handler=failure
        )
    ]
    result = next(e.data for e in events if e.kind == "tool_result")
    assert result == {
        "call_id": "failure1",
        "name": "lookup",
        "status": "failed",
        "result": None,
        "error": "Missing observation",
    }
