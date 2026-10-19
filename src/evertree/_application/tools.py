"""Consciousness tool dispatch and the Program runtime gateway."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

from evertree.core.memory.types import TraceOutputRef

from ..core.programs.lifecycle import git
from ..core.provider import LLMRequest, ToolDefinition
from ..core.runtime.coordination import semantic_scope
from ..core.values import json_value
from .prompts import CANDIDATE_INSTRUCTIONS, CODING_INSTRUCTIONS


class ToolsMixin:
    """Internal EverTree method group; state is owned and initialized by EverTree."""

    async def _tool(self, task_id, name, args, *, semantic_tools=None):
        """Apply task and self-improvement resource limits to a tracked conscious tool callback."""
        args = dict(args)
        purpose = args.pop("purpose", "task")
        if purpose not in {"task", "self_improvement"}:
            raise ValueError("Unknown operation purpose")
        improvement = purpose == "self_improvement"
        state = self.tasks.get(task_id)
        if improvement and not state.remaining("active_time_minutes", self_improvement=True):
            raise PermissionError(
                "Consciousness must allocate or reassess the self-improvement allowance first"
            )
        callback = asyncio.current_task()
        self._tool_tasks.setdefault(task_id, set()).add(callback)
        token = self._improvement.set(improvement)
        try:
            with self._meter(task_id, improvement=improvement):
                remaining = state.remaining("active_time_minutes", self_improvement=improvement)
                async with asyncio.timeout(remaining * 60 if remaining else None):
                    return await self._dispatch_tool(
                        task_id, name, args, semantic_tools=semantic_tools
                    )
        except TimeoutError:
            if name != "graph.search":
                raise
            return self._semantics().results(
                args["query"],
                args.get("kind"),
                [],
                [{"channel": "budget", "error": "Task time budget exhausted"}],
                args.get("limit", 20),
                task_id,
                scope=semantic_scope.get(),
            )
        finally:
            self._tool_tasks[task_id].discard(callback)
            self._improvement.reset(token)

    async def _dispatch_tool(self, task_id, name, args, *, semantic_tools=None):
        """Execute a conscious agent tool within its task and trace authority."""
        from ..core.semantics.tools import WRITE_TOOLS

        state = self.tasks.get(task_id)
        if state.terminal or state.hard_limit_reached:
            raise PermissionError("Task is stopped or its explicit resource limit was reached")
        if name in {"graph." + tool.name for tool in WRITE_TOOLS}:
            if semantic_tools is None:
                raise PermissionError("Graph writes require a scoped consciousness invocation")
            return await semantic_tools.handle(name.removeprefix("graph."), args)
        if name == "list_programs":
            return self.programs()
        if name == "run_program":
            return await self._run_program(task_id, args["program"], args["arguments"])
        if name == "work_on_code":
            return await self._invoke(
                task_id,
                LLMRequest(
                    args["instruction"],
                    self._workspace(task_id),
                    mode="exec",
                    native_coding=True,
                    instructions=CODING_INSTRUCTIONS,
                    timeout_seconds=self._remaining_seconds(state),
                ),
            )
        if name == "graph.search":
            exact = self._semantics().lookup(**args, task_id=task_id, scope=semantic_scope.get())
            if exact is not None:
                return exact
            from ..core.runtime.repository import ProgramExecutionError

            try:
                result = await self._run_program(task_id, "semantic_search", args)
            except ProgramExecutionError as exc:
                return self._semantics().results(
                    args["query"],
                    args.get("kind"),
                    [],
                    [{"channel": "runtime", "error": str(exc)}],
                    args.get("limit", 20),
                    task_id,
                    scope=semantic_scope.get(),
                )
            return result["result"]
        if name == "record_analysis":
            return self._record_analysis(task_id, args)
        if name == "graph.integrate":
            result = await self._run_program(task_id, "knowledge_integration", args)
            return result["result"]
        if name.startswith("graph."):
            return await self._graph_tool(task_id, name, args)
        if name == "recall":
            return json_value(self.memory.retrieve(args["query"], limit=10))
        if name == "create_candidate":
            program = self._program(args["program"], allow_inactive=True)
            candidate = self.lifecycle.create_candidate(
                program.program_id, args["claim"], candidate_name=args.get("candidate_name")
            )
            self._candidate_owners[candidate.id] = task_id
            self.datasets.inherit_exposure("program:" + str(program.program_id), candidate.id)
            return dataclasses.asdict(candidate)
        if name == "propose_program":
            result = self.propose_program(**args)
            self._candidate_owners[result["candidate"]["id"]] = task_id
            return result
        if name == "develop_candidate":
            candidate = self.lifecycle.candidate(args["candidate"])
            result = await self._invoke(
                task_id,
                LLMRequest(
                    json.dumps(
                        {
                            "instruction": args["instruction"],
                            "candidate": dataclasses.asdict(candidate),
                            "program": json_value(self.graph.get(candidate.program_id)),
                        },
                        ensure_ascii=False,
                    ),
                    Path(candidate.workspace),
                    mode="exec",
                    native_coding=True,
                    instructions=CANDIDATE_INSTRUCTIONS,
                    timeout_seconds=self._remaining_seconds(self.tasks.get(task_id)),
                ),
            )
            if git(Path(candidate.workspace), "status", "--porcelain"):
                git(Path(candidate.workspace), "add", "--all")
                git(Path(candidate.workspace), "commit", "-m", candidate.change_claim)
            self.lifecycle.retain_candidate(candidate.id)
            return {
                "candidate": candidate.id,
                "revision": git(Path(candidate.workspace), "rev-parse", "HEAD"),
                "result": result["text"],
            }
        if name == "evaluate_candidate":
            return await self.evaluate_candidate(args["candidate"], task_id=task_id)
        if name == "choose_candidate":
            candidate = self.lifecycle.candidate(args["candidate"])
            binding = self._evaluation_bindings.get(str(candidate.program_id))
            revision = await self.lifecycle.choose(
                args["candidate"],
                args["decision"],
                reason=args["reason"],
                expected_dataset_revision=binding["dataset_revision"] if binding else None,
            )
            return {"revision": revision, "decision": args["decision"]}
        if name == "list_actions":
            return await self.actions.list(args["session"], task_id=task_id)
        if name == "take_action":
            approved = await self._approve(task_id, {"method": "external_action", **args})
            if self.tasks.get(task_id).terminal or self._closed:
                raise PermissionError("Task stopped while waiting for approval")
            return await self.actions.take(
                args["session"],
                args["command"],
                task_id=task_id,
                operation_id=args["operation_id"],
                approved=approved,
            )
        raise ValueError("Unknown EverTree tool: " + name)

    def _semantics(self):
        from ..core.semantics.service import SemanticService

        if self._semantic_service is None or self._semantic_service.graph is not self.graph:
            self._semantic_service = SemanticService(
                self.graph,
                self.memory,
                self.attribution,
                self.semantic_config,
                self.search_index,
                self._core_operations(),
            )
        return self._semantic_service

    async def _graph_tool(self, task_id, name, args):
        """Route shared semantic tools through task-scoped reads and checked writes."""
        from ..core.semantics.reading import fact_card, fact_nodes, resolve
        from ..core.values import timestamp

        if name in {"graph.query", "graph.walk"}:
            return await self._semantics().execute(name, args, {"task_id": task_id})
        if name == "graph.history" and type(args["subject"]) is int:
            return json_value(self.graph.changes_of(args["subject"]))
        if name in {"graph.neighbors", "graph.history"}:
            node = resolve(self.graph, args["subject"])
            if isinstance(node, dict):
                return node
            if name == "graph.history":
                return json_value(self.graph.changes_of(node.id))
            return [
                fact_card(self.graph, f)
                for f in self.graph.facts()
                if node.id in fact_nodes(self.graph, f)
            ]
        if name == "graph.read_property_at":
            subject, prop = (
                resolve(self.graph, args["subject"]),
                resolve(self.graph, args["property"]),
            )
            if isinstance(subject, dict) or isinstance(prop, dict):
                return {"subject": json_value(subject), "property": json_value(prop)}
            return json_value(
                self.attribution.read_property(
                    subject.id,
                    prop.id,
                    valid_at=timestamp(args["valid_at"]) if args.get("valid_at") else None,
                    known_at=timestamp(args["known_at"]) if args.get("known_at") else None,
                    **args.get("parameters", {}),
                )
            )
        return self._core_operations().execute(
            name,
            args,
            metadata={
                "task_id": task_id,
                "program": {"role": "exec", "revision": self._program_revision()},
            },
        )

    def _core_operations(self):
        from ..core.operations import CoreOperations

        return CoreOperations(
            self.graph,
            self.memory,
            self.beliefs,
            self.attribution,
            self.evaluations,
            self.learning,
            self._observations,
            self._protected_nodes,
        )

    def _apply_delta(self, task_id, delta):
        return self._core_operations().apply_delta(
            delta, task_id=task_id, revision=self._program_revision()
        )

    async def _gateway(self, method, payload):
        """Service Program gateway requests with task-scoped model, action and Core capabilities."""
        from ..core.operations import authorize_operation

        payload = dict(payload)
        metadata = payload.pop("_runtime", {})
        task_id = metadata.get("task_id", self.attention.running_task)
        if task_id is None:
            raise PermissionError("No admitted Task")
        state = self.tasks.get(task_id)
        if state.terminal or state.hard_limit_reached:
            raise PermissionError("Task is stopped or its explicit resource limit was reached")
        authorize_operation(method, metadata["program"]["role"])
        if method == "memory.note":
            return self._record_analysis(
                task_id,
                payload,
                producer=metadata["program"]["program_id"],
                revision=metadata["program"]["revision"],
                owner_run=self._run_map.get(metadata.get("run_id")),
            )
        if method.startswith("semantic.") or method in {"graph.query", "graph.walk"}:
            if method in {"semantic.sources", "semantic.write"}:
                metadata = self._semantic_metadata(state, payload, metadata)
            return await self._semantics().execute(method, payload, metadata)
        if method == "resolve_program":
            spec = self._program(payload["program_id"])
            revision = metadata["program"]["revision"]
            return dataclasses.asdict(dataclasses.replace(spec, revision=revision))
        if method == "llm.run":
            tools = tuple(ToolDefinition(**tool) for tool in payload.get("tools", []))
            handler = payload.get("_tool_handler")
            if tools and not callable(handler):
                raise PermissionError("Program tools require a scoped runtime handler")
            budget_policy = self._pending_programs.get(task_id, {}).get("identity") in {
                "task_framing",
                "resource_control",
            }
            seconds = (
                min(
                    300,
                    (
                        state.hard_limits.get("active_time_minutes", float("inf"))
                        - state.spent.get("active_time_minutes", 0)
                    )
                    * 60,
                )
                if budget_policy
                else self._remaining_seconds(state)
            )
            profile_name = payload.get("profile")
            if profile_name not in {None, "remember"}:
                raise ValueError("Unknown model profile")
            profile = getattr(self.semantic_config, profile_name) if profile_name else None
            request = LLMRequest(
                payload["prompt"],
                self._workspace(task_id),
                instructions=payload.get("instructions", ""),
                mode=payload.get("mode", "model"),
                tools=tools,
                output_schema=payload.get("output_schema"),
                model=profile.model if profile else None,
                effort=profile.effort if profile else None,
                timeout_seconds=seconds,
            )
            return await self._invoke(
                task_id,
                request,
                run_ref=self._run_map.get(metadata.get("run_id")),
                tool_handler=handler,
            )
        if method in {"actions.list", "list_actions"}:
            return await self.actions.list(
                payload["session"], task_id=task_id, run_mode=metadata["run_mode"]
            )
        if method in {"actions.take", "take_action"}:
            approved = await self._approve(task_id, {"method": "external_action", **payload})
            if state.terminal or self._closed:
                raise PermissionError("Task stopped while waiting for approval")
            return await self.actions.take(
                payload["session"],
                payload["command"],
                task_id=task_id,
                operation_id=payload["operation_id"],
                run_mode=metadata["run_mode"],
                approved=approved,
            )
        result = self._core_operations().execute(method, payload, metadata=metadata)
        if method == "evaluation.review" and result["queued"]:
            reference = TraceOutputRef(**result["review_ref"])
            self._inputs.setdefault(task_id, []).append(
                {
                    "role": "observation",
                    "content": json.dumps(
                        {
                            "prediction_review": json_value(self.memory.resolve(reference)),
                            "event_id": reference.event_ref,
                        }
                    ),
                }
            )
            self.attention.request_attention(
                task_id, state.attention_priority, reason="Unmatched prediction experience"
            )
        return result
