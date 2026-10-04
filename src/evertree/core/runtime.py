"""Task admission and isolated, durable execution of committed Programs."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
import zipfile
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from .backup import _extended
from .sandbox import SandboxedProcess, SandboxLimits, prepare_python

Gateway = Callable[[str, dict[str, Any]], Awaitable[Any]]
TraceCallback = Callable[[dict[str, Any]], Awaitable[None]]


class RuntimeBusy(RuntimeError):
    pass


class ProgramExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProgramSpec:
    program_id: str | int
    git_path: str
    revision: str
    entrypoint: str = "run"
    role: Literal["model", "exec"] = "exec"

    def __post_init__(self):
        path = Path(self.git_path)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".py":
            raise ValueError("git_path must be a relative Python file path")
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.revision):
            raise ValueError("Program revision must be an exact Git commit SHA")
        if not self.entrypoint.isidentifier() or self.role not in ("model", "exec"):
            raise ValueError("Invalid Program entrypoint or role")


@dataclass(frozen=True)
class RunResult:
    run_id: str
    result: Any
    feedback: str | None = None


def _validate_git_metadata(repository: Path, *, initializing: bool = False) -> Path:
    """Keep Git's authority inside this repository before Git reads any config."""
    metadata = repository / ".git"
    if not metadata.exists() and not metadata.is_symlink():
        if initializing:
            return metadata
        raise ProgramExecutionError("Managed repository is missing its .git directory")

    def reject_link(path: Path) -> None:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ProgramExecutionError(
                "Git metadata must not contain symbolic links or reparse points"
            )

    reject_link(metadata)
    if not metadata.is_dir():
        raise ProgramExecutionError("Managed repository requires a private .git directory")
    # Check each directory before os.walk can descend into it. This includes
    # object packs, refs, config files and nested metadata, not only .git itself.
    for directory, folders, files in os.walk(metadata, followlinks=False):
        for name in (*folders, *files):
            reject_link(Path(directory) / name)
    for relative in (
        "commondir",
        "gitdir",
        "objects/info/alternates",
        "objects/info/http-alternates",
        "info/grafts",
    ):
        if (metadata / relative).exists():
            raise ProgramExecutionError(
                "Git metadata must not redirect objects or repository state"
            )
    for name in ("config", "config.worktree"):
        config = metadata / name
        if config.exists():
            contents = config.read_text(encoding="utf-8-sig", errors="replace")
            if re.search(r"(?im)^\s*\[\s*include(?:if)?(?:\s|\.|\])", contents):
                raise ProgramExecutionError("Git configuration includes are not allowed")
    return metadata


def _git(repository: Path, *arguments: str) -> bytes:
    # Candidate repositories contain untrusted .git/config and hooks. Git is
    # used as an object reader here, never as a way to execute their commands.
    if arguments and arguments[0] == "diff":
        arguments = ("diff", "--no-ext-diff", "--no-textconv", *arguments[1:])
    repository = Path(repository).absolute()
    metadata = _validate_git_metadata(
        repository, initializing=bool(arguments and arguments[0] == "init")
    )
    if arguments and arguments[0] == "init":
        arguments = ("init", "--template=", *arguments[1:])
    command = [
        "git",
        "-C",
        str(repository),
        "--git-dir=" + str(metadata),
        "--work-tree=" + str(repository),
        "-c",
        "core.hooksPath=",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.pager=",
        "-c",
        "commit.gpgSign=false",
        "-c",
        "tag.gpgSign=false",
        "-c",
        "core.attributesFile=" + os.devnull,
        "-c",
        "core.excludesFile=" + os.devnull,
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.file.allow=always",
        "-c",
        "transfer.fsckObjects=true",
        "-c",
        "fetch.fsckObjects=true",
        "-c",
        "fsck.skipList=" + os.devnull,
        "-c",
        "fetch.fsck.skipList=" + os.devnull,
    ]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
    )
    if arguments and arguments[0] in {
        "add",
        "status",
        "diff",
        "checkout",
        "switch",
        "merge",
        "reset",
        "commit",
    }:
        filters = subprocess.run(
            [
                *command,
                "config",
                "--name-only",
                "--get-regexp",
                r"^filter\..*\.(clean|smudge|process|required)$",
            ],
            capture_output=True,
            check=False,
            env=environment,
        )
        if filters.returncode not in (0, 1):
            raise ProgramExecutionError(filters.stderr.decode("utf-8", errors="replace").strip())
        for prefix in {
            name.rsplit(".", 1)[0] for name in filters.stdout.decode("utf-8").splitlines()
        }:
            for operation in ("clean", "smudge", "process"):
                command.extend(("-c", prefix + "." + operation + "="))
            command.extend(("-c", prefix + ".required=false"))
    result = subprocess.run(
        [*command, *arguments], capture_output=True, check=False, env=environment
    )
    if result.returncode:
        raise ProgramExecutionError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def extract_revision(repository: Path, revision: str, destination: Path) -> None:
    destination = _extended(destination)
    resolved = _git(repository, "rev-parse", "--verify", revision + "^{commit}").decode().strip()
    if resolved != revision:
        raise ValueError("An exact commit is required")
    archive = _git(repository, "archive", "--format=zip", revision)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        root = destination.resolve()
        for info in source.infolist():
            target = (root / info.filename).resolve()
            if (
                not target.is_relative_to(root)
                or ((info.external_attr >> 16) & 0o170000) == 0o120000
            ):
                raise ValueError("Program checkout contains an unsafe path or symbolic link")
        source.extractall(root)


class Runtime:
    """A core controller, with one admitted task and no implicit unsafe execution.

    ``gateway`` owns semantic validation, protected graph updates and approvals.
    Every call carries runtime-owned ``_runtime`` metadata. Test code may inject
    a process factory; the application always uses the native sandbox by default.
    """

    def __init__(
        self,
        state_dir: Path,
        repository: Path,
        gateway: Gateway,
        trace: TraceCallback | None = None,
        *,
        limits: SandboxLimits | None = None,
        process_factory: Callable[..., Any] | None = None,
        python_cache: Path | None = None,
    ) -> None:
        self.state_dir = Path(state_dir).resolve()
        self.repository = Path(repository).resolve()
        self.gateway, self.trace, self.limits = gateway, trace, limits or SandboxLimits()
        self._factory = process_factory or SandboxedProcess
        self._native = process_factory is None
        self.python_cache = (
            Path(python_cache).resolve() if python_cache else self.state_dir / "python"
        )
        self._admission = asyncio.Lock()
        self._active: dict[str, Any] | None = None
        self._final_tasks: set[str] = set()
        self._closed = False
        self._pause_requested = False
        self._gate = asyncio.Event()
        self._gate.set()
        self._paused = asyncio.Event()
        self._gateway_active = 0
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def is_running(self, task_id: str | None = None) -> bool:
        active = self._active
        return bool(active and (task_id is None or active["task_id"] == task_id))

    async def _trace(self, event: dict) -> None:
        if self.trace:
            await self.trace(event)

    async def execute(
        self,
        task_id: str,
        program: ProgramSpec,
        arguments: Mapping[str, Any],
        *,
        timeout: float = 300,
        run_mode: Literal["live", "evaluation", "simulation"] = "live",
        run_id: str | None = None,
    ) -> RunResult:
        if self._closed or task_id in self._final_tasks:
            raise ProgramExecutionError("Task is finalized or runtime is closed")
        if timeout <= 0 or run_mode not in ("live", "evaluation", "simulation"):
            raise ValueError("Invalid execution timeout or mode")
        if self._admission.locked() or self._active is not None:
            raise RuntimeBusy("The current task execution tree must stop before another starts")
        async with self._admission:
            await self._gate.wait()
            if self._closed or task_id in self._final_tasks:
                raise ProgramExecutionError("Task is finalized or runtime is closed")
            run_id = run_id or uuid.uuid4().hex
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
                raise ValueError("Invalid run ID")
            run_dir = self.state_dir / "runs" / run_id
            source_dir, scratch_dir = _extended(run_dir / "source"), run_dir / "scratch"
            if not source_dir.exists():
                await asyncio.to_thread(
                    extract_revision, self.repository, program.revision, source_dir
                )
            scratch_dir.mkdir(parents=True, exist_ok=True)
            journal = scratch_dir / "dbos.sqlite"
            configuration = {
                "task_id": task_id,
                "run_id": run_id,
                "run_mode": run_mode,
                "revision": program.revision,
                "program": asdict(program),
                "arguments": dict(arguments),
                "checkout": str(source_dir),
                "journal": str(journal),
                "executor_id": "run-" + run_id,
            }
            configuration_path = run_dir / "worker.json"
            if configuration_path.exists():
                previous = json.loads(configuration_path.read_text(encoding="utf-8"))
                if previous != configuration:
                    raise ProgramExecutionError(
                        "Resume must preserve code, arguments, task and mode"
                    )
            else:
                configuration_path.write_text(
                    json.dumps(configuration, allow_nan=False), encoding="utf-8"
                )
            worker_source = run_dir / "worker.py"
            if not worker_source.exists():
                shutil.copy2(Path(__file__).with_name("worker.py"), worker_source)
            known_runs_path = run_dir / "core_runs.json"
            known_runs = (
                json.loads(known_runs_path.read_text(encoding="utf-8"))
                if known_runs_path.exists()
                else {}
            )
            self._active = {
                "task_id": task_id,
                "run_id": run_id,
                "journal": journal,
                "program": program,
                "run_mode": run_mode,
                "process": None,
                "known_runs": known_runs,
                "cancelled": False,
                "run_dir": run_dir,
            }
            process = None
            reader_task = stderr_task = None
            try:
                if self._native:
                    executable = await asyncio.to_thread(prepare_python, self.python_cache)
                else:
                    executable = Path(sys.executable)
                if self._active["cancelled"]:
                    raise ProgramExecutionError("Task cancelled before worker startup")
                startup = asyncio.create_task(
                    asyncio.to_thread(
                        self._factory,
                        executable,
                        ["-I", "-u", str(worker_source), str(configuration_path)],
                        workdir=scratch_dir,
                        readable=(executable.parent, run_dir),
                        writable=(scratch_dir,),
                        limits=self.limits,
                    )
                )
                try:
                    process = await asyncio.shield(startup)
                except asyncio.CancelledError:
                    # to_thread cannot cancel CreateProcess. Acquire the returned
                    # handles so finally always owns and stops that worker.
                    process = await startup
                    raise
                self._active["process"] = process
                if self._active["cancelled"]:
                    await asyncio.to_thread(process.terminate)
                    raise ProgramExecutionError("Task cancelled during worker startup")
                stderr_task = asyncio.create_task(
                    self._read_stderr(process, run_dir / "stderr.log")
                )
                reader_task = asyncio.create_task(self._read_protocol(process))
                self._active["reader_task"] = reader_task
                result = await asyncio.wait_for(asyncio.shield(reader_task), timeout)
                return RunResult(run_id, result["result"], result.get("feedback"))
            except TimeoutError as exc:
                raise ProgramExecutionError(f"Execution exceeded {timeout:g} seconds") from exc
            except asyncio.CancelledError as exc:
                if self._active and self._active["cancelled"]:
                    raise ProgramExecutionError("Task execution cancelled") from exc
                raise
            finally:
                if process is not None:
                    await asyncio.to_thread(process.close)
                if reader_task:
                    reader_task.cancel()
                    await asyncio.gather(reader_task, return_exceptions=True)
                if stderr_task:
                    await asyncio.gather(stderr_task, return_exceptions=True)
                self._active = None
                if self._pause_requested:
                    self._paused.set()

    async def _read_stderr(self, process, destination):
        with destination.open("wb") as output:
            while True:
                try:
                    chunk = await asyncio.to_thread(process.stderr.read, 4096)
                except (OSError, ValueError):
                    return
                if not chunk:
                    return
                output.write(chunk)
                output.flush()

    async def _read_protocol(self, process):
        while True:
            line = await asyncio.to_thread(process.stdout.readline, 8 * 1024 * 1024)
            if not line:
                raise ProgramExecutionError(
                    "Worker stopped without a result; inspect its stderr.log"
                )
            try:
                message = json.loads(line)
            except ValueError as exc:
                raise ProgramExecutionError("Invalid worker protocol") from exc
            if not isinstance(message, dict):
                raise ProgramExecutionError("Invalid worker message")
            kind = message.get("type")
            if kind == "ready":
                continue
            if kind == "boundary":
                active = self._active
                if active is not None:
                    active["waiting"] = message.get("state") == "waiting"
                    if active["waiting"] and self._pause_requested and not self._gateway_active:
                        self._paused.set()
                continue
            if kind == "result":
                return message
            if kind == "error":
                raise ProgramExecutionError(message.get("error", "Worker execution failed"))
            if kind != "request" or message.get("method") != "gateway":
                raise ProgramExecutionError("Unknown worker request")
            request_id = message.get("id")
            if not isinstance(request_id, str):
                raise ProgramExecutionError("Request has no identity")
            try:
                value = await self._dispatch(message["payload"])
                response = {"id": request_id, "result": value}
                encoded = json.dumps(response, allow_nan=False).encode("utf-8") + b"\n"
            except Exception as exc:  # noqa: BLE001 -- cross-process error boundary
                encoded = (
                    json.dumps({"id": request_id, "error": f"{type(exc).__name__}: {exc}"}).encode(
                        "utf-8"
                    )
                    + b"\n"
                )
            await asyncio.to_thread(process.stdin.write, encoded)
            await asyncio.to_thread(process.stdin.flush)

    async def _dispatch(self, request):
        if self._pause_requested:
            self._paused.set()
        await self._gate.wait()
        active = self._active
        if active is None or active["cancelled"]:
            raise ProgramExecutionError("Task is no longer admitted")
        if not isinstance(request, dict):
            raise TypeError("Gateway request must be an object")
        active["waiting"] = False
        method, run_id = request["method"], request["run_id"]
        if method == "run_started":
            spec = ProgramSpec(**request["program"])
            if spec.revision != active["program"].revision:
                raise PermissionError("Worker requested another executable revision")
        else:
            if "program" in request:
                raise PermissionError("Program metadata is only accepted when registering a run")
            if run_id not in active["known_runs"]:
                raise PermissionError("Workflow is not admitted by protected core")
            spec = ProgramSpec(**active["known_runs"][run_id])
        payload = dict(request.get("payload", {}))
        trace_arguments = json.loads(
            json.dumps(
                {
                    key: value
                    for key, value in payload.items()
                    if key not in {"_runtime", "_execution"}
                },
                allow_nan=False,
            )
        )
        if not isinstance(method, str) or method.startswith("_"):
            raise PermissionError("Invalid gateway method")
        metadata = {
            "task_id": active["task_id"],
            "run_id": run_id,
            "run_mode": active["run_mode"],
            "program": asdict(spec),
        }
        source_line = request.get("source_line")
        if isinstance(source_line, int) and not isinstance(source_line, bool):
            from .anchors import parse_anchors

            cache = active.setdefault("anchors", {})
            if spec.git_path not in cache:
                source = (_extended(active["run_dir"] / "source") / spec.git_path).read_text(
                    encoding="utf-8"
                )
                cache[spec.git_path] = parse_anchors(
                    source,
                    code_node_id=spec.program_id,
                    git_path=spec.git_path,
                    commit_sha=spec.revision,
                )
            anchor = next(
                (
                    item
                    for item in cache[spec.git_path]
                    if item.line in {source_line, source_line - 1}
                ),
                None,
            )
            if anchor:
                metadata["anchor"] = anchor.op_id
                metadata["source_line"] = anchor.line
        self._gateway_active += 1
        try:
            if method == "run_started":
                parent = payload.get("parent_run_id")
                if parent is not None and parent not in active["known_runs"]:
                    raise PermissionError("Child workflow parent is not admitted")
                if parent is None and run_id != active["run_id"]:
                    raise PermissionError("Unknown root workflow")
                if parent is None and spec != active["program"]:
                    raise PermissionError("Worker changed the admitted root Program")
                if parent is not None:
                    resolved = await self.gateway(
                        "resolve_program",
                        {
                            "program_id": spec.program_id,
                            "_runtime": {
                                "task_id": active["task_id"],
                                "run_id": parent,
                                "run_mode": active["run_mode"],
                                "program": active["known_runs"][parent],
                            },
                        },
                    )
                    if isinstance(resolved, ProgramSpec):
                        resolved = asdict(resolved)
                    if ProgramSpec(**resolved) != spec:
                        raise PermissionError("Child Program does not match core registry")
                if (
                    parent
                    and active["known_runs"][parent]["role"] == "model"
                    and spec.role != "model"
                ):
                    raise PermissionError("A model Program cannot call exec")
                if run_id in active["known_runs"] and active["known_runs"][run_id] != asdict(spec):
                    raise PermissionError("Worker changed an already registered Program")
                active["known_runs"][run_id] = asdict(spec)
                (active["run_dir"] / "core_runs.json").write_text(
                    json.dumps(active["known_runs"]), encoding="utf-8"
                )
                await self._trace(
                    {
                        "arguments": payload.get("arguments", {}),
                        "parent_run_id": parent,
                        "type": method,
                        **metadata,
                    }
                )
                return None
            if method in ("run_finished", "run_failed", "trace"):
                fields = {
                    "run_finished": ("result",),
                    "run_failed": ("error",),
                    "trace": ("operator", "arguments", "output"),
                }[method]
                await self._trace(
                    {
                        **{key: payload[key] for key in fields if key in payload},
                        "type": method,
                        **metadata,
                    }
                )
                return None
            if method == "checkpoint":
                return None
            if spec.role == "model" and method in (
                "take_action",
                "actions.take",
                "action",
                "mutate_graph",
                "graph.apply",
                "update_parameters",
                "send_message",
                "respond",
                "llm_code",
            ):
                raise PermissionError("Model Program requested an effect")
            if active["run_mode"] != "live" and method in (
                "take_action",
                "actions.take",
                "action",
                "send_message",
                "respond",
            ):
                raise PermissionError("Live effects are unavailable in evaluation and simulation")
            if method == "agent.run" and spec.role == "model":
                payload["mode"] = "model"
            payload.pop("_execution", None)
            payload["_runtime"] = metadata
            result = await self.gateway(method, payload)
            result = asdict(result) if isinstance(result, ProgramSpec) else result
            await self._trace(
                {
                    "type": "trace",
                    **metadata,
                    "operator": method,
                    "arguments": trace_arguments,
                    "output": result,
                }
            )
            return result
        except Exception as error:
            if run_id in active["known_runs"] and method not in {
                "run_started",
                "run_finished",
                "run_failed",
                "trace",
            }:
                await self._trace(
                    {
                        "type": "trace",
                        **metadata,
                        "operator": method,
                        "arguments": trace_arguments,
                        "status": "failed",
                        "output": {"error": f"{type(error).__name__}: {error}"},
                    }
                )
            raise
        finally:
            self._gateway_active -= 1

    async def deliver(self, run_id: str, observation: Any, *, observation_id: str | None = None):
        await self._gate.wait()
        active = self._active
        if active is None or run_id not in {active["run_id"], *active["known_runs"]}:
            raise ProgramExecutionError("Observation recipient is not an admitted run")
        from dbos import DBOSClient

        client = DBOSClient(system_database_url="sqlite:///" + str(active["journal"]))
        try:
            await client.send_async(
                run_id,
                observation,
                "observations",
                idempotency_key=observation_id or uuid.uuid4().hex,
            )
        finally:
            client.destroy()

    async def cancel(self, task_id: str, *, finalize: bool = True) -> None:
        if finalize:
            self._final_tasks.add(task_id)
        active = self._active
        if active is None or active["task_id"] != task_id:
            return
        active["cancelled"] = True
        self._gate.set()
        process = active.get("process")
        if process:
            await asyncio.to_thread(process.terminate)
        if active.get("reader_task"):
            active["reader_task"].cancel()
        # Also wait for startup or an in-flight gateway call to unwind. A task
        # is not stopped until its admission slot can safely be reused.
        async with self._admission:
            pass
        await self._trace({"type": "task_stopped", "task_id": task_id, "run_id": active["run_id"]})

    async def finish_task(self, task_id: str):
        await self.cancel(task_id, finalize=True)

    @asynccontextmanager
    async def quiesce(self, timeout: float = 10):
        """Pause before a subsequent durable operation; refuse an unsafe backup.

        Reaching a new gateway request proves prior steps have returned to DBOS.
        A worker blocked in observation reception also has no mutable core work.
        If no operation boundary arrives, defer the backup rather than copy a
        journal while core effects may be unrecorded.
        """
        self._pause_requested = True
        self._gate.clear()
        self._paused.clear()
        if self._active is None or (self._active.get("waiting") and not self._gateway_active):
            self._paused.set()
        try:
            await asyncio.wait_for(self._paused.wait(), timeout)
            if self._gateway_active:
                raise RuntimeError("Gateway operation has not quiesced")
            yield
        finally:
            self._pause_requested = False
            self._gate.set()
            self._paused.clear()

    def snapshot(self):
        return {
            "final_tasks": sorted(self._final_tasks),
            "active": None
            if self._active is None
            else {
                "task_id": self._active["task_id"],
                "run_id": self._active["run_id"],
                "configuration": str(self._active["run_dir"] / "worker.json"),
            },
        }

    def restore(self, snapshot):
        if self._active:
            raise RuntimeError("Cannot restore a running runtime")
        self._final_tasks = set(snapshot.get("final_tasks", ()))

    async def close(self):
        self._closed = True
        if self._active:
            await self.cancel(self._active["task_id"], finalize=False)
