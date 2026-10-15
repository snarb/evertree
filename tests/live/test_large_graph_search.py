"""Build a substantial graph through the real integrator, then fork it for independent updates."""

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from evertree.core.graph.store import GraphStore
from evertree.core.memory.store import TraceStore
from evertree.core.semantics.reading import card
from evertree.core.values import json_value
from tests.support.large_graph import CORPUS, LargeGraphSession, graph_stats, write_json
from tests.support.semantic_review import review_graph

pytestmark = pytest.mark.skipif(
    os.environ.get("EVERTREE_LARGE_GRAPH_INTEGRATION") != "1",
    reason="Explicit large-graph model and embeddings opt-in required",
)

# Fixed before graph construction; critical identity targets are not relevance judgments
# for every returned neighbor. Missing graph representations count separately from retrieval misses.
QUERIES = [
    ("exact", "P-101", ["P-101"]),
    ("alias", "основной циркуляционный насос SN-A701", ["P-101"]),
    ("bilingual", "main cold loop circulation pump", ["P-101"]),
    ("sensor", "датчик давления перед основным насосом", ["PT-101"]),
    ("temperature", "измеритель температуры после теплообменника HX-1", ["TT-101"]),
    ("hydraulic-filter", "сетка на входе циркуляционного насоса", ["F-101"]),
    ("air-filter", "очистка воздуха в шкафу бесперебойного питания", ["AF-1"]),
    ("power", "battery backup of primary UPS", ["UPS-1", "BAT-1"]),
    ("queue", "буфер неподтвержденных сообщений шлюза", ["Q-1"]),
    ("cache", "кэш ключей для устранения повторных измерений", ["CACHE-1"]),
    ("tls", "сертификат основного MQTT брокера", ["CERT-A"]),
    ("time", "синхронизация времени шлюза и edge сервера", ["NTP-1"]),
    ("network", "коммутатор резервного сервера терял пакеты", ["SW-2"]),
    ("storage", "том хранилища временных рядов с недостатком свободного места", ["VOL-1"]),
    ("restore", "изолированная база для проверки восстановления", ["TSDB-TEST"]),
    ("absent", "калибровка газового хроматографа", []),
]
FOLLOWUPS = [
    (
        "alias-reuse",
        (
            "13 октября 2026 года насос А с заводским номером SN-A701, он же P-101, "
            "работал с 08:00 до 08:15 UTC. В этом сообщении нет сведений о P-102."
        ),
        (
            "Это новое наблюдение состояния известного основного насоса. Важно сохранить интервал "
            "и связь с прежней идентичностью; прежние наблюдения остаются историческими."
        ),
    ),
    (
        "interval-correction",
        (
            "Исправление журнала Север: UPS-1 вернулся с батареи на сетевое питание "
            "12 октября 2026 года в 10:09 UTC, а не в 10:07. Переход на батарею в 10:00 "
            "подтверждён. Записи UPS-2 верны и не меняются."
        ),
        (
            "Это уточнение конца уже записанного интервала UPS-1, а не новый эпизод "
            "и не смена идентичности. Источник исправления должен оставаться отдельным."
        ),
    ),
    (
        "new-sibling",
        (
            "На площадке Север установлен дополнительный центробежный насос P-103, "
            "заводской номер SN-A703. Он подключён к холодному контуру CC-1. Это отдельное "
            "устройство, P-101 и P-102 остаются на месте. Работа P-103 ещё не наблюдалась."
        ),
        (
            "Нужно запомнить новую идентичность и принадлежность контуру, переиспользовав "
            "известный класс насоса. Нельзя приписывать ему состояния старых насосов."
        ),
    ),
    (
        "cross-domain",
        (
            "13 октября в 14:00 снова росла очередь Q-1. MQTT-A был доступен, свободного "
            "места VOL-1 достаточно. Пока рассматриваем две гипотезы: INGEST-1 медленно "
            "обрабатывает сообщения либо GW-1 слишком часто повторяет публикации. "
            "Новых измерений скорости обработки и повторов ещё нет."
        ),
        (
            "Важно сохранить проверенные ограничения и альтернативные объяснения. "
            "Ни одну причину пока нельзя считать установленной. Гидравлический F-101 "
            "к этому цифровому инциденту не относится."
        ),
    ),
]


def named_instances(graph, label):
    pattern = re.compile(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])", re.IGNORECASE)
    return [node for node in graph.nodes() if node.kind == "instance" and pattern.search(node.name)]


@pytest.fixture(scope="module")
async def corpus_graph(tmp_path_factory):
    root = tmp_path_factory.mktemp("large-graph")
    restored = os.environ.get("EVERTREE_LARGE_GRAPH_SNAPSHOT")
    if restored:
        snapshot = json.loads(Path(restored).read_text())
        write_json(root / "baseline.json", snapshot)
        return root, snapshot, []
    session = LargeGraphSession(root / "build")
    packets = []
    try:
        for i, text in enumerate(CORPUS.read_text(encoding="utf-8").split("\n===\n"), 1):
            packets.append(
                await session.packet(
                    root / f"build-{i:02d}",
                    text,
                    "Этот раздел важен для продолжающегося сопровождения Север. Сохрани полезные "
                    "идентичности, зависимости, наблюдения, гипотезы и переиспользуемые выводы. "
                    "Связывай их с уже известной структурой площадки. Не нужно сохранять каждую "
                    "фразу; особенно важно не смешивать похожие обозначения разных объектов.",
                )
            )
        snapshot = session.snapshot()
        write_json(root / "baseline.json", snapshot)
        write_json(root / "build-metrics.json", packets)
        return root, snapshot, packets
    finally:
        await session.close()


def test_corpus_builds_substantial_graph(corpus_graph):
    _, snapshot, packets = corpus_graph
    graph = GraphStore.from_snapshot(snapshot["graph"])
    stats = graph_stats(graph)
    # Relations alone must not inflate the size claim: require substantial semantic content.
    semantic = sum(v for k, v in stats["by_kind"].items() if k != "relation_instance")
    assert stats["total"] >= 100 and semantic >= 50, stats
    assert not [p["error"] for p in packets if p["error"]], packets


async def test_search_on_identical_large_graph(corpus_graph):
    root, snapshot, _ = corpus_graph
    session = LargeGraphSession(root / "retrieval", snapshot=snapshot)
    rows = []
    try:
        for case, query, labels in QUERIES:
            started = time.perf_counter()
            raw = (await session.call("semantic_search", {"query": query})).result
            retrieval_seconds = time.perf_counter() - started
            targets = {
                label: [n.id for n in named_instances(session.graph, label)] for label in labels
            }
            rows.append(
                {
                    "case": case,
                    "query": query,
                    "targets": targets,
                    "raw": raw,
                    "retrieval_seconds": retrieval_seconds,
                }
            )
        write_json(root / "retrieval.json", rows)
        cards = [card(n) for n in session.graph.nodes()]
        write_json(root / "cards.json", cards)
        coverage = {
            "target_groups": sum(len(r["targets"]) for r in rows),
            "represented": sum(bool(ids) for r in rows for ids in r["targets"].values()),
            "raw_found": sum(
                bool(set(ids) & {c["id"] for c in r["raw"]["items"]})
                for r in rows
                for ids in r["targets"].values()
            ),
        }
        write_json(root / "retrieval-summary.json", coverage)
        assert all(r["raw"]["status"] == "complete" for r in rows)
    finally:
        await session.close()


@pytest.mark.parametrize("case,text,analysis", FOLLOWUPS, ids=[c[0] for c in FOLLOWUPS])
async def test_updates_on_large_graph(corpus_graph, case, text, analysis):
    root, snapshot, _ = corpus_graph
    directory = root / case
    session = LargeGraphSession(directory, snapshot=snapshot)
    before = {n.id for n in session.graph.nodes()}
    original = {
        label: named_instances(session.graph, label)
        for label in ("P-101", "P-102", "UPS-1", "UPS-2")
    }
    try:
        metrics = await session.packet(directory, text, analysis)
        assert metrics["error"] is None, metrics["error"]
        session.memory.validate()
        for label, nodes in original.items():
            assert [n.id for n in named_instances(session.graph, label)] == [n.id for n in nodes], (
                label
            )
        new = [n for n in session.graph.nodes() if n.id not in before]
        if case == "new-sibling":
            pumps = named_instances(session.graph, "P-103")
            assert len(pumps) == 1, pumps
            assert not [n for n in new if n.kind == "facet"]
            assert len(original["P-101"]) == 1
            before_graph = GraphStore.from_snapshot(snapshot["graph"])
            known_types = {
                f.args["type"]
                for f in before_graph.facts("IDENTITY_TYPE")
                if f.args["instance"] == original["P-101"][0].id
            }
            new_types = {
                f.args["type"]
                for f in session.graph.facts("IDENTITY_TYPE")
                if f.args["instance"] == pumps[0].id
            }
            # The missing CC-1 may legitimately need a Circuit class of its own.
            assert new_types == known_types, "Reuse the known pump class without a duplicate"
        if case == "alias-reuse":
            assert len(original["P-101"]) == 1, "Baseline failed to preserve the pump identity"
            assert not [n for n in new if n.kind == "instance"]
            states = [n for n in new if n.kind == "facet"]
            assert states
            assert any(
                f.args["instance"] == original["P-101"][0].id
                and f.args["facet"] in {s.id for s in states}
                for f in session.graph.facts("STATE_IDENTITY")
            )
            assert any(
                s.valid_from == datetime(2026, 10, 13, 8, tzinfo=UTC)
                and s.valid_until == datetime(2026, 10, 13, 8, 15, tzinfo=UTC)
                for s in states
            ), "The new observation must retain its own source interval"
        if case == "interval-correction":
            assert len(original["UPS-1"]) == 1
            before_graph = GraphStore.from_snapshot(snapshot["graph"])
            identity = original["UPS-1"][0].id
            ids = [
                f.args["facet"]
                for f in before_graph.facts("STATE_IDENTITY")
                if f.args["instance"] == identity
            ]
            targets = [
                before_graph.get(i)
                for i in ids
                if before_graph.get(i).valid_until
                and before_graph.get(i).valid_until.isoformat().startswith("2026-10-12T10:07")
            ]
            assert targets, "Baseline did not preserve the interval; correction cannot be evaluated"
            assert any(
                session.graph.get(n.id).valid_until == n.valid_until.replace(minute=9)
                for n in targets
            )
            assert not [n for n in new if n.kind in {"instance", "facet"}]
            for target in targets:
                old_history = before_graph.changes_of(target.id)
                history = session.graph.changes_of(target.id)
                assert history[: len(old_history)] == old_history
                assert len(history) > len(old_history)
                assert history[-1].provenance != old_history[-1].provenance
                event = session.memory.get_event(history[-1].provenance["event_ref"])
                assert event.dependencies, "The correction must cite its own recorded grounds"
            for fact in before_graph.facts("STATE_IDENTITY"):
                if fact.args["instance"] in {n.id for n in original["UPS-2"]}:
                    state_id = fact.args["facet"]
                    assert session.graph.get(state_id) == before_graph.get(state_id)
        if case == "cross-domain":
            assert any(n.kind == "claim" for n in new), "Alternative causes must remain hypotheses"
    finally:
        await session.close()


def test_baseline_preserves_source_meaning(corpus_graph):
    """Check source-grounded identities/time and concrete part-whole facts, not only size."""
    root, snapshot, _ = corpus_graph
    graph = GraphStore.from_snapshot(snapshot["graph"])
    TraceStore.from_snapshot(snapshot["trace"]).validate()
    problems = []
    for fact in graph.facts("PART_WHOLE"):
        part, whole = (graph.get(fact.args[key]) for key in ("part", "whole"))
        if {part.kind, whole.kind} == {"prototype", "instance"}:
            problems.append(f"Class used as a concrete component: {part.name} -> {whole.name}")
    # These report objects are equipment/data stores, not activities in the process taxonomy.
    participants = {
        n.id for label in ("CTRL-1", "Q-1", "CACHE-1") for n in named_instances(graph, label)
    }
    for fact in graph.facts("IDENTITY_TYPE"):
        if fact.args["instance"] in participants:
            prototype = graph.get(fact.args["type"])
            lineage = (prototype, *graph.ancestors(prototype.id))
            if any(n.name == "Process" for n in lineage):
                problems.append(
                    f"Component classified as activity: {graph.get(fact.args['instance']).name}"
                )
    for label, start, end in (
        ("P-101", (8, 0), (9, 10)),
        ("P-102", (9, 10), (9, 25)),
        ("UPS-1", (10, 0), (10, 7)),
    ):
        objects = named_instances(graph, label)
        if len(objects) != 1:
            problems.append(f"Expected one identity for {label}, found {len(objects)}")
            continue
        states = [
            graph.get(f.args["facet"])
            for f in graph.facts("STATE_IDENTITY")
            if f.args["instance"] == objects[0].id
        ]
        expected = (
            datetime(2026, 10, 12, *start, tzinfo=UTC),
            datetime(2026, 10, 12, *end, tzinfo=UTC),
        )
        if not any((n.valid_from, n.valid_until) == expected for n in states):
            problems.append(f"Missing or incorrect source interval for {label}: {expected}")
    if named_instances(graph, "P-103"):
        problems.append("An unobserved future pump was invented during baseline construction")
    if any(n.kind == "program" and n.name != "Process" for n in graph.nodes()):
        problems.append("A described diagnostic procedure became an executable Program")
    write_json(root / "meaning-audit.json", {"problems": problems})
    assert not problems, problems


async def test_baseline_preserves_operational_distinctions(corpus_graph):
    """Catch semantic losses that size, valid intervals and successful writes cannot detect."""
    root, snapshot, _ = corpus_graph
    graph = GraphStore.from_snapshot(snapshot["graph"])
    assert len(named_instances(graph, "CACHE-1")) == 1, "Deduplication cache identity was lost"
    review = await review_graph(
        root / "semantic-review",
        sources=CORPUS.read_text(encoding="utf-8"),
        nodes=[json_value(n) for n in graph.nodes()],
        criteria={
            "cache_setting": (
                "CACHE-1 is separately addressable and retains its deduplication-key purpose and "
                "24-hour retention. GW-1's 5-second response timeout is a separate setting. "
                "A generic concept about cache lifetime cannot replace the local configuration."
            ),
            "hydraulic_predicate": (
                "The HX-1 relation represents hydraulic separation of CC-1 and HC-1, not fluid "
                "connection. Name, type definition, arguments and fact meaning agree; a predicate "
                "ambiguously meaning connected-or-separated fails unless an explicit role "
                "distinguishes them. Heat transfer between separate circuits is compatible."
            ),
            "revisable_explanations": (
                "The final incident analysis preserves filter contamination, valve throttling "
                "and pressure-sensor bias as independently revisable hypotheses, with relevant "
                "grounds and limits. Cleaning supports the filter; original valve position is "
                "unknown; the later 14:00 reference check does not exclude transient morning "
                "sensor error. A single Claim listing all alternatives is insufficient. "
                "Separate Claims or precise qualified relation instances are both valid."
            ),
        },
    )
    assert all(item["passed"] for item in review.values()), review


async def test_cache_setting_correction_retains_identity_and_other_settings(corpus_graph):
    """A real follow-up must address the preserved component, not replace it with an abstraction."""
    root, snapshot, _ = corpus_graph
    session = LargeGraphSession(root / "cache-correction", snapshot=snapshot)
    try:
        caches = named_instances(session.graph, "CACHE-1")
        assert len(caches) == 1
        cache_id, revision = caches[0].id, session.graph.revision
        source = (
            "Исправление конфигурации Север: срок хранения ключей дедупликации в CACHE-1 "
            "был записан неверно. Он равен 12 часам, а не 24. Это исправление документации, "
            "не новое изменение настроек. Таймаут ответа GW-1 остаётся 5 секунд."
        )
        result = await session.packet(root / "cache-correction", source, "Уточни известные знания.")
        assert result["error"] is None
        assert [n.id for n in named_instances(session.graph, "CACHE-1")] == [cache_id]
        history = session.graph.snapshot()["history"]
        assert history[: len(snapshot["graph"]["history"])] == snapshot["graph"]["history"]
        assert any(c["seq"] > revision and c["before"] for c in history)
        session.memory.validate()
        review = await review_graph(
            root / "cache-correction-review",
            sources=CORPUS.read_text(encoding="utf-8") + "\n\nLater correction:\n" + source,
            nodes=[json_value(n) for n in session.graph.nodes()],
            criteria={
                "corrected_setting": (
                    "Current knowledge associates CACHE-1 retention with 12 hours. No remaining "
                    "current assertion still gives it 24 hours. GW-1 response timeout remains "
                    "5 seconds, and its value was not overwritten by the cache correction. "
                    "Explicitly historical or superseded descriptions are acceptable."
                )
            },
        )
        assert all(item["passed"] for item in review.values()), review
    finally:
        await session.close()
