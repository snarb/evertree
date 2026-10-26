"""Consciousness tool dispatch and the Program runtime gateway."""

from __future__ import annotations

import asyncio
import dataclasses
import json

from evertree.core.memory.types import TraceOutputRef

from ..core.provider import LLMRequest, ToolDefinition
from ..core.runtime.coordination import semantic_scope
from ..core.semantics.reading import belief_summary
from ..core.values import json_value
from .prompts import CODING_INSTRUCTIONS, LIFECYCLE_TOOLS, RESULTS_PROMPT_CHARS, bounded_event


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
            return self._semantics().failed_search(
                args["queries"],
                [{"channel": "budget", "error": "Task time budget exhausted"}],
                kinds=args.get("kinds"),
                limit=args.get("limit", 10),
                task_id=task_id,
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
                return self._semantics().failed_search(
                    args["queries"],
                    [{"channel": "runtime", "error": str(exc)}],
                    kinds=args.get("kinds"),
                    limit=args.get("limit", 10),
                    task_id=task_id,
                    scope=semantic_scope.get(),
                )
            return result["result"]
        if name == "record_analysis":
            return self._record_analysis(task_id, args)
        if name == "graph.integrate":
            result = await self._run_integration(task_id, args)
            output = dict(result["result"])
            if "processing" in output:
                progress = output["processing"]
                output["processing"] = {
                    "status": progress["status"],
                    "processed_units": len(progress["completed"]),
                    "pending_units": len(progress["pending"]),
                    "failed_units": len(progress["failed"]),
                }
            return output
        if name.startswith("graph."):
            return await self._graph_tool(task_id, name, args)
        if name == "recall":
            # Best groups first, within the same budget as recent results.
            recalled, size = [], 0
            for group in self.memory.retrieve(args["query"], limit=10):
                item = {
                    **json_value(group),
                    "events": [bounded_event(json_value(event)) for event in group.events],
                }
                size += len(json.dumps(item, ensure_ascii=False, default=str))
                if recalled and size > RESULTS_PROMPT_CHARS:
                    break
                recalled.append(item)
                self._surfaced.update(event.id for event in group.events)
            return recalled
        if name == "read_source":
            return await self._semantics().execute("memory.read_source", args, {"task_id": task_id})
        if name in LIFECYCLE_TOOLS:
            return await self._lifecycle_operation(task_id, name, args)
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

    async def _lifecycle_operation(self, task_id, name, args, *, caller=None):
        """Serve one lifecycle operation for consciousness tools or a meta Program.

        caller is the meta Program's id. A meta Program never manages candidates of
        its own slot, alternatives included: its changes need an independent decision.
        """
        if caller is not None:
            target = (
                args.get("program")
                if name in {"create_candidate", "propose_program", "derive_holdout"}
                else None
            )
            targets = [target] if target is not None else []
            targets.extend(
                self.lifecycle.candidate(identity).program_id
                for identity in [args.get("candidate"), *args.get("candidates", ())]
                if identity is not None
            )
            if name == "propose_program" and args.get("alternative_to") is not None:
                targets.append(args["alternative_to"])
            own = self._slot(caller)
            if any(
                self._slot(self._program(identity, allow_inactive=True).program_id) == own
                for identity in targets
            ):
                raise PermissionError("A meta Program cannot manage its own candidates")
        if name == "list_programs":
            return [
                {
                    "id": node.id,
                    "name": node.name,
                    "description": node.description,
                    **{
                        key: node.properties.get(key)
                        for key in (
                            "process",
                            "role",
                            "roles",
                            "lifecycle_status",
                            "alternative_to",
                        )
                    },
                    "belief": belief_summary(self.graph, node),
                    "operators": self._operators(node.id),
                }
                for node in self.graph.nodes(kind="program")
            ]
        if name == "create_candidate":
            return self.create_candidate(
                task_id, args["program"], args["claim"], candidate_name=args.get("candidate_name")
            )
        if name == "propose_program":
            result = self.propose_program(**args)
            self._own(task_id, result["candidate"]["id"])
            return result
        if name == "develop_candidate":
            return await self.develop_candidate(task_id, args["candidate"], args["instruction"])
        if name == "evaluate_candidate":
            return await self.evaluate_candidate(args["candidate"], task_id=task_id)
        if name == "compare_candidates":
            return self.compare_candidates(args["candidates"])
        if name == "derive_holdout":
            return self.derive_holdout(args["program"])
        if name == "refresh_candidate":
            return self.refresh_candidate(task_id, args["candidate"])
        if name == "choose_candidate":
            return await self.choose_candidate(
                task_id, args["candidate"], args["decision"], args["reason"]
            )
        raise ValueError("Unknown lifecycle operation: " + name)

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

        if name in {"graph.query", "graph.walk", "graph.sources"}:
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
        if name in {"graph.read_property", "graph.read_property_at", "graph.select_properties"}:
            from ..core.attribution_sources import read_property, select_properties

            async def step(method, payload):
                return self._core_operations().execute(
                    method,
                    payload,
                    metadata={
                        "task_id": task_id,
                        "program": {"role": "model", "revision": self._program_revision()},
                    },
                )

            async def call(program, arguments):
                return await self._run_program(task_id, program, arguments)

            if name == "graph.select_properties":
                payload = dict(args)
                payload["valid_at"] = payload.pop("at", None)
                return await select_properties(step, call, **payload)
            return await read_property(
                step,
                call,
                args["subject"],
                args["property"],
                valid_at=args.get("at", args.get("valid_at")),
                known_at=args.get("known_at"),
                parameters=args.get("parameters"),
                point_policy=args.get("point_policy"),
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
        authorize_operation(
            method, metadata["program"]["role"], meta=metadata["program"].get("meta", False)
        )
        if method.startswith("program."):
            if metadata["run_mode"] != "live":
                raise PermissionError("Lifecycle operations run only in live execution")
            return await self._lifecycle_operation(
                task_id,
                method.removeprefix("program."),
                payload,
                caller=metadata["program"]["program_id"],
            )
        if method == "memory.note":
            return self._record_analysis(
                task_id,
                payload,
                producer=metadata["program"]["program_id"],
                revision=metadata["program"]["revision"],
                owner_run=self._run_map.get(metadata.get("run_id")),
            )
        if method.startswith("semantic.") or method in {
            "graph.query",
            "graph.walk",
            "graph.sources",
            "memory.read_source",
        }:
            if method in {"semantic.sources", "semantic.prepare_sources", "semantic.write"}:
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
        if method in {"memory.retrieve", "memory.rank"}:
            self._surfaced.update(
                event["id"] for group in result for event in group.get("events", ())
            )
        elif method == "memory.resolve":
            self._surfaced.add(payload["reference"]["event_ref"])
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
