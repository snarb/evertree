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

    async def agent(
        self, payload: dict, *, tools, tool_handler, max_tool_calls: int = 40, stop_when=None
    ) -> Any:
        """Run a Program's LLM dialogue using only the declared tools.

        Handlers run at workflow level and replay during recovery. stop_when ends the
        dialogue after a matching successful tool and returns its name and result.
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
