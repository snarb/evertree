"""Provider calls, resource accounting, cancellation and answer delivery."""

from __future__ import annotations

import asyncio
import dataclasses
import time
from contextlib import contextmanager
from uuid import uuid4

from ..core.programs.lifecycle import git
from ..core.provider import AgentRequest


class TaskExecutionMixin:
    """Internal EverTree method group; state is owned and initialized by EverTree."""

    @staticmethod
    def _remaining_seconds(state):
        remaining = state.remaining("active_time_minutes")
        if remaining is None or remaining <= 0:
            raise RuntimeError("Consciousness must reassess the task's finite time budget")
        return remaining * 60

    @contextmanager
    def _meter(self, task_id, *, improvement=False, operation_id=None):
        """Charge the outer scope, and explicitly attributed nested improvement, once."""
        owner = self._accounting.get() is None
        meter = self._accounting.get() or {
            "charged_seconds": 0.0,
            "waiting_seconds": 0.0,
            "approvals": 0,
        }
        started = time.monotonic()
        charged_before, waiting_before = meter["charged_seconds"], meter["waiting_seconds"]
        token = self._accounting.set(meter)
        try:
            yield meter
        finally:
            self._accounting.reset(token)
            if owner or improvement:
                seconds = max(
                    0,
                    time.monotonic()
                    - started
                    - (meter["waiting_seconds"] - waiting_before)
                    - (meter["charged_seconds"] - charged_before),
                )
                self.tasks.record_usage(
                    task_id,
                    "active_time_minutes",
                    seconds / 60,
                    operation_id=operation_id or uuid4().hex,
                    self_improvement=improvement,
                )
                if improvement:
                    meter["charged_seconds"] += seconds

    async def _invoke(self, task_id, request: AgentRequest, *, run_ref=None, conversation=False):
        request_id = uuid4().hex
        async with self._state_lock:
            self._active_requests[request_id] = task_id
        own_run = run_ref is None
        run = (
            self.memory.start_run(
                "Consciousness", git(self.repository, "rev-parse", "main"), {"task_id": task_id}
            )
            if own_run
            else self.memory.get_run(run_ref)
        )
        self.memory.record(
            run,
            "provider_request",
            output={
                "prompt": request.prompt,
                "instructions": request.instructions,
                "mode": request.mode,
                "workspace": str(request.workspace),
                "native_coding": request.native_coding,
                "timeout_seconds": request.timeout_seconds,
                "output_schema": request.output_schema,
                "tools": [dataclasses.asdict(t) for t in request.tools],
                "session": dataclasses.asdict(request.session) if request.session else None,
            },
        )
        with self._meter(task_id, operation_id=request_id + ":active_time") as meter:
            used_tokens = 0
            usage_known = False
            result = None
            session = None
            try:

                async def handle_tool(name, args):
                    inherited = self._accounting.set(meter)
                    try:
                        return await self._tool(task_id, name, args)
                    finally:
                        self._accounting.reset(inherited)

                async def handle_approval(data):
                    inherited = self._accounting.set(meter)
                    try:
                        return await self._approve(task_id, data)
                    finally:
                        self._accounting.reset(inherited)

                async for event in self.provider.run(
                    request_id, request, tool_handler=handle_tool, approval_handler=handle_approval
                ):
                    self.memory.record(
                        run, "provider_event", output={"kind": event.kind, "data": event.data}
                    )
                    if event.kind == "session":
                        session = {"provider": event.data["provider"], "id": event.data["id"]}
                        if conversation:
                            self._sessions[task_id] = session
                    elif event.kind == "completed":
                        result = {**event.data, "session": session}
                    elif event.kind == "error":
                        raise RuntimeError(event.data["message"])
                    elif event.kind == "cancelled":
                        raise asyncio.CancelledError()
                    elif event.kind == "usage":
                        total = event.data.get("total_tokens")
                        usage_known = event.data.get("available", False) and type(total) is int
                        if usage_known:
                            used_tokens = max(used_tokens, total)
                        elif "tokens" in self.tasks.get(task_id).hard_limits:
                            raise RuntimeError(
                                "Provider usage is unknown; cannot enforce the user token limit"
                            )
                    if event.kind in {
                        "message",
                        "tool_call",
                        "tool_result",
                        "approval",
                        "file_change",
                    }:
                        await self._publish(event.kind, task_id, event.data)
                if result is None:
                    raise RuntimeError("Provider ended without a completed result")
                if not usage_known and "tokens" in self.tasks.get(task_id).hard_limits:
                    raise RuntimeError(
                        "Provider usage is unknown; cannot enforce the user token limit"
                    )
                return result
            finally:
                self._active_requests.pop(request_id, None)
                if own_run:
                    self.memory.finish_run(run, status="completed" if result else "failed")
                if used_tokens:
                    self.tasks.record_usage(
                        task_id,
                        "tokens",
                        used_tokens,
                        operation_id=request_id + ":tokens",
                        self_improvement=self._improvement.get(),
                    )

    async def _approve(self, task_id, data):
        if self.approval_handler is None:
            return False
        meter = self._accounting.get()
        if meter is not None:
            if not meter["approvals"]:
                meter["approval_started"] = time.monotonic()
            meter["approvals"] += 1
        try:
            return bool(await self.approval_handler({"task_id": task_id, **data}))
        finally:
            if meter is not None:
                meter["approvals"] -= 1
                if not meter["approvals"]:
                    meter["waiting_seconds"] += time.monotonic() - meter.pop("approval_started")

    async def _deliver(self, task_id, answer):
        identity = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._delivery[identity] = (task_id, future)
        await self._publish("answer", task_id, {"text": answer, "delivery_id": identity})
        try:
            return await future
        finally:
            self._delivery.pop(identity, None)

    async def acknowledge_delivery(self, delivery_id, *, delivered=True):
        _, future = self._delivery[delivery_id]
        if not future.done():
            future.set_result(delivered)

    async def cancel(self, task_id):
        self._cancel_requested.add(task_id)
        for request_id, owner in list(self._active_requests.items()):
            if owner == task_id:
                await self.provider.cancel(request_id)
        callbacks = [task for task in self._tool_tasks.get(task_id, ()) if task is not self._pump]
        for task in callbacks:
            task.cancel()
        await asyncio.gather(*callbacks, return_exceptions=True)
        await self.runtime.cancel(task_id)
        if self._current_task == task_id and self._pump and not self._pump.done():
            self._pump.cancel()
            await self._task_stopped[task_id].wait()
        state = self.tasks.get(task_id)
        if not state.terminal:
            await self._stop_task(state, "cancelled", "Cancelled by user")
        for owner, future in self._delivery.values():
            if owner == task_id and not future.done():
                future.set_result(False)
