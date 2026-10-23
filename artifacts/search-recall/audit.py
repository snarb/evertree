"""Audit local MultiHop-RAG against a pinned original and restore complete datasets."""

import argparse
import hashlib
import json
import unicodedata
from collections import Counter
from pathlib import Path


def normalized(text):
    """Ignore Unicode, whitespace and case differences for literal evidence checks."""
    return " ".join(unicodedata.normalize("NFKC", text).split()).casefold()


def unique(rows, key):
    """Reject ambiguous identities rather than silently keeping one duplicate."""
    indexed = {row[key]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"Duplicate {key} identities")
    return indexed


def coverage(articles, questions):
    """Check actual sources and quoted evidence independently of retrieval or a model."""
    sources = unique(articles, "url")
    unique(questions, "query")
    missing, nonliteral = [], []
    for index, question in enumerate(questions):
        for position, evidence in enumerate(question["evidence_list"]):
            detail = {"question_index": index, "evidence_index": position, "url": evidence["url"]}
            if evidence["url"] not in sources:
                missing.append(detail)
            elif normalized(evidence["fact"]) not in normalized(sources[evidence["url"]]["body"]):
                nonliteral.append(detail)
    return {
        "articles": len(articles),
        "questions": len(questions),
        "question_types": dict(Counter(q["question_type"] for q in questions)),
        "evidence_count": sum(len(q["evidence_list"]) for q in questions),
        "distinct_sources_per_question": dict(
            sorted(Counter(len({e["url"] for e in q["evidence_list"]}) for q in questions).items())
        ),
        "missing_sources": missing,
        "nonliteral_facts": nonliteral,
        "empty_bodies": [row["url"] for row in articles if not row.get("body", "").strip()],
    }


def analyze(local_articles, local_questions, articles, questions):
    """Compare complete records; a locally shortened gold list is itself a defect."""
    original_sources, original_questions = unique(articles, "url"), unique(questions, "query")
    local_sources = unique(local_articles, "url")
    changed, unknown = [], []
    for index, question in enumerate(local_questions):
        original = original_questions.get(question["query"])
        if original is None:
            unknown.append(index)
            continue
        if question != original:
            changed.append(
                {
                    "local_index": index,
                    "query": question["query"],
                    "changed_fields": [
                        key
                        for key in question.keys() | original.keys()
                        if question.get(key) != original.get(key)
                    ],
                    "local_evidence": len(question["evidence_list"]),
                    "original_evidence": len(original["evidence_list"]),
                    "omitted_evidence": [
                        {"url": item["url"], "category": item["category"], "title": item["title"]}
                        for item in original["evidence_list"]
                        if item not in question["evidence_list"]
                    ],
                }
            )
    restored_questions = [
        original_questions[q["query"]] for q in local_questions if q["query"] in original_questions
    ]
    needed = {
        e["url"] for q in restored_questions for e in q["evidence_list"]
    } | local_sources.keys()
    return {
        "local": coverage(local_articles, local_questions),
        "original": coverage(articles, questions),
        "identical_articles": sum(
            original_sources.get(row["url"]) == row for row in local_articles
        ),
        "changed_article_urls": [
            row["url"] for row in local_articles if original_sources.get(row["url"]) != row
        ],
        "unknown_local_questions": unknown,
        "identical_questions": sum(
            original_questions.get(q["query"]) == q for q in local_questions
        ),
        "changed_questions": changed,
        "omitted_evidence_count": sum(len(row["omitted_evidence"]) for row in changed),
        "missing_original_article_urls": sorted(needed - local_sources.keys()),
        "restored_sports": coverage(
            [row for row in articles if row["url"] in needed], restored_questions
        ),
        "limitations": [
            "Literal source coverage is necessary, not sufficient proof that the question or answer annotation is semantically correct.",
            "A null_query label expresses insufficient information in the original complete corpus; it cannot be inferred from a failed search.",
        ],
    }


def write_dataset(directory, articles, questions, *, origin, original_indices):
    """Save unchanged source records and gold labels separately, with content fingerprints."""
    directory.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, rows in (("articles.json", articles), ("questions.json", questions)):
        raw = (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode()
        (directory / name).write_bytes(raw)
        files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "rows": len(rows)}
    manifest = {
        "origin": origin,
        "original_question_indices": original_indices,
        "files": files,
        "coverage": coverage(articles, questions),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def read_dataset(directory):
    """Refuse modified or incomplete restored input before any paid/model evaluation."""
    manifest = json.loads((directory / "manifest.json").read_text())
    loaded = []
    for name in ("articles.json", "questions.json"):
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"][name]["sha256"]:
            raise ValueError("Dataset fingerprint mismatch: " + name)
        loaded.append(json.loads(raw))
    checked = coverage(*loaded)
    if checked["missing_sources"] or checked["nonliteral_facts"] or checked["empty_bodies"]:
        raise ValueError("Dataset lacks the source evidence required by its labels")
    return *loaded, manifest


def source_text(article):
    """Retain every original metadata field and the complete body, without labels or answers."""
    return json.dumps(article, ensure_ascii=False, indent=2)


def main(args):
    local_articles = json.loads((args.local / "sports.json").read_text())
    local_questions = json.loads((args.local / "sports_q.json").read_text())
    articles = json.loads((args.original / "corpus.json").read_text())
    questions = json.loads((args.original / "MultiHopRAG.json").read_text())
    origin = json.loads((args.original / "manifest.json").read_text())
    for name, info in origin["files"].items():
        if hashlib.sha256((args.original / name).read_bytes()).hexdigest() != info["sha256"]:
            raise ValueError("Original fingerprint mismatch: " + name)
    report = analyze(local_articles, local_questions, articles, questions)
    if report["unknown_local_questions"]:
        raise ValueError("Local questions have no authoritative original")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "audit.json").write_text(
        json.dumps({"origin": origin, **report}, ensure_ascii=False, indent=2) + "\n"
    )
    original_positions = {row["query"]: index for index, row in enumerate(questions)}
    selected = [original_positions[q["query"]] for q in local_questions]
    complete = [questions[index] for index in selected]
    needed = {e["url"] for q in complete for e in q["evidence_list"]} | {
        row["url"] for row in local_articles
    }
    write_dataset(
        args.output / "sports-closed",
        [row for row in articles if row["url"] in needed],
        complete,
        origin=origin,
        original_indices=selected,
    )
    write_dataset(
        args.output / "full",
        articles,
        questions,
        origin=origin,
        original_indices=list(range(len(questions))),
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "identical_articles",
                    "identical_questions",
                    "omitted_evidence_count",
                    "restored_sports",
                )
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args())


def add_dataset_arguments(parser):
    """Require audited input or an explicit opt-in to reproducing invalid historical labels."""
    parser.add_argument(
        "--exclude-results",
        type=Path,
        nargs="*",
        default=[],
        help="Prior result files whose question/source groups must be excluded",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dataset", type=Path, help="Fingerprint-checked restored dataset directory"
    )
    group.add_argument(
        "--historical",
        action="store_true",
        help="Reproduce the old incomplete local labels; no acceptance claim",
    )
