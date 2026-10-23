"""Source integrity must be checked against original labels before evaluating recall."""

import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "corpus_audit", Path(__file__).resolve().parents[2] / "artifacts/search-recall/audit.py"
)
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)


def article(url, body, category="sports"):
    return {"url": url, "title": url, "category": category, "body": body, "author": "Reporter"}


def test_shortened_gold_list_is_detected_even_when_every_local_fact_is_present():
    sports, other = article("sports", "A won"), article("other", "B lost", "entertainment")
    evidence = [
        {"url": row["url"], "fact": row["body"], "category": row["category"], "title": row["title"]}
        for row in (sports, other)
    ]
    original = {
        "query": "Compare A and B",
        "question_type": "comparison_query",
        "answer": "Yes",
        "evidence_list": evidence,
    }
    local = {**original, "evidence_list": evidence[:1]}
    result = audit.analyze([sports], [local], [sports, other], [original])
    assert not result["local"]["missing_sources"]
    assert not result["local"]["nonliteral_facts"]
    assert result["omitted_evidence_count"] == 1
    assert result["missing_original_article_urls"] == ["other"]
    assert result["restored_sports"]["evidence_count"] == 2
    assert result["restored_sports"]["articles"] == 2


def test_restored_dataset_keeps_all_metadata_and_refuses_modified_or_missing_sources(tmp_path):
    source = article("source", "A won")
    question = {
        "query": "Who won?",
        "question_type": "inference_query",
        "answer": "A",
        "evidence_list": [{"url": "source", "fact": "A won"}],
    }
    audit.write_dataset(tmp_path, [source], [question], origin={}, original_indices=[17])
    sources, questions, manifest = audit.read_dataset(tmp_path)
    assert json.loads(audit.source_text(sources[0])) == source
    assert questions == [question] and manifest["original_question_indices"] == [17]
    (tmp_path / "articles.json").write_text("[]")
    with pytest.raises(ValueError, match="fingerprint"):
        audit.read_dataset(tmp_path)
    audit.write_dataset(tmp_path, [], [question], origin={}, original_indices=[17])
    with pytest.raises(ValueError, match="source evidence"):
        audit.read_dataset(tmp_path)


def test_duplicate_source_identity_cannot_silently_replace_an_article():
    with pytest.raises(ValueError, match="Duplicate url"):
        audit.coverage([article("same", "A won"), article("same", "B lost")], [])


def test_retrieval_cards_use_complete_audited_records_and_do_not_import_answer_labels(
    tmp_path, monkeypatch
):
    from importlib import import_module
    from types import SimpleNamespace

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "artifacts/search-recall")
    )
    reader = import_module("diagnose")
    sources = [article("sports", "A won"), article("other", "B lost", "entertainment")]
    questions = [
        {
            "query": "Compare A and B",
            "answer": "Yes",
            "question_type": "comparison_query",
            "evidence_list": [{"url": row["url"], "fact": row["body"]} for row in sources],
        }
    ]
    audit.write_dataset(tmp_path, sources, questions, origin={}, original_indices=[17])
    cards, urls, selected_questions, selected, manifest = reader.corpus(
        SimpleNamespace(dataset=tmp_path, source=None, pilot=None, count=1), "full-text"
    )
    assert selected == [0] and selected_questions == questions
    assert manifest["original_question_indices"] == [17]
    assert [json.loads(row["description"]) for row in cards if row["id"] in urls] == sources


def test_incomplete_historical_labels_require_explicit_reproduction_opt_in(monkeypatch):
    from importlib import import_module
    from types import SimpleNamespace

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "artifacts/search-recall")
    )
    reader = import_module("diagnose")
    with pytest.raises(ValueError, match="audited --dataset"):
        reader.corpus(SimpleNamespace(dataset=None, historical=False), "full-text")


def test_independent_selection_excludes_prior_question_and_complete_source_group(
    tmp_path, monkeypatch
):
    from importlib import import_module
    from types import SimpleNamespace

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "artifacts/search-recall")
    )
    reader = import_module("diagnose")
    sources = [article("a", "A won"), article("b", "B lost"), article("c", "C played")]
    questions = [
        {
            "query": text,
            "answer": "x",
            "question_type": "comparison_query",
            "evidence_list": [{"url": row["url"], "fact": row["body"]} for row in group],
        }
        for text, group in [
            ("old", sources[:2]),
            ("paraphrased", sources[:2]),
            ("fresh", sources[1:]),
        ]
    ]
    dataset = tmp_path / "dataset"
    audit.write_dataset(dataset, sources, questions, origin={}, original_indices=[1, 2, 3])
    previous = tmp_path / "previous.json"
    # Old labels are shortened. Exclusion must use the restored complete source group.
    previous.write_text(json.dumps({"rows": [{"query": "old", "gold": ["a"]}]}))
    _, _, _, selected, manifest = reader.corpus(
        SimpleNamespace(
            dataset=dataset, source=None, pilot=None, count=1, exclude_results=[previous]
        ),
        "full-text",
    )
    assert selected == [2]
    assert manifest["exclusion_files_sha256"].keys() == {"previous.json"}


def test_frozen_plans_match_original_question_text_instead_of_old_local_indices(
    tmp_path, monkeypatch
):
    from importlib import import_module

    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "artifacts/search-recall")
    )
    runner = import_module("validate")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([{"query": "Earlier question", "queries": ["A", "B"]}]))
    selected, plans = runner.frozen_cases(
        cases, [{"query": "New question"}, {"query": "Earlier question"}]
    )
    assert selected == [1] and plans == {1: ["A", "B"]}
