"""Platform-neutral native process construction and execution limits."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, Self


class SandboxUnavailable(RuntimeError):
    """The required native containment could not be established."""


@dataclass(frozen=True)
class SandboxLimits:
    """Windows Job Object limits; macOS uses the caller's execution timeout."""

    memory_bytes: int = 512 * 1024 * 1024
    process_count: int = 32


def sandbox_backend() -> str:
    """Select the native isolation backend supported by this operating system."""
    if os.name == "nt":
        return "app_container"
    if sys.platform == "darwin":
        return "seatbelt"
    raise SandboxUnavailable("Native execution requires macOS Seatbelt or Windows AppContainer")


class SandboxedProcess(Protocol):
    """The native process operations used by runtime and tool execution."""

    pid: int
    stdin: BinaryIO
    stdout: BinaryIO
    stderr: BinaryIO
    command_environment: dict[str, str]

    def poll(self) -> int | None:
        """Return the sandboxed process exit code, or None while it is running."""
        ...

    def wait(self, timeout: float | None = None) -> int:
        """Wait for process exit and return its code; timeout is measured in seconds."""
        ...

    def terminate(self) -> None:
        """Stop the owned sandbox process tree and wait for termination."""
        ...

    def close(self) -> None:
        """Stop owned processes and release sandbox handles, streams and temporary resources."""
        ...

    def __enter__(self) -> Self: ...
    def __exit__(self, *args) -> None: ...


def start_process(
    executable: Path | None,
    arguments: list[str],
    *,
    workdir: Path,
    readable: tuple[Path, ...],
    writable: tuple[Path, ...],
    limits: SandboxLimits | None = None,
    path_entries: tuple[Path, ...] = (),
    profile_dir: Path | None = None,
    include_core: bool = True,
) -> SandboxedProcess:
    """Launch a process under native isolation with explicit readable and writable paths."""
    if sandbox_backend() == "app_container":
        from .appcontainer import SandboxedProcess as implementation
    else:
        from .seatbelt import SandboxedProcess as implementation
    return implementation(
        executable,
        arguments,
        workdir=workdir,
        readable=readable,
        writable=writable,
        limits=limits,
        path_entries=path_entries,
        profile_dir=profile_dir,
        include_core=include_core,
    )
