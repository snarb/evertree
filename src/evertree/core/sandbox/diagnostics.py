"""Native token and filesystem probes for sandbox diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

from .. import cache
from .appcontainer import (
    SandboxedProcess,
)
from .job import (
    SandboxUnavailable,
)


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
