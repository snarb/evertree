"""Batch retrieval, relevance filtering and per-query creation review contracts."""

import asyncio
import io
import json
from dataclasses import replace

import pytest

from evertree.common.semantic_search import search
from evertree.core.graph.types import GraphDelta, Node
from evertree.core.semantics.config import JevConfig, SemanticConfig, load_search_environment
from evertree.core.semantics.jev import JevFilter
from evertree.core.semantics.searching import search_queries
from evertree.core.values import ContractError
from evertree.processes.semantic_processing.knowledge_integration._exec import run
from tests.support.semantics import (
    EmptyIndex,
    context,
    recorded_experience,
    semantic_world,
    write_action,
)


async def test_batch_merges_exact_and_ranked_candidates_and_deduplicates_queries():
    calls = []

    class Index(EmptyIndex):
        async def lexical(self, nodes, queries, kind):
            calls.append(("bm25", queries))
            return [{"ids": ids[:14]}, {"ids": ids[8:]}]

        async def vector(self, nodes, queries, kind):
            calls.append(("vector", queries))
            return [{"ids": [ids[2], ids[0]]}, {"ids": [ids[10], ids[8]]}]

    world = semantic_world(index=Index())
    nodes = [Node(world.graph.reserve_id(), f"Candidate {i}") for i in range(22)]
    world.graph.apply(GraphDelta(creates=nodes), provenance="corpus")
    ids = [n.id for n in nodes]
    queries = ["Process", "related machines", "cooling", " RELATED   MACHINES ", "Process"]
    result = (await search(context(world, None), queries))["result"]
    assert calls == [("bm25", queries[1:3]), ("vector", queries[1:3])]
    assert [row["query"] for row in result["queries"]] == queries[:3]
    assert result["status"] == "complete" and not result["exact"]
    assert result["items"][0]["id"] == world.graph.find("Process").id
    assert [len(row["ids"]) for row in result["queries"]] == [1, 10, 10]
    returned = [node["id"] for node in result["items"]]
    assert len(returned) == len(set(returned)) <= 30
    shared = next(node for node in result["items"] if node["id"] == ids[8])
    assert shared["query_indices"] == [1, 2]
    assert shared["channels"] == ["bm25", "vector"]
    again = (await search(context(world, None), queries))["result"]
    assert again == result


async def test_partial_batch_failure_only_revokes_the_affected_query():
    class Index(EmptyIndex):
        async def vector(self, nodes, queries, kind):
            return [{"ids": []}, {"ids": [], "error": "unavailable"}]

    world = semantic_world(index=Index())
    refs, metadata = recorded_experience(world, "Two useful new terms")
    found = (await search(context(world, None), ["First", "Second"]))["result"]
    assert found["status"] == "incomplete"
    assert [row["status"] for row in found["queries"]] == ["complete", "incomplete"]
    assert found["errors"] == [{"channel": "vector", "error": "unavailable", "query_index": 1}]
    for name, allowed in [("First", True), ("Second", False)]:
        action = {"action": "create_concept", "name": name, "description": None, "sources": refs}
        result = write_action(world, refs, metadata, action, key=name, searched=False)
        assert ("object" in result) is allowed


async def test_batch_review_is_reused_across_own_writes_and_revoked_on_failed_refresh():
    calls = []

    class Index(EmptyIndex):
        async def lexical(self, nodes, queries, kind):
            calls.append(list(queries))
            return [{"ids": []} for _ in queries]

    world = semantic_world(index=Index())
    refs, _ = recorded_experience(world, "Several new meanings")

    async def model(payload, call):
        found = await call("search", {"queries": ["First", "Second", "Third"]})
        assert len(found["queries"]) == 3
        for name in ("First", "Second"):
            assert "object" in await call(
                "create_concept",
                {
                    "name": name,
                    "description": None,
                    "sources": refs,
                },
            )

        async def failed(*args):
            raise RuntimeError("offline")

        world.service.index.lexical = failed
        refreshed = await call("search", {"queries": ["Third"]})
        assert refreshed["status"] == "incomplete"
        rejected = await call(
            "create_concept", {"name": "Third", "description": None, "sources": refs}
        )
        assert "incomplete" in rejected["error"]

    await run(context(world, model, role="exec"), refs)
    assert calls == [["First", "Second", "Third"]]


@pytest.mark.parametrize("queries", [[], "text", [""], [" \t "], [True], [0], [-1], [[]]])
def test_invalid_queries_are_rejected(queries):
    with pytest.raises(ContractError):
        search_queries(queries)


def test_query_normalization_preserves_integer_and_numeric_name_distinction():
    assert search_queries(["CAFÉ animal", "cafe\u0301   ANIMAL", 12, "12", 12]) == [
        "CAFÉ animal",
        12,
        "12",
    ]


async def test_jev_scores_unique_candidates_before_limits_and_keeps_exact_matches(monkeypatch):
    class Index(EmptyIndex):
        async def lexical(self, nodes, queries, kind):
            return [{"ids": ids} for _ in queries]

    world = semantic_world(index=Index(), config=SemanticConfig(jev=JevConfig(enabled=True)))
    nodes = [Node(world.graph.reserve_id(), f"Candidate {i}") for i in range(15)]
    world.graph.apply(GraphDelta(creates=nodes), provenance="corpus")
    ids = [n.id for n in nodes]
    exact = world.graph.find("Process").id
    ids.insert(0, exact)
    calls = []

    async def score(queries, supplied):
        calls.append((queries, supplied))
        return {node["id"]: 0 if node["id"] in ids[1:6] else 0.05 for node in supplied}

    monkeypatch.setattr(world.service.jev, "score", score)
    found = (await search(context(world, None), ["Process", "other", "related"]))["result"]
    assert len(calls) == 1
    assert [n["id"] for n in calls[0][1]] == ids[1:]
    assert exact == found["items"][0]["id"]
    assert all(i not in {n["id"] for n in found["items"]} for i in ids[1:6])
    assert len(found["queries"][1]["ids"]) == 10
    assert found["status"] == "complete" and not found["warnings"]


async def test_jev_failed_batch_retains_candidates_and_does_not_revoke_search(monkeypatch):
    class Index(EmptyIndex):
        async def lexical(self, nodes, queries, kind):
            return [{"ids": [existing.id]} for _ in queries]

    world = semantic_world(index=Index(), config=SemanticConfig(jev=JevConfig(enabled=True)))
    existing = world.graph.find("Process")

    async def fail(*args):
        raise TimeoutError("must not expose upstream details")

    monkeypatch.setattr(world.service.jev, "score", fail)
    result = (await search(context(world, None), ["new object"]))["result"]
    assert result["status"] == "complete" and result["queries"][0]["status"] == "complete"
    assert result["items"][0]["id"] == existing.id
    assert result["warnings"][0]["channel"] == "jev"
    assert "upstream" not in json.dumps(result)


@pytest.mark.parametrize("enabled,threshold", [(False, 0.05), (True, 0)])
async def test_disabled_or_zero_threshold_never_calls_jev(monkeypatch, enabled, threshold):
    filter_ = JevFilter(JevConfig(enabled=enabled, threshold=threshold))

    async def fail(*args):
        pytest.fail("Jev must be bypassed")

    monkeypatch.setattr(filter_, "score", fail)
    assert await filter_.filter(["query"], [{"id": 1}]) == ({1}, [])


async def test_jev_batch_failure_is_local_and_threshold_boundary_is_inclusive(monkeypatch):
    filter_ = JevFilter(JevConfig(enabled=True, threshold=1))

    async def score(queries, nodes):
        if nodes[0]["id"] == 0:
            raise ValueError("malformed")
        return {node["id"]: 1 if node["id"] == 128 else 0.99 for node in nodes}

    monkeypatch.setattr(filter_, "score", score)
    kept, warnings = await filter_.filter(["query"], [{"id": i} for i in range(256)])
    assert kept == set(range(129))
    assert len(warnings) == 1 and warnings[0]["ids"] == list(range(128))


@pytest.mark.parametrize(
    "answer",
    [
        {},
        {"2": {"type": "noul", "noul": 0.5}},
        {"1": {"type": "score", "noul": 0.5}},
        {"1": {"type": "noul", "noul": True}},
        {"1": {"type": "noul", "noul": -1}},
        {"1": {"type": "noul", "noul": 1.01}},
        {"1": {"type": "noul", "noul": float("nan")}},
        {"1": {"type": "noul", "noul": "0.5"}},
    ],
)
async def test_jev_validates_response_ids_types_and_probabilities(monkeypatch, answer):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: io.BytesIO(json.dumps({"answers": answer}).encode()),
    )
    filter_ = JevFilter(JevConfig(enabled=True))
    kept, warnings = await filter_.filter(["query"], [{"id": 1}])
    assert kept == {1} and warnings


async def test_jev_http_protocol_and_two_request_concurrency_limit(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    active = maximum = 0
    release = asyncio.Event()
    sent = []

    def send(request, timeout):
        assert request.full_url == "https://api.typesafe.ai/v1/systemone"
        assert request.get_header("Authorization") == "Bearer test-only" and timeout == 10
        payload = json.loads(request.data)
        assert payload["state"]["queries"] == ["query"]
        sent.append(payload)
        return io.BytesIO(
            json.dumps(
                {"answers": {i: {"type": "noul", "noul": 0.05} for i in payload["questions"]}}
            ).encode()
        )

    async def thread(func):
        nonlocal active, maximum
        active += 1
        maximum = max(active, maximum)
        if active == 2:
            release.set()
        await release.wait()
        await asyncio.sleep(0)
        try:
            return func()
        finally:
            active -= 1

    monkeypatch.setattr("urllib.request.urlopen", send)
    monkeypatch.setattr(
        asyncio.get_running_loop(), "run_in_executor", lambda executor, func: thread(func)
    )
    kept, warnings = await JevFilter(JevConfig(enabled=True)).filter(
        ["query"], [{"id": i} for i in range(300)]
    )
    assert maximum == 2 and len(sent) == 3
    assert kept == set(range(300)) and not warnings
    assert all(len(p["questions"]) <= 128 for p in sent)


@pytest.mark.parametrize(
    "changes",
    [
        {"threshold": -1},
        {"threshold": 1.01},
        {"threshold": True},
        {"threshold": float("inf")},
        {"threshold": float("nan")},
        {"enabled": "yes"},
        {"model": " "},
        {"api_key_env": ""},
    ],
)
def test_jev_config_rejects_invalid_settings(changes):
    with pytest.raises(ValueError):
        replace(JevConfig(), **changes)


def test_jev_config_and_secrets_load_from_agent_home_without_overwriting_environment(
    tmp_path, monkeypatch
):
    (tmp_path / "evertree.toml").write_text("[semantics.jev]\nenabled=true\nthreshold=0.01\n")
    config = SemanticConfig.load(tmp_path)
    assert config.jev == JevConfig(enabled=True, threshold=0.01)
    monkeypatch.setenv("TYPESAFE_API_KEY", "already-present")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "TYPESAFE_API_KEY=from-file\nOPENAI_API_KEY=literal-$value\nUNRELATED_KEY=ignored\n"
    )
    load_search_environment(tmp_path, config)
    import os

    assert os.environ["TYPESAFE_API_KEY"] == "already-present"
    assert os.environ["OPENAI_API_KEY"] == "literal-$value"
    assert "UNRELATED_KEY" not in os.environ


async def test_jev_packs_long_cards_by_context_size_without_truncating_them():
    jev = JevFilter(JevConfig(enabled=True))
    nodes = [
        {"id": i, "name": f"Source {i}", "description": "detail " * 2000 + f"tail-{i}"}
        for i in range(20)
    ]
    batches = []

    async def score(queries, batch):
        assert queries == ["a question"]
        batches.append(batch)
        return {node["id"]: 0.8 for node in batch}

    jev.score = score
    kept, warnings = await jev.filter(["a question"], nodes)
    assert len(batches) > 1
    assert max(map(len, batches)) < len(nodes)
    assert [node for batch in batches for node in batch] == nodes
    assert kept == {node["id"] for node in nodes}
    assert warnings == []


async def test_integer_id_lookup_cannot_confirm_search_for_a_numeric_name():
    world = semantic_world()
    refs, metadata = recorded_experience(world, "A numeric name")
    identity = world.graph.find("Process").id
    found = (await search(context(world, None), [identity]))["result"]
    assert found["exact"]
    action = {
        "action": "create_concept",
        "name": str(identity),
        "description": None,
        "sources": refs,
    }
    result = write_action(world, refs, metadata, action, searched=False)
    assert "complete search" in result["error"]
