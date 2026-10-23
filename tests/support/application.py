from __future__ import annotations

import asyncio
import json

import pytest

from evertree.core.provider import LLMEvent, ScriptedProvider


def is_integration_request(request):
    return {"save_note", "update"} <= {tool.name for tool in request.tools}


def is_evidence_request(request):
    """Recognize the graph evidence assessment judgement by its output schema."""
    targets = (request.output_schema or {}).get("properties", {}).get("targets", {})
    return "evidence" in targets.get("items", {}).get("properties", {})


async def tool_events(request_id, request, handler, calls, *, finish=True):
    """Exercise the provider's native callback boundary with correlated events."""
    declared = {tool.name for tool in request.tools}
    calls = list(calls)
    if (
        finish
        and "finish_section" in declared
        and not any(name == "finish_section" for name, _ in calls)
    ):
        calls.append(("finish_section", {"complete": True, "remaining": ""}))
    yield LLMEvent("session", {"provider": "scripted", "id": request_id})
    for index, (name, arguments) in enumerate(calls):
        assert name in declared
        call = {"call_id": f"{request_id}:{index}", "name": name, "arguments": arguments}
        yield LLMEvent("tool_call", call)
        result = await handler(name, arguments)
        yield LLMEvent(
            "tool_result",
            {
                "call_id": call["call_id"],
                "name": name,
                "status": "completed",
                "result": result,
                "error": None,
            },
        )
    yield LLMEvent("completed", {"text": ""})


class IntegrationScriptedProvider(ScriptedProvider):
    """Complete automatic selection with no writes and assessment with no evidence.

    Tests that select knowledge or judge evidence script those requests themselves.
    """

    @property
    def task_requests(self):
        return [
            request
            for request in self.requests
            if not is_integration_request(request) and not is_evidence_request(request)
        ]

    async def run(self, request_id, request, **kwargs):
        if is_evidence_request(request):
            self.requests.append(request)
            for event in completed({"targets": [], "origins": [], "scopes": []}):
                yield event
            return
        if not is_integration_request(request):
            async for event in super().run(request_id, request, **kwargs):
                yield event
            return
        self.requests.append(request)
        async for event in tool_events(request_id, request, kwargs["tool_handler"], []):
            yield event


def completed(data):
    return [LLMEvent("completed", {"text": json.dumps(data), "parsed": data})]


def framing(objective="Count r in strawberry", minutes=3, improvement=0):
    return completed(
        {
            "objective": objective,
            "success_criteria": ["Use the supplied sources"],
            "constraints": [],
            "preferences": [],
            "execution_budget": {"active_time_minutes": minutes},
            "self_improvement_budget": improvement,
            "budget_reason": "Small task with a precise check",
            "initial_step": {
                "local_goal": objective,
                "expected_result": "A checked local result or a specific remaining question",
                "active_time_minutes": min(1, minutes),
            },
        }
    )


def budget_review(objective="Count r in strawberry", minutes=3, improvement=0):
    result = framing(objective, minutes, improvement)[0].data["parsed"]
    return completed(
        {
            key: result[key]
            for key in ("execution_budget", "self_improvement_budget", "budget_reason")
        }
    )


def decision(answer="3", status="completed"):
    return completed(
        {
            "analysis": {"text": "Current result: " + answer, "source_refs": []},
            "disposition": "propose_completion" if status == "completed" else status,
            "user_message": answer if status != "continue" else None,
            "progress": "Selected work complete",
            "next_step": {
                "local_goal": "Resolve the remaining local question",
                "expected_result": "A verified result or narrower uncertainty",
                "active_time_minutes": 1,
            }
            if status == "continue"
            else None,
        }
    )


def verification(verified=True):
    return completed(
        {
            "verified": verified,
            "reason": "Source and calculation checked" if verified else "Recheck calculation",
        }
    )


async def wait_for_event(agent, kind, *, timeout=45):
    seen = []
    if not hasattr(agent, "_test_event_stream"):
        agent._test_event_stream = agent.events()
    async with asyncio.timeout(timeout):
        while True:
            event = await anext(agent._test_event_stream)
            seen.append(event)
            if event.kind in {"task_failed", "task_cancelled"} and event.kind != kind:
                pytest.fail(f"Task ended before {kind}: {event.data}")
            if event.kind == kind:
                return event, seen
