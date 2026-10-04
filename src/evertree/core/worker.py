"""Private worker entrypoint. Its stdout is a JSON protocol, never Python objects.

Run only through Runtime; all authority and external credentials remain in core.
"""

from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import importlib.util
import inspect
import json
import sys
import threading
import traceback
import uuid
from pathlib import Path

from evertree.core.contracts import ProgramResult

_wire = sys.stdout
sys.stdout = sys.stderr
_send_lock = threading.Lock()
_pending: dict[str, asyncio.Future] = {}
_loop: asyncio.AbstractEventLoop | None = None
_configuration: dict = {}
_current = contextvars.ContextVar("evertree_program")
_programs: dict[tuple[str, str], object] = {}


def json_value(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Program output is not JSON serializable: {type(value).__name__}")


def send(message):
    with _send_lock:
        _wire.write(json.dumps(json_value(message), ensure_ascii=False, allow_nan=False) + "\n")
        _wire.flush()


def _reader():
    for line in sys.stdin:
        try:
            response = json.loads(line)
        except (ValueError, TypeError):
            continue
        _complete(response)
    if _loop is not None:
        _loop.call_soon_threadsafe(_disconnect)


def _complete(message):
    future = _pending.pop(message.get("id"), None)
    if future is None or future.done():
        return

    def finish():
        if future.done():
            return
        if "error" in message:
            future.set_exception(RuntimeError(message["error"]))
        else:
            future.set_result(message.get("result"))

    future.get_loop().call_soon_threadsafe(finish)


def _disconnect():
    for future in list(_pending.values()):
        if not future.done():
            future.get_loop().call_soon_threadsafe(
                future.set_exception, RuntimeError("Protected core disconnected")
            )
    _pending.clear()


async def rpc(method, payload):
    request_id = uuid.uuid4().hex
    future = asyncio.get_running_loop().create_future()
    _pending[request_id] = future
    send({"type": "request", "id": request_id, "method": method, "payload": payload})
    return await future


class Context:
    def __init__(self, spec, run_id):
        self.program, self.run_id = spec, run_id
        self.task_id = _configuration["task_id"]
        self.run_mode = _configuration["run_mode"]

    async def step(self, method: str, payload: dict | None = None):
        """Durable gateway operation, including LLM, graph reads and effects."""
        if not isinstance(method, str) or method.startswith("_"):
            raise ValueError("Invalid gateway method")
        frame = inspect.currentframe().f_back
        source_line = None
        if (
            Path(frame.f_code.co_filename).resolve()
            == (Path(_configuration["checkout"]) / self.program["git_path"]).resolve()
        ):
            source_line = frame.f_lineno
        del frame
        return await gateway_step(self.run_id, method, payload or {}, source_line)

    async def call(self, program, arguments: dict | None = None):
        """A child workflow, deliberately called outside a DBOS step."""
        spec = json_value(program)
        if isinstance(spec, (str, int)) and not isinstance(spec, bool):
            spec = await self.step("resolve_program", {"program_id": spec})
        if not isinstance(spec, dict):
            raise TypeError("Child program must be a ProgramSpec or program identifier")
        if spec.get("revision") != _configuration["revision"]:
            raise ValueError(
                "Cross-revision child requires explicit replacement of the execution tree"
            )
        if self.program["role"] == "model" and spec.get("role", "exec") != "model":
            raise PermissionError("A model Program cannot call exec")
        result = await program_workflow(spec, arguments or {}, self.run_id)
        return ProgramResult(result["result"], result.get("feedback"))

    async def next_observation(self, timeout_seconds: float = 60):
        if self.program["role"] != "exec":
            raise PermissionError("A model Program cannot receive observations")
        send({"type": "boundary", "state": "waiting", "run_id": self.run_id})
        try:
            return await DBOS.recv_async("observations", timeout_seconds=timeout_seconds)
        finally:
            send({"type": "boundary", "state": "running", "run_id": self.run_id})

    async def emit(self, operator: str, *, arguments=None, output=None):
        return await self.step(
            "trace",
            {"operator": operator, "arguments": arguments or {}, "output": json_value(output)},
        )

    async def checkpoint(self):
        return await self.step("checkpoint", {})


def load_program(spec):
    root = Path(_configuration["checkout"]).resolve()
    path = (root / spec["git_path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix != ".py":
        raise ValueError("Program path must be a Python file in the committed checkout")
    if spec["revision"] != _configuration["revision"]:
        raise ValueError("Program revision does not match worker revision")
    entrypoint = spec.get("entrypoint", "run")
    key = (str(path), entrypoint)
    if key not in _programs:
        relative = path.relative_to(root).with_suffix("").parts
        if relative[:2] == ("src", "evertree") and all(
            part.isidentifier() for part in relative[1:]
        ):
            module_name = ".".join(relative[1:])
        else:
            module_name = "_evertree_program_" + uuid.uuid5(uuid.NAMESPACE_URL, str(path)).hex
        module_spec = importlib.util.spec_from_file_location(module_name, path)
        if module_spec is None or module_spec.loader is None:
            raise ImportError(str(path))
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
        function = getattr(module, entrypoint)
        if not callable(function):
            raise TypeError("Program entrypoint is not callable")
        _programs[key] = function
    return _programs[key]


async def _main(configuration):
    global _configuration, _loop, DBOS, gateway_step, program_workflow
    from dbos import DBOS, SetWorkflowID

    _configuration = configuration
    _loop = asyncio.get_running_loop()
    threading.Thread(target=_reader, daemon=True).start()
    # The committed checkout is readable, but is never a source of trusted core imports.
    sys.path.append(str(Path(configuration["checkout"]) / "src"))
    import evertree
    import evertree.core

    # Cache the protected core package before adding committed program modules.
    # Common helpers, like Programs, must come from this exact Git revision.
    evertree.__path__.insert(0, str(Path(configuration["checkout"]) / "src" / "evertree"))

    @DBOS.step()
    async def gateway_step(run_id, method, payload, source_line=None, *, program=None):
        request = {
            "run_id": run_id,
            "method": method,
            "payload": json_value(payload),
            "source_line": source_line,
        }
        if program is not None:
            request["program"] = program
        return await rpc("gateway", request)

    @DBOS.workflow()
    async def program_workflow(spec, arguments, parent_run_id=None):
        run_id = DBOS.workflow_id
        context = Context(spec, run_id)
        token = _current.set(context)
        try:
            await gateway_step(
                run_id,
                "run_started",
                {"arguments": arguments, "parent_run_id": parent_run_id},
                program=spec,
            )
            function = load_program(spec)
            kwargs = dict(arguments)
            signature = inspect.signature(function)
            if "ctx" in signature.parameters:
                kwargs["ctx"] = context
            signature.bind(**kwargs)
            if inspect.iscoroutinefunction(function):
                result = await function(**kwargs)
            else:
                result = await asyncio.to_thread(function, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
            if hasattr(result, "result"):
                result = {
                    "result": json_value(result.result),
                    "feedback": getattr(result, "feedback", None),
                }
            elif isinstance(result, dict) and "result" in result:
                result = {"result": result["result"], "feedback": result.get("feedback")}
            else:
                raise TypeError("Program must return ProgramResult or {result, feedback}")
            if result["feedback"] is not None and not isinstance(result["feedback"], str):
                raise TypeError("ProgramResult.feedback must be a string or None")
            result = json_value(result)
            await gateway_step(run_id, "run_finished", {"result": result})
            return result
        except BaseException as exc:
            if not isinstance(exc, asyncio.CancelledError):
                await gateway_step(run_id, "run_failed", {"error": f"{type(exc).__name__}: {exc}"})
            raise
        finally:
            _current.reset(token)

    DBOS(
        config={
            "name": "evertree-worker",
            "application_version": configuration["revision"],
            "executor_id": configuration["executor_id"],
            "system_database_url": "sqlite:///" + configuration["journal"],
            "run_admin_server": False,
            "log_level": "ERROR",
        }
    )
    DBOS.launch()
    send({"type": "ready"})
    try:
        with SetWorkflowID(configuration["run_id"]):
            result = await program_workflow(configuration["program"], configuration["arguments"])
        send({"type": "result", "run_id": configuration["run_id"], **result})
    except BaseException as exc:  # noqa: BLE001 -- worker protocol boundary
        send(
            {
                "type": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        DBOS.destroy()


if __name__ == "__main__":
    try:
        asyncio.run(_main(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))))
    except BaseException as error:  # noqa: BLE001 -- executable entrypoint boundary
        send(
            {
                "type": "error",
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
            }
        )
        raise SystemExit(1)
