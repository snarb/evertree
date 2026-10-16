"""Isolated coding executors with shared immutable tool distributions."""

from __future__ import annotations

import shutil
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

from .. import cache
from ..backup import _extended
from .process import (
    SandboxedProcess,
    SandboxLimits,
    SandboxUnavailable,
    start_process,
)
from .python import _key, prepare_python


def start_exec_server(state_dir: Path, workspace: Path) -> SandboxedProcess:
    """Start the isolated tool executor with a writable workspace and private temporary profile."""
    from codex_cli_bin import bundled_codex_path

    state_dir, workspace = Path(state_dir).resolve(), Path(workspace).resolve()
    if state_dir.is_relative_to(workspace) or cache.cache_root().resolve().is_relative_to(
        workspace
    ):
        raise ValueError("Executor binaries and private state must be outside the coding workspace")
    codex = Path(bundled_codex_path()).resolve()
    if sys.platform == "darwin":
        return _start_macos(codex, workspace)
    git = shutil.which("git")
    if git is None:
        raise SandboxUnavailable("Native coding requires an installed Git distribution")
    git_root = Path(git).resolve().parent.parent
    git_exe = git_root / "mingw64" / "bin" / "git.exe"
    if not git_exe.is_file():
        raise SandboxUnavailable("Native Windows coding requires Git for Windows")

    def version(path):
        return _key([str(path), path.stat().st_size, path.stat().st_mtime_ns])

    def copy_git(destination):
        for relative in (
            "cmd",
            "mingw64/bin",
            "mingw64/libexec/git-core",
            "mingw64/share/git-core/templates",
        ):
            shutil.copytree(git_root / relative, _extended(destination / relative))

    with ExitStack() as resources:
        python, python_roots = resources.enter_context(prepare_python(include_core=False))
        codex_dir = resources.enter_context(
            cache.acquire(
                "codex",
                version(codex),
                lambda target: shutil.copytree(codex.parent, _extended(target), dirs_exist_ok=True),
            )
        )
        git_dir = resources.enter_context(cache.acquire("git", version(git_exe), copy_git))
        profile = resources.enter_context(cache.temporary_directory())
        workspace.mkdir(parents=True, exist_ok=True)
        process = start_process(
            codex_dir / codex.name,
            ["exec-server", "--listen", "stdio"],
            workdir=workspace,
            readable=(*python_roots, codex_dir, git_dir),
            writable=(workspace, profile),
            path_entries=(python.parent, git_dir / "cmd"),
            profile_dir=profile,
            limits=SandboxLimits(memory_bytes=1024 * 1024 * 1024),
        )
        process._resources.enter_context(resources.pop_all())
        process.shell_python = python
        return process


def _start_macos(codex: Path, workspace: Path) -> SandboxedProcess:
    from .commands import MacCommandGroups

    git = Path("/usr/bin/git")
    try:
        exec_path = subprocess.run(
            [str(git), "--exec-path"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise SandboxUnavailable(
            "Native macOS coding requires Git and Command Line Tools"
        ) from error
    git_runtime = Path(exec_path).resolve().parents[1]
    with ExitStack() as resources:
        python, roots = resources.enter_context(prepare_python(include_core=False))
        commands = MacCommandGroups(python)
        resources.callback(commands.close)
        profile = resources.enter_context(cache.temporary_directory())
        workspace.mkdir(parents=True, exist_ok=True)
        process = start_process(
            codex,
            ["exec-server", "--listen", "stdio"],
            workdir=workspace,
            readable=(*roots, codex, git_runtime, commands.path),
            writable=(workspace, profile),
            path_entries=(python.parent,),
            profile_dir=profile,
        )
        process._resources.enter_context(resources.pop_all())
        process.shell_python = python
        process.command_groups = commands
        return process
