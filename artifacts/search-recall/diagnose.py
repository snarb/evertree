"""Attribute retrieval losses using frozen corpus variants and complete channel ranks."""

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import random
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from audit import add_dataset_arguments, read_dataset, source_text

from evertree.core.graph.types import GraphDelta, Prototype
from evertree.core.semantics.config import JevConfig, SearchConfig, SemanticConfig
from evertree.core.semantics.index import OpenAIEmbeddings, RedisSearchIndex
from evertree.core.semantics.reading import card
from evertree.debug_integration import load_debug_environment
from tests.support.semantics import semantic_world


def evaluator():
    path = Path(__file__).parents[1] / "search-batch-jev/evaluate.py"
    spec = importlib.util.spec_from_file_location("batch_evaluation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CachedEmbeddings:
    def __init__(self, config, directory):
        self.provider = OpenAIEmbeddings(config)
        self.config = config
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    async def embed(self, texts):
        paths = [
            self.directory
            / (
                hashlib.sha256(
                    json.dumps(
                        [self.config.embedding_model, self.config.embedding_dimensions, t]
                    ).encode()
                ).hexdigest()
                + ".json"
            )
            for t in texts
        ]
        missing = {path: text for path, text in zip(paths, texts, strict=True) if not path.exists()}
        if missing:
            vectors = await self.provider.embed(list(missing.values()))
            for path, vector in zip(missing, vectors, strict=True):
                path.write_text(json.dumps(vector))
        return [json.loads(path.read_text()) for path in paths]


def prior_queries(value):
    """Read question text from preserved outputs without reusing their shortened gold lists."""
    if isinstance(value, dict):
        found = {value["query"]} if isinstance(value.get("query"), str) else set()
        return found | set().union(*(prior_queries(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(prior_queries(child) for child in value))
    return set()


def audited_corpus(args):
    """Build canonical full-source cards from original labels, retaining optional category distractors."""
    articles, questions, saved = read_dataset(args.dataset)
    excluded, category_cards = set(), []
    if args.source is not None:
        if args.pilot is None:
            raise ValueError("Category/old-pilot comparison requires --pilot with --source")
        local_questions = json.loads((args.source / "sports_q.json").read_text())
        split = json.loads((args.pilot / "split.json").read_text())
        excluded = {local_questions[i]["query"] for rows in split["splits"].values() for i in rows}
        base, article_ids, _, _, _ = evaluator().prepare(args.source, args.pilot, 1)
        bootstrap = {node.id for node in semantic_world().graph.nodes()}
        category_cards = [
            node
            for node in base.graph.nodes()
            if node.id not in article_ids and node.id not in bootstrap
        ]

    exclusion_files = {}
    for path in getattr(args, "exclude_results", []):
        content = path.read_bytes()
        exclusion_files[path.name] = hashlib.sha256(content).hexdigest()
        excluded.update(prior_queries(json.loads(content)))

    def group(question):
        urls = tuple(sorted({e["url"] for e in question["evidence_list"]}))
        return urls or ("null_query", question["query"])

    used = {group(q) for q in questions if q["query"] in excluded}
    order = list(range(len(questions)))
    random.Random(20261021).shuffle(order)
    selected = []
    for index in order:
        key = group(questions[index])
        if questions[index]["query"] not in excluded and key not in used:
            selected.append(index)
            used.add(key)
            if len(selected) == args.count:
                break
    if len(selected) != args.count:
        raise ValueError("Insufficient unique question/source groups")
    world = semantic_world()
    nodes, urls = [], {}
    for position, article in enumerate(articles):
        identity = world.graph.reserve_id()
        nodes.append(Prototype(identity, f"Article {position}", description=source_text(article)))
        urls[identity] = article["url"]
    for node in category_cards:
        nodes.append(Prototype(world.graph.reserve_id(), node.name, description=node.description))
    world.graph.apply(GraphDelta(creates=nodes), provenance="audited-original-corpus")
    manifest = {
        "implementation_sha256": evaluator().production_revision(),
        "seed": 20261021,
        "dataset": saved,
        "question_indices": selected,
        "original_question_indices": [saved["original_question_indices"][i] for i in selected],
        "excluded_query_count": len(excluded),
        "exclusion_files_sha256": exclusion_files,
        "category_distractors": len(category_cards),
        "node_count": len(nodes),
        "protocol": "Original complete labels and records from a fingerprint-checked restored dataset. Gold/answer fields never enter graph cards. Optional original category distractors are retained. Null queries remain distinct rather than collapsing all empty gold groups together.",
    }
    return [card(node) for node in world.graph.nodes()], urls, questions, selected, manifest


def corpus(args, variant):
    if getattr(args, "dataset", None) is not None:
        if variant != "full-text":
            raise ValueError("Audited original input supports only --variants full-text")
        return audited_corpus(args)
    if not getattr(args, "historical", False):
        raise ValueError(
            "Use an audited --dataset; --historical explicitly reproduces incomplete labels"
        )
    if args.source is None or args.pilot is None:
        raise ValueError("Historical reproduction requires --source and --pilot")
    base, base_urls, questions, selected, manifest = evaluator().prepare(
        args.source, args.pilot, args.count
    )
    if variant == "original":
        return [card(n) for n in base.graph.nodes()], base_urls, questions, selected, manifest
    articles = json.loads((args.source / "sports.json").read_text())
    summaries = {}
    for identity, url in base_urls.items():
        summaries.setdefault(url, base.graph.get(identity).description)
    world = semantic_world()
    nodes, urls = [], {}
    for article_index, article in enumerate(articles):
        if variant == "unique-summary":
            text = summaries[article["url"]]
        else:
            prefix = f"{article['title']}\n{article['source']} {article['published_at']}\n"
            text = prefix + article["body"]
        identity = world.graph.reserve_id()
        nodes.append(Prototype(identity, f"Article {article_index}", description=text))
        urls[identity] = article["url"]
    # Preserve the same category distractors; only article representations change.
    bootstrap = {node.id for node in world.graph.nodes()}
    for node in base.graph.nodes():
        if node.id not in base_urls and node.id not in bootstrap:
            nodes.append(
                Prototype(world.graph.reserve_id(), node.name, description=node.description)
            )
    world.graph.apply(GraphDelta(creates=nodes), provenance="recall-diagnosis")
    manifest.update(
        node_count=len(nodes),
        representation=variant,
        protocol="Same frozen query selection as original experiment; canonical source identity per article URL; original category distractors retained. Complete bodies and source/date metadata in full-text variant; no gold facts added to cards.",
    )
    return [card(n) for n in world.graph.nodes()], urls, questions, selected, manifest


def ranks(ids, urls):
    # Collapse source placements/chunks before allocating document quotas.
    return list(dict.fromkeys(urls.get(identity, f"node:{identity}") for identity in ids))


def fused(left, right, lexical_limit, vector_limit):
    scores = {}
    for channel in (left[:lexical_limit], right[:vector_limit]):
        for rank, identity in enumerate(channel, 1):
            scores[identity] = scores.get(identity, 0) + 1 / (60 + rank)
    return sorted(scores, key=lambda identity: (-scores[identity], identity))


async def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    config = replace(
        SemanticConfig.load(Path.cwd()),
        jev=JevConfig(enabled=False),
        search=SearchConfig(bm25_candidates=1000, vector_candidates=1000),
    )
    load_debug_environment(Path.cwd(), config)
    if args.lexical_only and urlsplit(os.environ[config.redis_url_env]).hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("Lexical-only diagnostic requires local Redis")
    for variant in args.variants:
        cards, urls, questions, selected, manifest = corpus(args, variant)
        index = RedisSearchIndex(
            config,
            "recall-diagnosis-" + uuid4().hex,
            embeddings=CachedEmbeddings(config, args.cache),
        )
        try:
            queries = [questions[i]["query"] for i in selected]
            started = time.perf_counter()
            if args.lexical_only:
                lexical = await index.lexical(cards, queries)
                vector = [{"ids": []} for _ in queries]
            else:
                lexical, vector = await asyncio.gather(
                    index.lexical(cards, queries), index.vector(cards, queries)
                )
            rows = []
            for i, left, right in zip(selected, lexical, vector, strict=True):
                if left.get("error") or right.get("error"):
                    raise RuntimeError("Incomplete diagnostic retrieval")
                left, right = ranks(left["ids"], urls), ranks(right["ids"], urls)
                gold = sorted({e["url"] for e in questions[i]["evidence_list"]})
                rows.append(
                    {
                        "index": i,
                        "query": questions[i]["query"],
                        "gold": gold,
                        "bm25": left,
                        "vector": right,
                    }
                )
            summary = []
            for a, b in ((7, 12), (32, 32), (64, 64), (128, 128)):
                total = raw_hits = final_hits = 0
                for row in rows:
                    ranked = fused(row["bm25"], row["vector"], a, b)
                    gold = set(row["gold"])
                    total += len(gold)
                    raw_hits += len(gold.intersection(ranked))
                    final_hits += len(gold.intersection(ranked[:10]))
                summary.append(
                    {
                        "bm25": a,
                        "vector": b,
                        "gold": total,
                        "raw_hits": raw_hits,
                        "final_hits": final_hits,
                    }
                )
            report = {
                "variant": variant,
                "lexical_only": args.lexical_only,
                "cards": len(cards),
                "manifest": manifest,
                "summary": summary,
                "rows": rows,
            }
            (args.output / f"{variant}.json").write_text(json.dumps(report, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "variant": variant,
                        "seconds": time.perf_counter() - started,
                        "summary": summary,
                    }
                ),
                flush=True,
            )
        finally:
            client = index.client
            if client is not None:
                for name in tuple(index._ready):
                    await client.execute_command("FT.DROPINDEX", name, "DD")
                keys = [key async for key in client.scan_iter(index.namespace + ":*")]
                if keys:
                    await client.delete(*keys)
            await index.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    add_dataset_arguments(parser)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--pilot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path("tmp/search-recall-embeddings"))
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--lexical-only", action="store_true")
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=["original", "unique-summary", "full-text"],
        default=["full-text"],
    )
    asyncio.run(main(parser.parse_args()))
