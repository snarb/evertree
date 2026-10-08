"""Real Luna decisions over populated GraphStore; isolated index channels are explicit."""

import json
import os
from uuid import uuid4

import pytest

from evertree.common.semantic_search import search
from evertree.core.codex.provider import CodexProvider
from evertree.core.provider import AgentRequest
from evertree.core.semantics.config import SemanticConfig
from tests.support.semantics import context, populated_search_world

pytestmark = pytest.mark.skipif(
    os.environ.get("EVERTREE_CODEX_INTEGRATION") != "1", reason="Explicit live Luna opt-in required"
)


@pytest.mark.parametrize(
    ("query", "kind", "target", "channel"),
    [
        (
            "Как называется тихий вибрирующий звук довольной кошки?",
            "concept",
            "concept",
            "taxonomy",
        ),
        (
            "Тип небольшого домашнего питомца, который ловит мышей",
            "prototype",
            "prototype",
            "taxonomy",
        ),
        ("Сохранённое состояние домашней кошки", "facet", "facet", "taxonomy"),
        (
            "Схема родства ребёнка женского пола и его матери",
            "relation_type",
            "relation_type",
            "taxonomy",
        ),
        ("Дочери Светланы", "instance", "daughters", "relations"),
        ("Сохранённые состояния дочерей Светланы", "facet", "facets", "relations"),
        ("Факты о том, кто является дочерьми Светланы", "relation_instance", "facts", "relations"),
        ("Категория животных, кормящих детёнышей молоком", "prototype", "mammals", "taxonomy"),
        ("Квантовый двигатель звездолёта", "concept", "absent", "taxonomy"),
    ],
)
async def test_live_luna_search_populated_graph(tmp_path, query, kind, target, channel):
    world = populated_search_world(config=SemanticConfig(taxonomy_enabled=channel == "taxonomy"))
    provider = CodexProvider(state_dir=tmp_path / "provider")
    calls = []

    async def model(payload):
        request = AgentRequest(
            payload["prompt"],
            tmp_path,
            instructions=payload["instructions"],
            output_schema=payload["output_schema"],
            model="gpt-6-luna",
            effort="low",
            timeout_seconds=180,
        )
        events = [event async for event in provider.run(uuid4().hex, request)]
        calls.append(
            {"request": payload, "events": [{"kind": e.kind, "data": e.data} for e in events]}
        )
        (tmp_path / "search-trace.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2))
        errors = [event.data for event in events if event.kind == "error"]
        assert not errors, errors
        completed = [event.data for event in events if event.kind == "completed"]
        assert len(completed) == 1
        return completed[0]["parsed"]

    try:
        result = (await search(context(world, model), query, kind=kind))["result"]
        (tmp_path / "search-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        assert result["status"] == "complete", result
        expected = (
            {n.id for n in world.family[target]}
            if target in world.family
            else set()
            if target == "absent"
            else {world.targets[target].id}
        )
        found = {item["id"]: item for item in result["items"]}
        assert expected <= found.keys(), result
        if target == "absent":
            assert not found, result
        assert all(channel in found[i]["channels"] for i in expected), result
        if channel == "relations":
            assert set(found) == expected, result
            assert all(found[i]["source_facts"] and found[i]["evidence"] for i in expected)
        else:
            prompts = [json.loads(c["request"]["prompt"]) for c in calls]
            assert any(
                "children" in n and n["children"] for p in prompts for n in p.get("nodes", [])
            )
        assert not result["exact"]
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "real_embeddings", [False, True], ids=["test-embeddings", "openai-embeddings"]
)
async def test_live_search_through_dbos_and_redis(tmp_path, real_embeddings):
    """Actual Program worker → core Redis → Luna → final checked cards."""
    from contextlib import suppress
    from dataclasses import asdict, replace
    from pathlib import Path

    from redis.asyncio import Redis
    from redis.exceptions import ResponseError

    from evertree.core.runtime.controller import ProgramSpec, Runtime
    from evertree.core.semantics.index import RedisSearchIndex
    from tests.live.test_codex_integration import collect
    from tests.support.runtime import TestProcess, commit_programs

    if not os.environ.get("EVERTREE_TEST_REDIS_URL"):
        pytest.skip("Real Redis URL required")
    if real_embeddings and not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OpenAI embedding key required for all-live retrieval")
    config = (
        SemanticConfig() if real_embeddings else replace(SemanticConfig(), embedding_dimensions=3)
    )

    class TestEmbeddings:
        async def embed(self, texts):
            return [[1.0, 0.0, 0.0] if "мышей" in text else [0.0, 1.0, 0.0] for text in texts]

    client = Redis.from_url(os.environ["EVERTREE_TEST_REDIS_URL"])
    index = RedisSearchIndex(
        config, uuid4().hex, client=client, embeddings=None if real_embeddings else TestEmbeddings()
    )
    world = populated_search_world(config=config, index=index)
    provider = CodexProvider(state_dir=tmp_path / "provider")
    root = Path(__file__).resolve().parents[2]
    paths = [
        "src/evertree/processes/semantic_processing/semantic_search/_model.py",
        "src/evertree/common/semantic_search.py",
        "src/evertree/common/structured.py",
    ]
    revision = commit_programs(tmp_path / "repo", {p: (root / p).read_text() for p in paths})
    spec = ProgramSpec(100, paths[0], revision, role="model")
    calls = []

    async def gateway(method, payload):
        payload = dict(payload)
        metadata = payload.pop("_runtime")
        if method == "resolve_program":
            return asdict(spec)
        if method == "agent.run":
            events, result = await collect(
                provider,
                AgentRequest(
                    payload["prompt"],
                    tmp_path,
                    instructions=payload["instructions"],
                    output_schema=payload["output_schema"],
                    model="gpt-6-luna",
                    effort="low",
                    timeout_seconds=180,
                ),
            )
            calls.append(
                {"request": payload, "events": [{"kind": e.kind, "data": e.data} for e in events]}
            )
            (tmp_path / "dbos-search-trace.json").write_text(
                json.dumps(calls, ensure_ascii=False, indent=2)
            )
            return result
        return await world.service.execute(method, payload, metadata)

    runtime = Runtime(tmp_path / "runtime", tmp_path / "repo", gateway, process_factory=TestProcess)
    try:
        result = (
            await runtime.execute(
                "task",
                spec,
                {"query": "домашний питомец ловит мышей", "kind": "prototype"},
                run_id="live-search",
            )
        ).result
        assert result["status"] == "complete", result
        cat = next(item for item in result["items"] if item["id"] == world.targets["prototype"].id)
        assert set(cat["channels"]) >= {"bm25", "vector", "taxonomy"}, result
        assert not result["exact"]
        before = len(calls)
        again = (
            await runtime.execute(
                "task",
                spec,
                {"query": "домашний питомец ловит мышей", "kind": "prototype"},
                run_id="live-search",
            )
        ).result
        assert again == result and len(calls) == before
    finally:
        await runtime.close()
        await provider.close()
        for name in tuple(index._ready):
            with suppress(ResponseError):
                await client.execute_command("FT.DROPINDEX", name, "DD")
        keys = [key async for key in client.scan_iter(index.namespace + ":*")]
        if keys:
            await client.delete(*keys)
        await index.close()
