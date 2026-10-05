"""Execution environments, shared Python distributions and native sandbox probes."""

from __future__ import annotations

import json
import shutil
from contextlib import ExitStack
from pathlib import Path

from . import cache
from .backup import _extended
from .python_environment import _key, prepare_python
from .windows_appcontainer import (  # noqa: F401 -- preserve public import paths
    SandboxedProcess,
    SandboxLimits,
    _grant,
    _revoke,
)
from .windows_job import (  # noqa: F401 -- preserve public import paths
    SandboxUnavailable,
    WindowsProcessTree,
)


def start_exec_server(state_dir: Path, workspace: Path) -> SandboxedProcess:
    """Share immutable tools; only this workspace and a temporary profile are writable."""
    from codex_cli_bin import bundled_codex_path

    state_dir, workspace = Path(state_dir).resolve(), Path(workspace).resolve()
    if state_dir.is_relative_to(workspace) or cache.cache_root().resolve().is_relative_to(
        workspace
    ):
        raise ValueError("Executor binaries and private state must be outside the coding workspace")
    codex = Path(bundled_codex_path()).resolve()
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
        process = SandboxedProcess(
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


def check_sandbox() -> dict[str, bool]:
    """Run a native token/filesystem probe for ``evertree doctor``.

    This launches only the fixed diagnostic below, with no model or network call.
    """
    with cache.temporary_directory() as probe:
        return _check_sandbox(probe)


def _check_sandbox(probe: Path) -> dict[str, bool]:
    scratch = probe / "scratch"
    scratch.mkdir(parents=True)
    protected = probe / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    code = f"""
import ctypes, json
from ctypes import wintypes as w
from pathlib import Path
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
advapi = ctypes.WinDLL('advapi32', use_last_error=True)
kernel.GetCurrentProcess.restype = w.HANDLE
advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
advapi.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
token, flag, needed = w.HANDLE(), w.DWORD(), w.DWORD()
assert advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token))
assert advapi.GetTokenInformation(token, 29, ctypes.byref(flag), ctypes.sizeof(flag), ctypes.byref(needed))
result = {{'app_container': bool(flag.value)}}
for mode in ('read', 'write'):
    try:
        path = Path({str(protected)!r})
        path.read_text() if mode == 'read' else path.write_text('forbidden')
        result[mode + '_denied'] = False
    except PermissionError:
        result[mode + '_denied'] = True
Path('allowed.txt').write_text('allowed')
result['scratch_writable'] = True
print(json.dumps(result), flush=True)
"""
    with SandboxedProcess(
        None,
        ["-I", "-c", code],
        workdir=scratch,
        readable=(),
        writable=(scratch,),
    ) as process:
        code = process.wait(timeout=30)
        if code:
            raise SandboxUnavailable(process.stderr.read(8192).decode(errors="replace"))
        result = json.loads(process.stdout.read())
        if not all(result.values()):
            raise SandboxUnavailable("Native sandbox probe did not enforce its boundaries")
        return result
