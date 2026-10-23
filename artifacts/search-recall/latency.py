"""Compare sequential and batch retrieval on one warm index with live query embeddings."""

import argparse
import asyncio
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
from evertree.core.semantics.index import OpenAIEmbeddings, RedisSearchIndex
from evertree.debug_integration import load_debug_environment
from tests.support.semantics import context, semantic_world


async def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    cards, _, questions, selected, manifest = corpus(args, "full-text")
    config = replace(SemanticConfig.load(Path.cwd()), jev=JevConfig(enabled=False))
    load_debug_environment(Path.cwd(), config)
    world = semantic_world(config=config)
    bootstrap = {node.id for node in world.graph.nodes()}
    world.graph.apply(
        GraphDelta(
            creates=[
                Prototype(n["id"], n["name"], description=n["description"])
                for n in cards
                if n["id"] not in bootstrap
            ]
        ),
        provenance="warm-latency-evaluation",
    )
    index = RedisSearchIndex(
        config, "latency-evaluation-" + uuid4().hex, embeddings=CachedEmbeddings(config, args.cache)
    )
    world.service.index = index
    selected = selected[: args.queries]
    queries = [questions[i]["query"] for i in selected]
    manifest.update(
        benchmark_indices=selected,
        retrieval=asdict(config.search),
        jev=asdict(config.jev),
        protocol="One warm canonical full-text index, cached document preparation excluded. Query embeddings always call OpenAI without local caching. Same query texts, alternating sequential/batch order across repeats. Jev off/on separately. No planning or answer-model calls. Latency only: batch Jev judges relevance to any query and need not return identical IDs to sequential Jev.",
    )
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    rows = []
    try:
        generation = await index._ensure(cards)
        await index._ensure_vectors(generation, cards)
        index.embeddings = OpenAIEmbeddings(config)
        warm = (await search(context(world, None), [queries[0]]))["result"]
        if warm["status"] != "complete":
            raise RuntimeError("Warm-up incomplete")
        for enabled in (False, True):
            world.service.jev.config = replace(config.jev, enabled=enabled)
            for repeat in range(args.repeats):
                for batch in (False, True) if repeat % 2 == 0 else (True, False):
                    requests = [queries] if batch else [[query] for query in queries]
                    before = time.perf_counter()
                    calls = []
                    for entries in requests:
                        started = time.perf_counter()
                        result = (await search(context(world, None), entries))["result"]
                        calls.append(
                            {
                                "queries": len(entries),
                                "seconds": time.perf_counter() - started,
                                "status": result["status"],
                                "warnings": result["warnings"],
                                "returned": len(result["items"]),
                            }
                        )
                        if result["status"] != "complete" or result["warnings"]:
                            raise RuntimeError(
                                "Incomplete retrieval or Jev fallback invalidates comparison"
                            )
                    row = {
                        "jev": enabled,
                        "batch": batch,
                        "repeat": repeat,
                        "seconds": time.perf_counter() - before,
                        "calls": calls,
                    }
                    rows.append(row)
                    (args.output / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
                    print(json.dumps(row), flush=True)
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
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--queries", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=2)
    asyncio.run(main(parser.parse_args()))
