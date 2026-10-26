"""Recheck one source section against an explicit seed graph without claiming a resumed pilot."""

import argparse
import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from diagnose import CachedEmbeddings
from integrated import OBJECTIVE, AcquisitionTranscript, restore, snapshot

from evertree.core.codex.provider import CodexProvider
from evertree.core.cognition.tasks import TaskSpecification
from evertree.core.semantics import api as semantics
from evertree.core.semantics.config import JevConfig, SemanticConfig
from evertree.core.semantics.index import RedisSearchIndex
from evertree.core.values import json_value
from evertree.debug_integration import load_debug_environment
from evertree.processes.self_semantic_processing.self_knowledge_integration._exec import run as integrate
from tests.support.live_semantics import native_semantic_context, production_revision


async def run(args):
    article = json.loads(args.articles.read_text())[args.article]
    if not 0 <= args.start < args.end <= len(article["body"]):
        raise ValueError("Section is outside the original body")
    args.output.mkdir(parents=True, exist_ok=False)
    revision = production_revision()
    remaining = json.loads(args.remaining_work.read_text()) if args.remaining_work else []
    if not isinstance(remaining, list) or any(not isinstance(item, str) for item in remaining):
        raise ValueError("Remaining work must be an array of model-reported strings")
    manifest = {
        "purpose": "Isolated section regression, not a full acquisition or matched reader benchmark",
        "production_revision": revision,
        "previous_attempt_remaining_work": remaining,
        "seed_snapshot": str(args.seed),
        "seed_sha256": hashlib.sha256(args.seed.read_bytes()).hexdigest(),
        "article": article,
        "section": {"source": 0, "path": ["article", "body"], "start": args.start, "end": args.end},
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    config = replace(SemanticConfig.load(Path.cwd()), jev=JevConfig(enabled=False))
    load_debug_environment(Path.cwd(), config)
    index = RedisSearchIndex(
        config, "section-regression-" + uuid4().hex, embeddings=CachedEmbeddings(config, args.cache)
    )
    provider = CodexProvider(state_dir=args.output / "codex")
    world = restore(json.loads(args.seed.read_text()), index, config)
    transcript = AcquisitionTranscript(world, args.output, args.article)
    try:
        source = world.memory.start_run("CorpusArticle", "evaluation", {}, run_mode="evaluation")
        event = world.memory.record(source, "observation", output={"article": article})
        world.memory.finish_run(source)
        async with native_semantic_context(
            world,
            provider,
            args.output,
            transcript,
            integration_context={"task": {"specification": TaskSpecification(OBJECTIVE).to_dict()}},
            operation_id="isolated-section-regression",
            timeout_seconds=300,
        ) as ctx:
            prepared = await semantics.prepare_sources(
                ctx,
                experience_refs=[json_value(world.memory.output_ref(event))],
                sections=[manifest["section"]],
                focus=None,
            )
            reference = prepared["experience"][0]["reference"]
            processing = (
                {"pending": [{"parts": [{"source": 0, "path": []}], "remaining_work": remaining}]}
                if remaining
                else None
            )
            result = await integrate(
                ctx,
                [{"event_ref": reference["event_ref"], "output_path": []}],
                processing=processing,
            )
        (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        if production_revision() != revision:
            raise RuntimeError("Production changed during section regression")
        print(json.dumps(result["result"]["processing"]), flush=True)
    finally:
        (args.output / "trace.json").write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2)
        )
        (args.output / "snapshot.json").write_text(
            json.dumps(snapshot(world), ensure_ascii=False, indent=2)
        )
        await provider.close()
        if index.client is not None:
            for name in tuple(index._ready):
                await index.client.execute_command("FT.DROPINDEX", name, "DD")
            keys = [key async for key in index.client.scan_iter(index.namespace + ":*")]
            if keys:
                await index.client.delete(*keys)
        await index.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--articles", type=Path, required=True)
    parser.add_argument("--article", type=int, required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--remaining-work", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("tmp/search-recall-embeddings"))
    asyncio.run(run(parser.parse_args()))
