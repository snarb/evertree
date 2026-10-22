"""Program lifecycle scenarios solved by the real conscious agent and coding provider.

Each case in cases.json installs its Programs through the real gates and binds the
developer holdouts; then a real Codex agent receives the task and must create,
develop, evaluate, compare, refresh and choose candidates itself. Model work varies,
so expectations are structural: slots, lifecycle statuses, decision counts, metric
improvement over the baseline and probes of the active code. Artifacts stay under
tmp_path.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from evertree.debug_lifecycle import load_cases, run_live
from tests.support.lifecycle import failures

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
# A stuck provider or worker must fail its case instead of holding the suite indefinitely.
CASE_TIMEOUT_SECONDS = 45 * 60


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
async def test_lifecycle_case(case, tmp_path):
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
            # A rate-limited model call ends the task as failed rather than raising.
            if "429" not in str(state["task"].get("reason")) or attempt == ATTEMPTS:
                break
        await asyncio.sleep(PAUSE_SECONDS)
    problems = failures(state, case["expect"], "live")
    (directory / "failures.json").write_text(json.dumps(problems, indent=2), encoding="utf-8")
    assert not problems, json.dumps(problems, indent=2)
