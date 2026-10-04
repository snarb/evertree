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

    async def step(self, method: str, payload: dict | None = None) -> Any: ...
    async def call(self, program: str | int, arguments: dict | None = None) -> ProgramResult: ...
    async def next_observation(self, timeout_seconds: float = 60) -> Any: ...
    async def emit(self, operator: str, *, arguments=None, output=None) -> Any: ...
    async def checkpoint(self) -> Any: ...
