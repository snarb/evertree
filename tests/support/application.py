from __future__ import annotations

import asyncio
import json

import pytest

from evertree.core.provider import AgentEvent, ScriptedProvider


def is_integration_request(request):
    return {"action", "delta_json", "decisions_json"} <= set(
        (request.output_schema or {}).get("properties", {})
    )


class IntegrationScriptedProvider(ScriptedProvider):
    """Supply trace-only integration decisions while exercising real packet validation."""

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
        decisions = [
            {
                "disposition": "trace_only",
                "reason": "This scenario needs no persistent graph structure",
                "source_refs": [item["reference"]],
                "affected_ids": [],
                "preservation_ids": [],
            }
            for item in material["experience"]
        ]
        yield AgentEvent("session", {"provider": self.name, "id": request_id})
        for event in completed(
            {
                "action": "commit",
                "query": "",
                "delta_json": "{}",
                "decisions_json": json.dumps(decisions),
                "summary": "Experience reviewed and retained in trace",
            }
        ):
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
    del result["initial_step"]
    return completed(result)


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
