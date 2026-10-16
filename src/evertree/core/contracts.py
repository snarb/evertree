"""Provider-independent boundary types shared by core and isolated Programs."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProgramResult[T]:
    result: T
    feedback: str | None = None


class ProgramContext(Protocol):
    task_id: str
    run_id: str
    run_mode: str

    async def step(self, method: str, payload: dict | None = None) -> Any:
        """Perform a durable Core operation whose recorded result is reused during recovery."""
        ...

    async def call(self, program: str | int, arguments: dict | None = None) -> ProgramResult:
        """Run a child Program as a workflow and return its result and feedback."""
        ...

    async def llm(
        self, payload: dict, *, tools, tool_handler, max_tool_calls: int = 40, stop_when=None
    ) -> Any:
        """Have the LLM work on payload["prompt"], letting it call the declared tools.

        Each tool call the model makes runs tool_handler(name, arguments) in Program
        code, and its result goes back to the model. Returns the model's final
        response, or {"tool", "result"} if stop_when accepts a successful tool result,
        which ends the call early. ValueError, TypeError and PermissionError from the
        handler are reported to the model; other errors fail the call.
        """
        ...

    async def next_observation(self, timeout_seconds: float = 60) -> Any:
        """Wait for a new observation delivered to this exec Program."""
        ...

    async def emit(self, operator: str, *, arguments=None, output=None) -> Any:
        """Record a semantic trace event for an operation performed by this Program."""
        ...

    async def checkpoint(self) -> Any:
        """Establish a durable boundary for runtime coordination."""
        ...


# Core API wrappers call these Programs by slug with exactly these arguments.
# Layout validation rejects a Program revision whose entrypoint cannot accept them,
# because candidates cannot change the protected wrappers.
CALLED_PROGRAMS: dict[str, tuple[str, ...]] = {
    "credit_assignment": ("target", "observation_ids", "context"),
    "semantic_search": ("query",),
}
