"""Provider calls, resource accounting, cancellation and answer delivery."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from contextlib import contextmanager
from uuid import uuid4

from ..core.memory.types import _references
from ..core.provider import LLMRequest, current_tool_call_id
from ..core.runtime.coordination import semantic_scope
from ..core.values import ContractError, json_value


class BudgetExhausted(RuntimeError):
    """The Task's allowance ran out; a budget review, not a failure, decides what follows."""


class TaskExecutionMixin:
    """Internal EverTree method group; state is owned and initialized by EverTree."""

    @staticmethod
    def _remaining_seconds(state):
        remaining = state.remaining("active_time_minutes")
        if remaining is None or remaining <= 0:
            raise BudgetExhausted("Consciousness must reassess the task's finite time budget")
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

    async def _invoke(self, task_id, request, **kwargs):
        """Own the execution chain and give each conscious invocation its own search scope."""
        with self._execution.enter():
            token = (
                semantic_scope.set("consciousness:" + uuid4().hex)
                if kwargs.get("conversation")
                else None
            )
            try:
                return await self._invoke_model(task_id, request, **kwargs)
            finally:
                if token is not None:
                    semantic_scope.reset(token)

    async def _invoke_model(
        self,
        task_id,
        request: LLMRequest,
        *,
        run_ref=None,
        conversation=False,
        run_name="Consciousness",
        tool_handler=None,
    ):
        """Stream a provider invocation into task usage, tool execution and semantic provenance."""
        request = dataclasses.replace(
            request, token_encoding=self.semantic_config.read.token_encoding
        )
        request_id = uuid4().hex
        async with self._state_lock:
            self._active_requests[request_id] = task_id
        own_run = run_ref is None
        run = (
            self.memory.start_run(run_name, self._program_revision(), {"task_id": task_id})
            if own_run
            else self.memory.get_run(run_ref)
        )
        request_event = self.memory.record(
            run,
            "provider_request",
            output={
                "prompt": request.prompt,
                "instructions": request.instructions,
                "mode": request.mode,
                "model": request.model,
                "effort": request.effort,
                "tool_sets": [s.name for s in request.tool_sets],
                "workspace": str(request.workspace),
                "native_coding": request.native_coding,
                "timeout_seconds": request.timeout_seconds,
                "output_schema": request.output_schema,
                "tools": [dataclasses.asdict(t) for t in request.tools],
                "session": dataclasses.asdict(request.session) if request.session else None,
            },
        )
        semantic_tools = None
        source_refs = []
        completed_calls = {}
        call_lock = asyncio.Lock()

        def remember_refs(value):
            from ..core.cognition.steps import trace_reference

            if isinstance(value, dict):
                if "event_ref" in value and set(value) <= {"event_ref", "output_path"}:
                    try:
                        reference = trace_reference(value)
                        self.memory.resolve(reference)
                        self._surfaced.add(reference.event_ref)
                        ref = json_value(reference)
                    except ValueError:
                        # Context may contain ordinary data that resembles a trace reference.
                        return
                    if ref not in source_refs:
                        source_refs.append(ref)
                else:
                    for item in value.values():
                        remember_refs(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    remember_refs(item)

        if conversation:
            from ..common.integration_actions import SemanticTools
            from ..core.operations import authorize_operation

            remember_refs(json.loads(request.prompt))

            async def search(queries, *, kinds=None, limit=10):
                return await self._dispatch_tool(
                    task_id, "graph.search", {"queries": queries, "kinds": kinds, "limit": limit}
                )

            async def describe(subject):
                return await self._graph_tool(task_id, "graph.describe", {"subject": subject})

            async def write(action, operation_key):
                authorize_operation("semantic.write", request.mode)
                result = await self._semantics().execute(
                    "semantic.write",
                    {
                        "action": action,
                        "operation_key": current_tool_call_id.get() or operation_key,
                        "experience_refs": source_refs,
                    },
                    {
                        "task_id": task_id,
                        "semantic_scope": semantic_scope.get(),
                        "program": {"role": request.mode, "revision": self._program_revision()},
                        "consciousness_graph_authorized": True,
                        "integration_operation_id": "consciousness:" + str(request_event.id),
                    },
                )
                await self.backup()
                return result

            semantic_tools = SemanticTools(search=search, describe=describe, write=write)
        with self._meter(task_id, operation_id=request_id + ":active_time") as meter:
            used_tokens = 0
            usage_known = False
            result = None
            session = None
            interrupted = False
            try:

                async def handle_tool(name, args):
                    inherited = self._accounting.set(meter)
                    try:
                        if tool_handler is not None:
                            return await tool_handler(name, args)
                        call_id = current_tool_call_id.get()
                        fingerprint = json.dumps({"name": name, "arguments": args}, sort_keys=True)
                        async with call_lock:
                            if conversation and call_id in completed_calls:
                                previous, output = completed_calls[call_id]
                                if previous != fingerprint:
                                    raise ValueError("A tool call ID cannot change its arguments")
                                return output
                            output = await self._tool(
                                task_id, name, args, semantic_tools=semantic_tools
                            )
                            if semantic_tools is not None and name in {
                                "graph.search",
                                "graph.describe",
                                "graph.query",
                                "graph.walk",
                                "graph.read_property",
                                "graph.summarize_property",
                                "graph.interpret_property",
                                "graph.select_properties",
                            }:
                                semantic_tools.remember_read(
                                    name.removeprefix("graph."), args, output
                                )
                            if conversation:
                                remember_refs(output)
                                if call_id is not None:
                                    completed_calls[call_id] = (fingerprint, output)
                            return output
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
                    output = {"kind": event.kind, "data": event.data}
                    try:
                        for reference in _references(event.data):
                            self.memory.resolve(reference)
                    except ContractError as exc:
                        # Unchecked SDK arguments are data; their tool validates the references.
                        output["data"] = {
                            "unvalidated_json": json.dumps(
                                json_value(event.data), ensure_ascii=False
                            ),
                            "reference_error": str(exc),
                        }
                    trace_event = self.memory.record(run, "provider_event", output=output)
                    if event.kind == "session":
                        session = {"provider": event.data["provider"], "id": event.data["id"]}
                        if conversation:
                            self._sessions[task_id] = session
                    elif event.kind == "completed":
                        result = {
                            **event.data,
                            "session": session,
                            "source_ref": dataclasses.asdict(self.memory.output_ref(trace_event)),
                        }
                    elif event.kind == "error":
                        # A time limit is an interruption the caller resumes, not a failure.
                        if event.data.get("type") == "TimeoutError":
                            raise TimeoutError(event.data["message"])
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
            except (asyncio.CancelledError, TimeoutError):
                interrupted = True
                await self.provider.cancel(request_id)
                raise
            finally:
                self._active_requests.pop(request_id, None)
                if own_run:
                    self.memory.finish_run(
                        run,
                        status="interrupted"
                        if interrupted
                        else "completed"
                        if result
                        else "failed",
                    )
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
        """Resolve a pending answer delivery with the transport's success or failure."""
        _, future = self._delivery[delivery_id]
        if not future.done():
            future.set_result(delivered)

    async def cancel(self, task_id, *, reason: str = "Cancelled by user"):
        """Cancel a task's provider calls and execution tree, then record its terminal outcome.

        reason is the saved decision that removes the commitment; it is never blank.
        """
        if not reason or not reason.strip():
            raise ValueError("A cancellation needs the reason for removing the commitment")
        self._cancel_requested.setdefault(task_id, reason)
        for request_id, owner in list(self._active_requests.items()):
            if owner == task_id:
                await self.provider.cancel(request_id)
        callbacks = [task for task in self._tool_tasks.get(task_id, ()) if task is not self._pump]
        for task in callbacks:
            task.cancel()
        await asyncio.gather(*callbacks, return_exceptions=True)
        await self.runtime.cancel(task_id)
        if self._current_task == task_id and self._pump and not self._pump.done():
            # A provider ending its turn may already have started the stop in the pump.
            if task_id not in self._stopping:
                self._pump.cancel()
            await self._task_stopped[task_id].wait()
        state = self.tasks.get(task_id)
        if not state.terminal:
            await self._stop_task(state, "cancelled", self._cancel_requested[task_id])
        for owner, future in self._delivery.values():
            if owner == task_id and not future.done():
                future.set_result(False)
