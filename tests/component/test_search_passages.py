"""Passage coverage and retrieval configuration without external services."""

from dataclasses import replace

import pytest
import tiktoken

from evertree.core.semantics.config import SearchConfig, SemanticConfig
from evertree.core.semantics.index import RedisSearchIndex


def test_passages_preserve_unicode_and_tail_without_duplicate_object_quotas():
    index = RedisSearchIndex(
        SemanticConfig(search=SearchConfig(chunk_tokens=64, chunk_overlap=16)), "passages"
    )
    text = "Начало 🦊 中文 " + "непрерывный 🏔️ текст " * 120 + "уникальный хвост"
    nodes = [
        {"id": 18, "name": "Объект", "kind": "concept", "description": text},
        {"id": 19, "name": "Другой", "kind": "concept"},
    ]
    passages = index._documents(nodes)
    texts = [row["text"] for row in passages if row["id"] == 18]
    assert len(texts) > 2
    assert texts[0].startswith("Объект Начало")
    assert texts[-1].endswith("уникальный хвост")
    assert all(part in "Объект " + text and "\ufffd" not in part for part in texts)
    encoder = tiktoken.get_encoding("cl100k_base")
    assert all(len(encoder.encode(part)) <= 68 for part in texts)
    assert len({row["key"] for row in passages}) == len(passages)
    assert index._fetch_count(nodes, 1) == len(texts)
    assert index._fetch_count(nodes, 2) == len(passages)
    assert index._ids(
        [3, b"a", [b"identity", b"18"], b"b", [b"identity", b"18"], b"c", [b"identity", b"19"]]
    ) == [18, 19]


def test_chunk_settings_change_derived_generation_and_config_loads(tmp_path):
    (tmp_path / "evertree.toml").write_text(
        "[semantics.search]\nbm25_candidates=40\nvector_candidates=80\nchunk_tokens=256\nchunk_overlap=64\n"
    )
    config = SemanticConfig.load(tmp_path)
    assert config.search == SearchConfig(40, 80, 256, 64)
    original = RedisSearchIndex(SemanticConfig(), "same")
    changed = RedisSearchIndex(replace(config), "same")
    assert original._generation([]) != changed._generation([])


def test_passage_ranks_keep_best_score_and_break_equal_scores_by_object_id():
    assert RedisSearchIndex._ids(
        [
            3,
            b"b",
            b"5.0",
            [b"identity", b"19"],
            b"a",
            b"5.0",
            [b"identity", b"18"],
            b"c",
            b"2.0",
            [b"identity", b"18"],
        ],
        lexical=True,
    ) == [18, 19]
    assert RedisSearchIndex._ids(
        [
            3,
            b"b",
            [b"identity", b"19", b"distance", b"0.2"],
            b"a",
            [b"identity", b"18", b"distance", b"0.2"],
            b"c",
            [b"identity", b"18", b"distance", b"0.6"],
        ]
    ) == [18, 19]


@pytest.mark.parametrize(
    "values",
    [
        {"bm25_candidates": 0},
        {"vector_candidates": 1001},
        {"vector_candidates": True},
        {"chunk_tokens": 63},
        {"chunk_tokens": 4097},
        {"chunk_tokens": True},
        {"chunk_overlap": -1},
        {"chunk_overlap": 768},
        {"chunk_overlap": False},
    ],
)
def test_invalid_search_configuration(values):
    with pytest.raises(ValueError, match="semantic search configuration"):
        SearchConfig(**values)
