import asyncio
import base64
import json
import os
import socket

import pytest
from websockets.asyncio.client import connect

from evertree.core.codex.executor import CodexExecutor


@pytest.mark.skipif(os.name != "nt", reason="Native Windows AppContainer")
async def test_native_executor_tools_deny_outside_files(tmp_path):
    """Real Windows isolation/tools are required; a test process cannot prove this OS contract."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    private = tmp_path / "private-state"
    private.mkdir()
    canaries = [
        private / "credentials-canary.json",
        private / "holdout-canary.json",
        private / "core-canary.py",
    ]
    for path in canaries:
        path.write_text("outside-workspace-canary", encoding="utf-8")
    executor = CodexExecutor(workspace, tmp_path / "executor")
    descriptor = await executor.start()
    request_id = 0
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        listener.settimeout(2)
        address = listener.getsockname()
        # A successful host connection rules out an absent service or firewall
        # timeout masquerading as executor network isolation.
        with socket.create_connection(address, timeout=2) as control:
            accepted, peer = listener.accept()
            assert peer == control.getsockname()
            accepted.close()
        async with connect(
            descriptor["execServerUrl"],
            additional_headers={
                "Authorization": "Bearer " + descriptor["authBearerToken"],
            },
        ) as connection:

            async def request(method, params):
                nonlocal request_id
                request_id += 1
                await connection.send(
                    json.dumps(
                        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
                    )
                )
                async with asyncio.timeout(15):
                    while True:
                        response = json.loads(await connection.recv())
                        if response.get("id") == request_id:
                            return response

            initialized = await request("initialize", {"clientName": "evertree-isolation-test"})
            assert "error" not in initialized
            shell = initialized["result"]["environmentInfo"]["shell"]
            assert shell["name"] == "cmd"
            assert shell["path"] == executor.command_environment["COMSPEC"]
            await connection.send(
                json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}})
            )

            async def run_command(process_id, command):
                response = await request(
                    "process/start",
                    {
                        "processId": process_id,
                        "argv": [shell["path"], "/c", command],
                        "cwd": workspace.as_uri(),
                        "env": executor.command_environment,
                        "tty": False,
                        "pipeStdin": False,
                        "arg0": None,
                        "sandbox": None,
                    },
                )
                assert "error" not in response, response
                async with asyncio.timeout(15):
                    while True:
                        response = await request(
                            "process/read",
                            {
                                "processId": process_id,
                                "afterSeq": None,
                                "maxBytes": 65536,
                                "waitMs": 1000,
                            },
                        )
                        assert "error" not in response, response
                        result = response["result"]
                        if result["closed"]:
                            outputs = tuple(
                                "".join(
                                    base64.b64decode(chunk["chunk"]).decode(
                                        "utf-8", errors="replace"
                                    )
                                    for chunk in result["chunks"]
                                    if chunk["stream"] == stream
                                )
                                for stream in ("stdout", "stderr")
                            )
                            return result["exitCode"], *outputs

            code, output, diagnostics = await run_command(
                "native-quoted",
                'python -c "from pathlib import Path; '
                "Path('quoted file & name.txt').write_text('quoted content'); "
                "print('quoted hello')\" && python -c \"print('second')\"",
            )
            assert code == 0, output + diagnostics
            assert output.splitlines() == ["quoted hello", "second"]
            assert (workspace / "quoted file & name.txt").read_text() == "quoted content"
            code, output, diagnostics = await run_command(
                "native-exit-code", 'python -c "import sys; sys.exit(7)"'
            )
            assert code == 7, output + diagnostics
            allowed = workspace / "allowed.txt"
            response = await request(
                "fs/writeFile",
                {
                    "path": allowed.as_uri(),
                    "sandbox": None,
                    "dataBase64": base64.b64encode(b"allowed").decode(),
                },
            )
            assert "error" not in response
            response = await request("fs/readFile", {"path": allowed.as_uri(), "sandbox": None})
            assert base64.b64decode(response["result"]["dataBase64"]) == b"allowed"
            removable = workspace / "remove-control.txt"
            removable.write_text("remove-control", encoding="utf-8")
            response = await request(
                "fs/remove",
                {
                    "path": removable.as_uri(),
                    "recursive": False,
                    "force": False,
                    "sandbox": None,
                },
            )
            assert "error" not in response
            assert not removable.exists(), "Native executor did not remove its allowed control"
            for path in canaries:
                response = await request("fs/readFile", {"path": path.as_uri(), "sandbox": None})
                assert "error" in response, "Native executor read an outside canary"
                response = await request(
                    "fs/writeFile",
                    {
                        "path": path.as_uri(),
                        "sandbox": None,
                        "dataBase64": base64.b64encode(b"changed").decode(),
                    },
                )
                assert "error" in response, "Native executor wrote an outside canary"
                response = await request(
                    "fs/remove",
                    {
                        "path": path.as_uri(),
                        "recursive": False,
                        "force": False,
                        "sandbox": None,
                    },
                )
                assert "error" in response, "Native executor removed an outside canary"
                assert response["error"]["code"] != -32602, (
                    "Malformed removal request is not a boundary test"
                )
            # Native subprocess tools inherit the same token, including when
            # the executor's protocol explicitly asks for no inner sandbox.
            child_code = f"""
import ctypes, importlib.util, json, socket
from ctypes import wintypes as w
from pathlib import Path
from evertree.core.contracts import ProgramContext, ProgramResult
assert ProgramResult('public contract').result == 'public contract'
for name in ('application', 'core.lifecycle', 'core.runtime', 'core.sandbox'):
    assert importlib.util.find_spec('evertree.' + name) is None, 'coding tools can import protected core'
assert importlib.util.find_spec('pydantic') is not None, 'coding tools lost installed libraries'
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
advapi = ctypes.WinDLL('advapi32', use_last_error=True)
kernel.GetCurrentProcess.restype = w.HANDLE
kernel.CloseHandle.argtypes = [w.HANDLE]
advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
advapi.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
token, flag, needed = w.HANDLE(), w.DWORD(), w.DWORD()
assert advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)), ctypes.get_last_error()
try:
    assert advapi.GetTokenInformation(token, 29, ctypes.byref(flag), ctypes.sizeof(flag), ctypes.byref(needed)), ctypes.get_last_error()
    assert flag.value == 1, 'native child is not in AppContainer'
finally:
    kernel.CloseHandle(token)
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as channel:
    channel.settimeout(2)
    try:
        channel.connect({address!r})
    except TimeoutError:
        pass  # Windows may silently drop AppContainer packets.
    except OSError as error:
        assert error.winerror == 10013, f'Expected WSAEACCES, got {{error!r}}'
    else:
        raise AssertionError('native child reached host loopback network')
assert Path.cwd() == Path({str(workspace)!r}), 'native process cwd differs from its workspace'
try:
    Path({str(canaries[0])!r}).read_text()
except PermissionError:
    Path('child-allowed.txt').write_text('allowed')
else:
    raise RuntimeError('child escaped AppContainer')
Path('boundary-report.json').write_text(json.dumps({{'app_container': True, 'loopback_denied': True}}))
"""
            (workspace / ".native-boundary-probe.py").write_text(child_code, encoding="utf-8")
            code, output, diagnostics = await run_command(
                "native-child", "python -I .native-boundary-probe.py"
            )
            assert code == 0, output + diagnostics
            # Confirm the same listener remained healthy through the child's
            # timeout, and that no delayed child connection reached its queue.
            with socket.create_connection(address, timeout=2) as control:
                accepted, peer = listener.accept()
                try:
                    assert peer == control.getsockname()
                finally:
                    accepted.close()
    finally:
        listener.close()
        await asyncio.wait_for(executor.close(), 15)
    assert allowed.read_text() == "allowed"
    assert (workspace / "child-allowed.txt").read_text() == "allowed"
    assert json.loads((workspace / "boundary-report.json").read_text()) == {
        "app_container": True,
        "loopback_denied": True,
    }
    assert all(path.read_text() == "outside-workspace-canary" for path in canaries)


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native isolation")
