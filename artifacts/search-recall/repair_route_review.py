"""Retain a failed judge attempt with conservative, explicit structural repairs."""

import argparse
import hashlib
import json
from pathlib import Path

from graph_routes import VARIANTS, read_statistics


def conservative_verdict(raw, count):
    """Never invent relevance or promote a verdict while repairing judge structure."""
    result = dict(raw)
    ratings, warnings = [], []
    for index in range(count):
        matches = [
            row
            for row in raw["read_relevance"]
            if type(row["read_index"]) is int and row["read_index"] == index
        ]
        if len(matches) == 1:
            ratings.extend(matches)
        else:
            ratings.append(
                {
                    "read_index": index,
                    "classification": "uncertain",
                    "reason": "Judge omitted this read or supplied conflicting duplicate ratings.",
                }
            )
            warnings.append({"read_index": index, "kind": "uncertain_read", "raw": matches})
    extras = [
        row
        for row in raw["read_relevance"]
        if type(row["read_index"]) is not int or not 0 <= row["read_index"] < count
    ]
    if extras:
        warnings.append({"kind": "nonexistent_read_ratings_discarded", "raw": extras})
    result["read_relevance"] = ratings
    for field, gaps in (
        ("correct", "missing_required_parts"),
        ("grounded_in_reads", "unsupported_claims"),
    ):
        if result[field] and result[gaps]:
            result[field] = False
            warnings.append({"kind": "contradictory_verdict_downgraded", "field": field})
    return result, warnings


def repair(directory, source):
    """Append only the next failed question, preserving its original judgment and trace."""
    output = directory / "route-answer-review.json"
    rows = json.loads(output.read_text())
    position = len(rows)
    trace = json.loads(source.read_text())
    completed = [
        event["data"]["text"]
        for request in trace
        for event in request.get("events", [])
        if event["kind"] == "completed"
    ]
    if len(completed) != 1:
        raise ValueError("Need exactly one completed first judge attempt")
    parsed = json.loads(completed[0])
    plan = json.loads((directory / "plan.json").read_text())
    order = VARIANTS[position % len(VARIANTS) :] + VARIANTS[: position % len(VARIANTS)]
    aliases = dict(zip("ABCD", order, strict=True))
    variants, statistics, warnings = {}, {}, []
    for alias, variant in aliases.items():
        reads = json.loads(
            (directory / "routes" / variant / str(position) / "trace.json").read_text()
        )["reads"]
        verdict, issues = conservative_verdict(parsed[alias], len(reads))
        variants[variant] = verdict
        statistics[variant] = read_statistics(reads, verdict["read_relevance"])
        warnings.extend({"variant": variant, **issue} for issue in issues)
    rows.append(
        {
            "original_index": plan["original_question_indices"][position],
            "label_status": parsed["label_status"],
            "label_reason": parsed["label_reason"],
            "aliases": aliases,
            "variants": variants,
            "reading_statistics": statistics,
            "reader_errors": {
                variant: json.loads((directory / f"routes-{variant}.json").read_text())[position][
                    "evaluation_errors"
                ]
                for variant in VARIANTS
            },
            "raw_judgment": parsed,
            "structural_repair": {
                "source_trace": str(source),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "repair_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "policy": "Retain first attempt; unknown/duplicate read ratings become uncertain; nonexistent reads are discarded; contradictory positive verdicts are downgraded. No semantic rating invented and no favorable retry selected.",
                "warnings": warnings,
            },
        }
    )
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    return warnings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--first-attempt", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(repair(args.output, args.first_attempt)))
