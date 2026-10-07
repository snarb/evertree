"""Conscious decision loop, task verification and outcome learning."""

from __future__ import annotations

import asyncio
import json

from evertree.core.cognition.attention import prepare_context
from evertree.core.cognition.tasks import TaskSpecification
from evertree.core.evaluation.acceptance import VerificationResult
from evertree.core.learning.contracts import LearningObjective, LearningSignal
from evertree.core.learning.coordinator import LearningCoordinator
from evertree.core.memory.types import MemoryQuery

from ..core.provider import AgentRequest
from ..core.values import json_value
from .prompts import (
    ANSWER_VERIFICATION_INSTRUCTIONS,
    CONSCIOUSNESS_INSTRUCTIONS,
    AnswerVerification,
    Decision,
)


class ConsciousnessMixin:
    """Internal EverTree method group; state is owned and initialized by EverTree."""

    async def _run_queue(self):
        while not self._closed and (identity := self.attention.next_task()) is not None:
            state = self.tasks.get(identity)
            self._current_task = identity
            self._task_stopped[identity] = asyncio.Event()
            try:
                pending = self._pending_programs.get(identity)
                if pending:
                    if pending["identity"] in {"task_framing", "resource_control"}:
                        if not await self._ensure_budget(state):
                            self.attention._queue.pop(identity, None)
                            continue
                    else:
                        recovered = await self._run_program(
                            identity, pending["identity"], pending["arguments"]
                        )
                        self._inputs[identity].append(
                            {
                                "role": "assistant",
                                "content": json.dumps({"recovered_program_result": recovered}),
                            }
                        )
                if not await self._ensure_budget(state):
                    self.attention._queue.pop(identity, None)
                    continue
                self.attention.admit(identity)
                await self._publish("task_started", identity)
                await self._execute_task(state)
            except asyncio.CancelledError:
                if not state.terminal:
                    if identity in self._cancel_requested:
                        await self._stop_task(state, "cancelled", "Cancelled by user")
                    else:
                        await self.runtime.cancel(state.id, finalize=False)
                        self.tasks.set_waiting(
                            state.id,
                            waiting_for=["resume"],
                            reason="Execution interrupted",
                            execution_stopped=True,
                        )
                if self._closed:
                    raise
            except Exception as exc:  # noqa: BLE001 -- controller failures become explicit task failures
                if not state.terminal:
                    cancelled = identity in self._cancel_requested
                    await self._stop_task(
                        state,
                        "cancelled" if cancelled else "failed",
                        "Cancelled by user" if cancelled else str(exc),
                    )
            finally:
                if self.attention.running_task == identity:
                    self.attention.release(
                        identity,
                        execution_stopped=True,
                        status="waiting" if state.status == "waiting" else "suspended",
                    )
                self._task_stopped[identity].set()
                self._current_task = None
                try:
                    await self.backup()
                except Exception as exc:  # noqa: BLE001 -- failed maintenance must not stop queued work
                    await self._publish("maintenance_error", identity, {"message": str(exc)})

    async def _ensure_budget(self, state):
        if state.hard_limit_reached:
            self.tasks.set_waiting(
                state.id,
                waiting_for=["user_limit_change"],
                reason="User-defined resource limit reached",
                execution_stopped=True,
            )
            await self._publish("task_waiting", state.id, {"reason": state.progress})
            return False
        pending = self._pending_programs.get(state.id)
        if (
            state.execution_budget is None
            or state.budget_exhausted
            or state.review_required
            or pending
            and pending["identity"] in {"task_framing", "resource_control"}
        ):
            await self._frame(state)
            if state.hard_limit_reached:
                return await self._ensure_budget(state)
        return True

    async def _frame(self, state):
        context = {**state.to_dict(), "inputs": list(self._inputs[state.id])}
        hard_remaining = state.hard_limits.get(
            "active_time_minutes", float("inf")
        ) - state.spent.get("active_time_minutes", 0)
        if hard_remaining <= 0:
            raise RuntimeError("User-defined resource limit reached")
        pending = self._pending_programs.get(state.id)
        if pending and pending["identity"] in {"task_framing", "resource_control"}:
            identity, arguments = pending["identity"], pending["arguments"]
        elif state.execution_budget is None:
            identity = "task_framing"
            arguments = {"request": self._inputs[state.id][-1]["content"], "context": context}
        else:
            identity = "resource_control"
            arguments = {"task_state": context, "evidence": {"trace": self._recent_trace(state.id)}}
        result = await self._run_program(
            state.id, identity, arguments, timeout=min(300, hard_remaining * 60)
        )
        self._accept_frame(state, result)
        await self._publish(
            "budget",
            state.id,
            {
                "execution_budget": state.execution_budget.to_dict(),
                "self_improvement_budget": state.self_improvement_budget,
            },
        )

    def _accept_frame(self, state, result):
        data = result["result"]
        self.tasks.assign_budget(
            state.id,
            data["execution_budget"],
            data["self_improvement_budget"],
            reason=data["budget_reason"],
        )
        if state.specification.revision == 1:
            self.tasks.revise_specification(
                state.id,
                TaskSpecification(
                    data["objective"],
                    tuple(data["success_criteria"]),
                    tuple(data["constraints"]),
                    tuple(data["preferences"]),
                    tuple(state.source_ids),
                    revision=2,
                ),
                provenance="run:" + result["run_id"],
            )

    async def _execute_task(self, state):
        while not state.terminal:
            if not await self._ensure_budget(state):
                return
            inputs = self._inputs[state.id]
            input_count = len(inputs)
            context = prepare_context(
                state,
                state.episode_ids[-1] if state.episode_ids else None,
                inputs[-1],
                messages=inputs[:-1],
                source_ids=state.source_ids,
            ).to_dict()
            context["programs"] = self.programs()
            context["memories"] = json_value(
                self.memory.retrieve(MemoryQuery(text=state.objective), limit=8)
            )
            context["memory_review"] = [event.id for event in self.memory.review_batch(limit=10)]
            context["verification_rate"] = self.learning.predict("verified_task_rate")
            context["recent_results"] = self._recent_trace(state.id)
            result = await self._invoke(
                state.id,
                AgentRequest(
                    json.dumps(context, ensure_ascii=False),
                    self._workspace(state.id),
                    instructions=CONSCIOUSNESS_INSTRUCTIONS,
                    mode="exec",
                    output_schema=Decision.model_json_schema(),
                    tools=self._tools(),
                    timeout_seconds=self._remaining_seconds(state),
                ),
                conversation=True,
            )
            decision = Decision.model_validate(result["parsed"])
            if len(inputs) != input_count:
                # An input accepted during the turn must reach the controller
                # before it can deliver an answer or finish this task.
                continue
            state.progress = decision.progress
            if decision.status == "continue":
                self._inputs[state.id].append({"role": "assistant", "content": decision.progress})
                await self.backup()
                continue
            if decision.status == "completed" and self.actions.pending(state.id):
                decision = Decision(
                    status="waiting",
                    answer="An external action has an unknown outcome. Reconcile it before completion.",
                    progress="Waiting for external action reconciliation",
                )
            if decision.status == "completed":
                check = await self._invoke(
                    state.id,
                    AgentRequest(
                        json.dumps(
                            {
                                "specification": state.specification.to_dict(),
                                "answer": decision.answer,
                                "trace": self._recent_trace(state.id),
                            },
                            ensure_ascii=False,
                        ),
                        self._workspace(state.id),
                        instructions=ANSWER_VERIFICATION_INSTRUCTIONS,
                        output_schema=AnswerVerification.model_json_schema(),
                        timeout_seconds=self._remaining_seconds(state),
                    ),
                )
                verification = AnswerVerification.model_validate(check["parsed"])
                if len(inputs) != input_count:
                    continue
                if not verification.verified:
                    self._inputs[state.id].append(
                        {
                            "role": "user",
                            "content": "Verification requires correction: " + verification.reason,
                            "source": "verification",
                        }
                    )
                    continue
            else:
                verification = None
            self._results[state.id] = {"answer": decision.answer}
            delivered = await self._deliver(state.id, decision.answer)
            if state.terminal:
                return
            if not delivered:
                self.tasks.set_waiting(
                    state.id,
                    waiting_for=["delivery"],
                    reason="Answer delivery failed",
                    execution_stopped=True,
                )
                await self._publish("task_waiting", state.id, {"reason": "Answer delivery failed"})
            elif decision.status == "waiting":
                self.tasks.set_waiting(
                    state.id,
                    waiting_for=[decision.answer],
                    reason=decision.progress,
                    execution_stopped=True,
                )
                await self._publish("task_waiting", state.id)
            else:
                await self._stop_task(
                    state,
                    "succeeded" if decision.status == "completed" else "failed",
                    verification.reason if verification else decision.progress,
                    VerificationResult("verified") if verification else None,
                )
            return

    async def _stop_task(self, state, status, reason, verification=None):
        await self.runtime.cancel(state.id)
        self._pending_programs.pop(state.id, None)
        for identity in state.program_run_ids:
            run_id = self._run_map.get(identity)
            if run_id and self.memory.get_run(run_id).status == "running":
                self.memory.finish_run(run_id, status="interrupted")
        self.tasks.finish(
            state.id, status, reason=reason, execution_stopped=True, verification=verification
        )
        if status in {"succeeded", "failed"} and state.id in self._predictions:
            from evertree.core.evaluation.scoring import evaluate_prediction

            run = self.memory.start_run(
                "TaskOutcome", self._program_revision(), {"task_id": state.id}
            )
            observed = status == "succeeded"
            event = self.memory.record(
                run, "verification_outcome", output={"verified": observed, "reason": reason}
            )
            ref = self.memory.output_ref(event)
            outcome_id = "task_verification:" + state.id
            evaluation = self.evaluations.add(
                evaluate_prediction(
                    self._predictions[state.id],
                    observed,
                    metrics=("brier",),
                    outcome_ids=(outcome_id,),
                    provenance=(str(event.id),),
                    subject="verified_task_rate",
                )
            )
            receipt = LearningCoordinator(self.learning).learn(
                LearningSignal(
                    evaluation,
                    LearningObjective(("brier",), "minimize", "runtime_verification"),
                    {outcome_id: observed},
                ),
                "verified_task_rate",
            )
            self.memory.record(
                run, "learning_receipt", arguments={"source": ref}, output=json_value(receipt)
            )
            self.memory.retain(ref, "learning:" + outcome_id)
            self.memory.finish_run(run)
        kind = {
            "succeeded": "task_completed",
            "failed": "task_failed",
            "cancelled": "task_cancelled",
        }[status]
        await self._discard_workspaces(state.id)
        await self._publish(kind, state.id, {"reason": reason})

    def _recent_trace(self, task_id):
        runs = {
            self._run_map[identity]
            for identity in self.tasks.get(task_id).program_run_ids
            if identity in self._run_map
        }
        runs.update(run.id for run in self.memory.runs if run.arguments.get("task_id") == task_id)
        meaningful = []
        for event in self.memory.events:
            if event.program_run not in runs or event.operator == "provider_request":
                continue
            if event.operator == "provider_event" and event.output.get("kind") not in {
                "tool_call",
                "tool_result",
                "file_change",
                "error",
                "completed",
                "cancelled",
            }:
                continue
            meaningful.append(json_value(event))
        # Token deltas and raw SDK notifications stay in the immutable trace,
        # but must not evict actual operation results from verification context.
        return meaningful[-40:]
