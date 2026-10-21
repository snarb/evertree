"""Native mirror of the live Program lifecycle scenarios in tests/lifecycle/cases.json.

Each scenario installs its Programs through the real gates, then replays its fixed
lifecycle steps with real Git, native workers and protected evaluation. Only the
coding agent and the meta Program's planner are scripted, so this proves the
mechanics (decisions, refusals, activation, sealing) but not model judgement,
which the live suite checks.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from evertree.application import EverTree
from evertree.debug_lifecycle import LifecycleSession, load_cases
from tests.support.lifecycle import MirrorProvider, failures

CASES = load_cases()

pytestmark = [
    pytest.mark.skipif(
        os.name != "nt" and sys.platform != "darwin", reason="Native macOS/Windows isolation"
    ),
    pytest.mark.usefixtures("offline_application"),
]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
async def test_lifecycle_scenario_mechanics(case, tmp_path):
    """Candidate tests and evaluation sides need native workers; a transport stub cannot prove them."""
    provider = MirrorProvider()
    async with EverTree(tmp_path / "agent", provider=provider) as agent:
        session = LifecycleSession(agent, case, tmp_path / "artifacts")
        try:
            await session.setup()
            await session.replay(provider)
            await session.probe()
            state = session.state()
        finally:
            session.save()
    problems = failures(state, case["expect"], "mirror")
    assert not problems, json.dumps(problems, indent=2)
