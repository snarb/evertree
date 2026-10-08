"""Real executor command lifetime across macOS process-group boundaries."""

import asyncio
import base64
import json
import os
import signal
import subprocess
import sys

import pytest
from websockets.asyncio.client import connect

from evertree.core.codex.executor import CodexExecutor

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS executor process groups")


@pytest.mark.parametrize(
    "inherit_output", [False, True], ids=["detached-output", "inherited-output"]
)
@pytest.mark.parametrize("finish", [False, True], ids=["cancel", "complete"])
async def test_executor_stops_command_descendants(tmp_path, inherit_output, finish):
    """Real command exit must kill descendants before inherited pipes or the executor close."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    started = workspace / "started.json"
    (workspace / "wait.py").write_text(
        "import json, os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(100)'], "
        + (
            "close_fds=True)\n"
            if inherit_output
            else "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        )
        + "Path('started.json').write_text(json.dumps([os.getpid(), child.pid]))\n"
        + ("print('final output', flush=True)\n" if finish else "time.sleep(100)\n")
    )
    executor = CodexExecutor(workspace, tmp_path / "state")
    pids = []
    try:
        descriptor = await executor.start()
        async with connect(
            descriptor["execServerUrl"],
            additional_headers={"Authorization": "Bearer " + descriptor["authBearerToken"]},
        ) as connection:
            sequence = 0

            async def request(method, params, *, expect_error=False):
                nonlocal sequence
                sequence += 1
                await connection.send(
                    json.dumps({"id": sequence, "method": method, "params": params})
                )
                async with asyncio.timeout(15):
                    while True:
                        response = json.loads(await connection.recv())
                        if response.get("id") == sequence:
                            if expect_error:
                                assert response["error"]["code"] == -32602
                                assert "tty=false" in response["error"]["message"]
                                return
                            assert "error" not in response, response
                            return response["result"]

            await request("initialize", {"clientName": "evertree-lifetime-test"})
            await connection.send(json.dumps({"method": "initialized", "params": {}}))
            if finish and inherit_output:
                await request(
                    "process/start",
                    {"processId": "pty", "argv": ["/bin/zsh", "-c", "exit 0"], "tty": True},
                    expect_error=True,
                )
            await request(
                "process/start",
                {
                    "processId": "waiting",
                    "argv": ["/bin/zsh", "-c", "python -I wait.py"],
                    "cwd": workspace.as_uri(),
                    "env": executor.command_environment,
                    "tty": False,
                    "pipeStdin": False,
                    "arg0": None,
                    "sandbox": None,
                },
            )
            async with asyncio.timeout(15):
                while not started.exists():
                    await asyncio.sleep(0.01)
            pids = json.loads(started.read_text())
            if finish:
                async with asyncio.timeout(15):
                    while True:
                        result = await request(
                            "process/read",
                            {
                                "processId": "waiting",
                                "afterSeq": None,
                                "maxBytes": 65536,
                                "waitMs": 1000,
                            },
                        )
                        if result["closed"]:
                            assert result["exitCode"] == 0
                            output = b"".join(
                                base64.b64decode(chunk["chunk"])
                                for chunk in result["chunks"]
                                if chunk["stream"] == "stdout"
                            )
                            assert output == b"final output\n"
                            break
            if not finish:
                await executor.close()
            for pid in pids:
                status = (
                    await asyncio.to_thread(
                        subprocess.run,
                        ["/bin/ps", "-p", str(pid), "-o", "stat="],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                ).stdout.strip()
                assert not status or status.startswith("Z"), (
                    f"Executor left PID {pid} alive ({status})"
                )
    finally:
        await executor.close()
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
