"""Real integration, embeddings and independent meaning checks on varied technical sources."""

import json
import os
from pathlib import Path

import pytest

from evertree.core.graph.types import GraphDelta, RelationType, Slot
from evertree.core.semantics.reading import fact_nodes
from evertree.core.values import json_value
from tests.support.large_graph import LargeGraphSession
from tests.support.semantic_review import review_graph

pytestmark = pytest.mark.skipif(
    os.environ.get("EVERTREE_LARGE_GRAPH_INTEGRATION") != "1",
    reason="Explicit model and embeddings opt-in required",
)
CASES = json.loads(
    (Path(__file__).parents[1] / "data" / "semantic_distinctions.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_operational_anchors_predicates_and_hypotheses(case, tmp_path):
    """Actual model writes must retain local settings, predicate meaning and revisable hypotheses."""
    restored = os.environ.get("EVERTREE_LARGE_GRAPH_SNAPSHOT")
    snapshot = json.loads(Path(restored).read_text()) if restored else None
    session = LargeGraphSession(tmp_path, snapshot=snapshot)
    session.metadata["integration_context"]["task"]["specification"]["objective"] = case[
        "objective"
    ]
    try:
        # Reproduce the ambiguous schema from the original run even without its saved snapshot.
        if (
            case["id"] == "thermal-control"
            and session.graph.find("HYDRAULICALLY_CONNECTED_BY") is None
        ):
            ambiguous = RelationType(
                id=session.graph.reserve_id(),
                name="HYDRAULICALLY_CONNECTED_BY",
                description=(
                    "Records two fluid circuits hydraulically connected or separated through "
                    "a specified interface component; does not imply fluid mixing where the "
                    "interface is a heat exchanger."
                ),
                signature=tuple(
                    Slot(label=label, value_type="instance", arity="one")
                    for label in ("circuit_a", "circuit_b", "interface")
                ),
            )
            session.graph.apply(
                GraphDelta(creates=(ambiguous,)), provenance="ambiguous-schema-fixture"
            )
        before = session.graph.revision
        metrics = await session.packet(
            tmp_path / "integration",
            case["source"],
            "Этот материал нужен для дальнейшего сопровождения и диагностики. "
            "Выдели полезные связи, объяснения и переиспользуемые выводы.",
        )
        assert metrics["error"] is None, metrics["error"]
        session.memory.validate()
        # Include updated objects and reused schemas/participants, but not unrelated baseline nodes.
        changed = {
            n["fields"]["id"]
            for change in session.graph.snapshot()["history"]
            if change["seq"] > before
            for n in change["after"]
        }
        related = set(changed)
        for identity in changed:
            node = session.graph.get(identity)
            if node.kind == "relation_instance":
                related.update({node.relation_type, *fact_nodes(session.graph, node)})
        review = await review_graph(
            tmp_path / "review",
            sources=case["source"],
            nodes=[json_value(session.graph.get(i)) for i in sorted(related)],
            criteria=case["criteria"],
        )
        assert all(item["passed"] for item in review.values()), review
    finally:
        await session.close()
