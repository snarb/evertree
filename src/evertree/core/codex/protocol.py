"""Codex wire responses and normalization of usage and native tool events."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from evertree.core.provider import AgentEvent, ProviderError


class _RawResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


def _request(client, method, params):
    return client.request(method, params, response_model=_RawResponse).model_dump()


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


# Keep existing trace type names and pickled references valid through the public module.
for _export in (
    _RawResponse,
    _request,
    _json,
    _usage,
    _native_tool_events,
):
    _export.__module__ = "evertree.core.codex_provider"
