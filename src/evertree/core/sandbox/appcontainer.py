"""Windows AppContainer launch, access grants and isolated process lifetime."""

from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .. import cache
from .job import SandboxUnavailable
from .python import prepare_python


@dataclass(frozen=True)
class SandboxLimits:
    memory_bytes: int = 512 * 1024 * 1024
    process_count: int = 32


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


# Keep existing trace type names and pickled references valid through the public module.
for _export in (
    SandboxLimits,
    _grant,
    _revoke,
    SandboxedProcess,
):
    _export.__module__ = "evertree.core.sandbox"
