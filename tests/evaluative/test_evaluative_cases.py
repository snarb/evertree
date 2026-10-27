"""Evaluative-control scenarios worked on by the real conscious agent.

Each case in cases.json seeds saved experience, gives a real Codex agent a task at a
different stage of the agent lifecycle and checks what Core recorded and what the agent
reported: calibrated forecasts of finished Tasks, supervisor feedback during and after
work, tension diagnoses with their components and coverage gaps, deadline statistics,
cancellation and reflection on the signals. Model answers vary, so checks are
structural. Artifacts stay under tmp_path.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from evertree.debug_evaluative_control import load_cases, run_live
from tests.support.evaluative import failures

CASES = load_cases()

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("EVERTREE_CODEX_INTEGRATION") != "1",
        reason="Explicit live opt-in required; cases use a real Codex agent and native workers",
    ),
    pytest.mark.usefixtures("offline_application"),
]

# A rate-limited model call fails the whole case; it reruns from scratch after a pause.
ATTEMPTS = 2
PAUSE_SECONDS = 120
CASE_TIMEOUT_SECONDS = 20 * 60


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
async def test_evaluative_case(case, tmp_path):
    for attempt in range(1, ATTEMPTS + 1):
        directory = tmp_path / f"attempt-{attempt}"
        try:
            state = await asyncio.wait_for(
                run_live(case, directory / "home", directory), CASE_TIMEOUT_SECONDS
            )
        except RuntimeError as error:
            if "429" not in str(error) or attempt == ATTEMPTS:
                raise
        else:
            if "429" not in str(state["task"].get("reason")) or attempt == ATTEMPTS:
                break
        await asyncio.sleep(PAUSE_SECONDS)
    problems = failures(state, case["expect"])
    (directory / "failures.json").write_text(json.dumps(problems, indent=2), encoding="utf-8")
    assert not problems, json.dumps(problems, indent=2)
