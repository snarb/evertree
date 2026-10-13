from __future__ import annotations

import asyncio
import json

import pytest

from evertree.core.provider import AgentEvent, ScriptedProvider


def is_integration_request(request):
    return {"save_note", "finish"} <= {tool.name for tool in request.tools}


async def tool_events(request_id, request, handler, calls):
    """Exercise the provider's native callback boundary with correlated events."""
    declared = {tool.name for tool in request.tools}
    yield AgentEvent("session", {"provider": "scripted", "id": request_id})
    for index, (name, arguments) in enumerate(calls):
        assert name in declared
        call = {"call_id": f"{request_id}:{index}", "name": name, "arguments": arguments}
        yield AgentEvent("tool_call", call)
        result = await handler(name, arguments)
        yield AgentEvent(
            "tool_result",
            {
                "call_id": call["call_id"],
                "name": name,
                "status": "completed",
                "result": result,
                "error": None,
            },
        )
    yield AgentEvent("completed", {"text": ""})


class IntegrationScriptedProvider(ScriptedProvider):
    """Call trace-only tools while exercising real packet validation."""

    @property
    def task_requests(self):
        return [request for request in self.requests if not is_integration_request(request)]

    async def run(self, request_id, request, **kwargs):
        if not is_integration_request(request):
            async for event in super().run(request_id, request, **kwargs):
                yield event
            return
        self.requests.append(request)
        material = json.loads(request.prompt)["material"]
        assert not material["context"].get("preservation_intents"), (
            "Use explicit integration scripts when testing preservation obligations"
        )
        calls = [
            ("trace_only", {"sources": [item["reference"] for item in material["experience"]]}),
            ("finish", {}),
        ]
        async for event in tool_events(request_id, request, kwargs["tool_handler"], calls):
            yield event


def completed(data):
    return [AgentEvent("completed", {"text": json.dumps(data), "parsed": data})]


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
