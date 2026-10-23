import asyncio
import json
from contextvars import Context
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from evertree.core.codex.provider import CodexProvider
from evertree.core.provider import (
    LLMEvent,
    LLMRequest,
    ProviderError,
    ScriptedProvider,
    ToolDefinition,
)
from tests.support.tokens import offline_tokenizer  # noqa: F401 -- offline BPE fixture


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
        if method == "thread/items/list":
            return response_model.model_validate(
                {
                    "data": [
                        {
                            "item": {
                                "type": "userMessage",
                                "content": [{"type": "text", "text": "prior request"}],
                            },
                            "turnId": "old",
                        }
                    ],
                    "nextCursor": None,
                }
            )
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
            "thread": {"id": "thread1", "ephemeral": params["ephemeral"]},
            "model": params["model"],
            "activePermissionProfile": {"id": params["permissions"]},
        }

    def turn_start(self, thread_id, prompt, params):
        self.prompt = prompt
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


async def test_sdk_thread_callback_keeps_application_execution_and_search_scope(app):
    """SDK reader callbacks have their own context, unlike asyncio.to_thread test clients."""
    from evertree.core.runtime.controller import RuntimeBusy
    from evertree.core.runtime.coordination import semantic_scope
    from tests.support.semantics import EmptyIndex

    scopes = []

    class Index(EmptyIndex):
        async def lexical(self, *args):
            scopes.append(semantic_scope.get())
            with pytest.raises(RuntimeBusy, match="execution chain"):
                Context().run(app.graph.reserve_id)
            return [{"ids": []} for _ in args[1]]

    class DetachedClient(FakeClient):
        def turn_start(self, *args):
            result = super().turn_start(*args)
            self.events.insert(0, SimpleNamespace(method="test/call", payload={}))
            return result

        def next_turn_notification(self, turn_id):
            event = super().next_turn_notification(turn_id)
            if event.method == "test/call":
                callback = Thread(
                    target=Context().run,
                    args=(
                        self.handler,
                        "item/tool/call",
                        {
                            "namespace": "graph",
                            "tool": "search",
                            "callId": "native-search",
                            "arguments": {"queries": ["unrecorded weight phrase"]},
                        },
                    ),
                )
                callback.start()
                callback.join(timeout=10)
                assert not callback.is_alive()
                return super().next_turn_notification(turn_id)
            return event

    app.search_index = Index()
    app.provider = CodexProvider(client_factory=DetachedClient)
    task = app.tasks.create_task("Read retained weight observations")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Native callback")
    request = LLMRequest(
        "{}",
        app._workspace(task.id),
        mode="exec",
        tools=tuple(tool for tool in app._tools() if tool.name == "graph.search"),
    )
    await app._invoke(task.id, request, conversation=True)
    calls = [
        event.output["data"]
        for event in app.memory.events
        if event.operator == "provider_event" and event.output.get("kind") == "tool_result"
    ]
    assert len(calls) == 1
    assert calls[0]["call_id"] == "native-search"
    assert calls[0]["status"] == "completed", calls[0]
    assert calls[0]["result"]["status"] == "complete"
    assert scopes and all(scope.startswith("consciousness:") for scope in scopes)
    assert semantic_scope.get() is None
    assert not app._execution.busy


async def test_consciousness_property_tools_dispatch_native_callbacks_to_real_stores(app):
    from evertree._application.prompts import tool_sets
    from evertree.core.attribution_evidence import AttributionEvidence
    from evertree.core.semantics.tools import READ_TOOLS
    from tests.support.semantics import recorded_experience, recorded_messages, write_action

    world = SimpleNamespace(graph=app.graph, memory=app.memory, service=app._semantics())
    sequence = 0

    def write(action, **fields):
        nonlocal sequence
        sequence += 1
        refs = recorded_messages(world, str(fields))
        _, metadata = recorded_experience(world)
        result = write_action(
            world,
            refs,
            metadata,
            {"action": action, "sources": refs, **fields},
            key=str(sequence),
        )
        assert "error" not in result, result
        return result["object"]

    def create(action, name, **fields):
        return write(action, name=name, description=None, **fields)

    domain = create("create_prototype", "Dog", parent=None)
    numeric = create("create_property", "Body mass", unit="kg", applies_to=[domain])
    classes = [create("create_concept", name) for name in ("Small", "Medium", "Large")]
    subjects = []
    for name, value in (("Jack", 8), ("Luna", 5), ("Grom", 10)):
        subject = create("create_instance", name, prototype=domain)
        subjects.append(subject)
        write(
            "relate",
            relation=app.graph.find("HAS_NUMERIC_VALUE").id,
            arguments=[
                {"role": key, "value": item}
                for key, item in {
                    "entity": subject,
                    "property": numeric,
                    "value": value,
                    "unit": "kg",
                }.items()
            ],
            conditions=[],
            description="An owner's measurement",
        )
    qualitative = create(
        "create_qualitative_property",
        "Relative size",
        property=numeric,
        domain=domain,
        classes=classes,
        conditions={},
    )
    assessment = AttributionEvidence(app.attribution, app.memory)
    for subject in subjects:
        prepared = assessment.prepare(subject, qualitative)
        source = next(item for item in prepared["sources"] if item["role"] == "measurement")
        chosen = prepared["conditional_interpretation"]["class"]
        assessment.record(
            subject,
            qualitative,
            prepared["input_revision"],
            assign=[
                {
                    "source_ref": source["ref"],
                    "likelihoods": {
                        str(identity): 0.8 if identity == chosen else 0.1 for identity in classes
                    },
                    "dependency_root": source["dependency_root"],
                }
            ],
            parameters=prepared["parameters"],
            at=prepared["at"],
        )

    calls = [
        (
            "read_property",
            {"subject": subjects[2], "property": qualitative, "point_policy": "argmax"},
        ),
        ("interpret_property", {"property": qualitative, "value": 7, "unit": "kg"}),
        (
            "select_properties",
            {
                "subjects": subjects,
                "order_by": {
                    "property": qualitative,
                    "direction": "desc",
                    "alternative": classes[2],
                },
                "limit": 1,
            },
        ),
    ]
    declared = {tool.name: tool for tool in app._tools()}
    shared = {tool.name: tool for tool in READ_TOOLS}
    for name, _ in calls:
        assert declared["graph." + name].input_schema == shared[name].input_schema
        assert declared["graph." + name].read_only
    temporal = next(
        tool
        for group in tool_sets()
        for tool in group.tools
        if tool.name == "graph.read_property_at"
    )
    assert {"valid_at", "known_at"} <= temporal.input_schema["properties"].keys()

    class PropertyClient(FakeClient):
        def turn_start(self, *args):
            result = super().turn_start(*args)
            self.events.insert(0, SimpleNamespace(method="test/call", payload={}))
            return result

        def next_turn_notification(self, turn_id):
            event = super().next_turn_notification(turn_id)
            if event.method == "test/call":
                for name, arguments in calls:
                    callback = Thread(
                        target=Context().run,
                        args=(
                            self.handler,
                            "item/tool/call",
                            {
                                "namespace": "graph",
                                "tool": name,
                                "callId": name,
                                "arguments": arguments,
                            },
                        ),
                    )
                    callback.start()
                    callback.join(timeout=10)
                    assert not callback.is_alive()
                return super().next_turn_notification(turn_id)
            return event

    before = app.graph.snapshot(), app.beliefs.snapshot(), app.attribution.snapshot()
    app.provider = CodexProvider(client_factory=PropertyClient)
    task = app.tasks.create_task("Read and compare learned dog size")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Native property reads")
    request = LLMRequest("{}", app._workspace(task.id), mode="exec", tools=app._tools())
    await app._invoke(task.id, request, conversation=True)
    results = {
        event.output["data"]["call_id"]: event.output["data"]
        for event in app.memory.events
        if event.operator == "provider_event" and event.output.get("kind") == "tool_result"
    }
    assert set(results) == {name for name, _ in calls}
    assert all(item["status"] == "completed" for item in results.values()), results
    assert results["read_property"]["result"]["value_U"] == classes[2]
    assert results["interpret_property"]["result"]["class"] == classes[0]
    assert results["select_properties"]["result"]["items"][0]["subject"] == subjects[2]
    assert before == (app.graph.snapshot(), app.beliefs.snapshot(), app.attribution.snapshot())


async def test_invalid_model_reference_fails_its_tool_and_allows_valid_callback_retry(app):
    from evertree.core.values import json_value

    run = app.memory.start_run("Observation", "test", {})
    source = app.memory.record(run, "user_input", output={"weight": 8})
    app.memory.finish_run(run)
    valid = json_value(app.memory.output_ref(source))
    invalid = {**valid, "output_path": ["class"]}
    bad_note = {"text": "Invalid note", "kind": "note", "source_refs": [invalid]}
    good_note = {"text": "Retained weight is 8", "kind": "note", "source_refs": [valid]}
    calls = [
        ("bad-note", "record_analysis", bad_note),
        ("repaired-note", "record_analysis", good_note),
        ("subsequent-read", "graph.describe", {"subject": app.graph.find("Self").id}),
    ]
    callbacks = {}

    class RepairClient(FakeClient):
        def turn_start(self, *args):
            result = super().turn_start(*args)
            self.events[:0] = [
                SimpleNamespace(
                    method="item/started",
                    payload={
                        "item": {
                            "type": "dynamicToolCall",
                            "id": "bad-note",
                            "tool": "record_analysis",
                            "arguments": bad_note,
                        }
                    },
                ),
                SimpleNamespace(method="test/call", payload={}),
            ]
            return result

        def next_turn_notification(self, turn_id):
            event = super().next_turn_notification(turn_id)
            if event.method == "test/call":
                for call_id, name, arguments in calls:

                    def invoke(call_id=call_id, name=name, arguments=arguments):
                        callbacks[call_id] = self.handler(
                            "item/tool/call",
                            {"tool": name, "callId": call_id, "arguments": arguments},
                        )

                    callback = Thread(target=Context().run, args=(invoke,))
                    callback.start()
                    callback.join(timeout=10)
                    assert not callback.is_alive()
                return super().next_turn_notification(turn_id)
            return event

    app.provider = CodexProvider(client_factory=RepairClient)
    task = app.tasks.create_task("Repair an invalid citation and continue")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Reference repair")
    request = LLMRequest(
        json.dumps({"source": valid, "untrusted_reference": invalid}),
        app._workspace(task.id),
        mode="exec",
        tools=app._tools(),
    )
    result = await app._invoke(task.id, request, conversation=True)
    assert result["text"] == '{"ok": true}'
    assert callbacks["bad-note"]["success"] is False
    assert "dangling TraceOutputRef" in callbacks["bad-note"]["contentItems"][0]["text"]
    assert callbacks["repaired-note"]["success"] is True
    assert callbacks["subsequent-read"]["success"] is True
    notes = [event for event in app.memory.events if event.operator == "analytical_note"]
    assert len(notes) == 1
    assert notes[0].output["text"] == good_note["text"]
    assert notes[0].dependencies == (app.memory.output_ref(source),)
    raw_events = [
        event
        for event in app.memory.events
        if event.operator == "provider_event" and "unvalidated_json" in event.output.get("data", {})
    ]
    assert raw_events
    assert any(
        json.loads(event.output["data"]["unvalidated_json"])
        .get("payload", {})
        .get("item", {})
        .get("arguments")
        == bad_note
        for event in raw_events
    )
    assert all(not event.dependencies for event in raw_events)
    for event in app.memory.events:
        for reference in event.dependencies:
            app.memory.resolve(reference)
    assert not app._execution.busy


async def test_tool_read_context_uses_latest_window_not_cumulative_usage(tmp_path):
    from evertree.core.tokens import current_read_context

    seen = []

    class ContextClient(FakeClient):
        def turn_start(self, *args):
            result = super().turn_start(*args)
            usage = token_notification(100_000, last=700)
            usage.payload["tokenUsage"]["modelContextWindow"] = 1000
            self.events[:0] = [usage, SimpleNamespace(method="test/call", payload={})]
            return result

        def next_turn_notification(self, turn_id):
            event = super().next_turn_notification(turn_id)
            if event.method == "test/call":
                for _ in range(2):
                    self.handler("item/tool/call", {"tool": "read", "arguments": {}})
                return super().next_turn_notification(turn_id)
            return event

    async def handle(name, arguments):
        seen.append(dict(current_read_context.get()))
        return {"ok": True}

    provider = CodexProvider(client_factory=ContextClient)
    request = LLMRequest(
        "Read", tmp_path, tools=(ToolDefinition("read", "Read", {}, read_only=True),)
    )
    events = [event async for event in provider.run("budget", request, tool_handler=handle)]
    assert any(event.kind == "completed" for event in events)
    assert [c["context_window"] for c in seen] == [1000, 1000]
    assert 0 < seen[1]["remaining_tokens"] < seen[0]["remaining_tokens"] <= 200
    assert current_read_context.get() is None


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
            "one", LLMRequest("Return ok", tmp_path, output_schema={"type": "object"})
        )
    ]
    assert events[-1].kind == "completed"
    assert events[-1].data["parsed"] == {"ok": True}
    assert clients[0].params["model"] == "gpt-6-luna"
    assert clients[0].params["ephemeral"] is True
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
                "one", LLMRequest("x", tmp_path, tools=(ToolDefinition("write", "write", {}),))
            )
        ]


@pytest.mark.asyncio
async def test_scripted_tool_requires_declaration(tmp_path):
    provider = ScriptedProvider([[LLMEvent("tool_call", {"name": "unlisted"})]])

    async def handle(name, arguments):
        raise AssertionError("Must not execute")

    with pytest.raises(ProviderError, match="not declared"):
        [
            event
            async for event in provider.run(
                "one", LLMRequest("x", tmp_path, mode="exec"), tool_handler=handle
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
    [event async for event in provider.run("one", LLMRequest("x", tmp_path, mode="exec"))]
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
        from evertree.core.tokens import current_read_context

        assert name == "lookup"
        context = current_read_context.get()
        assert context["model"] == "gpt-6-luna"
        assert context["context_window"] == 196000
        assert 0 < context["remaining_tokens"] < context["context_window"]
        return {"found": arguments["id"]}

    request = LLMRequest(
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
            LLMRequest("code", tmp_path, mode="exec", native_coding=True),
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
    assert rules["network"]["enabled"] is True


@pytest.mark.asyncio
async def test_missing_permission_profile_fails_before_turn(tmp_path):
    class UnsafeClient(FakeClient):
        def thread_start(self, params):
            return {
                "thread": {"id": "thread1", "ephemeral": params["ephemeral"]},
                "model": params["model"],
            }

        def turn_start(self, *args):
            raise AssertionError("Must not bill a turn without permissions")

    events = [
        event
        async for event in CodexProvider(client_factory=UnsafeClient).run(
            "one", LLMRequest("x", tmp_path)
        )
    ]
    assert events[-1].kind == "error"
    assert "permissions" in events[-1].data["message"]


def test_model_cannot_enable_native_coding(tmp_path):
    with pytest.raises(ValueError, match="exec"):
        LLMRequest("x", tmp_path, native_coding=True)


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
        ).run("one", LLMRequest("x", tmp_path, mode="exec", native_coding=True))
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
                LLMRequest(
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
    if resume:
        prior = [e async for e in provider.run("prior", LLMRequest("prior context", tmp_path))]
        assert prior[-1].kind == "completed"
    events = [
        event
        async for event in provider.run(
            "one",
            LLMRequest(
                "code",
                tmp_path,
                mode="exec",
                native_coding=True,
                session=SessionRef("codex", "thread1") if resume else None,
            ),
        )
    ]
    assert events[-1].kind == "completed"
    assert clients[-1].params["ephemeral"] is True
    if resume:
        assert "prior context" in clients[-1].prompt
    assert clients[-1].params["environments"] == [executors[0].environment]
    assert clients[-1].turn_params["environments"] == [executors[0].environment]
    assert clients[-1].turn_params["sandboxPolicy"] == {
        "type": "externalSandbox",
        "networkAccess": "enabled",
    }
    shell_policy = clients[-1].params["config"]["shell_environment_policy"]
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
            LLMRequest("code", tmp_path, mode="exec", native_coding=True),
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
    events = [e async for e in provider.run("catalog", LLMRequest("compute", tmp_path))]
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
            "native", LLMRequest("code", tmp_path, mode="exec", native_coding=True)
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
            "missing", LLMRequest("compute", tmp_path)
        )
    ]
    assert events[-1].kind == "error"
    assert "Exact gpt-6-luna metadata" in events[-1].data["message"]
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
            "bootstrap", LLMRequest("compute", tmp_path)
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
            "bootstrap", LLMRequest("compute", tmp_path)
        )
    ]
    assert events[-1].kind == "error"
    assert "Exact gpt-6-luna metadata" in events[-1].data["message"]
    assert len(clients) == 1 and clients[0].closed
    assert not hasattr(clients[0], "turn_params")


@pytest.mark.asyncio
async def test_unknown_session_reports_unavailable_history(tmp_path):
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
            LLMRequest("compute", tmp_path, session=SessionRef("codex", "previous-exec")),
        )
    ]
    assert events[-1].kind == "error"
    assert "Session history is unavailable" in events[-1].data["message"]
    assert not hasattr(clients[0], "turn_params")


async def test_ephemeral_continuation_retains_context_and_counts_fresh_usage(tmp_path):
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

    clients = []

    def factory(**kwargs):
        client = UsageClient(**kwargs)
        clients.append(client)
        return client

    provider = CodexProvider(client_factory=factory)
    first = [e async for e in provider.run("first", LLMRequest("first", tmp_path))]
    second = [
        e
        async for e in provider.run(
            "second", LLMRequest("second", tmp_path, session=SessionRef("codex", "thread1"))
        )
    ]
    assert [e.data["total_tokens"] for e in first if e.kind == "usage"] == [12, 12, 32]
    assert [e.data["total_tokens"] for e in second if e.kind == "usage"] == [42, 42, 72]
    assert clients[1].params["ephemeral"] is True
    assert '"text": "first"' in clients[1].prompt
    assert '{\\"ok\\": true}' in clients[1].prompt
    assert all(e.data["available"] for e in first + second if e.kind == "usage")
    assert first[-1].kind == second[-1].kind == "completed"


@pytest.mark.parametrize("reported", [True, False])
async def test_fresh_usage_and_missing_usage_is_explicit(tmp_path, reported):
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
            LLMRequest("compute", tmp_path),
        )
    ]
    usage = [e.data for e in events if e.kind == "usage"]
    assert len(usage) == 1
    assert usage[0]["available"] is reported
    if reported:
        assert usage[0]["total_tokens"] == 9000
    else:
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

    request = LLMRequest(
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

    request = LLMRequest(
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


@pytest.mark.parametrize("invalid_resume", [None, "model", "permission"])
async def test_tool_set_continuation_registers_real_schemas_and_resets_next_invocation(
    tmp_path, invalid_resume
):
    from evertree.core.provider import SessionRef
    from evertree.core.toolsets import ToolSet

    clients, reads = [], []

    class LoadingClient(FakeClient):
        def __init__(self, *args):
            super().__init__(*args)
            self.turns = 0
            self.schemas = []

        def request(self, method, params, response_model):
            if method in {"thread/start", "thread/resume"}:
                assert params["ephemeral"] is True
                self.schemas.append(params["dynamicTools"])
                result = self.thread_start(params)
                if len(self.schemas) > 1 and invalid_resume:
                    if invalid_resume == "model":
                        result["model"] = "unexpected-model"
                    else:
                        result["activePermissionProfile"] = {"id": "unexpected-permissions"}
                return response_model.model_validate(result)
            if method == "turn/interrupt":
                return response_model.model_validate({})
            return super().request(method, params, response_model)

        def turn_start(self, thread_id, prompt, params):
            self.turns += 1
            if len(clients) == 1 and self.turns == 1:
                result = self.handler(
                    "item/tool/call", {"tool": "load_tool_set", "arguments": {"name": "low"}}
                )
                assert result["success"]
                self.events = [
                    SimpleNamespace(
                        method="item/completed",
                        payload={"item": {"type": "dynamicToolCall", "tool": "load_tool_set"}},
                    ),
                    SimpleNamespace(
                        method="turn/completed", payload={"turn": {"status": "completed"}}
                    ),
                ]
            else:
                result = self.handler(
                    "item/tool/call", {"namespace": "graph", "tool": "get", "arguments": {"id": 7}}
                )
                assert result["success"] == (len(clients) == 1)
                if len(clients) == 1:
                    # Loading the same set is idempotent, with no third SDK turn.
                    assert self.handler(
                        "item/tool/call", {"tool": "load_tool_set", "arguments": {"name": "low"}}
                    )["success"]
                self.events = [
                    SimpleNamespace(
                        method="turn/completed", payload={"turn": {"status": "completed"}}
                    )
                ]
            self.events.insert(0, token_notification(10 if self.turns == 1 else 20))
            if self.turns > 1:
                assert '"text": "read"' in prompt
            return {"turn": {"id": f"turn{self.turns}"}}

    def factory(config, approval_handler):
        client = LoadingClient(config, approval_handler)
        clients.append(client)
        return client

    async def read(name, args):
        reads.append((name, args))
        return {"id": args["id"]}

    definitions = (
        ToolSet(
            "low",
            "Low-level reads",
            (ToolDefinition("graph.get", "Get", {"type": "object"}, read_only=True),),
        ),
    )
    provider = CodexProvider(state_dir=tmp_path / "provider", client_factory=factory)
    events = [
        event
        async for event in provider.run(
            "one", LLMRequest("read", tmp_path, tool_sets=definitions), tool_handler=read
        )
    ]
    if invalid_resume:
        assert events[-1].kind == "error"
        assert "continuation changed" in events[-1].data["message"]
        assert not reads and clients[0].turns == 1
        return
    assert events[-1].kind == "completed", events
    assert len([e for e in events if e.kind == "completed"]) == 1
    assert reads == [("graph.get", {"id": 7})]
    assert clients[0].turns == 2
    assert [e.data["total_tokens"] for e in events if e.kind == "usage"] == [10, 30]
    assert [d["name"] for d in clients[0].schemas[0]] == ["load_tool_set"]
    assert clients[0].schemas[1][1]["name"] == "graph"
    events = [
        event
        async for event in provider.run(
            "two",
            LLMRequest(
                "again", tmp_path, session=SessionRef("codex", "thread1"), tool_sets=definitions
            ),
            tool_handler=read,
        )
    ]
    assert events[-1].kind == "completed"
    assert [d["name"] for d in clients[1].schemas[0]] == ["load_tool_set"]
    assert len(reads) == 1


async def test_readonly_child_cannot_load_write_authority(tmp_path):
    from evertree.core.toolsets import ToolSet

    provider = ScriptedProvider(
        [
            [
                LLMEvent("tool_call", {"name": "load_tool_set", "arguments": {"name": "low"}}),
                LLMEvent("tool_call", {"name": "graph.apply", "arguments": {}}),
            ]
        ]
    )
    request = LLMRequest(
        "read",
        tmp_path,
        tool_sets=(ToolSet("low", "Mixed tools", (ToolDefinition("graph.apply", "Write", {}),)),),
    )

    async def handler(*args):
        pytest.fail("Write authority leaked into model invocation")

    with pytest.raises(ProviderError, match="not declared"):
        async for _ in provider.run("model", request, tool_handler=handler):
            pass


async def test_independent_model_effort_profiles(tmp_path, model_cache):
    data = json.loads(model_cache.read_text())
    data["models"][0]["supported_reasoning_levels"].append({"effort": "low", "description": "Low"})
    model_cache.write_text(json.dumps(data))
    clients = []

    def factory(config, approval_handler):
        client = FakeClient(config, approval_handler)
        clients.append(client)
        return client

    provider = CodexProvider(state_dir=tmp_path / "provider", client_factory=factory)
    for effort in ("low", "high"):
        events = [
            event
            async for event in provider.run(effort, LLMRequest("inspect", tmp_path, effort=effort))
        ]
        assert events[-1].kind == "completed", events
        assert clients[-1].turn_params["effort"] == effort


async def test_ephemeral_history_keeps_public_tool_results_without_nested_context(tmp_path):
    from evertree.core.provider import SessionRef

    clients = []

    class HistoryClient(FakeClient):
        def turn_start(self, *args):
            result = super().turn_start(*args)
            if len(clients) == 1:
                self.events[:0] = [
                    SimpleNamespace(
                        method="item/completed",
                        payload={"item": {"type": "reasoning", "text": "private reasoning"}},
                    ),
                    SimpleNamespace(
                        method="item/completed",
                        payload={
                            "item": {
                                "type": "dynamicToolCall",
                                "tool": "read",
                                "contentItems": [{"type": "inputText", "text": "retained result"}],
                            }
                        },
                    ),
                ]
            return result

    def factory(**kwargs):
        client = HistoryClient(**kwargs)
        clients.append(client)
        return client

    provider = CodexProvider(client_factory=factory)
    for ordinal, prompt in enumerate(("first request", "second request", "new request")):
        events = [
            e
            async for e in provider.run(
                str(ordinal),
                LLMRequest(
                    prompt, tmp_path, session=SessionRef("codex", "thread1") if ordinal else None
                ),
            )
        ]
        assert events[-1].kind == "completed"
    prompt = clients[-1].prompt
    assert "retained result" in prompt
    assert "first request" in prompt and "second request" in prompt
    assert "private reasoning" not in prompt
    assert prompt.endswith("Current user request:\nnew request")
    assert prompt.count("<evertree-history>") == 1
    await provider.close()
    assert not provider._histories


@pytest.mark.parametrize("invocation_timeout", [True, False])
async def test_timeout_diagnostic_distinguishes_deadline_from_sdk_timeout(
    tmp_path, monkeypatch, invocation_timeout
):
    provider = CodexProvider()

    async def catalog(*args):
        if invocation_timeout:
            await asyncio.Event().wait()
        raise TimeoutError

    monkeypatch.setattr(provider, "_computation_catalog", catalog)
    events = [
        event
        async for event in provider.run(
            "timeout",
            LLMRequest("test", tmp_path, timeout_seconds=0.01 if invocation_timeout else None),
        )
    ]
    (error,) = [event.data for event in events if event.kind == "error"]
    assert error["type"] == "TimeoutError"
    if invocation_timeout:
        assert "0.01-second wall-clock limit" in error["message"]
        assert "debugger pauses" in error["message"]
    else:
        assert error["message"] == "SDK operation timed out."
    assert not provider._active
