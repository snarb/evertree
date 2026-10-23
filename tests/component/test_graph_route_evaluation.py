"""Ablations enforce their actual tools, visible evidence and shared reading allowances."""

import importlib.util
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from evertree._application.prompts import consciousness_tools, semantic_tools
from evertree.core.graph.types import GraphDelta, Node
from evertree.core.tokens import count_tokens, current_read_context
from evertree.core.values import json_value
from tests.support.semantics import context, semantic_world
from tests.support.tokens import offline_tokenizer  # noqa: F401 -- offline BPE fixture


@pytest.fixture
def review_repair(evaluation):
    spec = importlib.util.spec_from_file_location(
        "route_review_repair", Path(evaluation.__file__).with_name("repair_route_review.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_review_repair_unknown_reads_widen_bounds_without_inventing_relevance(
    evaluation, review_repair
):
    raw = {
        "correct": True,
        "grounded_in_reads": True,
        "missing_required_parts": [],
        "unsupported_claims": [],
        "read_relevance": [
            {"read_index": 0, "classification": "relevant", "reason": "Useful"},
            {"read_index": 0, "classification": "irrelevant", "reason": "Conflicting"},
            {"read_index": 8, "classification": "relevant", "reason": "Nonexistent"},
        ],
    }
    fixed, warnings = review_repair.conservative_verdict(raw, 2)
    assert [row["classification"] for row in fixed["read_relevance"]] == [
        "uncertain",
        "uncertain",
    ]
    statistics = evaluation.read_statistics(
        [{"tokens": 20}, {"tokens": 30}], fixed["read_relevance"]
    )
    assert statistics["irrelevant_tokens_lower_bound"] == 0
    assert statistics["irrelevant_tokens_upper_bound"] == 50
    assert len(warnings) == 3
    assert len(raw["read_relevance"]) == 3


def test_review_repair_contradictions_cannot_promote_success(review_repair):
    fixed, warnings = review_repair.conservative_verdict(
        {
            "correct": True,
            "grounded_in_reads": True,
            "missing_required_parts": ["Required date"],
            "unsupported_claims": ["Wrong participant"],
            "read_relevance": [],
        },
        0,
    )
    assert not fixed["correct"]
    assert not fixed["grounded_in_reads"]
    assert len(warnings) == 2


@pytest.fixture
def evaluation(monkeypatch):
    root = Path(__file__).resolve().parents[2] / "artifacts/search-recall"
    monkeypatch.syspath_prepend(str(root))
    spec = importlib.util.spec_from_file_location(
        "graph_route_evaluation", root / "graph_routes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_world(text="Original exact evidence"):
    world = semantic_world()
    run = world.memory.start_run("Article", "revision", {})
    event = world.memory.record(run, "observation", output={"article": {"body": text}})
    world.memory.finish_run(run)
    reference = world.memory.output_ref(event, ("article", "body"))
    node = Node(world.graph.reserve_id(), "Source anchor", description=text)
    world.operations.apply_delta(
        GraphDelta(creates=(node,)), task_id="task", revision="revision", source_refs=(reference,)
    )
    return world, node, json_value(reference)


@pytest.mark.parametrize("channel_error", [False, True])
async def test_index_preparation_cannot_supply_reader_evidence(evaluation, channel_error):
    world, node, _ = source_world()
    before = world.graph.snapshot(), world.memory.snapshot()

    class PreparationIndex:
        async def lexical(self, cards, queries):
            assert any(card["id"] == node.id for card in cards)
            return [{"ids": [node.id]}]

        async def vector(self, cards, queries):
            return [{"error": "Unavailable"}] if channel_error else [{"ids": [node.id]}]

    if channel_error:
        with pytest.raises(RuntimeError, match="Both search channels"):
            await evaluation.prepare_index(world, PreparationIndex())
    else:
        prepared = await evaluation.prepare_index(world, PreparationIndex())
        assert prepared["cards"] == len(world.graph.nodes())
    assert (world.graph.snapshot(), world.memory.snapshot()) == before
    session = evaluation.RouteSession(context(world, None, role="model"), "graph_sources")
    with pytest.raises(ValueError, match="Unread graph"):
        session.citations([{"object_id": node.id, "reference": None, "supports": "Unseen"}])


@pytest.mark.parametrize("failure", ["timeout", "citation"])
async def test_reader_failure_is_saved_once_and_resume_does_not_retry_it(
    evaluation, tmp_path, monkeypatch, failure
):
    """External failures cannot silently select a luckier answer on benchmark resume."""
    world, _, reference = source_world()
    article = {"url": "https://example.test/a", "body": "Original evidence."}
    question = {"query": "What was observed?", "answer": "Evidence", "evidence_list": []}
    plan = {"files": {}, "original_question_indices": [7]}
    (tmp_path / "acquired.json").write_text(
        json.dumps(
            {
                "plan": plan,
                "completed": [article["url"]],
                "production_revision": evaluation.production_revision(),
                "references": {str(reference["event_ref"]): article["url"]},
                "snapshot": evaluation.snapshot(world),
            }
        )
    )
    invocations = []

    @asynccontextmanager
    async def native_context(restored, provider, directory, transcript, **options):
        async def model(payload, call):
            invocations.append(payload)
            await call("graph.search", {"queries": ["Source anchor"]})
            if failure == "timeout":
                raise TimeoutError("External provider deadline")
            return {
                "parsed": {
                    "answer": "Evidence",
                    "evidence": [{"object_id": 99999, "reference": None, "supports": "Unseen"}],
                    "unresolved": [],
                }
            }

        yield context(restored, model, role="model")

    monkeypatch.setattr(evaluation, "native_semantic_context", native_context)
    args = SimpleNamespace(output=tmp_path, variant="graph_sources", resume=False)
    await evaluation.evaluate(
        args, [article], [question], plan, world.service.config, world.service.index, None
    )
    path = tmp_path / "routes-graph_sources.json"
    saved = json.loads(path.read_text())
    assert len(saved) == 1
    assert saved[0]["evaluation_errors"][0]["kind"] == (
        "reader_failure" if failure == "timeout" else "invalid_citation"
    )
    assert saved[0]["cited_source_lineage"] == []
    trace = json.loads((tmp_path / "routes/graph_sources/0/trace.json").read_text())
    assert trace["reads"][0]["name"] == "graph.search"
    args.resume = True
    await evaluation.evaluate(
        args, [article], [question], plan, world.service.config, world.service.index, None
    )
    assert len(invocations) == 1
    assert json.loads(path.read_text()) == saved


def test_review_reports_bounds_instead_of_calling_all_mixed_text_irrelevant(evaluation):
    reads = [{"tokens": value} for value in (100, 200, 300, 40, 50)]
    ratings = [
        {"read_index": i, "classification": classification}
        for i, classification in enumerate(
            ("relevant", "mixed", "irrelevant", "administrative", "uncertain")
        )
    ]
    result = evaluation.read_statistics(reads, list(reversed(ratings)))
    assert result["irrelevant_tokens_lower_bound"] == 300
    assert result["irrelevant_tokens_upper_bound"] == 550
    assert result["tokens_by_relevance"]["administrative"] == 40
    assert sum(result["read_counts"].values()) == len(reads)


@pytest.mark.parametrize("indices", [[0], [0, 0], [0, 2], [False, 1]])
def test_review_rejects_omitted_duplicate_or_invalid_read_ratings(evaluation, indices):
    reads = [{"tokens": 100}, {"tokens": 200}]
    ratings = [{"read_index": i, "classification": "irrelevant"} for i in indices]
    with pytest.raises(ValueError, match="every actual read exactly once"):
        evaluation.read_statistics(reads, ratings)


async def test_review_retains_early_rich_reads_and_rejects_changed_evidence(
    evaluation, tmp_path, monkeypatch
):
    """Judging must use the actual trace even when the final card cache is less detailed."""
    args = SimpleNamespace(output=tmp_path, resume=False)
    plan = {"files": {"articles.json": "frozen"}, "original_question_indices": [17]}
    reader = {
        "plan": plan["files"],
        "reader_revision": evaluation.production_revision(),
        "model": evaluation.MODEL,
        "effort": evaluation.EFFORT,
    }
    (tmp_path / "route-evaluation.json").write_text(json.dumps(reader))
    question = {"query": "Who repaired device D?", "answer": "A", "evidence_list": []}
    answer = {"answer": "A", "evidence": [], "unresolved": []}
    reads = [
        {
            "name": "graph.search",
            "arguments": {"queries": ["device D"]},
            "tokens": 100,
            "result": {
                "items": [
                    {
                        "id": 10,
                        "name": "Repair",
                        "kind": "relation_instance",
                        "description": "A repaired device D.",
                    }
                ]
            },
        },
        {
            "name": "graph.query",
            "arguments": {"subject": 10},
            "tokens": 20,
            "result": {"nodes": [{"id": 10, "name": "Repair", "kind": "relation_instance"}]},
        },
    ]
    for variant in evaluation.VARIANTS:
        (tmp_path / f"routes-{variant}.json").write_text(
            json.dumps(
                [
                    {
                        "original_index": 17,
                        "question": question["query"],
                        "answer": answer,
                        "read_evidence": reads[-1]["result"]["nodes"],
                    }
                ]
            )
        )
        directory = tmp_path / "routes" / variant / "0"
        directory.mkdir(parents=True)
        (directory / "trace.json").write_text(json.dumps({"reads": reads}))
    requests = []

    async def judge(provider, directory, payload, transcript, **options):
        supplied = json.loads(payload["prompt"])
        requests.append(supplied)
        assert set(supplied["responses"]) == {"A", "B", "C", "D"}
        for response in supplied["responses"].values():
            actual = response["actual_reads"]
            assert actual[0]["result"]["items"][0]["description"] == "A repaired device D."
            assert "description" not in actual[1]["result"]["nodes"][0]
        verdict = {
            "correct": True,
            "grounded_in_reads": True,
            "reason": "The first read supports it.",
            "missing_required_parts": [],
            "unsupported_claims": [],
            "read_relevance": [
                {"read_index": i, "classification": "relevant", "reason": "Used"}
                for i in range(len(reads))
            ],
        }
        return {
            "parsed": {
                "label_status": "supported",
                "label_reason": "Source support",
                **{alias: verdict for alias in supplied["responses"]},
            }
        }

    monkeypatch.setattr(evaluation, "provider_result", judge)
    await evaluation.review(args, [{"body": "A repaired device D."}], [question], plan, None)
    judged = json.loads((tmp_path / "route-answer-review.json").read_text())
    assert len(judged) == 1 and set(judged[0]["variants"]) == set(evaluation.VARIANTS)
    args.resume = True
    await evaluation.review(args, [{"body": "A repaired device D."}], [question], plan, None)
    assert len(requests) == 1
    path = tmp_path / "routes" / "raw" / "0" / "trace.json"
    path.write_text(json.dumps({"reads": reads[:1]}))
    with pytest.raises(ValueError, match="Review inputs or settings changed"):
        await evaluation.review(args, [{"body": "A repaired device D."}], [question], plan, None)
    assert len(requests) == 1


def test_four_variants_expose_only_their_real_production_read_tools(evaluation):
    search = {"graph.search"}
    routes = {"graph.describe", "graph.query", "graph.walk", "graph.read_property"}
    expected = {
        "raw": search | {"graph.describe"},
        "graph_search": search,
        "graph_routes": search | routes,
        "graph_sources": search | routes | {"graph.sources", "read_source"},
    }
    production = {tool.name: tool for tool in semantic_tools()}
    for variant, names in expected.items():
        tools = evaluation.variant_tools(variant)
        assert {tool.name for tool in tools} == names
        assert all(tool == production[tool.name] and tool.read_only for tool in tools)
    exposed = {tool.name for tool in consciousness_tools()}
    assert {"graph.sources", "read_source"} <= exposed
    assert "graph.read_source" not in exposed


@pytest.mark.parametrize(
    ("variant", "name", "arguments"),
    [
        ("raw", "graph.query", {"subject": 1}),
        ("graph_search", "graph.describe", {"subject": 1}),
        ("graph_routes", "read_source", {"reference": {"event_ref": 1}}),
    ],
)
async def test_disabled_routes_cannot_be_called_through_handler(
    evaluation, variant, name, arguments
):
    session = evaluation.RouteSession(None, variant)
    with pytest.raises(ValueError, match="unavailable"):
        await session.call(name, arguments)
    assert session.tokens == 0 and not session.trace


@pytest.mark.parametrize("remaining", [None, 90000])
async def test_exact_source_page_uses_remaining_evaluation_budget_before_core_cursor_moves(
    evaluation, remaining
):
    world, _, reference = source_world("Evidence line α.\n" * 3000)
    session = evaluation.RouteSession(
        context(world, None, role="model"), "graph_sources", token_budget=2000
    )
    provider_context = {"model": "gpt-5", "context_window": 100000, "remaining_tokens": remaining}
    token = current_read_context.set(provider_context)
    try:
        result = await session.call("read_source", {"reference": reference})
        assert current_read_context.get() == provider_context
    finally:
        current_read_context.reset(token)
    assert result.get("content")
    assert result["start"] == 0 and result["has_more"]
    assert result["content"] == ("Evidence line α.\n" * 3000)[: result["end"]]
    assert session.tokens == count_tokens(result, evaluation.MODEL) <= 2000
    assert session.remaining_tokens == 2000 - session.tokens
    assert session.source_pages == [result]


async def test_source_metadata_is_not_a_read_citation_and_context_is_distinct(evaluation):
    world, node, reference = source_world()
    session = evaluation.RouteSession(context(world, None, role="model"), "graph_sources")
    token = current_read_context.set({"model": "gpt-5", "context_window": 100000})
    try:
        listing = await session.call("graph.sources", {"subjects": [node.id]})
        assert listing["items"][0]["reference"] == reference
        citation = {"object_id": None, "reference": reference, "supports": "Original wording"}
        with pytest.raises(ValueError, match="Unread source"):
            session.citations([citation])
        page = await session.call("read_source", {"reference": reference})
    finally:
        current_read_context.reset(token)
    assert session.citations([citation]) == (set(), [reference])
    with pytest.raises(ValueError, match="Unread source"):
        session.citations([{**citation, "reference": page["context_reference"]}])
    with pytest.raises(ValueError, match="exactly one"):
        session.citations([{**citation, "object_id": node.id}])
    with pytest.raises(ValueError, match="Unread graph"):
        session.citations([{**citation, "object_id": 999999, "reference": None}])


async def test_rejected_oversized_search_is_not_visible_or_citable(evaluation):
    world, node, _ = source_world("Long source " * 2000)
    session = evaluation.RouteSession(context(world, None, role="model"), "raw", token_budget=1000)
    result = await session.call("graph.search", {"queries": [node.id], "limit": 1})
    assert "error" in result and session.visible == {}
    assert session.tokens == count_tokens(result, evaluation.MODEL) <= 1000
    with pytest.raises(ValueError, match="Unread graph"):
        session.citations([{"object_id": node.id, "reference": None, "supports": "Unread"}])


async def test_call_allowance_blocks_further_graph_reads(evaluation):
    world, _, _ = source_world()
    session = evaluation.RouteSession(
        context(world, None, role="model"), "graph_search", call_budget=1
    )
    first = await session.call("graph.search", {"queries": ["Process"], "limit": 1})
    assert first["items"] and session.remaining_calls == 0
    before = world.memory.snapshot()
    result = await session.call("graph.search", {"queries": ["Unseen"]})
    assert "exhausted" in result["error"]
    assert world.memory.snapshot() == before
