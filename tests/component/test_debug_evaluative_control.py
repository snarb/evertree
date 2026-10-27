"""The live evaluative-control harness seeds, drives and reads scenarios correctly.

A scripted model stands in for Codex so the harness's own bookkeeping (seeding, host
events during the task, tool and Program traces, statistics and checks) is proven
before live runs depend on it.
"""

from __future__ import annotations

import asyncio

from evertree.debug_evaluative_control import EvaluativeSession, load_case
from tests.support.application import IntegrationScriptedProvider as ScriptedProvider
from tests.support.application import decision, framing, verification
from tests.support.component import component_app
from tests.support.evaluative import failures, tool_calls


async def drive(tmp_path, case, scripts):
    provider = scripts if isinstance(scripts, ScriptedProvider) else ScriptedProvider(scripts)
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        session = EvaluativeSession(agent, case)
        session.setup()
        await asyncio.wait_for(session.run_task(), 60)
        state = session.state()
        state["stats"] = {}
        return session, state


async def test_seeded_feedback_is_found_by_the_conscious_tool_and_checked(tmp_path):
    case = load_case("EVL-03")
    step = [
        *tool_calls(
            ("load_tool_set", {"name": "evaluative_signals"}),
            (
                "supervisor_feedback",
                {
                    "period": ["2000-01-01T00:00:00Z", "2100-01-01T00:00:00Z"],
                    "processes": ["Process"],
                },
            ),
        ),
        *decision("The supervisor rated it -2: the report omitted deadline risks."),
    ]
    session, state = await drive(tmp_path, case, [framing(), step, verification()])
    (call,) = [call for call in state["tool_calls"] if call["name"] == "supervisor_feedback"]
    assert call["result"]["items"][0]["comment"].startswith("The report omitted")
    assert call["result"]["items"][0]["subject"] == session.names["report"]
    assert failures(state, case["expect"]) == []


async def test_cancellation_during_the_task_is_applied_and_checked(tmp_path):
    case = {**load_case("EVL-09"), "during": [{"action": "cancel", "reason": "Withdrawn"}]}
    _, state = await drive(tmp_path, case, [framing(), decision(), verification()])
    assert state["task"]["status"] == "cancelled"
    assert state["task_state"]["outcome_reason"] == "Withdrawn"
    problems = failures(state, [c for c in case["expect"] if c["check"] != "stats"])
    assert [p["check"]["check"] for p in problems] == ["task_field"]


class RespondingProvider(ScriptedProvider):
    """Answer each request by its kind, so host events may land at any point of the work."""

    def __init__(self):
        super().__init__([])

    async def run(self, request_id, request, **kwargs):
        # A real provider awaits I/O; yielding lets scheduled host events land meanwhile.
        await asyncio.sleep(0.05)
        instructions = request.instructions or ""
        if instructions.startswith("You define the task"):
            self.scripts = [framing()]
        elif instructions.startswith("Check whether the proposed answer"):
            self.scripts = [verification("fraise" in request.prompt)]
        elif "The answer must be written in French" in request.prompt:
            self.scripts = [decision("C'est une fraise.")]
        else:
            self.scripts = [decision("A strawberry is a fruit.")]
        async for event in super().run(request_id, request, **kwargs):
            yield event


async def test_scheduled_feedback_reaches_the_running_task(tmp_path):
    """Feedback arriving during work reaches a later step before the answer is accepted."""
    case = load_case("EVL-02")
    _, state = await drive(tmp_path, case, RespondingProvider())
    assert failures(state, case["expect"]) == []
