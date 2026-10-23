"""Replay saved misses with cached embeddings and expose channel/fusion ranks, without API calls."""

import argparse
import asyncio
import json
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from diagnose import CachedEmbeddings, corpus

from evertree.common.semantic_search import search
from evertree.core.graph.types import GraphDelta, Prototype
from evertree.core.semantics.config import JevConfig, SemanticConfig
from evertree.core.semantics.index import RedisSearchIndex
from evertree.debug_integration import load_debug_environment
from tests.support.semantics import context, semantic_world


async def run(args):
    cards, urls, questions, _, manifest = corpus(
        SimpleNamespace(dataset=args.dataset, source=None, pilot=None, count=1), "full-text"
    )
    articles = json.loads((args.dataset / "articles.json").read_text())
    titles = {a["url"]: a["title"] for a in articles}
    identities = {url: identity for identity, url in urls.items()}
    cases = {}
    for path in args.runs:
        for row in json.loads(path.read_text()):
            missing = set(row["gold"]) - set(row["returned"])
            if not missing:
                continue
            key = (row["query"], tuple(row["queries"]))
            case = cases.setdefault(
                key,
                {
                    "index": row["index"],
                    "queries": row["queries"],
                    "missing": set(),
                    "original_runs": [],
                },
            )
            case["missing"].update(missing)
            case["original_runs"].append(path.name)
    config = replace(SemanticConfig.load(Path.cwd()), jev=JevConfig(enabled=False))
    load_debug_environment(Path.cwd(), config)
    embeddings = CachedEmbeddings(config, args.cache)

    async def no_api(texts):
        raise RuntimeError("Embedding cache miss: replay forbids external API calls")

    embeddings.provider.embed = no_api
    index = RedisSearchIndex(config, "miss-replay-" + uuid4().hex, embeddings=embeddings)
    world = semantic_world(config=config, index=index)
    bootstrap = {node.id for node in world.graph.nodes()}
    world.graph.apply(
        GraphDelta(
            creates=[
                Prototype(n["id"], n["name"], description=n["description"])
                for n in cards
                if n["id"] not in bootstrap
            ]
        ),
        provenance="miss-replay",
    )
    captures = defaultdict(dict)
    for channel in ("lexical", "vector"):
        original = getattr(index, channel)

        async def capture(nodes, queries, kind=None, original=original, channel=channel):
            rows = await original(nodes, queries, kind)
            if any(row.get("error") for row in rows):
                raise RuntimeError("Replay channel incomplete")
            for query, row in zip(queries, rows, strict=True):
                captures[query][channel] = row["ids"]
            return rows

        setattr(index, channel, capture)
    results = []
    try:
        for (text, _), case in cases.items():
            result = (await search(context(world, None), case["queries"]))["result"]
            if result["status"] != "complete":
                raise RuntimeError("Incomplete replay")
            returned = {row["id"] for row in result["items"]}
            comparisons = []
            for query in case["queries"]:
                ranks = {
                    name: {identity: rank for rank, identity in enumerate(ids, 1)}
                    for name, ids in captures[query].items()
                }
                scores = defaultdict(float)
                for channel in ranks.values():
                    for identity, rank in channel.items():
                        scores[identity] += 1 / (60 + rank)
                fused = sorted(scores, key=lambda identity: (-scores[identity], identity))
                positions = {identity: rank for rank, identity in enumerate(fused, 1)}
                comparisons.append(
                    {
                        "query": query,
                        "gold": [
                            {
                                "title": titles[url],
                                "url": url,
                                "bm25_rank": ranks["lexical"].get(identities[url]),
                                "vector_rank": ranks["vector"].get(identities[url]),
                                "fused_rank": positions.get(identities[url]),
                                "rrf": scores.get(identities[url]),
                            }
                            for url in sorted(case["missing"])
                        ],
                        "top_ten": [
                            {
                                "title": titles.get(
                                    urls.get(identity), world.graph.get(identity).name
                                ),
                                "bm25_rank": ranks["lexical"].get(identity),
                                "vector_rank": ranks["vector"].get(identity),
                                "rrf": scores[identity],
                            }
                            for identity in fused[:10]
                        ],
                    }
                )
            results.append(
                {
                    "index": case["index"],
                    "question": text,
                    "original_runs": case["original_runs"],
                    "originally_missing": [
                        {
                            "url": url,
                            "title": titles[url],
                            "returned_in_replay": identities[url] in returned,
                            "gold_facts": [
                                e["fact"]
                                for e in questions[case["index"]]["evidence_list"]
                                if e["url"] == url
                            ],
                        }
                        for url in sorted(case["missing"])
                    ],
                    "rankings": comparisons,
                }
            )
        args.output.write_text(
            json.dumps(
                {
                    "notice": "Fresh derived index, Jev disabled, cached embeddings only; these are diagnostic replay ranks, not recovered historical ranks. All questions were already observed. Original misses remain preserved.",
                    "manifest": manifest,
                    "cases": results,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        for row in results:
            print(
                json.dumps(
                    {
                        "index": row["index"],
                        "ranks": [
                            {"query": r["query"], "gold": r["gold"]} for r in row["rankings"]
                        ],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    finally:
        if index.client:
            for name in tuple(index._ready):
                await index.client.execute_command("FT.DROPINDEX", name, "DD")
            keys = [key async for key in index.client.scan_iter(index.namespace + ":*")]
            if keys:
                await index.client.delete(*keys)
        await index.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--cache", type=Path, default=Path("tmp/search-recall-embeddings"))
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
