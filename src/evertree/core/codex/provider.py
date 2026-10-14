"""Codex invocation, dynamic tool callbacks, event streaming and cancellation."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evertree.core.provider import AgentEvent, AgentRequest, ProviderError, current_tool_call_id
from evertree.core.sandbox.process import sandbox_backend

from .configuration import (
    _COMPUTATION_CAPABILITIES,
    EFFORT,
    MODEL,
    _start_owned_client,
    computation_catalog,
    create_client,
    thread_config,
)
from .protocol import (
    _add_usage,
    _continuation_input,
    _json,
    _native_tool_events,
    _request,
    _usage,
)


@dataclass
class _Invocation:
    client: Any
    task: asyncio.Task | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    callbacks: set = field(default_factory=set)
    cancelling: bool = False


def _dynamic_tools(tools):
    definitions = []
    namespaces = {}
    for tool in tools:
        spec = {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        if "." in tool.name:
            namespace, name = tool.name.split(".", 1)
            spec["name"] = name
            namespaces.setdefault(namespace, []).append(spec)
        else:
            definitions.append(spec)
    definitions.extend(
        {"type": "namespace", "name": name, "description": name + " operations", "tools": group}
        for name, group in namespaces.items()
    )
    return definitions


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
        self._histories: dict[str, list] = {}

    def _client(self, *, request: AgentRequest | None = None, handler=None, model_catalog=None):
        return create_client(
            codex_bin=self.codex_bin,
            client_factory=self._client_factory,
            request=request,
            handler=handler,
            model_catalog=model_catalog,
        )

    async def _computation_catalog(self, model_name=MODEL, effort=EFFORT):
        return await computation_catalog(self.state_dir, self._client, model_name, effort)

    _thread_config = staticmethod(thread_config)

    async def _open_executor(self, client, workspace):
        from .executor import CodexExecutor

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
                native = {"available": True, "status": "connected", "isolation": sandbox_backend()}
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
        if request.mode == "model" and any(not t.read_only for t in request.tools):
            raise ProviderError("Model calls cannot expose action tools")
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        model_name, effort = request.model or MODEL, request.effort or EFFORT
        available_sets = {s.name: s.for_mode(request.mode) for s in request.tool_sets}
        active_tools = {tool.name: tool for tool in request.tools}
        loaded_sets = set()
        pending_load = False
        if available_sets:
            from ..toolsets import loader_definition

            active_tools["load_tool_set"] = loader_definition(tuple(available_sets.values()))
        allowed_tools = set(active_tools)

        async def dispatch_server_request(method, params):
            nonlocal pending_load
            params = params or {}
            await queue.put(AgentEvent("provider_event", {"method": method, "payload": params}))
            if method == "item/tool/call":
                name = params.get("tool", "")
                if params.get("namespace"):
                    name = params["namespace"] + "." + name
                call_id = params.get("callId") or uuid.uuid4().hex
                arguments = params.get("arguments", {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if (
                    name not in allowed_tools
                    or (tool_handler is None and name != "load_tool_set")
                    or (request.mode == "model" and not active_tools[name].read_only)
                ):
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
                    if name == "load_tool_set":
                        selected = available_sets[arguments["name"]]
                        if selected.name not in loaded_sets:
                            for tool in selected.tools:
                                active_tools[tool.name] = tool
                            allowed_tools.update(t.name for t in selected.tools)
                            loaded_sets.add(selected.name)
                            pending_load = True
                        result = {
                            "loaded": selected.name,
                            "tools": [t.name for t in selected.tools],
                            "continuation": "End this SDK turn now. EverTree will continue with these callable tools; do not try them before the continuation."
                            if pending_load
                            else "Already available in this turn.",
                        }
                    else:
                        token = current_tool_call_id.set(call_id)
                        try:
                            result = await tool_handler(name, arguments)
                        finally:
                            current_tool_call_id.reset(token)
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
            nonlocal pending_load
            final_text = ""
            process_tree = None
            executor = None
            client = None
            usage_seen = False
            baseline = {}
            history = []
            carried_usage = {key: 0 for key in _usage({}, None) if key != "available"}
            carried_usage["available"] = True
            latest_usage = None

            async def report_missing_usage():
                nonlocal usage_seen
                if invocation.turn_id and not usage_seen:
                    await queue.put(AgentEvent("usage", _usage({}, None)))
                    usage_seen = True

            deadline = asyncio.timeout(request.timeout_seconds)
            try:
                async with deadline:
                    catalog, catalog_digest = (
                        (None, None)
                        if request.native_coding
                        else await self._computation_catalog(model_name, effort)
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
                        "model": model_name,
                        "ephemeral": True,
                        "cwd": str(request.workspace.resolve()),
                        "approvalPolicy": "never",
                        "approvalsReviewer": "user",
                        "permissions": client._evertree_profile,
                        "runtimeWorkspaceRoots": [str(request.workspace.resolve())],
                        "selectedCapabilityRoots": [],
                        "allowProviderModelFallback": False,
                        "developerInstructions": request.instructions
                        + (
                            "\nAfter load_tool_set reports a pending continuation, end this SDK turn immediately. EverTree will continue the same operation with registered tools."
                            if available_sets
                            else ""
                        )
                        + (
                            "\nNative commands run in a Windows AppContainer with cmd.exe as the default shell. "
                            "Python is on PATH. Use Python pathlib/os for directory listing, reading and editing, "
                            "and Python unittest for local tests. Windows volume-path APIs used by dir, PowerShell "
                            "and Git can return Access denied inside this container even within the workspace. "
                            "Use Python commands or the native filesystem tools in that case; do not retry with "
                            "broader permissions. Git commits and protected evaluation are performed by EverTree core."
                            if request.native_coding and os.name == "nt"
                            else (
                                "\nNative commands run in a macOS Seatbelt filesystem sandbox. "
                                "Python and Git are on PATH. Outgoing internet access is allowed. "
                                "Use stdio commands (tty=false); interactive terminals are unavailable. "
                                "Only the workspace and temporary profile are writable. "
                                "Git commits and protected evaluation are performed by EverTree core."
                                if request.native_coding
                                else ""
                            )
                        ),
                        "config": {**thread_config, "model_reasoning_effort": effort},
                    }
                    params["environments"] = [executor.environment] if executor else []
                    params["dynamicTools"] = _dynamic_tools(active_tools.values())
                    prompt = request.prompt
                    if request.session:
                        if request.session.id not in self._histories:
                            raise ProviderError("Session history is unavailable in this provider")
                        history = list(self._histories[request.session.id])
                        prompt = _continuation_input(history, request.prompt)
                    # Ephemeral threads disappear with the client process. Carry public
                    # context locally instead of persisting helper chats in Codex history.
                    history.append(
                        {
                            "type": "userMessage",
                            "content": [{"type": "text", "text": request.prompt}],
                        }
                    )
                    started = await asyncio.to_thread(_request, client, "thread/start", params)
                    invocation.thread_id = started["thread"]["id"]
                    if started["thread"].get("ephemeral") is not True:
                        raise ProviderError("Codex did not create an ephemeral thread")
                    if (started.get("activePermissionProfile") or {}).get(
                        "id"
                    ) != client._evertree_profile:
                        raise ProviderError(
                            "Codex did not activate the required filesystem permissions"
                        )
                    if started.get("model") != model_name:
                        raise ProviderError("Codex did not select the requested model")
                    await queue.put(
                        AgentEvent(
                            "session",
                            {
                                "provider": self.name,
                                "id": invocation.thread_id,
                                "ephemeral": True,
                                "requested_model": model_name,
                                "requested_effort": effort,
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
                        "model": model_name,
                        "effort": effort,
                        "approvalPolicy": "never",
                        "runtimeWorkspaceRoots": [str(request.workspace.resolve())],
                    }
                    turn_params["environments"] = [executor.environment] if executor else []
                    if executor:
                        # Only the selected exec-server receives tool commands.
                        # Its OS process already has native filesystem isolation;
                        # nested SDK sandboxing would fail inside that boundary.
                        turn_params["sandboxPolicy"] = {
                            "type": "externalSandbox",
                            "networkAccess": "enabled",
                        }
                    else:
                        turn_params["permissions"] = client._evertree_profile
                    if request.output_schema is not None:
                        turn_params["outputSchema"] = request.output_schema
                    turn = _json(
                        await asyncio.to_thread(
                            client.turn_start, invocation.thread_id, prompt, turn_params
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
                            if item.get("type") not in {"reasoning", "userMessage", None}:
                                history.append(item)
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
                            usage = _add_usage(carried_usage, _usage(total, baseline))
                            latest_usage = usage
                            if not usage["available"]:
                                baseline = None
                            usage_seen = True
                            await queue.put(AgentEvent("usage", usage))
                        elif method == "model/rerouted" and data.get("toModel") != model_name:
                            raise ProviderError("Codex rerouted the explicitly requested model")
                        elif method == "turn/completed":
                            status = data["turn"]["status"]
                            if (
                                pending_load
                                and not invocation.cancelling
                                and status in {"completed", "interrupted"}
                            ):
                                pending_load = False
                                params["dynamicTools"] = _dynamic_tools(active_tools.values())
                                previous_thread = invocation.thread_id
                                self._histories[previous_thread] = list(history)
                                carried_usage = latest_usage or _usage({}, None)
                                baseline, latest_usage = {}, None
                                resumed = await asyncio.to_thread(
                                    _request, client, "thread/start", params
                                )
                                if (
                                    resumed.get("model") != model_name
                                    or resumed["thread"].get("ephemeral") is not True
                                    or (resumed.get("activePermissionProfile") or {}).get("id")
                                    != client._evertree_profile
                                ):
                                    raise ProviderError(
                                        "Codex continuation changed the requested model or permissions"
                                    )
                                invocation.thread_id = resumed["thread"]["id"]
                                await queue.put(
                                    AgentEvent(
                                        "session",
                                        {
                                            "provider": self.name,
                                            "id": invocation.thread_id,
                                            "ephemeral": True,
                                            "continued_from": previous_thread,
                                            "requested_model": model_name,
                                            "requested_effort": effort,
                                            "effective_model": resumed["model"],
                                        },
                                    )
                                )
                                usage_seen = False
                                turn = _json(
                                    await asyncio.to_thread(
                                        client.turn_start,
                                        invocation.thread_id,
                                        _continuation_input(
                                            history, request.prompt, continued=True
                                        ),
                                        turn_params,
                                    )
                                )
                                invocation.turn_id = turn["turn"]["id"]
                                final_text = ""
                                continue
                            await report_missing_usage()
                            if status == "completed":
                                parsed = None
                                if request.output_schema is not None:
                                    parsed = json.loads(final_text)
                                    from evertree.common.structured import validate

                                    validate(parsed, request.output_schema)
                                self._histories[invocation.thread_id] = list(history)
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
                message = str(exc)
                if isinstance(exc, TimeoutError):
                    message = (
                        f"Model invocation exceeded its {request.timeout_seconds:g}-second "
                        "wall-clock limit (including startup, tool execution and debugger pauses)."
                        if deadline.expired()
                        else message or "SDK operation timed out."
                    )
                await queue.put(
                    AgentEvent("error", {"message": message, "type": type(exc).__name__})
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
        invocation.cancelling = True
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
        self._histories.clear()
