"""Consciousness tool dispatch and the Program runtime gateway."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

from ..core.graph import GraphDelta, Node
from ..core.lifecycle import git
from ..core.memory import TraceOutputRef
from ..core.provider import AgentRequest
from ..core.values import json_value
from .prompts import CANDIDATE_INSTRUCTIONS, CODING_INSTRUCTIONS


class ToolsMixin:
    """Internal EverTree method group; state is owned and initialized by EverTree."""

    async def _tool(self, task_id, name, args):
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
                    return await self._dispatch_tool(task_id, name, args)
        finally:
            self._tool_tasks[task_id].discard(callback)
            self._improvement.reset(token)

    async def _dispatch_tool(self, task_id, name, args):
        state = self.tasks.get(task_id)
        if state.terminal or state.hard_limit_reached:
            raise PermissionError("Task is stopped or its explicit resource limit was reached")
        if name == "list_programs":
            return self.programs()
        if name == "run_program":
            return await self._run_program(task_id, args["program"], args["arguments"])
        if name == "work_on_code":
            return await self._invoke(
                task_id,
                AgentRequest(
                    args["instruction"],
                    self._workspace(task_id),
                    mode="exec",
                    native_coding=True,
                    instructions=CODING_INSTRUCTIONS,
                    timeout_seconds=self._remaining_seconds(state),
                ),
            )
        if name == "read_graph":
            node = (
                self.graph.get(args["id"])
                if "id" in args
                else self.graph.find(args.get("name", ""))
            )
            return json_value(node) if node else None
        if name == "recall":
            return json_value(self.memory.retrieve(args["query"], limit=10))
        if name == "remember":
            node = Node(self.graph.reserve_id(), args["name"], description=args["description"])
            self._apply_delta(task_id, GraphDelta(creates=(node,)))
            return json_value(node)
        if name == "create_candidate":
            self._program(args["program"], allow_inactive=True)
            candidate = self.lifecycle.create_candidate(args["program"], args["claim"])
            self._candidate_owners[candidate.id] = task_id
            self.datasets.inherit_exposure("program:" + str(args["program"]), candidate.id)
            return dataclasses.asdict(candidate)
        if name == "propose_program":
            result = self.propose_program(**args)
            self._candidate_owners[result["candidate"]["id"]] = task_id
            return result
        if name == "develop_candidate":
            candidate = self.lifecycle.candidate(args["candidate"])
            result = await self._invoke(
                task_id,
                AgentRequest(
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
            delta, task_id=task_id, revision=git(self.repository, "rev-parse", "main")
        )

    async def _gateway(self, method, payload):
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
        if method == "resolve_program":
            spec = self._program(payload["program_id"])
            revision = metadata["program"]["revision"]
            return dataclasses.asdict(dataclasses.replace(spec, revision=revision))
        if method == "agent.run":
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
            request = AgentRequest(
                payload["prompt"],
                self._workspace(task_id),
                instructions=payload.get("instructions", ""),
                mode="model",
                output_schema=payload.get("output_schema"),
                timeout_seconds=seconds,
            )
            return await self._invoke(
                task_id, request, run_ref=self._run_map.get(metadata.get("run_id"))
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
