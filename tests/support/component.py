"""Execute trusted source Programs directly for component tests.

This harness does not model process isolation, Git revisions, DBOS, or backups.
It shares the production gateway and traces; their business rules stay real.
Never use it to test worker durability or untrusted candidate code.
"""

import asyncio
import importlib
import inspect
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from evertree.application import EverTree
from evertree.core.provider import ScriptedProvider
from evertree.core.runtime import ProgramExecutionError, RunResult, Runtime

REVISION = "0" * 40


class SourceRuntime(Runtime):
    """Replace only worker transport with calls to installed trusted Programs."""

    async def execute(
        self, task_id, program, arguments, *, run_id=None, timeout=300, run_mode="live"
    ):
        assert program.revision == REVISION
        if self._closed or task_id in self._final_tasks:
            raise ProgramExecutionError("Task is finalized or runtime is closed")
        run_id = run_id or uuid4().hex
        run_dir = self.state_dir / run_id
        run_dir.mkdir(parents=True)
        async with self._admission:
            self._active = {
                "task_id": task_id,
                "run_id": run_id,
                "program": program,
                "run_mode": run_mode,
                "cancelled": False,
                "known_runs": {},
                "run_dir": run_dir,
            }
            work = asyncio.create_task(self._call(program, arguments, run_id))
            self._active["reader_task"] = work
            try:
                output = await asyncio.wait_for(work, timeout)
                return RunResult(run_id, output["result"], output.get("feedback"))
            finally:
                self._active = None

    async def _call(self, spec, arguments, run_id):
        async def step(method, payload=None):
            return await self._dispatch(
                {"run_id": run_id, "method": method, "payload": payload or {}}
            )

        await self._dispatch(
            {
                "run_id": run_id,
                "method": "run_started",
                "program": asdict(spec),
                "payload": {"arguments": arguments, "parent_run_id": None},
            }
        )
        path = Path(spec.git_path)
        assert path.parts[:3] == ("src", "evertree", "processes")
        function = getattr(
            importlib.import_module(".".join(path.with_suffix("").parts[1:])), spec.entrypoint
        )
        kwargs = dict(arguments)
        if "ctx" in inspect.signature(function).parameters:
            kwargs["ctx"] = SimpleNamespace(step=step)
        result = function(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        if hasattr(result, "result"):
            result = {"result": result.result, "feedback": result.feedback}
        await step("run_finished", {"result": result})
        return result


@asynccontextmanager
async def component_app(directory, *, provider=None, approval_handler=None):
    """Build real stores and coordinator; substitute only persistence and transport."""
    app = EverTree(
        directory, provider=provider or ScriptedProvider([]), approval_handler=approval_handler
    )
    app.state_dir.mkdir(parents=True, exist_ok=True)
    app._bootstrap_state(REVISION)
    app.runtime = SourceRuntime(
        app.state_dir / "runtime", app.repository, app._gateway, app._runtime_trace
    )

    app._program_revision = lambda: REVISION

    def source(spec):
        assert spec["revision"] == REVISION
        path = Path(spec["git_path"])
        assert path.parts[:3] == ("src", "evertree", "processes")
        return (Path(__file__).resolve().parents[2] / path).read_text(encoding="utf-8")

    app._program_source = source
    app.backup = AsyncMock(return_value=None)
    app._make_lifecycle()
    app._started = True
    try:
        yield app
    finally:
        await app.close()
