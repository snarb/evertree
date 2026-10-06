"""Codex launch policy, model capabilities, permissions and thread configuration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from evertree.core.provider import AgentRequest, ProviderError

from .protocol import _request

MODEL = "gpt-6-luna"


EFFORT = "high"


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
    filesystem[str(Path(__file__).resolve().parents[1])] = "deny"
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


def create_client(
    *,
    codex_bin,
    client_factory,
    request: AgentRequest | None = None,
    handler=None,
    model_catalog=None,
):
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
    binary = str(Path(codex_bin).resolve()) if codex_bin else str(bundled_codex_path())
    command = [sys.executable, "-I", "-S", "-c", _LAUNCHER, binary]
    for item in overrides:
        command.extend(("--config", item))
    command.extend(("app-server", "--listen", "stdio://"))
    config = CodexConfig(
        codex_bin=codex_bin,
        config_overrides=tuple(overrides),
        launch_args_override=tuple(command),
        cwd=str(request.workspace.resolve()) if request else None,
        client_name="evertree",
        client_title="EverTree",
        experimental_api=True,
    )
    factory = client_factory or CodexClient
    client = factory(
        config=config, approval_handler=handler or (lambda *_: {"decision": "decline"})
    )
    client._evertree_profile = profile_id
    return client


async def computation_catalog(state_dir: Path, create_client):
    cache = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "models_cache.json"
    if not cache.is_file():
        # model/list refreshes public metadata without starting/billing a turn.
        bootstrap = create_client()
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
        raise ProviderError("Exact Luna metadata is unavailable; refusing model fallback") from exc
    efforts = selected.get("supported_reasoning_levels", [])
    if not any(item.get("effort") == EFFORT for item in efforts):
        raise ProviderError("Exact Luna metadata does not support high reasoning effort")
    model = {key: value for key, value in selected.items() if key in _MODEL_METADATA_FIELDS}
    model.update(_COMPUTATION_CAPABILITIES)
    encoded = json.dumps({"models": [model]}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    directory = state_dir / "model-catalogs"
    directory.mkdir(parents=True, exist_ok=True)
    catalog = directory / (digest + ".json")
    temporary = directory / (uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, catalog)
    finally:
        temporary.unlink(missing_ok=True)
    return catalog, digest


def thread_config(client, workspace: Path, command_environment=None) -> dict[str, Any]:
    # Empty maps merge with inherited TOML maps; they do not remove entries.
    # Inspect names only and explicitly disable every effective MCP server.
    effective = _request(client, "config/read", {"cwd": str(workspace), "includeLayers": False})[
        "config"
    ]
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


# Keep existing trace type names and pickled references valid through the public module.
for _export in (
    _profile,
    _toml,
    _attach_process_tree,
    _start_owned_client,
):
    _export.__module__ = "evertree.core.codex_provider"
