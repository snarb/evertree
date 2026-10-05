"""Local EverTree core: one task, explicit effects, durable Program execution."""

from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import json
import os
import time
import weakref
from pathlib import Path
from typing import Any, Literal  # noqa: F401 -- retain the public schema annotation namespace
from uuid import uuid4

from ._application.consciousness import ConsciousnessMixin
from ._application.execution import TaskExecutionMixin
from ._application.persistence import PersistenceMixin
from ._application.programs import ProgramsMixin
from ._application.prompts import (  # noqa: F401 -- preserve existing imports from this module
    CONSCIOUSNESS_INSTRUCTIONS,
    AnswerVerification,
    Decision,
    consciousness_tools,
)
from ._application.tools import ToolsMixin
from .core.backup import BackupManager
from .core.cache import prune
from .core.codex_provider import CodexProvider
from .core.environment import capture_runtime, require_committed_runtime
from .core.evaluation import SupervisorFeedback, exact_json_equal
from .core.lifecycle import git, initialize_seed_repository, resolve_program_remote
from .core.memory import TraceOutputRef
from .core.provider import AgentProvider
from .core.runtime import Runtime
from .core.values import json_value


@dataclasses.dataclass(frozen=True)
class EverTreeEvent:
    kind: str
    task_id: str | None
    data: dict[str, Any]


class EventSubscription:
    """A live event consumer; leaving its context releases its queue."""

    def __init__(self, owner):
        self._owner = owner
        self._queue: asyncio.Queue[EverTreeEvent | None] = asyncio.Queue()
        self._closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._closed and self._queue.empty():
            raise StopAsyncIteration
        try:
            event = await self._queue.get()
        except asyncio.CancelledError:
            self.close()
            raise
        if event is None:
            raise StopAsyncIteration
        return event

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.close()

    async def aclose(self):
        self.close()

    def close(self):
        if not self._closed:
            self._closed = True
            self._owner._subscribers.discard(self)
            self._queue.put_nowait(None)


class EverTree(ConsciousnessMixin, TaskExecutionMixin, PersistenceMixin, ProgramsMixin, ToolsMixin):
    """An asynchronous local agent. Use as an async context manager.

    ``directory`` is the agent's home, not an unrestricted tool working directory.
    Each task gets a writable workspace under .state/workspaces. The installed
    trusted core and the live Program repository are outside that workspace.
    """

    _tools = staticmethod(consciousness_tools)

    def __init__(
        self,
        directory: str | Path,
        *,
        provider: AgentProvider | None = None,
        approval_handler=None,
        runtime_factory=Runtime,
        program_remote: str | None = None,
    ):
        self.directory = Path(directory).resolve()
        self.state_dir = self.directory / ".state"
        self.repository = self.state_dir / "program-repository"
        self.provider = provider or CodexProvider(state_dir=self.state_dir / "codex-runtime")
        self.approval_handler = approval_handler
        self._runtime_factory = runtime_factory
        self._program_remote = program_remote
        self._subscribers: weakref.WeakSet[EventSubscription] = weakref.WeakSet()
        self._accounting = contextvars.ContextVar("evertree_accounting", default=None)
        self._improvement = contextvars.ContextVar("evertree_improvement", default=False)
        self._operations = 0
        self._pump: asyncio.Task | None = None
        self._maintenance: asyncio.Task | None = None
        self._active_requests: dict[str, str] = {}
        self._tool_tasks: dict[str, set] = {}
        self._task_stopped: dict[str, asyncio.Event] = {}
        self._cancel_requested: set[str] = set()
        self._current_task: str | None = None
        self._delivery: dict[str, tuple[str, asyncio.Future]] = {}
        self._results: dict[str, dict] = {}
        self._closed = False
        self._started = False
        self._state_lock = asyncio.Lock()
        self._lock_file = None
        self.runtime = None
        self.lifecycle = None
        self._environment = None
        self._candidate_owners: dict[str, str] = {}
        self._reset_stores()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def start(self):
        if self._started:
            return self
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._lock_file = (self.state_dir / "agent.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self._lock_file.seek(0)
                if not self._lock_file.read(1):
                    self._lock_file.write(b"0")
                    self._lock_file.flush()
                self._lock_file.seek(0)
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            await asyncio.to_thread(prune, self.directory)
            await asyncio.to_thread(require_committed_runtime, Path(__file__).parent)
            self._environment = await asyncio.to_thread(capture_runtime, Path(__file__).parent)
            await asyncio.to_thread(
                initialize_seed_repository, Path(__file__).parent, self.repository
            )
            self.runtime = self._runtime_factory(
                self.state_dir / "runtime",
                self.repository,
                self._gateway,
                self._runtime_trace,
            )
            self._program_remote = await asyncio.to_thread(
                resolve_program_remote, Path(__file__).parent, self._program_remote
            )
            self._make_lifecycle()
            self.backups = BackupManager(self.state_dir / "backups")
            if self.backups.list():
                await self.restore()
            else:
                self._bootstrap()
            await self._discard_workspaces()
            self._recover_inputs()
            self._started = True
            self._maintenance = asyncio.create_task(self._periodic_maintenance())
            return self
        except BaseException:
            if self.runtime:
                await self.runtime.close()
            self._lock_file.close()
            self._lock_file = None
            raise

    def observe(
        self,
        value: Any,
        *,
        source_id: str,
        task_id: str | None = None,
        projections: dict | None = None,
        context: dict | None = None,
    ) -> TraceOutputRef:
        """Record a host-supplied observation. Provider text cannot call this trust boundary."""
        if not source_id:
            raise ValueError("Observation source identity is required")
        projection = (
            self.prediction_evaluator().project_observation(value, projections or {}, context)
            if context is not None
            else {}
        )
        if projections and context is None:
            raise ValueError("Semantic observation projections require a prediction context")
        for event in self.memory.events:
            if event.id in self._observations and event.arguments.get("source_id") == source_id:
                if not exact_json_equal(json_value(event.output), json_value(value)) or any(
                    not exact_json_equal(json_value(event.arguments.get(key)), expected)
                    for key, expected in projection.items()
                ):
                    raise ValueError("Observation identity reused with different contents")
                return self.memory.output_ref(event)
        run = self.memory.start_run(
            "Observation", git(self.repository, "rev-parse", "main"), {"task_id": task_id}
        )
        event = self.memory.record(
            run, "observation", arguments={"source_id": source_id, **projection}, output=value
        )
        self._observations.add(event.id)
        ref = self.memory.output_ref(event)
        self.memory.retain(ref, "observation:" + source_id)
        self.memory.finish_run(run)
        return ref

    def prediction_evaluator(self):
        from .core.predictions import PredictionEvaluator

        return PredictionEvaluator(
            self.graph, self.memory, self.evaluations, observation_ids=self._observations
        )

    def save_prediction(self, target, reference: TraceOutputRef, context: dict, **settings):
        """Index an original trace output before its outcome becomes known."""
        fact = self.prediction_evaluator().save_prediction(target, reference, context, **settings)
        self._protected_nodes.update((fact.id, fact.relation_type))
        return fact

    def supervisor_feedback(
        self,
        feedback: SupervisorFeedback,
        *,
        source_id: str,
        task_id: str | None = None,
        context: dict | None = None,
    ) -> TraceOutputRef:
        """Record host feedback; agents cannot mint this external signal through tools."""
        if not isinstance(feedback, SupervisorFeedback):
            raise TypeError("Pass a validated SupervisorFeedback")
        if context is None:
            if task_id is None:
                raise ValueError("Feedback needs a task or an explicit process context")
            task = self.tasks.get(task_id)
            context = {
                "process_id": "Consciousness",
                "subject": task_id,
                "episode": task.episode_ids[-1] if task.episode_ids else task_id,
            }
        ref = self.observe(
            {"channel": "supervisor_feedback_signal", **feedback.to_dict()},
            source_id=source_id,
            task_id=task_id,
            context=context,
            projections={"supervisor_feedback_signal": {"value": ["value"]}},
        )
        if task_id is not None and not self.tasks.get(task_id).terminal:
            messages = self._inputs.setdefault(task_id, [])
            if not any(item.get("source_id") == source_id for item in messages):
                messages.append(
                    {
                        "role": "observation",
                        "source_id": source_id,
                        "content": json.dumps(
                            {
                                "supervisor_feedback": feedback.to_dict(),
                                "reference": json_value(ref),
                            }
                        ),
                    }
                )
                self.attention.request_attention(
                    task_id,
                    self.tasks.get(task_id).attention_priority,
                    reason="External supervisor feedback",
                )
        return ref

    async def submit(
        self,
        text: str,
        *,
        task_id: str | None = None,
        source_id: str | None = None,
        hard_limits: dict | None = None,
    ):
        await self.start()
        if self._closed or not text.strip():
            raise ValueError("A nonempty input and an open agent are required")
        async with self._state_lock:
            source_id = source_id or uuid4().hex
            if source_id in self._seen_inputs:
                return self.tasks.get(self._seen_inputs[source_id])
            state = (
                self.tasks.get(task_id)
                if task_id
                else self.tasks.create_task(
                    text, episode_id=uuid4().hex, source_ids=(source_id,), hard_limits=hard_limits
                )
            )
            self._predictions.setdefault(state.id, self.learning.predict("verified_task_rate"))
            if state.terminal:
                raise ValueError("Completed tasks cannot be resumed; submit a new task")
            incoming = {
                "role": "user",
                "content": text,
                "source_id": source_id,
                "received_at": time.time(),
            }
            self._append_input({"task": state.to_dict(), "input": incoming})
            self._inputs.setdefault(state.id, []).append(incoming)
            self._seen_inputs[source_id] = state.id
            if source_id not in state.source_ids:
                state.source_ids.append(source_id)
            if self.attention.running_task != state.id:
                state.status = "queued"
                self.attention.request_attention(state.id, state.attention_priority)
            await self._publish("input", state.id, {"source_id": source_id})
        if self._pump is None or self._pump.done():
            self._pump = asyncio.create_task(self._run_queue())
        return state

    async def resume(self, task_id: str, text: str | None = None, *, hard_limits=None):
        await self.start()
        state = self.tasks.get(task_id)
        if state.terminal:
            raise ValueError("A completed task cannot resume")
        if hard_limits is not None:
            if any(
                not isinstance(v, (int, float)) or not 0 < v < float("inf")
                for v in hard_limits.values()
            ):
                raise ValueError("User resource limits must be finite and positive")
            state.hard_limits = dict(hard_limits)
        state.review_required = True
        return await self.submit(
            text or "Continue the saved task from its retained state.", task_id=task_id
        )

    async def _publish(self, kind, task_id=None, data=None):
        event = EverTreeEvent(kind, task_id, data or {})
        for subscriber in tuple(self._subscribers):
            subscriber._queue.put_nowait(event)

    def events(self) -> EventSubscription:
        """Subscribe to future events and any answer still awaiting delivery.

        Subscribe before submitting work, preferably with ``async with``. Past
        progress lives in memory; it is not buffered for absent consumers.
        """
        subscriber = EventSubscription(self)
        if self._closed:
            subscriber.close()
            return subscriber
        self._subscribers.add(subscriber)
        for delivery_id, (task_id, future) in self._delivery.items():
            if not future.done():
                subscriber._queue.put_nowait(
                    EverTreeEvent(
                        "answer",
                        task_id,
                        {
                            "text": self._results.get(task_id, {}).get("answer", ""),
                            "delivery_id": delivery_id,
                        },
                    )
                )
        return subscriber

    async def run(self, text: str, **kwargs) -> dict:
        """Convenience transport: return the answer and acknowledge its delivery."""
        async with self.events() as stream:
            state = await self.submit(text, **kwargs)
            if state.terminal or state.status == "waiting":
                return {
                    "task_id": state.id,
                    "status": state.status,
                    "answer": self._results.get(state.id, {}).get("answer", ""),
                    "reason": state.outcome_reason,
                }
            async for event in stream:
                if event.task_id != state.id:
                    continue
                if event.kind == "answer":
                    await self.acknowledge_delivery(event.data["delivery_id"])
                if event.kind in {
                    "task_completed",
                    "task_waiting",
                    "task_failed",
                    "task_cancelled",
                }:
                    return {
                        "task_id": state.id,
                        "status": self.tasks.get(state.id).status,
                        "answer": self._results.get(state.id, {}).get("answer", ""),
                        **event.data,
                    }
        raise RuntimeError("Agent closed before delivering a task outcome")

    def _workspace(self, task_id):
        path = self.state_dir / "workspaces" / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def close(self):
        if self._closed:
            return
        self._closed = True
        if self._maintenance:
            self._maintenance.cancel()
        if self._pump and not self._pump.done():
            self._pump.cancel()
            await asyncio.gather(self._pump, return_exceptions=True)
        try:
            if self.runtime:
                await self.runtime.close()
                await self.backup()
        finally:
            try:
                try:
                    await self.provider.close()
                finally:
                    if self.lifecycle is not None:
                        await self._discard_workspaces()
            finally:
                if self._lock_file:
                    self._lock_file.close()
                    self._lock_file = None
                await self._publish("closed")
                for subscriber in tuple(self._subscribers):
                    subscriber.close()
