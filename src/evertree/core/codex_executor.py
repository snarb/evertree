"""Authenticated loopback transport for an AppContainer-owned Codex executor.

The SDK harness keeps account credentials on the trusted host. Its native tools
use an external execution environment whose server has only stdio handles and
the filesystem rights granted by ``sandbox.start_exec_server``. This bridge
transports JSON-RPC; it never executes a command or accesses a requested path.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
from collections import deque
from http import HTTPStatus
from pathlib import Path
from typing import Any
from uuid import uuid4

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

_MAX_FRAME = 16 * 1024 * 1024
_STDERR_BLOCK = 4096
_CMD_SHIM = """import subprocess, sys
command = '"' + sys.argv[1] + '" /d /s /c "' + sys.argv[2] + '"'
sys.exit(subprocess.call(command, executable=sys.argv[1], shell=False))
"""


def _frame(value: str | bytes) -> str:
    """One WebSocket message maps to one newline-delimited JSON-RPC object."""
    message = json.loads(value)
    if not isinstance(message, dict):
        raise TypeError("Executor transport requires a JSON-RPC object")
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class CodexExecutor:
    def __init__(self, workspace: Path, state_dir: Path, *, process_factory=None):
        self.workspace = Path(workspace).resolve()
        self.state_dir = Path(state_dir).resolve()
        if self.state_dir == self.workspace or self.state_dir.is_relative_to(self.workspace):
            raise ValueError("Executor runtime must be outside its writable workspace")
        self.environment_id = "evertree-" + uuid4().hex
        self._token = secrets.token_urlsafe(32)
        self._factory = process_factory
        self._process = None
        self._server = None
        self._connection = None
        self._stderr_task = None
        self._stderr_tail: deque[bytes] = deque(maxlen=8)
        self._process_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._closing = False
        self._closed = False
        self._started = False
        self._close_task = None
        self._metadata_requests: dict[str | int, str] = {}

    @property
    def environment(self) -> dict[str, Any]:
        return {
            "environmentId": self.environment_id,
            "cwd": str(self.workspace),
            "runtimeWorkspaceRoots": [str(self.workspace)],
        }

    @property
    def command_environment(self) -> dict[str, str]:
        if self._process is None:
            raise RuntimeError("Executor is not running")
        return dict(self._process.command_environment)

    async def start(self) -> dict[str, Any]:
        if self._started or self._closed:
            raise RuntimeError("Executor may be started only once")
        self._started = True
        if self._factory is None:
            from .sandbox import start_exec_server

            factory = start_exec_server
        else:
            factory = self._factory
        startup = asyncio.create_task(asyncio.to_thread(factory, self.state_dir, self.workspace))
        try:
            self._process = await asyncio.shield(startup)
        except asyncio.CancelledError:
            # A background startup may already have created its OS process.
            # Await ownership even on cancellation, then tear it down.
            try:
                process = await startup
                await asyncio.to_thread(process.close)
            finally:
                self._closed = True
            raise
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._process.stderr))
        try:
            self._server = await serve(
                self._handle,
                "127.0.0.1",
                0,
                process_request=self._authorize,
                max_size=_MAX_FRAME,
                max_queue=16,
                compression=None,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=2,
            )
        except BaseException:
            await self.close()
            raise
        port = self._server.sockets[0].getsockname()[1]
        return {
            "environmentId": self.environment_id,
            "execServerUrl": f"ws://127.0.0.1:{port}/",
            "authBearerToken": self._token,
        }

    def _authorize(self, connection: ServerConnection, request):
        # A web page cannot claim an executor connection, even if it discovers
        # the port. The per-invocation capability is never put in a URL or log.
        values = request.headers.get_all("Authorization")
        expected = "Bearer " + self._token
        if (
            request.path != "/"
            or request.headers.get_all("Origin")
            or len(values) != 1
            or not hmac.compare_digest(values[0].encode("utf-8"), expected.encode("ascii"))
        ):
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized executor connection\n")
        if self._connection is not None or self._closing:
            return connection.respond(
                HTTPStatus.CONFLICT, "Executor connection is already in use\n"
            )
        return None

    async def _drain_stderr(self, stream):
        try:
            while chunk := await asyncio.to_thread(stream.read, _STDERR_BLOCK):
                self._stderr_tail.append(chunk)
        except (OSError, ValueError):
            return

    async def _receive(self, connection, process):
        async for value in connection:
            frame = _frame(value)
            message = json.loads(frame)
            if message.get("method") in {"initialize", "environment/info"} and "id" in message:
                self._metadata_requests[message["id"]] = message["method"]
            params = message.get("params")
            if message.get("method") == "process/start" and isinstance(params, dict):
                argv = params.get("argv")
                if (
                    isinstance(argv, list)
                    and len(argv) == 3
                    and argv[0] == process.command_environment["COMSPEC"]
                    and argv[1] == "/c"
                    and isinstance(argv[2], str)
                    and params.get("arg0") is None
                ):
                    # Codex 0.160 applies CRT argument quoting to the complete
                    # CMD /c string, corrupting its nested double quotes. Python
                    # accepts CRT argv and forwards an exact raw Windows command
                    # line. Both interpreters are children of the AppContainer
                    # executor, with unchanged stdio, cwd, env and process Job.
                    params["argv"] = [
                        str(process.shell_python),
                        "-I",
                        "-S",
                        "-c",
                        _CMD_SHIM,
                        argv[0],
                        argv[2],
                    ]
                    frame = json.dumps(
                        message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    )
            packet = (frame + "\n").encode("utf-8")
            await asyncio.to_thread(self._write, process.stdin, packet)

    @staticmethod
    def _write(stream, packet):
        stream.write(packet)
        stream.flush()

    async def _send(self, connection, process):
        while True:
            line = await asyncio.to_thread(process.stdout.readline, _MAX_FRAME + 1)
            if not line:
                return
            if len(line) > _MAX_FRAME or not line.endswith(b"\n"):
                raise ValueError("Invalid or oversized executor output frame")
            frame = _frame(line)
            message = json.loads(frame)
            if "id" in message and (method := self._metadata_requests.pop(message["id"], None)):
                result = message.get("result")
                if isinstance(result, dict):
                    info = result.get("environmentInfo") if method == "initialize" else result
                    if isinstance(info, dict) and info.get("platformOs") == "windows":
                        # Windows PowerShell 5's filesystem provider fails its
                        # DOS path normalization inside this AppContainer.
                        # cmd.exe can launch programs with the same OS token.
                        # Codex permits only the executor-advertised default shell
                        # for remote tools, so select this supported shell here.
                        info["shell"] = {
                            "name": "cmd",
                            "path": process.command_environment["COMSPEC"],
                        }
                        frame = json.dumps(
                            message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                        )
            await connection.send(frame)

    async def _handle(self, connection: ServerConnection):
        # Recheck after the handshake so simultaneous authorized upgrades cannot
        # both obtain the sole executor stream.
        if self._connection is not None or self._closing or self._process is None:
            await connection.close(code=1008, reason="Executor unavailable")
            return
        self._connection = connection
        process = self._process
        relay = [
            asyncio.create_task(self._receive(connection, process)),
            asyncio.create_task(self._send(connection, process)),
        ]
        try:
            done, _ = await asyncio.wait(relay, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (OSError, TypeError, ValueError, ConnectionClosed):
            await connection.close(code=1011, reason="Executor transport failed")
        finally:
            # Closing the OS owner kills all descendants and unblocks every
            # pending pipe read before their asyncio wrappers are cancelled.
            await self._stop_process()
            for task in relay:
                task.cancel()
            await asyncio.gather(*relay, return_exceptions=True)
            self._connection = None
            if not self._closing:
                self._close_task = asyncio.create_task(self.close())

    async def _stop_process(self):
        async with self._process_lock:
            if self._process is not None:
                process, self._process = self._process, None
                await asyncio.to_thread(process.close)

    async def close(self):
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            try:
                await self._stop_process()
            finally:
                if self._server is not None:
                    self._server.close()
                    await self._server.wait_closed()
                if self._stderr_task is not None:
                    await asyncio.gather(self._stderr_task, return_exceptions=True)
                self._closed = True

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *_):
        await self.close()
