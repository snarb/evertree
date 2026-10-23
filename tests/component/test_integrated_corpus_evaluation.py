"""Acquisition checkpoints must preserve real source lineage across restoration."""

import importlib.util
import json
from pathlib import Path

import pytest

from evertree.core.semantics.config import SemanticConfig
from tests.support.semantics import EmptyIndex, recorded_experience, semantic_world, write_action


@pytest.fixture
def evaluation(monkeypatch):
    root = Path(__file__).resolve().parents[2] / "artifacts/search-recall"
    monkeypatch.syspath_prepend(str(root))
    spec = importlib.util.spec_from_file_location("integrated_corpus", root / "integrated.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_serialized_acquisition_preserves_article_provenance_without_injecting_source_cards(
    evaluation,
):
    world = semantic_world()
    refs, metadata = recorded_experience(world, {"article": "A won"}, {"article": "B lost"})
    result = write_action(
        world,
        refs,
        metadata,
        {
            "action": "create_claim",
            "name": "A victory",
            "description": "A won.",
            "sources": refs[:1],
        },
    )
    assert "error" not in result
    identity = result["object"]
    restored = evaluation.restore(
        json.loads(json.dumps(evaluation.snapshot(world))), EmptyIndex(), SemanticConfig()
    )
    assert restored.graph.snapshot() == world.graph.snapshot()
    references = {refs[0]["event_ref"]: "article-A", refs[1]["event_ref"]: "article-B"}
    assert evaluation.source_urls(restored, [identity], references) == {"article-A"}
    assert len(restored.graph.nodes(kind="claim")) == 1


async def test_graph_queries_return_actual_fact_ids_available_for_evidence(evaluation):
    from tests.support.semantics import context

    world = semantic_world()
    refs, metadata = recorded_experience(world, "One pump")
    result = write_action(
        world,
        refs,
        metadata,
        {
            "action": "create_prototype",
            "name": "Pump",
            "description": "A pump.",
            "parent": None,
            "sources": refs,
        },
    )
    assert "error" not in result
    session = evaluation.GraphSession(context(world, None), reads=1)
    from evertree.core.tokens import current_read_context

    token = current_read_context.set({"model": "gpt-5", "context_window": 32768})
    try:
        value = await session.call("graph.query", {"subject": result["object"]})
    finally:
        current_read_context.reset(token)
    assert "error" not in value
    assert session.reads == 0
    assert "budget exhausted" in (await session.call("graph.walk", {"start": "Pump"}))["error"]


def test_structure_counts_domain_links_separately_from_automatic_identity_scaffolding(evaluation):
    from evertree.core.graph.types import GraphDelta
    from evertree.core.memory.types import TraceOutputRef

    world = semantic_world()
    refs, metadata = recorded_experience(world, "P1 is part of P2")
    root = write_action(
        world,
        refs,
        metadata,
        {
            "action": "create_prototype",
            "name": "Equipment",
            "description": "Equipment.",
            "parent": None,
            "sources": refs,
        },
        key="root",
    )["object"]
    child = write_action(
        world,
        refs,
        metadata,
        {
            "action": "create_prototype",
            "name": "Pump",
            "description": "A pump.",
            "parent": root,
            "sources": refs,
        },
        key="child",
    )["object"]
    identities = [
        write_action(
            world,
            refs,
            metadata,
            {
                "action": "create_instance",
                "name": name,
                "description": name,
                "prototype": child,
                "sources": refs,
            },
            key=name,
        )["object"]
        for name in ("P1", "P2")
    ]
    fact = world.graph.new_fact("PART_WHOLE", {"part": identities[0], "whole": identities[1]})
    world.operations.apply_delta(
        GraphDelta(creates=[fact]),
        task_id="task",
        revision="revision",
        source_refs=[TraceOutputRef(**ref) for ref in refs],
    )
    result = evaluation.structure(world)
    assert len(result["structural_fact_ids"]) == 3
    assert [row["id"] for row in result["domain_assertions"]] == [fact.id]
    assert result["domain_components"] == [sorted([fact.id, *identities])]


async def test_recall_uses_actual_retained_sources_and_separates_event_and_object_ids(evaluation):
    from tests.support.semantics import context

    world = semantic_world()
    refs, _ = recorded_experience(world, {"article": {"url": "source-A", "body": "A won"}})
    session = evaluation.MemoryGraphSession(context(world, None))
    result = await session.call("recall", {"query": "A won"})
    assert result[0]["events"][0]["output"]["article"]["body"] == "A won"
    identity = refs[0]["event_ref"]
    assert session.check_references([{"kind": "memory_event", "id": identity}]) == (
        set(),
        {identity},
    )
    with pytest.raises(ValueError, match="never read"):
        session.check_references([{"kind": "graph_object", "id": identity}])
    await session.call("graph.search", {"queries": ["Process"]})
    assert session.check_references([{"kind": "graph_object", "id": 1}]) == ({1}, set())
    assert evaluation.event_urls(world, [identity], {identity: "source-A"}) == {"source-A"}


def test_resuming_frozen_graph_answers_rejects_a_changed_reader(evaluation, tmp_path):
    evaluation.pin_reader(tmp_path, "graph", "acquired-v1", "reader-v2")
    evaluation.pin_reader(tmp_path, "graph", "acquired-v1", "reader-v2")
    with pytest.raises(ValueError, match="Reader changed"):
        evaluation.pin_reader(tmp_path, "graph", "acquired-v1", "reader-v3")
    assert json.loads((tmp_path / "graph-versions.json").read_text()) == {
        "acquisition": "acquired-v1",
        "reader": "reader-v2",
    }


@pytest.mark.parametrize("mutation", [None, "body", "plan", "references", "order"])
def test_explicit_seed_requires_exact_originals_and_completed_prefix(evaluation, mutation):
    from copy import deepcopy

    world = semantic_world()
    articles = [{"url": "first", "body": "Exact first source"}, {"url": "second", "body": "Second"}]
    run = world.memory.start_run("CorpusArticle", "evaluation", {})
    event = world.memory.record(run, "observation", output={"article": articles[0]})
    world.memory.finish_run(run)
    plan = {"files": {"articles": "frozen"}}
    record = {
        "plan": plan,
        "completed": ["first"],
        "references": {str(event.id): "first"},
        "snapshot": evaluation.snapshot(world),
    }
    candidate = deepcopy(articles)
    if mutation == "body":
        candidate[0]["body"] = "Changed source"
    if mutation == "plan":
        record["plan"] = {"files": {}}
    if mutation == "references":
        record["references"] = {}
    if mutation == "order":
        candidate.reverse()
    if mutation is None:
        evaluation.validate_seed(record, candidate, plan)
    else:
        with pytest.raises(ValueError):
            evaluation.validate_seed(record, candidate, plan)
