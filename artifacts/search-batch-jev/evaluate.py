"""Historical summary/placement experiment, retained to reproduce the original result.

Use ../search-recall/validate.py for canonical full-text source objects. This import
deliberately preserves the original lossy summaries and duplicate source placements.

Run from the repository with PYTHONPATH=. and --source pointing to the semgraph
sports corpus and --pilot pointing to
artifacts/search-flat in codex/search-flat-jev. Uses real Redis, OpenAI embeddings
and Typesafe; results and request-free diagnostics are saved under --output.
"""

import argparse
import asyncio
import hashlib
import json
import pickle
import random
import statistics
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from evertree.common.semantic_search import search
from evertree.core.graph.types import GraphDelta, Prototype
from evertree.core.semantics.config import JevConfig, SemanticConfig
from evertree.core.semantics.index import RedisSearchIndex
from evertree.debug_integration import load_debug_environment
from tests.support.live_semantics import production_revision
from tests.support.semantics import context, semantic_world


class Record:
    pass


class TreeReader(pickle.Unpickler):
    def find_class(self, module, name):
        if module == "category_tree" and name in {"CategoryTree", "Node"}:
            return Record
        raise ValueError("Unsupported corpus pickle class")


def prepare(source, pilot, count):
    questions = json.loads((source / "sports_q.json").read_text())
    split = json.loads((pilot / "split.json").read_text())
    used = {i for indices in split["splits"].values() for i in indices}
    groups = {tuple(sorted({e["url"] for e in questions[i]["evidence_list"]})) for i in used}
    eligible = list(range(len(questions)))
    random.Random(20261021).shuffle(eligible)
    selected = []
    for i in eligible:
        group = tuple(sorted({e["url"] for e in questions[i]["evidence_list"]}))
        if i not in used and group not in groups:
            selected.append(i)
            groups.add(group)
            if len(selected) == count:
                break
    if len(selected) != count:
        raise ValueError("Insufficient independent gold groups")
    with (source / "sport_tree.pkl").open("rb") as stream:
        tree = TreeReader(stream).load()
    articles = json.loads((source / "sports.json").read_text())
    world = semantic_world()
    nodes, urls = [], {}
    for old, entry in sorted(tree.node_map.items()):
        node = entry["node"]
        article = node.text is not None
        label = "Article" if article else " ".join(node.name.split()[:2])
        identity = world.graph.reserve_id()
        nodes.append(Prototype(identity, f"{label} #{old}", description=node.name))
        if article:
            urls[identity] = articles[int(node.text_id)]["url"]
    world.graph.apply(GraphDelta(creates=nodes), provenance="independent-search-evaluation")
    manifest = {
        "implementation_sha256": production_revision(),
        "seed": 20261021,
        "question_indices": selected,
        "excluded_pilot_indices": sorted(used),
        "node_count": len(nodes),
        "source_sha256": {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in ("sports_q.json", "sports.json", "sport_tree.pkl")
        },
        "threshold": 0.05,
        "model": "jev-1.13.0",
        "protocol": "Frozen new gold groups; no tuning on evaluation outcomes. Title/summary cards only. Same current flat graph for sequential and batch calls. Warm index; no LLM planning time included.",
    }
    return world, urls, questions, selected, manifest


def quality(rows):
    gold_total = sum(len(set(row["gold"])) for row in rows)
    hits = sum(len(set(row["returned"]) & set(row["gold"])) for row in rows)
    returned = sum(len(set(row["returned"])) for row in rows)
    raw_hits = sum(len(set(row["raw_relevant"])) for row in rows)
    kept_hits = sum(len(set(row["kept_relevant"])) for row in rows)
    return {
        "gold": gold_total,
        "hits": hits,
        "returned": returned,
        "precision": hits / returned if returned else 0,
        "recall": hits / gold_total if gold_total else 0,
        "relevant_raw_candidates": raw_hits,
        "relevant_candidates_retained": kept_hits,
        "relevant_candidate_retention": kept_hits / raw_hits if raw_hits else None,
    }


async def evaluate(args):
    args.output.mkdir(parents=True, exist_ok=True)
    world, urls, questions, selected, manifest = prepare(args.source, args.pilot, args.count)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    config = replace(SemanticConfig.load(Path.cwd()), jev=JevConfig(enabled=False))
    load_debug_environment(Path.cwd(), config)
    index = RedisSearchIndex(config, "search-batch-evaluation-" + uuid4().hex)
    world.service.index = index
    captured = []
    original_filter = world.service.jev.filter

    async def capture(queries, nodes):
        kept, warnings = await original_filter(queries, nodes)
        captured.append(
            {
                "queries": queries,
                "raw_ids": [n["id"] for n in nodes],
                "kept_ids": sorted(kept),
                "warnings": warnings,
            }
        )
        return kept, warnings

    world.service.jev.filter = capture
    rows, timings, statuses = [], [], []
    try:
        warm = (await search(context(world, None), [questions[selected[0]]["query"]]))["result"]
        if warm["status"] != "complete":
            raise RuntimeError("Live retrieval unavailable; no quality or latency claim is valid")
        for enabled in (False, True):
            world.service.jev.config = replace(config.jev, enabled=enabled)
            for batch_size in (1, 4):
                started = time.perf_counter()
                batch_times = []
                for start in range(0, len(selected), batch_size):
                    indices = selected[start : start + batch_size]
                    queries = [questions[i]["query"] for i in indices]
                    captured.clear()
                    before = time.perf_counter()
                    result = (await search(context(world, None), queries))["result"]
                    elapsed = time.perf_counter() - before
                    batch_times.append(elapsed)
                    statuses.append(
                        {
                            "jev": enabled,
                            "batch_size": batch_size,
                            "indices": indices,
                            "status": result["status"],
                            "warnings": result["warnings"],
                            "errors": result["errors"],
                        }
                    )
                    raw = set(captured[0]["raw_ids"]) if captured else set()
                    kept = set(captured[0]["kept_ids"]) if captured else set()
                    for position, i in enumerate(indices):
                        gold = {e["url"] for e in questions[i]["evidence_list"]}
                        ids = result["queries"][position]["ids"]
                        # Retention is measured before truncation, against each query's own raw ranks.
                        # A union request evaluates relevance to any supplied query, as production does.
                        singleton_raw = raw if batch_size == 1 else set()
                        rows.append(
                            {
                                "jev": enabled,
                                "batch_size": batch_size,
                                "question_index": i,
                                "gold": sorted(gold),
                                "returned": sorted({urls[n] for n in ids if n in urls}),
                                "raw_relevant": sorted(
                                    {urls[n] for n in singleton_raw if n in urls} & gold
                                ),
                                "kept_relevant": sorted(
                                    {urls[n] for n in kept if n in urls} & gold
                                ),
                                "seconds": elapsed,
                            }
                        )
                    (args.output / "progress.json").write_text(
                        json.dumps({"statuses": statuses, "rows": rows}, indent=2) + "\n"
                    )
                    print(
                        json.dumps(
                            {
                                "jev": enabled,
                                "batch_size": batch_size,
                                "completed": start + len(indices),
                                "seconds": round(elapsed, 3),
                                "status": result["status"],
                                "warnings": len(result["warnings"]),
                            }
                        ),
                        flush=True,
                    )
                timings.append(
                    {
                        "jev": enabled,
                        "batch_size": batch_size,
                        "seconds": time.perf_counter() - started,
                        "median_request_seconds": statistics.median(batch_times),
                        "calls": len(batch_times),
                    }
                )
        summary = {"manifest": manifest, "timings": timings, "quality": []}
        for enabled in (False, True):
            for batch_size in (1, 4):
                selected_rows = [
                    row for row in rows if row["jev"] == enabled and row["batch_size"] == batch_size
                ]
                metrics = quality(selected_rows)
                if batch_size != 1:
                    metrics["relevant_candidate_retention"] = None
                    metrics.pop("relevant_raw_candidates", None)
                    metrics.pop("relevant_candidates_retained", None)
                summary["quality"].append({"jev": enabled, "batch_size": batch_size, **metrics})
        summary["all_searches_complete"] = all(row["status"] == "complete" for row in statuses)
        summary["filter_warnings"] = sum(len(row["warnings"]) for row in statuses)
        retention = next(
            row["relevant_candidate_retention"]
            for row in summary["quality"]
            if row["jev"] and row["batch_size"] == 1
        )
        summary["retention_target_passed"] = (
            summary["all_searches_complete"]
            and not summary["filter_warnings"]
            and retention is not None
            and retention >= 0.99
        )
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2), flush=True)
    finally:
        client = index.client
        if client is not None:
            for generation in tuple(index._ready):
                await client.execute_command("FT.DROPINDEX", generation, "DD")
            keys = [key async for key in client.scan_iter(index.namespace + ":*")]
            if keys:
                await client.delete(*keys)
        await index.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=20)
    asyncio.run(evaluate(parser.parse_args()))
