"""Durable cognitive work products and bounded, resumable integration packets."""

from __future__ import annotations

import asyncio
import hashlib
import json
from uuid import uuid4

from ..common.source_sections import section_context, section_value, source_sections
from ..core.cognition.steps import trace_reference
from ..core.values import json_value

# Service Programs run after integration; their outputs are not experience to integrate.
EVIDENCE_ASSESSMENT_SLUGS = (
    "evidence_assessment",
    "graph_evidence_assessment",
    "program_evidence_assessment",
)


class KnowledgeIntegrationMixin:
    """Runtime owns boundaries and context; the Program owns semantic selection."""

    def _input_version(self, state):
        values = [
            {k: v for k, v in item.items() if k not in {"source_ref", "received_at"}}
            for item in self._inputs[state.id]
            if item.get("role") == "user" or item.get("source_id")
        ]
        observations = [
            event.id
            for event in self.memory.events
            if event.id in self._observations
            and self.memory.get_run(event.program_run).arguments.get("task_id") == state.id
        ]
        return hashlib.sha256(
            json.dumps({"inputs": values, "observations": observations}, sort_keys=True).encode()
        ).hexdigest()

    def _record_analysis(
        self, task_id, value, *, producer="Consciousness", revision=None, owner_run=None
    ):
        ref = self._core_operations().execute(
            "memory.note",
            value,
            metadata={
                "task_id": task_id,
                "owner_run": owner_run,
                "program": {
                    "program_id": producer,
                    "revision": revision or self._program_revision(),
                    "role": "exec",
                },
            },
        )
        self.memory.retain(trace_reference(ref), "task:" + task_id)
        return ref

    def _integration_context(self, state):
        """Collect task requirements and budget for the integration decision."""
        return {
            "task": {
                "id": state.id,
                "specification": state.specification.to_dict(),
                "remaining_active_time_minutes": state.remaining("active_time_minutes"),
                "self_improvement_remaining": state.remaining(
                    "active_time_minutes", self_improvement=True
                ),
            },
        }

    def _semantic_metadata(self, state, payload, metadata):
        """Derive integration authority and stable write scope from the actual running Program."""
        metadata = dict(metadata)
        program = metadata.get("program", {})
        process = self.graph.find("SelfKnowledgeIntegration")
        node = self.graph.get(program["program_id"])
        run_id = metadata.get("run_id")
        recorded_id = self._run_map.get(run_id)
        recorded = self.memory.get_run(recorded_id) if recorded_id is not None else None
        metadata["knowledge_integration_authorized"] = (
            process is not None
            and node.properties.get("process") == process.id
            and program.get("role") == "exec"
            and run_id in state.program_run_ids
            and recorded is not None
            and recorded.status == "running"
            and recorded.program == program.get("program_id")
            and recorded.base_commit_sha == program.get("revision")
        )
        refs = [json_value(trace_reference(ref)) for ref in payload.get("experience_refs", [])]
        checkpoint = state.step_state.get("integration", {})
        if refs and refs == checkpoint.get("experience_refs"):
            metadata["integration_operation_id"] = checkpoint["operation_id"]
            metadata["integration_context"] = checkpoint["context"]
        else:
            operation_id = "run:" + str(metadata.get("run_id"))
            calls = state.step_state.setdefault("integration_calls", {})
            if operation_id not in calls:
                calls[operation_id] = {
                    "experience_refs": refs,
                    "context": self._integration_context(state),
                }
            call = calls[operation_id]
            if refs != call["experience_refs"]:
                raise ValueError("An integration operation cannot replace its experience inputs")
            metadata["integration_operation_id"] = operation_id
            metadata["integration_context"] = call["context"]
        return metadata

    @staticmethod
    def _mark_integrated(state, revision, refs):
        coverage = state.step_state.setdefault("integrated", {}).setdefault(str(revision), [])
        known = {json.dumps(ref, sort_keys=True) for ref in coverage}
        for ref in refs:
            normalized = json_value(trace_reference(ref))
            key = json.dumps(normalized, sort_keys=True)
            if key not in known:
                coverage.append(normalized)
                known.add(key)

    def _experience_refs(self, state):
        """Select every substantive result, excluding integration and provider duplicates."""
        run_ids = {self._run_map[key] for key in state.program_run_ids if key in self._run_map}
        run_ids.update(
            run.id
            for run in self.memory.runs
            if isinstance(run.program, str) and run.arguments.get("task_id") == state.id
        )
        excluded_programs = {
            node.id
            for node in self.graph.nodes(kind="program")
            if node.properties.get("slug")
            in {
                "knowledge_integration",
                "task_framing",
                "resource_control",
                "semantic_search",
                *EVIDENCE_ASSESSMENT_SLUGS,
            }
        }
        excluded = set()
        for run in self.memory.runs:
            parent = (
                self.memory.get_event(run.caller_event).program_run if run.caller_event else None
            )
            if (
                run.program in excluded_programs
                or run.program
                in {
                    "AnswerVerification",
                    "ExperienceFragments",
                    "GraphMutation",
                    "SemanticWrite",
                    "KnowledgeIntegrationDiagnostic",
                    "EvidenceAssessmentDiagnostic",
                }
                or parent in excluded
                or run.arguments.get("owner_run") in excluded
            ):
                excluded.add(run.id)
        refs = []
        for event in self.memory.events:
            if event.program_run not in run_ids or event.program_run in excluded:
                continue
            if event.operator in {
                "provider_request",
                "code_anchors",
                "call_program",
                "conscious_step_started",
                "semantic_write",
            }:
                continue
            if isinstance(event.operator, int):
                operator = self.graph.get(event.operator).name
                if operator.endswith(":memory.note"):
                    continue
            elif event.operator == "memory.note":
                continue
            if event.operator == "conscious_step_result":
                # Notes have their own references; the enclosing step duplicates them.
                continue
            if event.operator == "provider_event":
                kind = event.output.get("kind")
                if kind not in {"tool_result", "file_change", "error", "cancelled"}:
                    continue
                data = event.output.get("data", {})
                if data.get("name") in {"graph.integrate", "record_analysis", "run_program"}:
                    continue
            if event.operator in {"run_started", "step_started"} or event.output is None:
                continue
            refs.append(self.memory.output_ref(event))
        return refs

    def _bounded_experience(self, state, refs):
        """Split large retained values into addressable fragments with an explicit unprocessed tail."""
        fragments = state.step_state.setdefault("fragments", {})
        result = []
        for ref in refs:
            key = json.dumps(json_value(ref), sort_keys=True)
            if key in fragments:
                result.extend(fragments[key])
                continue
            value = json_value(self.memory.resolve(ref))
            analytical = self.memory.get_event(ref.event_ref).operator == "analytical_note"
            encoded = json.dumps(value, ensure_ascii=False)
            if len(encoded) <= 16000:
                result.append(json_value(ref))
                continue
            run = self.memory.start_run(
                "ExperienceFragments", self._program_revision(), {"task_id": state.id}
            )
            parts = []
            content = value["text"] if analytical else value
            for section in source_sections(content):
                selected = section_value(content, section)
                event = self.memory.record(
                    run,
                    "experience_fragment",
                    output={
                        "source_ref": json_value(ref),
                        "encoding": "analytical_text" if analytical else "structured",
                        "note_metadata": {k: v for k, v in value.items() if k != "text"}
                        if analytical
                        else None,
                        "location": section,
                        "context": section_context(content, section),
                        **(
                            {"text": selected} if isinstance(selected, str) else {"value": selected}
                        ),
                    },
                    dependencies=(ref,),
                )
                parts.append(json_value(self.memory.output_ref(event)))
            self.memory.finish_run(run)
            fragments[key] = parts
            result.extend(parts)
        return result

    async def _run_integration(self, task_id, arguments, *, retry=True):
        """Resume saved source sections; execution progress stays outside conscious context."""
        state = self.tasks.get(task_id)
        base_arguments = {
            "experience_refs": arguments["experience_refs"],
            "focus": arguments.get("focus"),
        }
        identity = hashlib.sha256(
            json.dumps(
                {"revision": state.specification.revision, "arguments": base_arguments},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        attempts = state.step_state.setdefault("integration_attempts", {})
        attempt_sources = state.step_state.setdefault("integration_attempt_sources", {})
        attempt_sources[identity] = arguments["experience_refs"]
        saved = attempts.get(identity)
        payload = dict(arguments)
        pending = self._pending_programs.get(task_id)
        if pending and pending["identity"] == "knowledge_integration":
            recorded = self._run_map.get(pending["run_id"])
            if recorded is not None and self.memory.get_run(recorded).status == "failed":
                self._pending_programs.pop(task_id)
                pending = None
        if pending and pending["identity"] == "knowledge_integration":
            payload = pending["arguments"]
            if payload["experience_refs"] != arguments["experience_refs"] or payload.get(
                "focus"
            ) != arguments.get("focus"):
                raise RuntimeError("Resume the pending integration before changing its sources")
        elif saved:
            progress = json.loads(json.dumps(saved))
            if retry:
                progress["pending"] = [entry["unit"] for entry in progress["failed"]] + progress[
                    "pending"
                ]
                progress["failed"] = []
            payload["processing"] = progress
        try:
            output = await self._run_program(task_id, "knowledge_integration", payload)
        except BaseException:
            interrupted = self._pending_programs.get(task_id)
            run = self._run_map.get(interrupted["run_id"]) if interrupted else None
            if run is not None:
                for event in reversed(self.memory.events):
                    if event.program_run == run and event.operator == "integration_processing":
                        attempts[identity] = json_value(event.output)
                        break
            raise
        progress = output["result"].get("processing")
        if progress is not None:
            attempts[identity] = progress
            if retry:
                unfinished = {
                    part["source"]
                    for unit in [
                        *progress["pending"],
                        *(entry["unit"] for entry in progress["failed"]),
                    ]
                    for part in unit["parts"]
                }
                completed = [
                    ref for i, ref in enumerate(arguments["experience_refs"]) if i not in unfinished
                ]
                self._mark_integrated(state, state.specification.revision, completed)
                failed = state.step_state.setdefault("integration_failed", {}).setdefault(
                    str(state.specification.revision), []
                )
                failed[:] = [ref for ref in failed if ref not in completed]
                residual_events = {
                    trace_reference(attempt_sources[key][part["source"]]).event_ref
                    for key, progress in attempts.items()
                    for unit in [
                        *progress["pending"],
                        *(entry["unit"] for entry in progress["failed"]),
                    ]
                    for part in unit["parts"]
                }
                covered = state.step_state["integrated"][str(state.specification.revision)]
                for ref in self._experience_refs(state):
                    pieces = state.step_state.get("fragments", {}).get(
                        json.dumps(json_value(ref), sort_keys=True), [json_value(ref)]
                    )
                    residual_events.update(
                        trace_reference(piece).event_ref for piece in pieces if piece not in covered
                    )
                for ref in completed:
                    event_ref = trace_reference(ref).event_ref
                    if event_ref not in residual_events:
                        self.memory.release(event_ref, "integration_pending:" + state.id)
            await self.backup()
        return output

    def _integration_diagnostic(self, state, checkpoint, error):
        run = self.memory.start_run(
            "KnowledgeIntegrationDiagnostic", self._program_revision(), {"task_id": state.id}
        )
        self.memory.record(
            run,
            "integration_error",
            arguments={"operation_id": checkpoint["operation_id"]},
            output={"error": str(error)},
        )
        self.memory.finish_run(run, status="failed")

    async def _integrate_step(self, state):
        """Attempt one bounded packet between steps without gating the conscious result."""
        work = state.step_state
        checkpoint = work.get("integration")
        if checkpoint is None:
            revision = state.specification.revision
            coverage = work.setdefault("integrated", {}).setdefault(str(revision), [])
            covered = {json.dumps(ref, sort_keys=True) for ref in coverage}
            covered.update(
                json.dumps(ref, sort_keys=True)
                for ref in work.setdefault("integration_failed", {}).get(str(revision), [])
            )
            unreviewed = [
                ref
                for ref in self._experience_refs(state)
                if json.dumps(json_value(ref), sort_keys=True) not in covered
            ]
            refs = self._bounded_experience(state, unreviewed)
            remaining = [ref for ref in refs if json.dumps(ref, sort_keys=True) not in covered]
            if not remaining:
                return False
            batch, size = [], 0
            for ref in remaining:
                cost = len(
                    json.dumps(
                        json_value(self.memory.resolve(trace_reference(ref))), ensure_ascii=False
                    )
                )
                if batch and size + cost > 24000:
                    break
                batch.append(ref)
                size += cost
            checkpoint = {
                "operation_id": uuid4().hex,
                "experience_refs": batch,
                "specification_revision": revision,
                "context": self._integration_context(state),
                "status": "pending",
            }
            work["integration"] = checkpoint
            for reference in remaining:
                self.memory.retain(trace_reference(reference), "task:" + state.id)
            await self.backup()
        if state.hard_limit_reached or state.budget_exhausted:
            return False
        progress = None
        try:
            checkpoint["status"] = "running"
            arguments = {"experience_refs": checkpoint["experience_refs"]}
            if "pending_program" in checkpoint:
                self._pending_programs[state.id] = checkpoint.pop("pending_program")
                arguments = self._pending_programs[state.id]["arguments"]
            output = await self._run_integration(state.id, arguments, retry=False)
            progress = output["result"].get("processing")
            if output["result"].get("error"):
                raise RuntimeError(output["result"]["error"])
        except asyncio.CancelledError:
            checkpoint["status"] = "interrupted"
            raise
        except Exception as exc:  # noqa: BLE001 -- integration cannot block conscious work
            self._integration_diagnostic(state, checkpoint, exc)
            if state.hard_limit_reached or state.budget_exhausted:
                checkpoint["status"] = "interrupted"
                await self.backup()
                return False
            if self._pending_programs.get(state.id, {}).get("identity") == "knowledge_integration":
                self._pending_programs.pop(state.id, None)
            failed = list(checkpoint["experience_refs"])
            completed = []
        else:
            if progress and progress["pending"]:
                checkpoint["status"] = "pending"
                await self.backup()
                return True
            failed_indexes = {
                part["source"]
                for entry in (progress or {}).get("failed", [])
                for part in entry["unit"]["parts"]
            }
            failed = [
                ref for i, ref in enumerate(checkpoint["experience_refs"]) if i in failed_indexes
            ]
            completed = [
                ref
                for i, ref in enumerate(checkpoint["experience_refs"])
                if i not in failed_indexes
            ]
            if failed:
                self._integration_diagnostic(
                    state, checkpoint, "; ".join(entry["error"] for entry in progress["failed"])
                )
        self._mark_integrated(state, checkpoint["specification_revision"], completed)
        failed_refs = work.setdefault("integration_failed", {}).setdefault(
            str(checkpoint["specification_revision"]), []
        )
        failed_refs.extend(ref for ref in failed if ref not in failed_refs)
        work.pop("integration")
        await self.backup()
        await self._assess_evidence(state, checkpoint["experience_refs"])
        return True

    async def _drain_integration(self, state):
        """Consider remaining sections serially without exceeding the existing task allowance."""
        while not state.hard_limit_reached and not state.budget_exhausted:
            if not await self._integrate_step(state):
                break

    def _integration_status(self, state):
        """Report processed source pieces and real residuals, without claiming fact completeness."""
        revision = str(state.specification.revision)
        covered = {
            json.dumps(ref, sort_keys=True)
            for ref in state.step_state.get("integrated", {}).get(revision, [])
        }
        failed = {
            json.dumps(ref, sort_keys=True)
            for ref in state.step_state.get("integration_failed", {}).get(revision, [])
        }
        roots = self._experience_refs(state)
        root_keys = {json.dumps(json_value(ref), sort_keys=True) for ref in roots}
        remaining = [
            ref for ref in roots if json.dumps(json_value(ref), sort_keys=True) not in covered
        ]
        units = {
            json.dumps(ref, sort_keys=True) for ref in self._bounded_experience(state, remaining)
        }
        processed = len(root_keys & covered) + len(units & covered)
        failed_count = len(units & failed)
        pending = len(units - covered - failed)
        return {
            "status": "incomplete" if pending or failed_count else "processed",
            "processed_sources": processed,
            "pending_sources": pending,
            "failed_sources": failed_count,
        }

    async def _assess_evidence(self, state, experience_refs):
        """Assess integrated experience as evidence; failures stay diagnostics, not step errors.

        Elements left unassessed by a failure stay pending for the next assessment.
        """
        if state.hard_limit_reached or state.budget_exhausted:
            return
        try:
            await self._run_program(
                state.id, "evidence_assessment", {"experience_refs": experience_refs}
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- assessment cannot block conscious work
            run = self.memory.start_run(
                "EvidenceAssessmentDiagnostic", self._program_revision(), {"task_id": state.id}
            )
            self.memory.record(run, "evidence_assessment_error", output={"error": str(exc)})
            self.memory.finish_run(run, status="failed")
            if self._pending_programs.get(state.id, {}).get("identity") == "evidence_assessment":
                self._pending_programs.pop(state.id, None)
        await self.backup()
