from __future__ import annotations

import asyncio
import json

import pytest

from evertree.core.provider import AgentEvent


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
        }
    )


def decision(answer="3", status="completed"):
    return completed({"status": status, "answer": answer, "progress": "Selected work complete"})


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
