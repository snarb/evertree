"""Register macOS exec-server command groups before executing their payloads."""

from __future__ import annotations

import json
import os
import socket
import struct
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

from .job import MacProcessGroup

_LAUNCHER = """
import json, os, socket, sys
with socket.socket(socket.AF_UNIX) as channel:
    channel.settimeout(10)
    channel.connect(sys.argv[1])
    channel.sendall((sys.argv[2] + '\\n').encode())
    if channel.recv(1) != b'1':
        sys.exit(125)
argv = sys.argv[4:]
executable = argv[0]
arg0 = json.loads(sys.argv[3])
if arg0 is not None:
    argv[0] = arg0
os.execvpe(executable, argv, os.environ)
"""


class MacCommandGroups:
    """Small launch handshake, not a background process/resource monitor.

    exec-server creates a separate session for each command, so its own process
    group cannot stop command descendants. The socket's kernel peer PID gives
    the owner the real command group, rather than accepting a supplied PID.
    """

    def __init__(self, python: Path):
        self.python = python
        # Darwin's Unix socket paths are limited to 104 bytes, regardless of cache depth.
        self._directory = tempfile.TemporaryDirectory(prefix="evertree-", dir="/private/tmp")
        self.path = Path(self._directory.name) / "groups.sock"
        self._server = socket.socket(socket.AF_UNIX)
        self._server.bind(str(self.path))
        self._server.listen()
        self._server.settimeout(0.1)
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._commands = {}
        self._groups = {}
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def wrap(self, process_id: str, argv: list[str], arg0) -> list[str]:
        nonce = uuid4().hex
        with self._lock:
            if self._closed.is_set():
                raise RuntimeError("Executor command owner is closed")
            self._commands[nonce] = process_id
        return [
            str(self.python),
            "-I",
            "-S",
            "-c",
            _LAUNCHER,
            str(self.path),
            nonce,
            json.dumps(arg0),
            *argv,
        ]

    def _accept(self):
        while not self._closed.is_set():
            try:
                peer, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with peer:
                try:
                    peer.settimeout(2)
                    request = b""
                    while len(request) <= 32 and not request.endswith(b"\n"):
                        block = peer.recv(33 - len(request))
                        if not block:
                            break
                        request += block
                    nonce = request.decode("ascii").strip()
                    # SOL_LOCAL / LOCAL_PEERPID; this identity comes from the kernel.
                    pid = struct.unpack("i", peer.getsockopt(0, 2, 4))[0]
                    with self._lock:
                        if (
                            self._closed.is_set()
                            or nonce not in self._commands
                            or nonce in self._groups
                            or os.getpgid(pid) != pid
                        ):
                            continue
                        self._groups[nonce] = MacProcessGroup(pid)
                        peer.sendall(b"1")
                except (OSError, UnicodeError):
                    continue

    def release(self, process_id: str):
        with self._lock:
            for nonce, identity in list(self._commands.items()):
                if identity == process_id:
                    group = self._groups.pop(nonce, None)
                    if group:
                        group.close()
                    del self._commands[nonce]

    def close(self):
        with self._lock:
            if self._closed.is_set():
                return
            self._closed.set()
            for group in self._groups.values():
                group.close()
            self._groups.clear()
            self._commands.clear()
        self._server.close()
        self._thread.join(timeout=3)
        self._directory.cleanup()
