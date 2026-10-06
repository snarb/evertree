"""Windows Job Object ownership of a trusted subprocess tree."""

from __future__ import annotations

import ctypes
import os
import time


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


# Keep existing trace type names and pickled references valid through the public module.
for _export in (
    SandboxUnavailable,
    WindowsProcessTree,
):
    _export.__module__ = "evertree.core.sandbox"
