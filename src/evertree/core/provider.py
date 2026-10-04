"""Provider-neutral boundary. SDK types and credentials never enter Programs."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

type ToolHandler = Callable[[str, dict[str, Any]], Awaitable[Any]]
type ApprovalHandler = Callable[[dict[str, Any]], Awaitable[bool]]
type ToolStatus = Literal["completed", "failed", "declined", "cancelled"]


class UsageData(TypedDict):
    """Cumulative counters for this run, never a session total or an event delta.

    Consumers replace the previous snapshot, never sum these events. None means
    the provider cannot attribute usage to this invocation; it does not mean zero.
    Cached/reasoning counters are subsets of input/output, not additional tokens.
    """

    available: bool
    total_tokens: int | None
    input_tokens: int | None
    cached_input_tokens: int | None
    cache_write_input_tokens: int | None
    output_tokens: int | None
    reasoning_output_tokens: int | None


class ToolCallData(TypedDict):
    """Same envelope for native and declared tools; arguments are tool-specific."""

    call_id: str
    name: str
    arguments: Any


class ToolResultData(TypedDict):
    call_id: str
    name: str
    status: ToolStatus
    result: Any
    error: str | None


class FileChangeData(TypedDict):
    """One proposed/applied path change, correlated with its tool result."""

    call_id: str
    path: str
    operation: Literal["add", "update", "delete"]
    status: ToolStatus
    diff: str
    moved_to: str | None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class SessionRef:
    provider: str
    id: str


@dataclass(frozen=True)
class AgentRequest:
    """One invocation; the runtime supplies context and authorizes every capability."""

    prompt: str
    workspace: Path
    instructions: str = ""
    mode: Literal["model", "exec"] = "model"
    native_coding: bool = False
    output_schema: dict[str, Any] | None = None
    tools: tuple[ToolDefinition, ...] = ()
    session: SessionRef | None = None
    timeout_seconds: float | None = None

    def __post_init__(self):
        if self.native_coding and self.mode != "exec":
            raise ValueError("Native coding requires an exec invocation")


@dataclass(frozen=True)
class AgentEvent:
    """Normalized payloads above; provider_event alone contains SDK-specific data."""

    kind: Literal[
        "session",
        "message",
        "tool_call",
        "tool_result",
        "approval",
        "usage",
        "file_change",
        "error",
        "completed",
        "cancelled",
        "provider_event",
    ]
    data: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    """Provider could not satisfy the request; never silently changes model."""


class AgentProvider(Protocol):
    name: str

    def run(
        self,
        request_id: str,
        request: AgentRequest,
        *,
        tool_handler: ToolHandler | None = None,
        approval_handler: ApprovalHandler | None = None,
    ) -> AsyncIterator[AgentEvent]: ...

    async def cancel(self, request_id: str) -> None: ...

    async def doctor(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class ScriptedProvider:
    """Explicit offline test provider; never used as a fallback for Codex."""

    name = "scripted"

    def __init__(self, scripts: list[list[AgentEvent]]):
        self.scripts = list(scripts)
        self.requests: list[AgentRequest] = []
        self.cancelled: set[str] = set()

    async def run(self, request_id, request, *, tool_handler=None, approval_handler=None):
        self.requests.append(request)
        if not self.scripts:
            raise ProviderError("Offline provider has no remaining script")
        yield AgentEvent("session", {"provider": self.name, "id": request_id})
        for index, event in enumerate(self.scripts.pop(0)):
            if request_id in self.cancelled:
                yield AgentEvent("cancelled")
                return
            if event.kind == "tool_call":
                if request.mode != "exec" or tool_handler is None:
                    raise ProviderError("Tool execution is not permitted")
                if event.data["name"] not in {tool.name for tool in request.tools}:
                    raise ProviderError("Tool was not declared")
                call = {
                    "call_id": event.data.get("call_id") or f"{request_id}:{index}",
                    "name": event.data["name"],
                    "arguments": event.data.get("arguments", {}),
                }
                yield AgentEvent("tool_call", call)
                try:
                    result = await tool_handler(call["name"], call["arguments"])
                except Exception as exc:
                    yield AgentEvent(
                        "tool_result",
                        {
                            "call_id": call["call_id"],
                            "name": call["name"],
                            "status": "failed",
                            "result": None,
                            "error": str(exc),
                        },
                    )
                    raise
                yield AgentEvent(
                    "tool_result",
                    {
                        "call_id": call["call_id"],
                        "name": call["name"],
                        "status": "completed",
                        "result": result,
                        "error": None,
                    },
                )
            elif event.kind == "approval":
                allowed = bool(approval_handler and await approval_handler(event.data))
                yield AgentEvent("approval", {**event.data, "approved": allowed})
            else:
                yield event

    async def cancel(self, request_id):
        self.cancelled.add(request_id)

    async def doctor(self):
        return {"provider": self.name, "available": True, "offline": True}

    async def close(self):
        pass
