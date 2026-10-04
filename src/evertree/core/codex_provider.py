"""Codex SDK adapter, pinned to the SDK's public low-level client.

The low-level client is needed because the high-level facade does not expose
dynamic tools or approval callbacks. Transport and subprocess handling remain
the responsibility of the official SDK. Blocking SDK calls are offloaded from
the event loop; each invocation has its own client to permit nested tool calls.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from evertree.core.provider import AgentEvent, AgentRequest, ProviderError

MODEL = "gpt-6-luna"
EFFORT = "high"

# CodexConfig.env merges os.environ instead of replacing it. Keep the SDK's
# transport but launch its server through a small, isolated standard-library
# shim so host permission overrides, credentials and interpreter hooks cannot
# reach either the server or its commands. The existing CODEX_HOME login stays
# in place; credentials are never copied into a candidate workspace.
_ENVIRONMENT_NAMES = frozenset(
    {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "SYSTEMDRIVE",
        "COMSPEC",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "APPDATA",
        "HOME",
        "LANG",
        "LC_ALL",
        "TERM",
        "CODEX_HOME",
    }
)
_LAUNCHER = (
    "import os,sys,subprocess,threading\n"
    f"allowed={tuple(sorted(_ENVIRONMENT_NAMES))!r}\n"
    "env={k:v for k,v in os.environ.items() if k.upper() in allowed}\n"
    # Wait for SDK initialize, sent only after the launcher joins its Job Object.
    # Thus even the server itself cannot race process-tree ownership.
    "first=sys.stdin.buffer.readline()\n"
    "if not first: sys.exit(0)\n"
    "child=subprocess.Popen(sys.argv[1:],env=env,stdin=subprocess.PIPE)\n"
    "child.stdin.write(first); child.stdin.flush()\n"
    "def relay():\n"
    " try:\n"
    "  for line in sys.stdin.buffer:\n"
    "   child.stdin.write(line); child.stdin.flush()\n"
    "  child.stdin.close()\n"
    " except (BrokenPipeError,OSError): pass\n"
    "threading.Thread(target=relay,daemon=True).start()\n"
    "os._exit(child.wait())\n"
)
_DISABLED_FEATURES = (
    "apps",
    "plugins",
    "remote_plugin",
    "hooks",
    "codex_hooks",
    "memories",
    "browser_use",
    "computer_use",
    "multi_agent",
    "multi_agent_v2",
    "goals",
    "image_generation",
    "view_image",
    "shell_snapshot",
    "skill_search",
    "skill_mcp_dependency_install",
    "external_agent_memory_import",
    "code_mode",
    "code_mode_only",
    "chronicle",
    "artifact",
    "workspace_dependencies",
    "current_time_reminder",
    "sleep_tool",
    "send_message_to_user_async",
    "request_permissions_tool",
    "standalone_web_search",
    "token_budget",
    "deferred_executor",
)

# Public ModelInfo fields in the pinned 0.160 protocol. Never copy the surrounding
# models_cache envelope (account/cache identity), other models or unknown fields.
_MODEL_METADATA_FIELDS = frozenset(
    [
        "guardian",
        "slug",
        "display_name",
        "description",
        "default_reasoning_level",
        "supported_reasoning_levels",
        "shell_type",
        "visibility",
        "supported_in_api",
        "priority",
        "additional_speed_tiers",
        "service_tiers",
        "default_service_tier",
        "available_access_programs",
        "availability_nux",
        "upgrade",
        "model_messages",
        "include_skills_usage_instructions",
        "include_plugin_usage_instructions",
        "include_apps_usage_instructions",
        "supports_reasoning_summary_parameter",
        "default_reasoning_summary",
        "support_verbosity",
        "default_verbosity",
        "apply_patch_tool_type",
        "web_search_tool_type",
        "truncation_policy",
        "supports_image_detail_original",
        "context_window",
        "max_context_window",
        "auto_compact_token_limit",
        "comp_hash",
        "effective_context_window_percent",
        "experimental_supported_tools",
        "input_modalities",
        "supports_search_tool",
        "supports_experimental_context",
        "use_responses_lite",
        "supports_reasoning_effort_updates",
        "node_repl_auto_review_required",
        "node_repl_disabled",
        "auto_review_model_override",
        "model_specialty",
        "tool_mode",
        "multi_agent_version",
        "multi_agent_reasoning_effort",
    ]
)
_COMPUTATION_CAPABILITIES = {
    "tool_mode": "direct",
    "experimental_supported_tools": [],
    "shell_type": "disabled",
    "apply_patch_tool_type": None,
    "multi_agent_version": None,
    "supports_search_tool": False,
    "node_repl_disabled": True,
}


class _RawResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _request(client, method, params):
    return client.request(method, params, response_model=_RawResponse).model_dump()


def _profile(request: AgentRequest | None) -> tuple[str, dict[str, Any]]:
    profile = "evertree_" + uuid.uuid4().hex
    filesystem = {":root": "deny", ":minimal": "read"}
    if request is not None:
        workspace = request.workspace.resolve()
        filesystem[str(workspace)] = "write" if request.native_coding else "deny"
        for name in (".git", ".codex", ".agents", ".env"):
            if (workspace / name).exists():
                filesystem[str(workspace / name)] = "deny"
        for hidden in (workspace / ".state", workspace / "src" / "evertree" / "core"):
            if hidden.exists():
                filesystem[str(hidden)] = "deny"
    filesystem[str(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve())] = "deny"
    filesystem[str(Path(__file__).resolve().parent)] = "deny"
    return profile, {"filesystem": filesystem, "network": {"enabled": False}}


def _toml(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + "=" + _toml(v) for k, v in value.items()) + "}"
    return json.dumps(value, ensure_ascii=False)


def _attach_process_tree(client):
    # This adapter is the only consumer of the pinned SDK's process handle.
    # Test transports intentionally have no OS child.
    process = getattr(client, "_proc", None)
    if process is None:
        return None
    from evertree.core.sandbox import WindowsProcessTree

    return WindowsProcessTree(process.pid)


async def _start_owned_client(client):
    start = asyncio.create_task(asyncio.to_thread(client.start))
    try:
        await asyncio.shield(start)
    except asyncio.CancelledError:
        # Starting an SDK subprocess in a worker cannot be interrupted. Reap it
        # even if the request is cancelled before start returns its process.
        try:
            await start
        finally:
            tree = _attach_process_tree(client)
            try:
                if tree:
                    await asyncio.to_thread(tree.close)
            finally:
                await asyncio.to_thread(client.close)
        raise
    return _attach_process_tree(client)


@dataclass
class _Invocation:
    client: Any
    task: asyncio.Task | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    callbacks: set = field(default_factory=set)


def _json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    return value


_TOKEN_FIELDS = {
    "total_tokens": "totalTokens",
    "input_tokens": "inputTokens",
    "cached_input_tokens": "cachedInputTokens",
    "cache_write_input_tokens": "cacheWriteInputTokens",
    "output_tokens": "outputTokens",
    "reasoning_output_tokens": "reasoningOutputTokens",
}


def _usage(total, baseline):
    required = set(_TOKEN_FIELDS.values()) - {"cacheWriteInputTokens"}
    available = (
        baseline is not None
        and required <= total.keys()
        and all(
            isinstance(total.get(key, 0), int)
            and not isinstance(total.get(key, 0), bool)
            and total.get(key, 0) >= baseline.get(key, 0)
            for key in _TOKEN_FIELDS.values()
        )
    )
    return {
        "available": available,
        **{
            normalized: total.get(raw, 0) - baseline.get(raw, 0) if available else None
            for normalized, raw in _TOKEN_FIELDS.items()
        },
    }


def _native_tool_events(item, *, completed):
    """Map supported SDK items once; dynamic calls use the callback path instead."""
    kind, call_id = item.get("type"), item["id"]
    if kind == "commandExecution":
        name = "shell"
        arguments = {"command": item["command"], "cwd": item["cwd"]}
        result = {"output": item.get("aggregatedOutput"), "exit_code": item.get("exitCode")}
    elif kind == "fileChange":
        name = "file_patch"
        changes = [
            {
                "path": change["path"],
                "operation": change["kind"]["type"],
                "diff": change["diff"],
                "moved_to": change["kind"].get("move_path"),
            }
            for change in item["changes"]
        ]
        arguments = {"changes": changes}
        result = arguments
    elif kind == "mcpToolCall":
        name = item["server"] + "." + item["tool"]
        arguments, result = item["arguments"], item.get("result")
    else:
        return ()
    if not completed:
        return (
            AgentEvent("tool_call", {"call_id": call_id, "name": name, "arguments": arguments}),
        )
    status = item.get("status", "completed")
    status = {"interrupted": "cancelled", "inProgress": "failed"}.get(status, status)
    if status not in {"completed", "failed", "declined", "cancelled"}:
        raise ProviderError("Unknown native tool completion status: " + str(status))
    error = item.get("error")
    if error is not None and not isinstance(error, str):
        error = json.dumps(error, ensure_ascii=False)
    if status != "completed" and error is None:
        error = f"{name}: {status}"
    events = [
        AgentEvent(
            "tool_result",
            {"call_id": call_id, "name": name, "status": status, "result": result, "error": error},
        )
    ]
    if kind == "fileChange":
        events.extend(
            AgentEvent("file_change", {"call_id": call_id, "status": status, **change})
            for change in changes
        )
    return tuple(events)


class CodexProvider:
    name = "codex"

    def __init__(
        self,
        *,
        state_dir: Path | None = None,
        codex_bin: str | None = None,
        client_factory=None,
        executor_factory=None,
    ):
        self.state_dir = Path(state_dir or Path.cwd() / ".state" / "codex-runtime").resolve()
        self.codex_bin = codex_bin
        self._client_factory = client_factory
        self._executor_factory = executor_factory
        self._active: dict[str, _Invocation] = {}
        self._thread_usage: dict[str, dict[str, int]] = {}

    def _client(self, *, request: AgentRequest | None = None, handler=None, model_catalog=None):
        from codex_cli_bin import bundled_codex_path
        from openai_codex.client import CodexClient, CodexConfig

        native_coding = request is not None and request.native_coding
        profile_id, profile = _profile(request)
        overrides = [
            'model="gpt-6-luna"',
            'model_reasoning_effort="high"',
            'model_provider="openai"',
            'approval_policy="never"',
            'windows.sandbox="elevated"',
            'web_search="disabled"',
            "allow_login_shell=false",
            "notify=[]",
            "project_doc_max_bytes=0",
            "tools.experimental_request_user_input.enabled=false",
            "features.skip_host_skill_discovery=true",
            'shell_environment_policy.inherit="none"',
            "shell_environment_policy.experimental_use_profile=false",
            "shell_environment_policy.ignore_default_excludes=false",
            "features.shell_tool=" + str(native_coding).lower(),
            "features.unified_exec=" + str(native_coding).lower(),
            "default_permissions=" + json.dumps(profile_id),
            "permissions." + profile_id + "=" + _toml(profile),
        ]
        if not native_coding:
            overrides.append("tools.update_plan.enabled=false")
        if model_catalog is not None:
            if native_coding:
                raise ProviderError("Native coding must use the original model catalog")
            overrides.append("model_catalog_json=" + json.dumps(str(model_catalog)))
        overrides.extend("features." + feature + "=false" for feature in _DISABLED_FEATURES)
        binary = (
            str(Path(self.codex_bin).resolve()) if self.codex_bin else str(bundled_codex_path())
        )
        command = [sys.executable, "-I", "-S", "-c", _LAUNCHER, binary]
        for item in overrides:
            command.extend(("--config", item))
        command.extend(("app-server", "--listen", "stdio://"))
        config = CodexConfig(
            codex_bin=self.codex_bin,
            config_overrides=tuple(overrides),
            launch_args_override=tuple(command),
            cwd=str(request.workspace.resolve()) if request else None,
            client_name="evertree",
            client_title="EverTree",
            experimental_api=True,
        )
        factory = self._client_factory or CodexClient
        client = factory(
            config=config, approval_handler=handler or (lambda *_: {"decision": "decline"})
        )
        client._evertree_profile = profile_id
        return client

    async def _computation_catalog(self):
        cache = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "models_cache.json"
        if not cache.is_file():
            # model/list refreshes public metadata without starting/billing a turn.
            bootstrap = self._client()
            tree = None
            try:
                tree = await _start_owned_client(bootstrap)
                await asyncio.to_thread(bootstrap.initialize)
                await asyncio.to_thread(bootstrap.model_list, True)
            finally:
                try:
                    if tree:
                        await asyncio.to_thread(tree.close)
                finally:
                    await asyncio.to_thread(bootstrap.close)
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            selected = next(model for model in cached["models"] if model.get("slug") == MODEL)
        except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
            raise ProviderError(
                "Exact Luna metadata is unavailable; refusing model fallback"
            ) from exc
        efforts = selected.get("supported_reasoning_levels", [])
        if not any(item.get("effort") == EFFORT for item in efforts):
            raise ProviderError("Exact Luna metadata does not support high reasoning effort")
        model = {key: value for key, value in selected.items() if key in _MODEL_METADATA_FIELDS}
        model.update(_COMPUTATION_CAPABILITIES)
        encoded = json.dumps({"models": [model]}, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        digest = hashlib.sha256(encoded).hexdigest()
        directory = self.state_dir / "model-catalogs"
        directory.mkdir(parents=True, exist_ok=True)
        catalog = directory / (digest + ".json")
        temporary = directory / (uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_bytes(encoded)
            os.replace(temporary, catalog)
        finally:
            temporary.unlink(missing_ok=True)
        return catalog, digest

    @staticmethod
    def _thread_config(client, workspace: Path, command_environment=None) -> dict[str, Any]:
        # Empty maps merge with inherited TOML maps; they do not remove entries.
        # Inspect names only and explicitly disable every effective MCP server.
        effective = _request(
            client, "config/read", {"cwd": str(workspace), "includeLayers": False}
        )["config"]
        config: dict[str, Any] = {"model_reasoning_effort": EFFORT}
        config["mcp_servers"] = {
            name: {"enabled": False, "required": False} for name in effective.get("mcp_servers", {})
        }
        old_set = (effective.get("shell_environment_policy") or {}).get("set") or {}
        safe_set = {name: "" for name in old_set}
        safe_set.update(
            command_environment
            if command_environment is not None
            else {
                name: value
                for name, value in os.environ.items()
                if name.upper() in _ENVIRONMENT_NAMES - {"CODEX_HOME"}
            }
        )
        config["shell_environment_policy"] = {
            "inherit": "none",
            "set": safe_set,
            "experimental_use_profile": False,
        }
        return config

    async def _open_executor(self, client, workspace):
        from .codex_executor import CodexExecutor

        factory = self._executor_factory or CodexExecutor
        executor = factory(workspace, self.state_dir / "executor")
        try:
            connection = await executor.start()
            await asyncio.to_thread(
                _request, client, "environment/add", {**connection, "connectTimeoutMs": 15000}
            )
            return executor
        except BaseException:
            await executor.close()
            raise

    async def doctor(self) -> dict[str, Any]:
        client = self._client()
        process_tree = None
        executor = None
        try:
            async with asyncio.timeout(120):
                process_tree = await _start_owned_client(client)
                metadata = _json(await asyncio.to_thread(client.initialize))
                account = _json(await asyncio.to_thread(client.account_read))
                models = _json(await asyncio.to_thread(client.model_list, True))
                workspace = self.state_dir / "diagnostics" / uuid.uuid4().hex / "workspace"
                workspace.mkdir(parents=True, exist_ok=True)
                executor = await self._open_executor(client, workspace)
                native = {"available": True, "status": "connected", "isolation": "app_container"}
                selected = next(
                    (m for m in models["data"] if m.get("model") == MODEL or m["id"] == MODEL),
                    None,
                )
                efforts = (
                    []
                    if selected is None
                    else [e["reasoningEffort"] for e in selected["supportedReasoningEfforts"]]
                )
                authenticated = account.get("account") is not None
                return {
                    "provider": self.name,
                    "model": MODEL,
                    "effort": EFFORT,
                    "available": authenticated and selected is not None and EFFORT in efforts,
                    "authenticated": authenticated,
                    "model_available": selected is not None,
                    "effort_available": EFFORT in efforts,
                    "native_coding_available": native["available"],
                    "native_coding": native,
                    "sdk_version": importlib.metadata.version("openai-codex"),
                    "runtime": metadata,
                }
        except Exception as exc:  # noqa: BLE001 -- SDK diagnostics must return a structured failure
            return {
                "provider": self.name,
                "model": MODEL,
                "effort": EFFORT,
                "available": False,
                "error": str(exc),
            }
        finally:
            try:
                if executor:
                    await executor.close()
            finally:
                try:
                    if process_tree:
                        await asyncio.to_thread(process_tree.close)
                finally:
                    await asyncio.to_thread(client.close)

    async def run(self, request_id, request, *, tool_handler=None, approval_handler=None):
        if request_id in self._active:
            raise ProviderError("Request is already running")
        if request.session and request.session.provider != self.name:
            raise ProviderError("Cannot resume another provider's session")
        if request.mode == "model" and request.tools:
            raise ProviderError("Model calls cannot expose action tools")
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        allowed_tools = {tool.name for tool in request.tools}

        async def dispatch_server_request(method, params):
            params = params or {}
            await queue.put(AgentEvent("provider_event", {"method": method, "payload": params}))
            if method == "item/tool/call":
                name = params.get("tool", "")
                call_id = params.get("callId") or uuid.uuid4().hex
                arguments = params.get("arguments", {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if name not in allowed_tools or tool_handler is None or request.mode != "exec":
                    return {
                        "success": False,
                        "contentItems": [
                            {"type": "inputText", "text": "Tool not authorized by EverTree"}
                        ],
                    }
                await queue.put(
                    AgentEvent(
                        "tool_call",
                        {"name": name, "arguments": arguments, "call_id": call_id},
                    )
                )
                try:
                    result = await tool_handler(name, arguments)
                    text = json.dumps(result, ensure_ascii=False, allow_nan=False)
                    await queue.put(
                        AgentEvent(
                            "tool_result",
                            {
                                "name": name,
                                "result": result,
                                "call_id": call_id,
                                "status": "completed",
                                "error": None,
                            },
                        )
                    )
                    return {"success": True, "contentItems": [{"type": "inputText", "text": text}]}
                except asyncio.CancelledError:
                    await queue.put(
                        AgentEvent(
                            "tool_result",
                            {
                                "name": name,
                                "call_id": call_id,
                                "result": None,
                                "status": "cancelled",
                                "error": "Tool call cancelled",
                            },
                        )
                    )
                    raise
                except Exception as exc:  # noqa: BLE001 -- return tool failures to the agent protocol
                    await queue.put(
                        AgentEvent(
                            "tool_result",
                            {
                                "name": name,
                                "call_id": call_id,
                                "result": None,
                                "status": "failed",
                                "error": str(exc),
                            },
                        )
                    )
                    return {
                        "success": False,
                        "contentItems": [{"type": "inputText", "text": str(exc)}],
                    }
            if method in {
                "item/commandExecution/requestApproval",
                "item/fileChange/requestApproval",
            }:
                # Native tools already have their full authorized workspace.
                # Approval must never turn a candidate command into a host command.
                await queue.put(
                    AgentEvent("approval", {"method": method, **params, "approved": False})
                )
                return {"decision": "decline"}
            # Unknown SDK requests do not inherit the SDK's permissive default.
            if method == "item/permissions/requestApproval":
                return {"permissions": {}, "scope": "turn"}
            return {}

        async def server_request(method, params):
            task = asyncio.current_task()
            invocation.callbacks.add(task)
            try:
                return await dispatch_server_request(method, params)
            finally:
                invocation.callbacks.discard(task)

        def handler(method, params):
            future = asyncio.run_coroutine_threadsafe(server_request(method, params), loop)
            try:
                return future.result()
            except Exception:  # noqa: BLE001 -- failed SDK callbacks must deny the operation
                return {"decision": "decline", "success": False, "contentItems": []}

        invocation = _Invocation(None)
        self._active[request_id] = invocation

        async def produce():
            final_text = ""
            process_tree = None
            executor = None
            client = None
            usage_seen = False
            baseline = self._thread_usage.get(request.session.id) if request.session else {}

            async def report_missing_usage():
                nonlocal usage_seen
                if invocation.turn_id and not usage_seen:
                    await queue.put(AgentEvent("usage", _usage({}, None)))
                    usage_seen = True

            try:
                async with asyncio.timeout(request.timeout_seconds):
                    catalog, catalog_digest = (
                        (None, None) if request.native_coding else await self._computation_catalog()
                    )
                    client = self._client(request=request, handler=handler, model_catalog=catalog)
                    invocation.client = client
                    process_tree = await _start_owned_client(client)
                    metadata = _json(await asyncio.to_thread(client.initialize))
                    if request.native_coding:
                        executor = await self._open_executor(client, request.workspace.resolve())
                    thread_config = await asyncio.to_thread(
                        self._thread_config,
                        client,
                        request.workspace.resolve(),
                        executor.command_environment if executor else None,
                    )
                    params = {
                        "model": MODEL,
                        "cwd": str(request.workspace.resolve()),
                        "approvalPolicy": "never",
                        "approvalsReviewer": "user",
                        "permissions": client._evertree_profile,
                        "runtimeWorkspaceRoots": [str(request.workspace.resolve())],
                        "selectedCapabilityRoots": [],
                        "allowProviderModelFallback": False,
                        "developerInstructions": request.instructions
                        + (
                            "\nNative commands run in a Windows AppContainer with cmd.exe as the default shell. "
                            "Python is on PATH. Use Python pathlib/os for directory listing, reading and editing, "
                            "and Python unittest for local tests. Windows volume-path APIs used by dir, PowerShell "
                            "and Git can return Access denied inside this container even within the workspace. "
                            "Use Python commands or the native filesystem tools in that case; do not retry with "
                            "broader permissions. Git commits and protected evaluation are performed by EverTree core."
                            if request.native_coding
                            else ""
                        ),
                        "config": thread_config,
                    }
                    params["environments"] = [executor.environment] if executor else []
                    # Empty is intentional: a resumed computational session must
                    # not inherit the previous invocation's dynamic tool set.
                    params["dynamicTools"] = [
                        {
                            "type": "function",
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.input_schema,
                        }
                        for t in request.tools
                    ]
                    if request.session:
                        started = await asyncio.to_thread(
                            _request,
                            client,
                            "thread/resume",
                            {"threadId": request.session.id, **params},
                        )
                    else:
                        # Keep experimental request AND response fields omitted by
                        # the pinned SDK's generated models, notably permissions.
                        started = await asyncio.to_thread(_request, client, "thread/start", params)
                    invocation.thread_id = started["thread"]["id"]
                    if (started.get("activePermissionProfile") or {}).get(
                        "id"
                    ) != client._evertree_profile:
                        raise ProviderError(
                            "Codex did not activate the required filesystem permissions"
                        )
                    if started.get("model") != MODEL:
                        raise ProviderError("Codex did not select the requested model")
                    await queue.put(
                        AgentEvent(
                            "session",
                            {
                                "provider": self.name,
                                "id": invocation.thread_id,
                                "requested_model": MODEL,
                                "requested_effort": EFFORT,
                                "effective_model": started.get("model", "unknown"),
                                "sdk_version": importlib.metadata.version("openai-codex"),
                                "runtime": metadata,
                                "execution_environment": executor.environment if executor else None,
                                "capability_restrictions": (
                                    {
                                        "catalog_sha256": catalog_digest,
                                        "model_capabilities": _COMPUTATION_CAPABILITIES,
                                        "environments": [],
                                        "dynamic_tools": sorted(allowed_tools),
                                    }
                                    if catalog is not None
                                    else None
                                ),
                                "provider_internal_requests": "not_exposed",
                            },
                        )
                    )
                    turn_params = {
                        "model": MODEL,
                        "effort": EFFORT,
                        "approvalPolicy": "never",
                        "runtimeWorkspaceRoots": [str(request.workspace.resolve())],
                    }
                    turn_params["environments"] = [executor.environment] if executor else []
                    if executor:
                        # Only the selected exec-server receives tool commands.
                        # Its OS process already owns an AppContainer token;
                        # a second SDK sandbox would fail inside that container.
                        turn_params["sandboxPolicy"] = {
                            "type": "externalSandbox",
                            "networkAccess": "restricted",
                        }
                    else:
                        turn_params["permissions"] = client._evertree_profile
                    if request.output_schema is not None:
                        turn_params["outputSchema"] = request.output_schema
                    turn = _json(
                        await asyncio.to_thread(
                            client.turn_start, invocation.thread_id, request.prompt, turn_params
                        )
                    )
                    invocation.turn_id = turn["turn"]["id"]
                    while True:
                        event = await asyncio.to_thread(
                            client.next_turn_notification, invocation.turn_id
                        )
                        # The pinned SDK wraps newer notifications as UnknownNotification.
                        data = _json(event.payload)
                        if type(event.payload).__name__ == "UnknownNotification":
                            data = data["params"]
                        method = event.method
                        await queue.put(
                            AgentEvent("provider_event", {"method": method, "payload": data})
                        )
                        if method == "item/agentMessage/delta":
                            await queue.put(
                                AgentEvent(
                                    "message", {"text": data.get("delta", ""), "delta": True}
                                )
                            )
                        elif method == "item/started":
                            item = data.get("item", {})
                            if item.get("type") in {
                                "commandExecution",
                                "mcpToolCall",
                                "fileChange",
                            }:
                                for normalized in _native_tool_events(item, completed=False):
                                    await queue.put(normalized)
                        elif method == "item/completed":
                            item = data.get("item", {})
                            if item.get("type") == "agentMessage":
                                final_text = item.get("text", final_text)
                            elif item.get("type") in {
                                "commandExecution",
                                "mcpToolCall",
                                "fileChange",
                            }:
                                for normalized in _native_tool_events(item, completed=True):
                                    await queue.put(normalized)
                        elif method == "thread/tokenUsage/updated":
                            total = data["tokenUsage"]["total"]
                            usage = _usage(total, baseline)
                            if not usage["available"]:
                                baseline = None
                            self._thread_usage[invocation.thread_id] = dict(total)
                            usage_seen = True
                            await queue.put(AgentEvent("usage", usage))
                        elif method == "model/rerouted" and data.get("toModel") != MODEL:
                            raise ProviderError("Codex rerouted the explicitly requested model")
                        elif method == "turn/completed":
                            await report_missing_usage()
                            status = data["turn"]["status"]
                            if status == "completed":
                                parsed = None
                                if request.output_schema is not None:
                                    parsed = json.loads(final_text)
                                    from evertree.common.structured import validate

                                    validate(parsed, request.output_schema)
                                await queue.put(
                                    AgentEvent("completed", {"text": final_text, "parsed": parsed})
                                )
                            elif status == "interrupted":
                                await queue.put(AgentEvent("cancelled"))
                            else:
                                raise ProviderError(str(data["turn"].get("error") or status))
                            break
            except asyncio.CancelledError:
                await report_missing_usage()
                await queue.put(AgentEvent("cancelled"))
                raise
            except Exception as exc:  # noqa: BLE001 -- normalize SDK and transport failures
                await report_missing_usage()
                await queue.put(
                    AgentEvent("error", {"message": str(exc), "type": type(exc).__name__})
                )
            finally:
                callbacks = tuple(invocation.callbacks)
                for callback in callbacks:
                    callback.cancel()
                await asyncio.gather(*callbacks, return_exceptions=True)
                try:
                    if executor:
                        await executor.close()
                finally:
                    try:
                        if process_tree:
                            await asyncio.to_thread(process_tree.close)
                    finally:
                        try:
                            if client:
                                await asyncio.to_thread(client.close)
                        finally:
                            await queue.put(None)

        invocation.task = asyncio.create_task(produce())
        try:
            while (event := await queue.get()) is not None:
                yield event
        finally:
            if not invocation.task.done():
                invocation.task.cancel()
            await asyncio.gather(invocation.task, return_exceptions=True)
            self._active.pop(request_id, None)

    async def cancel(self, request_id):
        invocation = self._active.get(request_id)
        if invocation is None:
            return
        if invocation.thread_id and invocation.turn_id:
            try:
                async with asyncio.timeout(5):
                    await asyncio.to_thread(
                        invocation.client.turn_interrupt, invocation.thread_id, invocation.turn_id
                    )
            except Exception:
                logging.getLogger(__name__).debug(
                    "Codex interrupt failed; stopping process tree", exc_info=True
                )
        if invocation.task:
            invocation.task.cancel()
            await asyncio.gather(invocation.task, return_exceptions=True)

    async def close(self):
        for request_id in list(self._active):
            await self.cancel(request_id)
