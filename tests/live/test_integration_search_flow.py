"""Real model + Redis + embeddings: inspect queries, graph navigation and identity reuse."""

import json
import os
from pathlib import Path

import pytest
from redis.exceptions import ResponseError

from evertree.core.graph.types import Facet, GraphDelta, NodeUpdate
from evertree.debug_integration import DebugSession, load_debug_environment
from tests.support.pump_search import seed_pump_history

pytestmark = pytest.mark.skipif(
    os.environ.get("EVERTREE_CODEX_INTEGRATION") != "1"
    or os.environ.get("EVERTREE_EMBEDDINGS_INTEGRATION") != "1",
    reason="Explicit model and embeddings opt-in required; also needs configured Redis Search",
)


@pytest.fixture
async def session(tmp_path):
    session = DebugSession(tmp_path, timeout_seconds=120)
    load_debug_environment(Path(__file__).resolve().parents[2], session.config)
    try:
        yield session
    finally:
        histories = [
            call["payload"]["history"] for call in session.calls if call["method"] == "agent.close"
        ]
        (tmp_path / "search-flow.json").write_text(
            json.dumps(
                [item for batch in histories for item in batch], ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        # DebugSession closes its client; reconnect only to remove this test's private indexes.
        from redis.asyncio import Redis

        client = Redis.from_url(os.environ[session.config.redis_url_env])
        try:
            for name in tuple(session.index._ready):
                try:
                    await client.execute_command("FT.DROPINDEX", name, "DD")
                except ResponseError:
                    pass
            keys = [key async for key in client.scan_iter(session.index.namespace + ":*")]
            if keys:
                await client.delete(*keys)
        finally:
            await client.aclose()


@pytest.mark.parametrize("exact_name", [True, False], ids=["exact-name", "hybrid-search"])
async def test_existing_pump_search_navigation_and_new_state(session, exact_name):
    """Reuse a class, identity and known interval; add only the new state using real retrieval."""
    targets = seed_pump_history(session.graph)
    if not exact_name:
        session.graph.apply(
            GraphDelta(updates=(NodeUpdate(targets["pump"].id, {"name": "Насос контура Н-1"}),)),
            provenance="retrieval-evaluation-name-variant",
        )
    before = {node.id for node in session.graph.nodes()}
    await session.run()
    history = [
        item
        for call in session.calls
        if call["method"] == "agent.close"
        for item in call["payload"]["history"]
    ]
    created = [node for node in session.graph.nodes() if node.id not in before]
    assert not [node for node in created if node.kind in {"prototype", "instance"}], created
    states = [node for node in created if isinstance(node, Facet)]
    assert len(states) == 1, created
    state = states[0]
    assert state.valid_from == targets["off"].valid_until
    assert state.valid_until == targets["off"].valid_until.replace(minute=20)
    assert any(
        fact.args == {"facet": state.id, "instance": targets["pump"].id}
        for fact in session.graph.facts("STATE_IDENTITY")
    )
    known = session.graph.get(targets["off"].id)
    assert isinstance(known, Facet)
    assert (known.valid_from, known.valid_until) == (
        targets["off"].valid_from,
        targets["off"].valid_until,
    )
    assert session.graph.get(targets["other"].id) == targets["other"]
    described = {
        item["result"].get("subject", {}).get("id")
        for item in history
        if item["name"] == "describe"
    }
    assert targets["pump"].id in described or targets["off"].id in described, history


def _ancestors(graph, identity):
    ancestors, pending = set(), [identity]
    while pending:
        child = pending.pop()
        for fact in graph.facts("SUBTYPE_OF"):
            parent = fact.args["supertype"]
            if fact.args["type"] == child and parent not in ancestors:
                ancestors.add(parent)
                pending.append(parent)
    return ancestors


def _experience(session, monkeypatch, task, text, analysis):
    from evertree import debug_integration

    for name, value in (
        ("USER_TASK", task),
        ("INPUT_TEXT", text),
        ("CONSCIOUS_ANALYSIS", analysis),
    ):
        monkeypatch.setattr(debug_integration, name, value)
    session.metadata["integration_context"]["task"]["specification"]["objective"] = task


@pytest.mark.parametrize("mode", ["create-parent", "reuse-parent", "repair-existing-class"])
async def test_pump_class_is_connected_to_broader_class(session, mode):
    """Real retrieval must discover an existing parent or build the absent class hierarchy."""
    from evertree.core.graph.types import Prototype

    parent = None
    if mode != "create-parent":
        parent = Prototype(
            session.graph.reserve_id(),
            "Оборудование",
            description="Equipment: технические устройства, включая насосы и компрессоры.",
        )
        session.graph.apply(GraphDelta(creates=(parent,)), provenance="existing-parent")
    pump_class = None
    if mode == "repair-existing-class":
        pump_class = Prototype(
            session.graph.reserve_id(),
            "Насос",
            description="Pump: устройство для перекачки жидкости",
        )
        session.graph.apply(GraphDelta(creates=(pump_class,)), provenance="isolated-pump-class")
    await session.run()
    graph = session.graph
    instances = [node for node in graph.nodes() if node.kind == "instance"]
    assert len(instances) == 1, instances
    classes = [
        fact.args["type"]
        for fact in graph.facts("IDENTITY_TYPE")
        if fact.args["instance"] == instances[0].id
    ]
    assert classes
    if pump_class:
        assert pump_class.id in classes, (
            "Connect the existing class instead of creating a duplicate"
        )
    ancestors = set().union(*(_ancestors(graph, cls) for cls in classes))
    assert ancestors, "The pump class must not remain an isolated root"
    if parent:
        assert parent.id in ancestors, "Reuse the available broader class"
    states = [node for node in graph.nodes() if isinstance(node, Facet)]
    assert len(states) == 2, states
    assert len(list(graph.nodes())) - len(session.seed_ids) <= 16


async def test_hierarchy_in_another_domain(session, monkeypatch):
    """Reuse the same classification flow outside the pump example in the instructions."""
    _experience(
        session,
        monkeypatch,
        "Сохрани классификацию лабораторного термометра Т-7 для сравнения приборов.",
        "Т-7 — лабораторный термометр. Термометр является измерительным прибором. "
        "Измерительный прибор — техническое устройство для измерения физических величин.",
        "Важно различать конкретный Т-7, класс термометров и более общий класс измерительных "
        "приборов: это позволит сравнивать разные приборы. Показания и точность Т-7 пока неизвестны.",
    )
    await session.run()
    graph = session.graph
    instances = [node for node in graph.nodes() if node.kind == "instance"]
    assert len(instances) == 1
    classes = [
        fact.args["type"]
        for fact in graph.facts("IDENTITY_TYPE")
        if fact.args["instance"] == instances[0].id
    ]
    assert classes and any(_ancestors(graph, cls) for cls in classes)
    assert not [node for node in graph.nodes() if isinstance(node, Facet)]
    assert len(list(graph.nodes())) - len(session.seed_ids) <= 12


async def test_correct_recorded_interval_without_new_identity(session, monkeypatch):
    """A source correction updates the existing Facet and preserves its history."""
    targets = seed_pump_history(session.graph)
    before = {node.id for node in session.graph.nodes()}
    _experience(
        session,
        monkeypatch,
        "Исправь ошибочную границу ранее записанного выключенного состояния насоса Н-1.",
        "Проверка журнала уточнила: 12 октября 2026 насос Н-1 был выключен с 09:00 до 09:12 UTC. "
        "Ранее указанное 09:10 — ошибка записи. О состоянии после 09:12 новых сведений нет.",
        "Это исправление конца того же состояния, а не новое состояние или другой насос. "
        "Остальные объекты и наблюдения не затронуты.",
    )
    await session.run()
    graph = session.graph
    updated = graph.get(targets["off"].id)
    assert updated.valid_from == targets["off"].valid_from
    assert updated.valid_until == targets["off"].valid_until.replace(minute=12)
    assert len(graph.changes_of(updated.id)) >= 2
    assert graph.get(targets["other"].id) == targets["other"]
    assert not [
        node
        for node in graph.nodes()
        if node.id not in before and node.kind in {"instance", "facet"}
    ]


async def test_routine_series_does_not_expand_into_taxonomy(session, monkeypatch):
    """A useful hierarchy policy must not turn every routine source into objects and classes."""
    _experience(
        session,
        monkeypatch,
        "Оставь серию доступной для будущего анализа тренда. Сейчас выводов о тренде нет.",
        "Датчик теплицы 12 октября 2026 с 08:00 UTC, интервал 1 минута, температура в C: "
        + ", ".join(["20.0", "20.1", "20.2", "20.1"] * 6),
        "Обычная короткая серия без обнаруженных аномалий. Исходные данные записаны; "
        "создавать отдельное состояние на каждый отсчёт не нужно. Долгосрочный тренд неизвестен.",
    )
    await session.run()
    created = [node for node in session.graph.nodes() if node.id not in session.seed_ids]
    assert len(created) <= 8, created
    assert sum(isinstance(node, Facet) for node in created) <= 1
