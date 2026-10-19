"""Text-based evidence assessment cases run through real integration and assessment.

Each case in cases.json records user messages, observations and documents step by step;
the real KnowledgeIntegration and EvidenceAssessment Programs run after every step with a
real Codex model, Redis Search and OpenAI embeddings, and expectations are checked on the
belief snapshot after each step. Model judgement varies, so expectations are ordinal and
elements are selected by kind and keywords. Artifacts for every case stay under tmp_path.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest

from evertree.debug_evidence_assessment import EvidenceSession
from evertree.debug_integration import load_debug_environment
from tests.evidence.checks import check

CASES = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
REPOSITORY = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("EVERTREE_CODEX_INTEGRATION") != "1",
    reason="Explicit live opt-in required; cases use a real model, Redis and embeddings",
)


# A rate-limited or stalled model call fails the whole case; it is rerun from the start
# after a pause. A single call normally takes well under a minute.
ATTEMPTS = 3
PAUSE_SECONDS = 120
CALL_TIMEOUT_SECONDS = 300


async def _run(case, directory):
    """Run a case in a fresh session, retrying from scratch when the model is rate limited
    or a call stalls."""
    for attempt in range(1, ATTEMPTS + 1):
        session = EvidenceSession(
            directory / f"attempt-{attempt}",
            task=case["task"],
            steps=case["steps"],
            timeout_seconds=CALL_TIMEOUT_SECONDS,
        )
        load_debug_environment(REPOSITORY, session.config)
        missing = [
            name
            for name in (session.config.redis_url_env, session.config.openai_key_env)
            if not os.environ.get(name)
        ]
        if missing:
            pytest.skip("Search needs " + ", ".join(missing))
        try:
            await session.run()
        except (RuntimeError, TimeoutError) as error:
            transient = isinstance(error, TimeoutError) or any(
                marker in str(error).lower() for marker in ("429", "timed out", "timeout")
            )
            if not transient or attempt == ATTEMPTS:
                raise
            await asyncio.sleep(PAUSE_SECONDS)
        else:
            return session


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
async def test_evidence_case(case, tmp_path):
    session = await _run(case, tmp_path)
    failures = []
    for expectation in case["expect"]:
        failure = check(session.history, expectation)
        if failure:
            failures.append({"expectation": expectation, "failure": failure})
    (session.output_dir / "history.json").write_text(
        json.dumps(
            {"history": session.history, "failures": failures}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    assert not failures, json.dumps(failures, ensure_ascii=False, indent=2)
