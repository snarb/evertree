"""Measure actual Core results on the corrected corpus, with frozen retrieval settings."""

import argparse
import asyncio
import hashlib
import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from audit import add_dataset_arguments
from diagnose import CachedEmbeddings, corpus

from evertree.common.semantic_search import search
from evertree.core.graph.types import GraphDelta, Prototype
from evertree.core.semantics.config import JevConfig, SemanticConfig
from evertree.core.semantics.index import RedisSearchIndex
from evertree.core.semantics.searching import query_key, search_queries
from evertree.debug_integration import load_debug_environment
from tests.support.semantics import context, semantic_world


def frozen_cases(path, questions):
    """Match earlier question-only plans to complete original labels by text, never old indices."""
    rows = json.loads(path.read_text())
    by_text = {question["query"]: i for i, question in enumerate(questions)}
    selected, plans = [], {}
    for row in rows:
        index = by_text[row["query"]]
        if index in plans:
            raise ValueError("Duplicate frozen question")
        selected.append(index)
        plans[index] = search_queries(row["queries"])
    if not selected:
        raise ValueError("Frozen cases must be nonempty")
    return selected, plans


async def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    cards, urls, questions, selected, manifest = corpus(args, "full-text")
    case_plans = None
    if args.cases:
        selected, case_plans = frozen_cases(args.cases, questions)
        manifest["question_indices"] = selected
        manifest["original_question_indices"] = [
            manifest["dataset"]["original_question_indices"][i] for i in selected
        ]
        manifest["frozen_cases_sha256"] = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    positions = {identity: position for position, identity in enumerate(selected)}
    plans = json.loads(args.plans.read_text()) if args.plans else None
    supplied = {
        i: case_plans[i]
        if case_plans
        else search_queries(plans[str(i)])
        if plans
        else [questions[i]["query"]]
        for i in selected[args.start :]
    }
    world = semantic_world()
    bootstrap = {node.id for node in world.graph.nodes()}
    world.graph.apply(
        GraphDelta(
            creates=[
                Prototype(n["id"], n["name"], description=n["description"])
                for n in cards
                if n["id"] not in bootstrap
            ]
        ),
        provenance="canonical-corpus-validation",
    )
    config = replace(SemanticConfig.load(Path.cwd()), jev=JevConfig(enabled=args.jev))
    manifest.update(
        retrieval=asdict(config.search),
        jev=asdict(config.jev),
        development_indices=selected[:20],
        diagnostic_indices=selected[20:60],
        validation_indices=selected[60:100],
        fresh_validation_indices=selected[100:],
        evaluation_indices=selected[args.start :],
        query_plans_sha256=hashlib.sha256(args.plans.read_bytes()).hexdigest()
        if args.plans
        else None,
        representation="One canonical object per URL, complete original article records; optional category distractor count is recorded in the corpus manifest.",
    )
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    load_debug_environment(Path.cwd(), config)
    index = RedisSearchIndex(
        config, "recall-validation-" + uuid4().hex, embeddings=CachedEmbeddings(config, args.cache)
    )
    world.service.index = index
    world.service.jev.config = config.jev
    raw_channels = {}
    for name in ("lexical", "vector"):
        original = getattr(index, name)

        async def channel(nodes, queries, kind=None, original=original, name=name):
            rows = await original(nodes, queries, kind)
            for query, row in zip(queries, rows, strict=True):
                raw_channels.setdefault(query_key(query), {})[name] = row
            return rows

        setattr(index, name, channel)
    kept = set()
    original_filter = world.service.jev.filter

    async def capture(queries, nodes):
        nonlocal kept
        kept, warnings = await original_filter(queries, nodes)
        return kept, warnings

    world.service.jev.filter = capture
    rows = []
    selected = selected[args.start :]
    try:
        for start in range(0, len(selected), args.batch_size):
            indices = selected[start : start + args.batch_size]
            queries = search_queries([query for i in indices for query in supplied[i]])
            before = time.perf_counter()
            result = (await search(context(world, None), queries))["result"]
            elapsed = time.perf_counter() - before
            summaries = {query_key(row["query"]): row for row in result["queries"]}
            for i in indices:
                query = questions[i]["query"]
                gold = {e["url"] for e in questions[i]["evidence_list"]}
                raw = {
                    identity
                    for focus in supplied[i]
                    for channel in raw_channels[query_key(focus)].values()
                    for identity in channel["ids"]
                }
                query_rows = [summaries[query_key(focus)] for focus in supplied[i]]
                returned = {identity for row in query_rows for identity in row["ids"]}
                rows.append(
                    {
                        "index": i,
                        "group": "development"
                        if positions[i] < 20
                        else "diagnostic"
                        if positions[i] < 60
                        else "validation"
                        if positions[i] < 100
                        else "fresh_validation",
                        "query": query,
                        "queries": supplied[i],
                        "gold": sorted(gold),
                        "raw": sorted({urls[n] for n in raw if n in urls}),
                        "kept": sorted({urls[n] for n in raw & kept if n in urls}),
                        "returned": sorted({urls[n] for n in returned if n in urls}),
                        "returned_objects": len(returned),
                        "raw_objects": len(raw),
                        "status": "complete"
                        if all(row["status"] == "complete" for row in query_rows)
                        else "incomplete",
                        "warnings": result["warnings"],
                        "seconds": elapsed,
                    }
                )
            (args.output / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "completed": start + len(indices),
                        "seconds": round(elapsed, 3),
                        "warnings": len(result["warnings"]),
                    }
                ),
                flush=True,
            )
        summary = []
        for group in ("development", "diagnostic", "validation", "fresh_validation"):
            sample = [row for row in rows if row["group"] == group]
            total = sum(len(row["gold"]) for row in sample)
            counts = {
                stage: sum(len(set(row[stage]) & set(row["gold"])) for row in sample)
                for stage in ("raw", "kept", "returned")
            }
            summary.append(
                {
                    "group": group,
                    "questions": len(sample),
                    "focused_queries": sum(len(row["queries"]) for row in sample),
                    "gold": total,
                    **counts,
                    "returned_article_urls": sum(len(row["returned"]) for row in sample),
                    "returned_objects": sum(row["returned_objects"] for row in sample),
                    "recall": counts["returned"] / total if total else None,
                    "candidate_recall": counts["raw"] / total if total else None,
                    "relevant_candidate_retention": counts["kept"] / counts["raw"]
                    if counts["raw"]
                    else None,
                    "gold_url_precision": counts["returned"]
                    / sum(len(row["returned"]) for row in sample)
                    if any(row["returned"] for row in sample)
                    else None,
                    "warnings": sum(bool(row["warnings"]) for row in sample),
                    "all_complete": all(row["status"] == "complete" for row in sample),
                }
            )
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary), flush=True)
    finally:
        if index.client is not None:
            for name in tuple(index._ready):
                await index.client.execute_command("FT.DROPINDEX", name, "DD")
            keys = [key async for key in index.client.scan_iter(index.namespace + ":*")]
            if keys:
                await index.client.delete(*keys)
        await index.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    add_dataset_arguments(parser)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--pilot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path("tmp/search-recall-embeddings"))
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--jev", action="store_true")
    parser.add_argument("--plans", type=Path)
    parser.add_argument(
        "--cases", type=Path, help="Recheck frozen question/query plans against restored labels"
    )
    parser.add_argument("--start", type=int, default=0)
    asyncio.run(main(parser.parse_args()))
