"""Conscious decision loop, task verification and outcome learning."""

from __future__ import annotations

import asyncio
import json

from evertree.core.cognition.steps import ConsciousStepResult, ConsciousStepSpec
from evertree.core.cognition.tasks import TaskSpecification
from evertree.core.evaluation.acceptance import VerificationResult
from evertree.core.learning.contracts import LearningObjective, LearningSignal
from evertree.core.learning.coordinator import LearningCoordinator
from evertree.core.memory.types import MemoryQuery, TraceOutputRef

from ..core.provider import AgentRequest
from ..core.values import json_value
from .prompts import (
    ANSWER_VERIFICATION_INSTRUCTIONS,
    CONSCIOUSNESS_INSTRUCTIONS,
    AnswerVerification,
    tool_sets,
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
                if pending and pending["identity"] == "knowledge_integration":
                    operation_id = "run:" + pending["run_id"]
                    checkpoint = state.step_state.setdefault(
                        "integration",
                        {
                            "operation_id": operation_id,
                            "experience_refs": pending["arguments"]["experience_refs"],
                            "specification_revision": state.specification.revision,
                            "context": state.step_state.get("integration_calls", {})
                            .get(operation_id, {})
                            .get("context", self._integration_context(state)),
                            "status": "interrupted",
                        },
                    )
                    # Budget review can run before the interrupted workflow resumes.
                    checkpoint["pending_program"] = self._pending_programs.pop(identity)
                    pending = None
                if pending:
                    if pending["identity"] in {"task_framing", "resource_control"}:
                        if not await self._ensure_budget(state):
                            self.attention._queue.pop(identity, None)
                            continue
                    else:
                        recovered = await self._run_program(
                            identity, pending["identity"], pending["arguments"]
                        )
                        run_id = self._run_map[recovered["run_id"]]
                        event_id = self.memory.semantic_trace(run_id).events[-1]
                        ref = self.memory.output_ref(self.memory.get_event(event_id))
                        state.step_state["recovered_program_ref"] = json_value(ref)
                        self.memory.retain(ref, "task:" + identity)
                        state.step_state["status"] = "result_ready"
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
            or set(state.source_ids) != set(state.specification.source_ids)
            or pending
            and pending["identity"] in {"task_framing", "resource_control"}
        ):
            await self._frame(state)
            if state.hard_limit_reached:
                return await self._ensure_budget(state)
        return True

    async def _frame(self, state):
        source_ids = tuple(state.source_ids)
        context = {**state.to_dict(), "inputs": list(self._inputs[state.id])}
        hard_remaining = state.hard_limits.get(
            "active_time_minutes", float("inf")
        ) - state.spent.get("active_time_minutes", 0)
        if hard_remaining <= 0:
            raise RuntimeError("User-defined resource limit reached")
        pending = self._pending_programs.get(state.id)
        if pending and pending["identity"] in {"task_framing", "resource_control"}:
            identity, arguments = pending["identity"], pending["arguments"]
            if identity == "task_framing":
                source_ids = tuple(arguments["context"]["source_ids"])
        elif state.execution_budget is None or set(state.source_ids) != set(
            state.specification.source_ids
        ):
            identity = "task_framing"
            arguments = {"request": self._inputs[state.id][-1]["content"], "context": context}
        else:
            identity = "resource_control"
            arguments = {"task_state": context, "evidence": {"trace": self._recent_trace(state.id)}}
        result = await self._run_program(
            state.id, identity, arguments, timeout=min(300, hard_remaining * 60)
        )
        self._accept_frame(state, result, revise=identity == "task_framing", source_ids=source_ids)
        await self._publish(
            "budget",
            state.id,
            {
                "execution_budget": state.execution_budget.to_dict(),
                "self_improvement_budget": state.self_improvement_budget,
            },
        )

    def _accept_frame(self, state, result, *, revise=True, source_ids=None):
        data = result["result"]
        self.tasks.assign_budget(
            state.id,
            data["execution_budget"],
            data["self_improvement_budget"],
            reason=data["budget_reason"],
        )
        if revise:
            self.tasks.revise_specification(
                state.id,
                TaskSpecification(
                    data["objective"],
                    tuple(data["success_criteria"]),
                    tuple(data["constraints"]),
                    tuple(data["preferences"]),
                    tuple(state.source_ids) if source_ids is None else source_ids,
                    revision=state.specification.revision + 1,
                ),
                provenance="run:" + result["run_id"],
            )

        if data.get("initial_step") is not None:
            state.current_step = ConsciousStepSpec.model_validate(data["initial_step"]).model_dump(
                mode="json"
            )

    async def _verification_waiting(self, state, reason):
        self.tasks.set_waiting(
            state.id, waiting_for=["verification"], reason=reason, execution_stopped=True
        )
        await self._publish("task_waiting", state.id, {"reason": reason})
        await self.backup()

    async def _execute_task(self, state):
        while not state.terminal:
            if not await self._ensure_budget(state):
                return
            if set(state.source_ids) != set(state.specification.source_ids):
                continue
            inputs = self._inputs[state.id]
            for incoming in inputs:
                if incoming.get("role") == "user" and incoming.get("source_id"):
                    value = {key: value for key, value in incoming.items() if key != "source_ref"}
                    incoming["source_ref"] = json_value(
                        self.observe(
                            value, source_id="input:" + incoming["source_id"], task_id=state.id
                        )
                    )
            work = state.step_state
            if work.get("integration") or work.get("status") in {
                "result_ready",
                "interrupted",
                "running",
            }:
                await self._integrate_step(state)
            if set(state.source_ids) != set(state.specification.source_ids):
                continue
            version = self._input_version(state)
            saved = work.get("pending_result")
            if saved and (
                work.get("input_version") != version
                or work.get("specification_revision") != state.specification.revision
            ):
                work.pop("pending_result", None)
                work["status"] = "superseded"
                continue
            if saved:
                decision = ConsciousStepResult.model_validate(saved)
            else:
                spec = ConsciousStepSpec.model_validate(state.current_step)
                seconds = min(spec.active_time_minutes * 60, self._remaining_seconds(state))
                admitted_step = spec.model_copy(
                    update={"active_time_minutes": seconds / 60}
                ).model_dump(mode="json")
                context = self._conscious_context(state, admitted_step)
                work.update(
                    status="running",
                    input_version=version,
                    specification_revision=state.specification.revision,
                )
                await self.backup()
                try:
                    async with asyncio.timeout(seconds):
                        result = await self._invoke(
                            state.id,
                            AgentRequest(
                                json.dumps(context, ensure_ascii=False, indent=2),
                                self._workspace(state.id),
                                instructions=CONSCIOUSNESS_INSTRUCTIONS,
                                mode="exec",
                                output_schema=ConsciousStepResult.model_json_schema(),
                                tools=self._tools(),
                                tool_sets=tool_sets(),
                                timeout_seconds=seconds,
                            ),
                            conversation=True,
                        )
                    decision = ConsciousStepResult.model_validate(result["parsed"])
                    for note in [decision.analysis, *decision.findings]:
                        for reference in note.source_refs:
                            self.memory.resolve(reference)
                except asyncio.CancelledError:
                    work["status"] = "interrupted"
                    raise
                except (TimeoutError, ValueError) as exc:
                    work["status"] = "interrupted"
                    work["interruption_reason"] = str(exc) or "Step time budget reached"
                    await self._integrate_step(state)
                    if state.status != "waiting":
                        self.tasks.set_waiting(
                            state.id,
                            waiting_for=["resume"],
                            reason=work["interruption_reason"],
                            execution_stopped=True,
                        )
                        await self._publish(
                            "task_waiting", state.id, {"reason": work["interruption_reason"]}
                        )
                    return
                record = decision.model_dump(mode="json")
                note_refs = [
                    self._record_analysis(state.id, note.model_dump(mode="json"))
                    for note in [decision.analysis, *decision.findings]
                ]
                run = self.memory.start_run(
                    "ConsciousStep", self._program_revision(), {"task_id": state.id}
                )
                event = self.memory.record(run, "conscious_step_result", output=decision)
                self.memory.finish_run(run)
                state.last_step_ref = json_value(self.memory.output_ref(event))
                self.memory.retain(self.memory.output_ref(event), "task:" + state.id)
                work.setdefault("history", []).append(state.last_step_ref)
                work.update(
                    status="result_ready",
                    pending_result=record,
                    analysis_ref=note_refs[0],
                    finding_refs=note_refs[1:],
                )
                state.progress = decision.progress
                state.plan = decision.plan
                state.unresolved_questions = decision.unresolved_questions
                await self.backup()
                await self._integrate_step(state)
            if (
                version != self._input_version(state)
                or work.get("specification_revision") != state.specification.revision
            ):
                work.pop("pending_result", None)
                work["status"] = "superseded"
                continue
            if decision.disposition == "propose_completion" and self.actions.pending(state.id):
                self.tasks.set_waiting(
                    state.id,
                    waiting_for=["external_action"],
                    reason="External action outcome requires reconciliation",
                    execution_stopped=True,
                )
                await self._publish("task_waiting", state.id, {"reason": state.progress})
                return
            verification = None
            if decision.disposition == "propose_completion":
                if state.budget_exhausted or state.hard_limit_reached:
                    await self._verification_waiting(
                        state, "Insufficient budget for independent completion verification"
                    )
                    return
                try:
                    check = await self._invoke(
                        state.id,
                        AgentRequest(
                            json.dumps(
                                {
                                    "specification": self._prompt_specification(state),
                                    "answer": decision.user_message,
                                    "trace": self._prompt_results(state),
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                            self._workspace(state.id),
                            instructions=ANSWER_VERIFICATION_INSTRUCTIONS,
                            output_schema=AnswerVerification.model_json_schema(),
                            timeout_seconds=self._remaining_seconds(state),
                        ),
                        run_name="AnswerVerification",
                    )
                    verification = AnswerVerification.model_validate(check["parsed"])
                except (TimeoutError, ValueError) as exc:
                    await self._verification_waiting(
                        state, "Completion verification interrupted: " + str(exc)
                    )
                    return
                if (
                    version != self._input_version(state)
                    or work.get("specification_revision") != state.specification.revision
                ):
                    work.pop("pending_result", None)
                    work["status"] = "superseded"
                    continue
                if not verification.verified:
                    work.pop("pending_result", None)
                    work["verification_feedback"] = verification.reason
                    state.current_step = ConsciousStepSpec(
                        local_goal="Correct the independently identified gap: "
                        + verification.reason,
                        expected_result="Checked correction and updated completion proposal",
                        active_time_minutes=min(
                            1.0, max(0.001, state.remaining("active_time_minutes"))
                        ),
                    ).model_dump(mode="json")
                    work["status"] = "ready"
                    continue
            delivered = True
            if decision.user_message is not None:
                self._results[state.id] = {"answer": decision.user_message}
                delivered = await self._deliver(state.id, decision.user_message)
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
                return
            if (
                version != self._input_version(state)
                or work.get("specification_revision") != state.specification.revision
            ):
                work.pop("pending_result", None)
                work["status"] = "superseded"
                continue
            work.pop("pending_result", None)
            work["status"] = "processed"
            if decision.disposition == "continue":
                state.current_step = decision.next_step.model_dump(mode="json")
                await self.backup()
                continue
            if decision.disposition == "waiting":
                if decision.next_step is not None:
                    state.current_step = decision.next_step.model_dump(mode="json")
                self.tasks.set_waiting(
                    state.id,
                    waiting_for=decision.unresolved_questions or ["resume"],
                    reason=decision.progress,
                    execution_stopped=True,
                )
                await self._publish("task_waiting", state.id)
            else:
                await self._stop_task(
                    state,
                    "succeeded" if decision.disposition == "propose_completion" else "failed",
                    verification.reason if verification else decision.progress,
                    VerificationResult("verified") if verification else None,
                )
            return

    async def _stop_task(self, state, status, reason, verification=None):
        await self.runtime.cancel(state.id)
        self._pending_programs.pop(state.id, None)
        if self._semantic_service is not None:
            self._semantic_service.release(state.id)
        for identity in state.program_run_ids:
            run_id = self._run_map.get(identity)
            if run_id and self.memory.get_run(run_id).status == "running":
                self.memory.finish_run(run_id, status="interrupted")
        self.tasks.finish(
            state.id, status, reason=reason, execution_stopped=True, verification=verification
        )
        for event in self.memory.events:
            self.memory.release(event.id, "task:" + state.id)
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

    @staticmethod
    def _prompt_specification(state):
        specification = state.specification.to_dict()
        return {
            key: specification[key]
            for key in ("objective", "success_criteria", "constraints", "preferences")
        }

    def _prompt_event(self, event):
        def name(identity):
            if not isinstance(identity, int):
                return identity
            matches = self.graph.lookup(identity)
            return matches[0].name if matches else identity

        run = self.memory.get_run(event["program_run"])
        result = {
            "reference": {"event_ref": event["id"], "output_path": []},
            "program": name(run.program),
            "operation": name(event["operator"]),
            "status": event["status"],
            "output": event["output"],
        }
        if run.run_mode != "live":
            result["run_mode"] = run.run_mode
        if event["arguments"]:
            result["arguments"] = event["arguments"]
        return result

    def _prompt_excluded_runs(self):
        service_programs = {
            node.id
            for node in self.graph.nodes(kind="program")
            if node.properties.get("slug")
            in {"knowledge_integration", "task_framing", "resource_control"}
        }
        excluded = {
            event.program_run
            for event in self.memory.events
            if event.operator == "graph_delta"
            and (event.arguments or {}).get("integration_operation_id")
        }
        for run in self.memory.runs:
            parent = (
                self.memory.get_event(run.caller_event).program_run if run.caller_event else None
            )
            if (
                run.program in service_programs
                or run.program
                in {"KnowledgeIntegrationDiagnostic", "SemanticWrite", "AnswerVerification"}
                or parent in excluded
                or run.arguments.get("owner_run") in excluded
            ):
                excluded.add(run.id)
        return excluded

    def _prompt_results(self, state):
        excluded = self._prompt_excluded_runs()
        results = []
        for event in self._recent_trace(state.id, limit=None):
            if event["program_run"] in excluded or event["operator"] in {
                "conscious_step_result",
                "analytical_note",
                "code_anchors",
                "run_started",
                "step_started",
            }:
                continue
            if event["operator"] == "provider_event":
                output = event["output"]
                if output.get("kind") in {"completed", "tool_call"} or output.get("data", {}).get(
                    "name"
                ) in {"graph.integrate", "record_analysis"}:
                    continue
            if event["output"] is not None:
                results.append(self._prompt_event(event))
        return results[-40:]

    def _conscious_context(self, state, admitted_step):
        work = state.step_state
        inputs = [
            {key: item[key] for key in ("role", "content", "source_ref") if key in item}
            for item in self._inputs[state.id]
        ]
        result = {
            "specification": self._prompt_specification(state),
            "incoming": inputs[-1],
            "messages": inputs[:-1],
            "state": {
                "current_step": admitted_step,
                "plan": state.plan,
                "progress": state.progress,
                "unresolved_questions": state.unresolved_questions,
                "remaining": {
                    key: state.remaining(key) for key in state.execution_budget.resources
                },
                "self_improvement_remaining": {
                    key: state.remaining(key, self_improvement=True)
                    for key in state.execution_budget.resources
                },
                "step_state": {
                    key: work[key]
                    for key in (
                        "analysis_ref",
                        "finding_refs",
                        "verification_feedback",
                        "interruption_reason",
                    )
                    if key in work
                },
            },
            "programs": [
                {"id": node.id, "name": node.name, "description": node.description}
                for node in self.graph.nodes(kind="program")
                if node.properties.get("active", True)
            ],
            "recent_results": self._prompt_results(state),
        }
        input_events = {
            item["source_ref"]["event_ref"] for item in inputs if item.get("source_ref")
        }
        result["recent_results"] = [
            item
            for item in result["recent_results"]
            if item["reference"]["event_ref"] not in input_events
        ]
        known = input_events | {item["reference"]["event_ref"] for item in result["recent_results"]}
        for ref in [state.last_step_ref, work.get("analysis_ref"), *work.get("finding_refs", [])]:
            if ref:
                known.add(ref["event_ref"])
        excluded = self._prompt_excluded_runs()
        result["memories"] = [
            self._prompt_event(json_value(group.events[-1]))
            for group in self.memory.retrieve(MemoryQuery(text=state.objective), limit=8)
            if group.events[-1].id not in known
            and group.events[-1].output is not None
            and group.events[-1].program_run not in excluded
            and group.events[-1].operator
            not in {
                "provider_request",
                "provider_event",
                "run_started",
                "step_started",
                "code_anchors",
                "conscious_step_result",
            }
        ]
        if work.get("recovered_program_ref"):
            result["recovered_program_result"] = {
                "reference": work["recovered_program_ref"],
                "result": json_value(
                    self.memory.resolve(TraceOutputRef(**work["recovered_program_ref"]))
                ),
            }
        # Working Notes remain available regardless of graph materialization.
        if state.last_step_ref:
            result["last_step_ref"] = state.last_step_ref
            result["last_step_result"] = json_value(
                self.memory.resolve(TraceOutputRef(**state.last_step_ref))
            )
        result["previous_step_results"] = [
            {"reference": ref, "result": json_value(self.memory.resolve(TraceOutputRef(**ref)))}
            for ref in work.get("history", [])[-3:]
            if ref != state.last_step_ref
        ]
        return result

    def _recent_trace(self, task_id, *, limit=40):
        runs = {
            self._run_map[identity]
            for identity in self.tasks.get(task_id).program_run_ids
            if identity in self._run_map
        }
        runs.update(
            run.id
            for run in self.memory.runs
            if isinstance(run.program, str) and run.arguments.get("task_id") == task_id
        )
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
        return meaningful if limit is None else meaningful[-limit:]
