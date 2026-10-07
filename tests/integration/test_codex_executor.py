import asyncio
import json
import os
import subprocess
import sys
import threading

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from evertree.core.codex.executor import _CMD_SHIM, CodexExecutor


class PipeProcess:
    """A harmless protocol fixture; production always uses AppContainer."""

    def __init__(self, code=None):
        code = (
            code
            or "import sys\nfor line in sys.stdin:\n sys.stdout.write(line); sys.stdout.flush()"
        )
        self.process = subprocess.Popen(
            [sys.executable, "-I", "-S", "-c", code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.stdin, self.stdout, self.stderr = (
            self.process.stdin,
            self.process.stdout,
            self.process.stderr,
        )
        self.closed = False
        self.shell_python = sys.executable
        self.command_environment = {
            "COMSPEC": os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
        }

    def close(self):
        self.process.terminate()
        self.process.wait(timeout=5)
        for stream in (self.stdin, self.stdout, self.stderr):
            stream.close()
        self.closed = True


@pytest.mark.asyncio
async def test_authenticated_bridge_preserves_protocol_and_stops_process(tmp_path):
    """Use real pipes/processes and loopback transport to verify executor protocol and ownership."""
    process = PipeProcess()
    executor = CodexExecutor(
        tmp_path / "candidate", tmp_path / "runtime", process_factory=lambda *_: process
    )
    descriptor = await executor.start()
    assert descriptor["execServerUrl"].startswith("ws://127.0.0.1:")
    assert executor.environment["environmentId"] == descriptor["environmentId"]
    assert executor.environment["runtimeWorkspaceRoots"] == [
        str((tmp_path / "candidate").resolve())
    ]
    try:
        async with connect(
            descriptor["execServerUrl"],
            additional_headers={
                "Authorization": "Bearer " + descriptor["authBearerToken"],
            },
        ) as connection:
            payload = {"id": "a", "method": "fixture", "params": {"text": "Привет\nworld"}}
            await connection.send(json.dumps(payload, indent=2, ensure_ascii=False))
            assert json.loads(await asyncio.wait_for(connection.recv(), 3)) == payload
            assert not process.closed
    finally:
        await asyncio.wait_for(executor.close(), 5)
    assert process.closed
    assert process.process.poll() is not None


@pytest.mark.asyncio
async def test_bridge_adapts_only_the_pinned_native_cmd_request(tmp_path):
    """Use real pipes/processes and loopback transport to verify executor protocol and ownership."""
    process = PipeProcess()
    executor = CodexExecutor(
        tmp_path / "candidate", tmp_path / "runtime", process_factory=lambda *_: process
    )
    descriptor = await executor.start()
    cmd = process.command_environment["COMSPEC"]
    command = 'python -c "print(123)" && echo done'
    original = {
        "id": "native",
        "method": "process/start",
        "params": {
            "processId": "p1",
            "argv": [cmd, "/c", command],
            "cwd": "file:///candidate",
            "env": {"TEST": "value"},
            "tty": False,
            "pipeStdin": True,
            "arg0": None,
            "sandbox": None,
        },
    }
    try:
        async with connect(
            descriptor["execServerUrl"],
            additional_headers={"Authorization": "Bearer " + descriptor["authBearerToken"]},
        ) as connection:
            await connection.send(json.dumps(original))
            actual = json.loads(await asyncio.wait_for(connection.recv(), 3))
            assert actual["params"].pop("argv") == [
                sys.executable,
                "-I",
                "-S",
                "-c",
                _CMD_SHIM,
                cmd,
                command,
            ]
            expected = json.loads(json.dumps(original))
            expected["params"].pop("argv")
            assert actual == expected
            for method, argv, arg0 in (
                ("fixture", [cmd, "/c", command], None),
                ("process/start", ["another-cmd.exe", "/c", command], None),
                ("process/start", [cmd, "/d", "/c", command], None),
                ("process/start", [cmd, "/c", command], "custom-argv0"),
                ("process/start", [cmd, "/c", 123], None),
            ):
                payload = {
                    **original,
                    "method": method,
                    "params": {**original["params"], "argv": argv, "arg0": arg0},
                }
                await connection.send(json.dumps(payload))
                assert json.loads(await asyncio.wait_for(connection.recv(), 3)) == payload
    finally:
        await asyncio.wait_for(executor.close(), 5)


@pytest.mark.asyncio
async def test_bridge_rejects_missing_token_browser_and_concurrent_clients(tmp_path):
    """Use real pipes/processes and loopback transport to verify executor protocol and ownership."""
    process = PipeProcess()
    executor = CodexExecutor(
        tmp_path / "candidate", tmp_path / "runtime", process_factory=lambda *_: process
    )
    descriptor = await executor.start()
    headers = {"Authorization": "Bearer " + descriptor["authBearerToken"]}
    try:
        for arguments in ({}, {"additional_headers": headers, "origin": "https://untrusted.test"}):
            with pytest.raises(InvalidStatus) as denied:
                async with connect(descriptor["execServerUrl"], **arguments):
                    pytest.fail("Unauthenticated/browser client reached the executor")
            assert denied.value.response.status_code == 401
        assert not process.closed
        async with connect(descriptor["execServerUrl"], additional_headers=headers) as first:
            await first.send('{"id":1,"method":"fixture"}')
            await first.recv()
            with pytest.raises(InvalidStatus) as denied:
                async with connect(descriptor["execServerUrl"], additional_headers=headers):
                    pytest.fail("Two connections reached one executor")
            assert denied.value.response.status_code == 409
    finally:
        await asyncio.wait_for(executor.close(), 5)


@pytest.mark.asyncio
async def test_bridge_close_unblocks_idle_pipe_and_socket(tmp_path):
    """Use real pipes/processes and loopback transport to verify executor protocol and ownership."""
    process = PipeProcess()
    executor = CodexExecutor(
        tmp_path / "candidate", tmp_path / "runtime", process_factory=lambda *_: process
    )
    descriptor = await executor.start()
    async with connect(
        descriptor["execServerUrl"],
        additional_headers={
            "Authorization": "Bearer " + descriptor["authBearerToken"],
        },
    ):
        await asyncio.wait_for(executor.close(), 5)
    assert process.closed


@pytest.mark.asyncio
async def test_cancelling_start_waits_for_factory_then_reaps_process(tmp_path):
    """Use real pipes/processes and loopback transport to verify executor protocol and ownership."""
    entered, release = threading.Event(), threading.Event()
    process = PipeProcess()

    def factory(*_):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Test did not release executor startup")
        return process

    executor = CodexExecutor(tmp_path / "candidate", tmp_path / "runtime", process_factory=factory)
    startup = asyncio.create_task(executor.start())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        startup.cancel()
        await asyncio.sleep(0)
        assert not startup.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(startup, 5)
        assert process.closed
        assert executor._server is None
        with pytest.raises(RuntimeError, match="only once"):
            await executor.start()
    finally:
        release.set()
        await executor.close()
        if not process.closed:
            process.close()


@pytest.mark.asyncio
async def test_listen_failure_reaps_executor(tmp_path, monkeypatch):
    """Use real pipes/processes and loopback transport to verify executor protocol and ownership."""
    process = PipeProcess()
    executor = CodexExecutor(
        tmp_path / "candidate", tmp_path / "runtime", process_factory=lambda *_: process
    )

    async def fail_listen(*_, **__):
        raise OSError("Fixture cannot bind socket")

    monkeypatch.setattr("evertree.core.codex.executor.serve", fail_listen)
    with pytest.raises(OSError, match="cannot bind"):
        await executor.start()
    assert process.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["[]", "not json", '{"value": NaN}'])
async def test_malformed_client_frame_closes_executor(tmp_path, payload):
    """Use real pipes/processes and loopback transport to verify executor protocol and ownership."""
    process = PipeProcess()
    executor = CodexExecutor(
        tmp_path / "candidate", tmp_path / "runtime", process_factory=lambda *_: process
    )
    descriptor = await executor.start()
    try:
        async with connect(
            descriptor["execServerUrl"],
            additional_headers={
                "Authorization": "Bearer " + descriptor["authBearerToken"],
            },
        ) as connection:
            await connection.send(payload)
            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(connection.recv(), 3)
    finally:
        await asyncio.wait_for(executor.close(), 5)
    assert process.closed


@pytest.mark.asyncio
async def test_malformed_executor_output_closes_process(tmp_path):
    """Use real pipes/processes and loopback transport to verify executor protocol and ownership."""
    process = PipeProcess(
        "import sys\nsys.stdin.readline()\nsys.stdout.write('invalid\\n');sys.stdout.flush()\nsys.stdin.read()"
    )
    executor = CodexExecutor(
        tmp_path / "candidate", tmp_path / "runtime", process_factory=lambda *_: process
    )
    descriptor = await executor.start()
    try:
        async with connect(
            descriptor["execServerUrl"],
            additional_headers={
                "Authorization": "Bearer " + descriptor["authBearerToken"],
            },
        ) as connection:
            await connection.send('{"method":"fixture"}')
            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(connection.recv(), 3)
    finally:
        await asyncio.wait_for(executor.close(), 5)
    assert process.closed


@pytest.mark.asyncio
async def test_only_executor_metadata_selects_working_windows_shell(tmp_path):
    """Use real pipes/processes and loopback transport to verify executor protocol and ownership."""
    code = """
import json, sys
for line in sys.stdin:
 request = json.loads(line)
 info = {'platformOs':'windows','shell':{'name':'powershell','path':'powershell.exe'},'cwd':'file:///workspace','capabilities':{'sandboxedFileStreaming':True}}
 result = {'environmentInfo': info, 'sessionId':'session'} if request['method'] == 'initialize' else info
 print(json.dumps({'id':request['id'],'result':result}), flush=True)
"""
    process = PipeProcess(code)
    executor = CodexExecutor(
        tmp_path / "candidate", tmp_path / "runtime", process_factory=lambda *_: process
    )
    descriptor = await executor.start()
    try:
        async with connect(
            descriptor["execServerUrl"],
            additional_headers={
                "Authorization": "Bearer " + descriptor["authBearerToken"],
            },
        ) as connection:
            for identity, method in enumerate(("initialize", "environment/info", "fixture")):
                await connection.send(json.dumps({"id": identity, "method": method, "params": {}}))
                response = json.loads(await asyncio.wait_for(connection.recv(), 3))
                info = (
                    response["result"]["environmentInfo"]
                    if method == "initialize"
                    else response["result"]
                )
                assert info["cwd"] == "file:///workspace"
                assert info["capabilities"] == {"sandboxedFileStreaming": True}
                if method == "fixture":
                    assert info["shell"]["name"] == "powershell"
                else:
                    assert info["shell"] == {
                        "name": "cmd",
                        "path": process.command_environment["COMSPEC"],
                    }
                assert not executor._metadata_requests
    finally:
        await asyncio.wait_for(executor.close(), 5)
