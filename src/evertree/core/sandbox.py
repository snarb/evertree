"""Native Windows containment for generated Python.

An AppContainer denies access outside explicitly granted directories. A Job Object
owns the complete process tree. Neither mechanism is replaced with Python checks.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from . import cache
from .backup import _extended


class SandboxUnavailable(RuntimeError):
    """The required native containment could not be established."""


class WindowsProcessTree:
    """Lifetime ownership for a trusted SDK server and the children it launches.

    This is a Job Object only, not a filesystem sandbox. Attach immediately after
    SDK startup, before submitting a turn, so tool descendants inherit the job.
    """

    def __init__(self, pid: int):
        if os.name != "nt":
            raise SandboxUnavailable("Windows process-tree ownership requires Windows")
        from ctypes import wintypes as w

        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateJobObjectW.argtypes = [w.LPVOID, w.LPCWSTR]
        self._kernel.CreateJobObjectW.restype = w.HANDLE
        self._kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self._kernel.OpenProcess.restype = w.HANDLE
        self._kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self._kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
        self._kernel.QueryInformationJobObject.argtypes = [
            w.HANDLE,
            ctypes.c_int,
            w.LPVOID,
            w.DWORD,
            w.LPVOID,
        ]
        self._kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self._kernel.CloseHandle.argtypes = [w.HANDLE]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("times", ctypes.c_int64 * 2),
                ("flags", w.DWORD),
                ("minimum", ctypes.c_size_t),
                ("maximum", ctypes.c_size_t),
                ("active", w.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", w.DWORD),
                ("scheduling", w.DWORD),
            ]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("basic", BASIC_LIMIT),
                ("io", ctypes.c_uint64 * 6),
                ("memory", ctypes.c_size_t * 4),
            ]

        self._job = self._kernel.CreateJobObjectW(None, None)
        if not self._job:
            raise ctypes.WinError(ctypes.get_last_error())
        process = None
        try:
            limits = EXTENDED_LIMIT()
            limits.basic.flags = 0x2000
            if not self._kernel.SetInformationJobObject(
                self._job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            process = self._kernel.OpenProcess(0x0100 | 0x0001, False, pid)
            if not process or not self._kernel.AssignProcessToJobObject(self._job, process):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self._kernel.CloseHandle(self._job)
            self._job = None
            raise
        finally:
            if process:
                self._kernel.CloseHandle(process)

    def close(self):
        if not self._job:
            return
        from ctypes import wintypes as w

        class ACCOUNTING(ctypes.Structure):
            _fields_ = [
                ("times", ctypes.c_int64 * 4),
                ("faults", w.DWORD),
                ("total", w.DWORD),
                ("active", w.DWORD),
                ("terminated", w.DWORD),
            ]

        try:
            if not self._kernel.TerminateJobObject(self._job, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            deadline = time.monotonic() + 10
            while True:
                counts = ACCOUNTING()
                if not self._kernel.QueryInformationJobObject(
                    self._job, 1, ctypes.byref(counts), ctypes.sizeof(counts), None
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                if not counts.active:
                    break
                if time.monotonic() > deadline:
                    raise SandboxUnavailable("SDK process tree did not stop")
                time.sleep(0.01)
        finally:
            self._kernel.CloseHandle(self._job)
            self._job = None


@dataclass(frozen=True)
class SandboxLimits:
    memory_bytes: int = 512 * 1024 * 1024
    process_count: int = 32


def _key(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


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


@contextmanager
def prepare_python(*, include_core: bool = True):
    """One dependency installation, plus a small venv containing only EverTree sources."""
    from importlib import metadata

    from .environment import _installed_packages

    if os.name != "nt":
        raise SandboxUnavailable("Generated programs currently require Windows AppContainer.")
    # These are the worker's declared dependencies, not the developer's entire environment.
    packages = _installed_packages(("dbos", "pydantic"))
    base_key = _key([1, sys.version, packages])

    def build_base(destination):
        destination = _extended(destination)
        base = Path(sys.base_prefix)
        for name in ("python.exe", "pythonw.exe", "LICENSE.txt"):
            if (base / name).is_file():
                shutil.copy2(base / name, destination / name)
        for path in base.glob("*.dll"):
            shutil.copy2(path, destination / path.name)
        for name in ("Lib", "DLLs"):
            if (base / name).is_dir():
                shutil.copytree(
                    base / name,
                    destination / name,
                    ignore=shutil.ignore_patterns("__pycache__", "site-packages", "test", "tests"),
                )
        site = destination / "Lib" / "site-packages"
        for name in packages:
            distribution = metadata.distribution(name)
            if distribution.files is None:
                raise SandboxUnavailable(f"Installed dependency has no file manifest: {name}")
            for relative in distribution.files:
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or "__pycache__" in relative.parts
                    or relative.suffix in (".pth", ".pyc", ".egg-link")
                ):
                    continue
                target = site / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(distribution.locate_file(relative), target)

    package_root = Path(__file__).resolve().parents[1]
    if include_core:
        sources = {
            path.relative_to(package_root): path.read_bytes()
            for path in package_root.rglob("*.py")
            if not set(path.relative_to(package_root).parts)
            & {"processes", "common", "__pycache__"}
        }
    else:
        sources = {
            Path("__init__.py"): b"",
            Path("core/__init__.py"): b"",
            Path("core/contracts.py"): (package_root / "core" / "contracts.py").read_bytes(),
        }
    source_key = _key(
        [base_key, {str(path): hashlib.sha256(data).hexdigest() for path, data in sources.items()}]
    )
    with cache.acquire("python", base_key, build_base) as base:

        def build_sources(destination):
            subprocess.run(
                [
                    str(base / "python.exe"),
                    "-I",
                    "-m",
                    "venv",
                    "--without-pip",
                    "--system-site-packages",
                    str(destination),
                ],
                check=True,
                capture_output=True,
                creationflags=0x08000000,
            )
            for relative, data in sources.items():
                target = _extended(destination / "Lib/site-packages/evertree" / relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

        kind = "worker" if include_core else "public"
        with cache.acquire(kind, source_key, build_sources) as environment:
            yield environment / "Scripts/python.exe", (base, environment)


def _grant(path: Path, sid: str, rights: str) -> None:
    # icacls reads and replaces the ACL: concurrent grants/revocations can lose entries.
    with cache._lock(cache.cache_root() / ".acl.lock"):
        result = subprocess.run(
            ["icacls.exe", str(path), "/grant", f"*{sid}:(OI)(CI){rights}", "/Q"],
            capture_output=True,
            text=True,
            creationflags=0x08000000,
            check=False,
        )
    if result.returncode:
        raise SandboxUnavailable(f"Could not grant sandbox access to {path}: {result.stderr}")


def _revoke(path: Path, sid: str) -> None:
    with cache._lock(cache.cache_root() / ".acl.lock"):
        subprocess.run(
            ["icacls.exe", str(path), "/remove:g", "*" + sid, "/Q"],
            capture_output=True,
            creationflags=0x08000000,
            check=False,
        )


class SandboxedProcess:
    """Popen-like owner of an AppContainer and a non-breakaway Job Object."""

    def __init__(
        self,
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
    ) -> None:
        if os.name != "nt":
            raise SandboxUnavailable("Windows AppContainer is required; no unsafe fallback exists.")
        self._process = self._job = None
        self._grants: list[Path] = []
        self._sid = ""
        self._profile = "EverTree.Worker." + uuid.uuid4().hex
        self._profile_created = False
        self._closed = False
        self._lock = threading.RLock()
        self.stdin: BinaryIO
        self.stdout: BinaryIO
        self.stderr: BinaryIO
        self._resources = ExitStack()
        try:
            if executable is None:
                executable, python_roots = self._resources.enter_context(
                    prepare_python(include_core=include_core)
                )
                readable = (*readable, *python_roots)
            if profile_dir is None:
                profile_dir = self._resources.enter_context(cache.temporary_directory())
                writable = (*writable, profile_dir)
            self._launch(
                executable,
                arguments,
                workdir,
                readable,
                writable,
                limits or SandboxLimits(),
                path_entries,
                profile_dir,
            )
        except BaseException:
            self._resources.close()
            raise

    def _launch(
        self, executable, arguments, workdir, readable, writable, limits, path_entries, profile_dir
    ):
        import msvcrt
        from ctypes import wintypes as w

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        userenv = ctypes.WinDLL("userenv", use_last_error=True)
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self._kernel, self._userenv = kernel, userenv
        SIZE_T = ctypes.c_size_t
        HANDLE = w.HANDLE

        class SECURITY_ATTRIBUTES(ctypes.Structure):
            _fields_ = [
                ("nLength", w.DWORD),
                ("lpSecurityDescriptor", w.LPVOID),
                ("bInheritHandle", w.BOOL),
            ]

        class STARTUPINFO(ctypes.Structure):
            _fields_ = [
                ("cb", w.DWORD),
                ("lpReserved", w.LPWSTR),
                ("lpDesktop", w.LPWSTR),
                ("lpTitle", w.LPWSTR),
                ("dwX", w.DWORD),
                ("dwY", w.DWORD),
                ("dwXSize", w.DWORD),
                ("dwYSize", w.DWORD),
                ("dwXCountChars", w.DWORD),
                ("dwYCountChars", w.DWORD),
                ("dwFillAttribute", w.DWORD),
                ("dwFlags", w.DWORD),
                ("wShowWindow", w.WORD),
                ("cbReserved2", w.WORD),
                ("lpReserved2", ctypes.POINTER(w.BYTE)),
                ("hStdInput", HANDLE),
                ("hStdOutput", HANDLE),
                ("hStdError", HANDLE),
            ]

        class STARTUPINFOEX(ctypes.Structure):
            _fields_ = [("StartupInfo", STARTUPINFO), ("lpAttributeList", w.LPVOID)]

        class PROCESS_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("hProcess", HANDLE),
                ("hThread", HANDLE),
                ("dwProcessId", w.DWORD),
                ("dwThreadId", w.DWORD),
            ]

        class SECURITY_CAPABILITIES(ctypes.Structure):
            _fields_ = [
                ("AppContainerSid", w.LPVOID),
                ("Capabilities", w.LPVOID),
                ("CapabilityCount", w.DWORD),
                ("Reserved", w.DWORD),
            ]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", w.DWORD),
                ("MinimumWorkingSetSize", SIZE_T),
                ("MaximumWorkingSetSize", SIZE_T),
                ("ActiveProcessLimit", w.DWORD),
                ("Affinity", SIZE_T),
                ("PriorityClass", w.DWORD),
                ("SchedulingClass", w.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", SIZE_T),
                ("JobMemoryLimit", SIZE_T),
                ("PeakProcessMemoryUsed", SIZE_T),
                ("PeakJobMemoryUsed", SIZE_T),
            ]

        def configure(dll, name, args, result=w.BOOL):
            function = getattr(dll, name)
            function.argtypes, function.restype = args, result
            return function

        close = configure(kernel, "CloseHandle", [HANDLE])
        configure(kernel, "WaitForSingleObject", [HANDLE, w.DWORD], w.DWORD)
        configure(kernel, "GetExitCodeProcess", [HANDLE, ctypes.POINTER(w.DWORD)])
        configure(kernel, "TerminateJobObject", [HANDLE, w.UINT])
        configure(kernel, "TerminateProcess", [HANDLE, w.UINT])
        configure(
            kernel, "QueryInformationJobObject", [HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, w.LPVOID]
        )
        create_profile = configure(
            userenv,
            "CreateAppContainerProfile",
            [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.LPVOID, w.DWORD, ctypes.POINTER(w.LPVOID)],
            ctypes.c_long,
        )
        configure(userenv, "DeleteAppContainerProfile", [w.LPCWSTR], ctypes.c_long)
        derive_sid = configure(
            userenv,
            "DeriveAppContainerSidFromAppContainerName",
            [w.LPCWSTR, ctypes.POINTER(w.LPVOID)],
            ctypes.c_long,
        )
        sid_string = configure(
            advapi, "ConvertSidToStringSidW", [w.LPVOID, ctypes.POINTER(w.LPWSTR)]
        )
        free_sid = configure(advapi, "FreeSid", [w.LPVOID], w.LPVOID)
        local_free = configure(kernel, "LocalFree", [w.LPVOID], w.LPVOID)
        create_pipe = configure(
            kernel,
            "CreatePipe",
            [
                ctypes.POINTER(HANDLE),
                ctypes.POINTER(HANDLE),
                ctypes.POINTER(SECURITY_ATTRIBUTES),
                w.DWORD,
            ],
        )
        set_handle = configure(kernel, "SetHandleInformation", [HANDLE, w.DWORD, w.DWORD])
        create_job = configure(kernel, "CreateJobObjectW", [w.LPVOID, w.LPCWSTR], HANDLE)
        set_job = configure(
            kernel, "SetInformationJobObject", [HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
        )
        assign = configure(kernel, "AssignProcessToJobObject", [HANDLE, HANDLE])
        initialize = configure(
            kernel,
            "InitializeProcThreadAttributeList",
            [w.LPVOID, w.DWORD, w.DWORD, ctypes.POINTER(SIZE_T)],
        )
        update = configure(
            kernel,
            "UpdateProcThreadAttribute",
            [w.LPVOID, w.DWORD, SIZE_T, w.LPVOID, SIZE_T, w.LPVOID, w.LPVOID],
        )
        delete_attributes = configure(kernel, "DeleteProcThreadAttributeList", [w.LPVOID], None)
        create_process = configure(
            kernel,
            "CreateProcessW",
            [
                w.LPCWSTR,
                w.LPWSTR,
                w.LPVOID,
                w.LPVOID,
                w.BOOL,
                w.DWORD,
                w.LPVOID,
                w.LPCWSTR,
                ctypes.POINTER(STARTUPINFOEX),
                ctypes.POINTER(PROCESS_INFORMATION),
            ],
        )
        resume = configure(kernel, "ResumeThread", [HANDLE], w.DWORD)

        def checked(ok, operation):
            if not ok:
                raise SandboxUnavailable(f"{operation}: {ctypes.WinError(ctypes.get_last_error())}")
            return ok

        sid = w.LPVOID()
        sid_text = w.LPWSTR()
        handles = []
        attr = None
        try:
            hr = create_profile(
                self._profile, self._profile, "EverTree isolated worker", None, 0, ctypes.byref(sid)
            )
            if hr < 0:
                # A service/restricted host may have no loaded user profile. An
                # ephemeral AppContainer SID still gives the identical OS token
                # boundary; no profile storage or network capability is needed.
                hr = derive_sid(self._profile, ctypes.byref(sid))
                if hr < 0:
                    raise SandboxUnavailable(
                        f"Cannot create AppContainer SID: 0x{hr & 0xFFFFFFFF:08x}"
                    )
            else:
                self._profile_created = True
            checked(sid_string(sid, ctypes.byref(sid_text)), "ConvertSidToStringSid")
            self._sid = sid_text.value
            for path in dict.fromkeys(Path(p).resolve() for p in readable):
                _grant(path, self._sid, "RX")
                self._grants.append(path)
            for path in dict.fromkeys(Path(p).resolve() for p in writable):
                _grant(path, self._sid, "M")
                self._grants.append(path)

            security = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
            child_stdin, parent_stdin = HANDLE(), HANDLE()
            parent_stdout, child_stdout = HANDLE(), HANDLE()
            parent_stderr, child_stderr = HANDLE(), HANDLE()
            for read, write in (
                (child_stdin, parent_stdin),
                (parent_stdout, child_stdout),
                (parent_stderr, child_stderr),
            ):
                checked(
                    create_pipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(security), 0),
                    "CreatePipe",
                )
                handles.extend((read.value, write.value))
            for parent in (parent_stdin, parent_stdout, parent_stderr):
                checked(set_handle(parent, 1, 0), "SetHandleInformation")
            size = SIZE_T()
            initialize(None, 2, 0, ctypes.byref(size))
            attr = ctypes.create_string_buffer(size.value)
            checked(initialize(attr, 2, 0, ctypes.byref(size)), "Initialize attributes")
            caps = SECURITY_CAPABILITIES(sid, None, 0, 0)
            checked(
                update(attr, 0, 0x00020009, ctypes.byref(caps), ctypes.sizeof(caps), None, None),
                "Set AppContainer capabilities",
            )
            inherited = (HANDLE * 3)(child_stdin.value, child_stdout.value, child_stderr.value)
            checked(
                update(attr, 0, 0x00020002, inherited, ctypes.sizeof(inherited), None, None),
                "Set inherited pipe handles",
            )
            startup = STARTUPINFOEX()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.dwFlags = 0x00000100
            startup.StartupInfo.hStdInput = child_stdin
            startup.StartupInfo.hStdOutput = child_stdout
            startup.StartupInfo.hStdError = child_stderr
            startup.lpAttributeList = ctypes.cast(attr, w.LPVOID)
            self._job = checked(create_job(None, None), "CreateJobObject")
            job_limits = EXTENDED_LIMIT()
            job_limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x0008 | 0x0200
            job_limits.BasicLimitInformation.ActiveProcessLimit = limits.process_count
            job_limits.JobMemoryLimit = limits.memory_bytes
            checked(
                set_job(self._job, 9, ctypes.byref(job_limits), ctypes.sizeof(job_limits)),
                "Set job limits",
            )
            local_data, roaming_data = (
                profile_dir / "AppData" / "Local",
                profile_dir / "AppData" / "Roaming",
            )
            local_data.mkdir(parents=True, exist_ok=True)
            roaming_data.mkdir(parents=True, exist_ok=True)
            windows = os.environ.get("SYSTEMROOT", r"C:\Windows")
            environment = {
                "SYSTEMROOT": windows,
                "WINDIR": os.environ.get("WINDIR", windows),
                "SYSTEMDRIVE": Path(windows).anchor.rstrip("\\"),
                "USERPROFILE": str(profile_dir),
                "LOCALAPPDATA": str(local_data),
                "APPDATA": str(roaming_data),
                "USERNAME": "EverTree",
                "HOMEDRIVE": profile_dir.anchor.rstrip("\\"),
                "HOMEPATH": str(profile_dir)[len(profile_dir.anchor) - 1 :],
                "COMSPEC": str(Path(windows) / "System32" / "cmd.exe"),
                "TEMP": str(profile_dir),
                "TMP": str(profile_dir),
                "PATH": ";".join(
                    str(path)
                    for path in (
                        executable.parent,
                        *path_entries,
                        Path(windows) / "System32",
                        Path(windows) / "System32/WindowsPowerShell/v1.0",
                    )
                ),
                "PYTHONUTF8": "1",
                "PATHEXT": ".COM;.EXE;.BAT;.CMD",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "NUL",
            }
            self.command_environment = dict(environment)
            env_block = ctypes.create_unicode_buffer(
                "\0".join(f"{key}={value}" for key, value in sorted(environment.items())) + "\0\0"
            )
            command = ctypes.create_unicode_buffer(
                subprocess.list2cmdline([str(executable), *arguments])
            )
            info = PROCESS_INFORMATION()
            checked(
                create_process(
                    str(executable),
                    command,
                    None,
                    None,
                    True,
                    0x00080000 | 0x00000400 | 0x00000004 | 0x08000000,
                    env_block,
                    str(workdir),
                    ctypes.byref(startup),
                    ctypes.byref(info),
                ),
                "Create AppContainer process",
            )
            self._process = info.hProcess
            self.pid = info.dwProcessId
            try:
                if not assign(self._job, self._process):
                    error = ctypes.get_last_error()
                    kernel.TerminateProcess(self._process, 1)
                    raise SandboxUnavailable(
                        f"Assign process to Job Object: {ctypes.WinError(error)}"
                    )
                if resume(info.hThread) == 0xFFFFFFFF:
                    checked(False, "ResumeThread")
            finally:
                close(info.hThread)
            for child in (child_stdin, child_stdout, child_stderr):
                close(child)
                handles.remove(child.value)
            self.stdin = os.fdopen(msvcrt.open_osfhandle(parent_stdin.value, os.O_WRONLY), "wb", 0)
            self.stdout = os.fdopen(
                msvcrt.open_osfhandle(parent_stdout.value, os.O_RDONLY), "rb", 0
            )
            self.stderr = os.fdopen(
                msvcrt.open_osfhandle(parent_stderr.value, os.O_RDONLY), "rb", 0
            )
            handles.clear()
        except BaseException:
            if self._job:
                kernel.TerminateJobObject(self._job, 1)
            self.close()
            raise
        finally:
            if attr is not None:
                delete_attributes(attr)
            for handle in handles:
                close(handle)
            if sid_text:
                local_free(sid_text)
            if sid:
                free_sid(sid)

    def poll(self) -> int | None:
        from ctypes import wintypes as w

        if not self._process:
            return 1
        status = w.DWORD()
        if not self._kernel.GetExitCodeProcess(self._process, ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        return None if status.value == 259 else status.value

    def wait(self, timeout: float | None = None) -> int:
        if not self._process:
            return 1
        milliseconds = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        result = self._kernel.WaitForSingleObject(self._process, milliseconds)
        if result == 258:
            raise subprocess.TimeoutExpired("EverTree sandbox", timeout)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return self.poll() or 0

    def terminate(self) -> None:
        with self._lock:
            self._terminate()

    def _terminate(self) -> None:
        if self._job and not self._kernel.TerminateJobObject(self._job, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        self.wait(timeout=10)
        if self._job:
            from ctypes import wintypes as w

            class ACCOUNTING(ctypes.Structure):
                _fields_ = [
                    ("times", ctypes.c_int64 * 4),
                    ("faults", w.DWORD),
                    ("total", w.DWORD),
                    ("active", w.DWORD),
                    ("terminated", w.DWORD),
                ]

            deadline = time.monotonic() + 10
            while True:
                counts = ACCOUNTING()
                if not self._kernel.QueryInformationJobObject(
                    self._job, 1, ctypes.byref(counts), ctypes.sizeof(counts), None
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                if counts.active == 0:
                    break
                if time.monotonic() > deadline:
                    raise SandboxUnavailable("Worker process tree did not terminate")
                time.sleep(0.01)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._job:
                self.terminate()
                self._kernel.CloseHandle(self._job)
                self._job = None
            if self._process:
                self._kernel.CloseHandle(self._process)
                self._process = None
            for name in ("stdin", "stdout", "stderr"):
                stream = getattr(self, name, None)
                if stream:
                    stream.close()
            for path in self._grants:
                _revoke(path, self._sid)
            self._grants.clear()
            if hasattr(self, "_userenv") and self._profile_created:
                self._userenv.DeleteAppContainerProfile(self._profile)
            self._resources.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
