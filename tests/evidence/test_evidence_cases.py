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


# A rate-limited model fails the whole case; it is rerun from the start after a pause.
RATE_LIMIT_ATTEMPTS = 3
RATE_LIMIT_PAUSE_SECONDS = 120


async def _run(case, directory):
    """Run a case in a fresh session, retrying from scratch when the model is rate limited."""
    for attempt in range(1, RATE_LIMIT_ATTEMPTS + 1):
        session = EvidenceSession(
            directory / f"attempt-{attempt}", task=case["task"], steps=case["steps"]
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
        except RuntimeError as error:
            if "429" not in str(error) or attempt == RATE_LIMIT_ATTEMPTS:
                raise
            await asyncio.sleep(RATE_LIMIT_PAUSE_SECONDS)
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
