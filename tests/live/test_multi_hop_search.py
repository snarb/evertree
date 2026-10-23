"""Opt-in real model navigation through names that are absent from the original question."""

import json
import os
from uuid import uuid4

import pytest

from evertree.core.codex.provider import CodexProvider
from evertree.core.graph.types import GraphDelta, Node
from evertree.core.semantics.tools import MULTIHOP_SEARCH_INSTRUCTIONS
from tests.support.live_semantics import native_semantic_context
from tests.support.search_session import ANSWER_SCHEMA, SearchSession, adaptive_tools
from tests.support.semantics import semantic_world

pytestmark = pytest.mark.skipif(
    os.environ.get("EVERTREE_CODEX_INTEGRATION") != "1",
    reason="Explicit real-model opt-in required",
)


async def test_model_follows_two_discovered_names_before_answering(tmp_path):
    """Real native tools must expose each hidden link before the model can read the next one."""
    world = semantic_world()
    nonce = uuid4().hex
    anchor = Node(
        world.graph.reserve_id(),
        "Beacon " + nonce[:6],
        description="Its fallback route is RX-" + nonce[6:12] + ".",
    )
    route = Node(
        world.graph.reserve_id(),
        "RX-" + nonce[6:12],
        description="This route delivers backup telemetry to archive service SE-"
        + nonce[12:18]
        + ".",
    )
    archive = Node(
        world.graph.reserve_id(),
        "SE-" + nonce[12:18],
        description="This archive retains backup telemetry for 17 days.",
    )
    world.graph.apply(
        GraphDelta(creates=[anchor, route, archive]), provenance="synthetic-navigation"
    )
    provider, transcript = CodexProvider(state_dir=tmp_path / "codex"), []
    session = None
    try:
        async with native_semantic_context(
            world, provider, tmp_path, transcript, role="model"
        ) as ctx:
            session = SearchSession(ctx)
            result = await ctx.llm(
                {
                    "prompt": f"How long is backup telemetry retained by the archive reached through the fallback route of {anchor.name}?",
                    "instructions": MULTIHOP_SEARCH_INSTRUCTIONS
                    + " Use only graph tools for this fictional system. Start from the exact known object name. Cite IDs actually read. You have at most three searches, six total query entries and four describes. State unresolved gaps instead of inventing links.",
                    "output_schema": ANSWER_SCHEMA,
                    "mode": "model",
                },
                tools=adaptive_tools(),
                tool_handler=session.call,
                max_tool_calls=10,
            )
            output = result["parsed"]
            assert archive.id in session.check_evidence(output["evidence"])
            assert {anchor.id, route.id, archive.id} <= session.visible.keys()
            assert "17" in output["answer"] and "day" in output["answer"].casefold()
            assert not output["unresolved"]
            assert len(session.trace) >= 3
            assert archive.id not in {
                item["id"] for item in session.trace[0]["result"].get("items", [])
            }
    finally:
        (tmp_path / "multi-hop.json").write_text(
            json.dumps(
                {"transcript": transcript, "reads": session.trace if session else []},
                ensure_ascii=False,
                indent=2,
            )
        )
        await provider.close()
