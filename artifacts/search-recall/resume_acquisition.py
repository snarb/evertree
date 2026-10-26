"""Continue one interrupted source-only acquisition from saved writes and processing state."""

import argparse
import asyncio
import hashlib
import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from audit import read_dataset
from diagnose import CachedEmbeddings
from integrated import (
    OBJECTIVE,
    AcquisitionTranscript,
    restore,
    snapshot,
    structure,
    validate_seed,
)

from evertree.core.codex.provider import CodexProvider
from evertree.core.cognition.tasks import TaskSpecification
from evertree.core.semantics.config import JevConfig, SemanticConfig
from evertree.core.semantics.index import RedisSearchIndex
from evertree.debug_integration import load_debug_environment
from evertree.processes.self_semantic_processing.self_knowledge_integration._exec import run as integrate
from tests.support.live_semantics import native_semantic_context, production_revision


def continuation_state(prefix, partial, articles, plan, *, retry_failed=False):
    """Reject mixed histories and recover the next article's original reference and queue."""
    validate_seed(prefix, articles, plan)
    position = len(prefix["completed"])
    if prefix.get("analysis_instructions") or position >= len(articles):
        raise ValueError("Continuation needs an unfinished source-only acquisition")
    for store, key in (("graph", "history"), ("memory", "events")):
        previous = prefix["snapshot"][store][key]
        if partial[store][key][: len(previous)] != previous:
            raise ValueError("Partial snapshot does not preserve the completed prefix")
    originals = [
        event
        for event in partial["memory"]["events"]
        if event["output"] == {"article": articles[position]}
    ]
    if len(originals) != 1:
        raise ValueError("Partial snapshot needs one exact original for the next article")
    original = originals[0]
    progress_events = [
        event
        for event in partial["memory"]["events"]
        if event["id"] > original["id"] and event["operator"] == "integration_processing"
    ]
    if not progress_events:
        raise ValueError("Partial snapshot has no processing state for this article")
    progress_event = progress_events[-1]
    progress = json.loads(json.dumps(progress_event["output"]))
    units = [
        *progress["completed"],
        *progress["pending"],
        *(row["unit"] for row in progress["failed"]),
    ]
    if any(
        type(part["source"]) is not int or part["source"] != 0
        for unit in units
        for part in unit["parts"]
    ):
        raise ValueError("Continuation processing must refer to this single original source")
    if progress["failed"]:
        if not retry_failed:
            raise ValueError("Failed units require explicit --retry-failed")
        progress["pending"] = [row["unit"] for row in progress["failed"]] + progress["pending"]
        progress["failed"] = []
    progress["status"] = "incomplete" if progress["pending"] else "processed"
    return (
        position,
        {"event_ref": original["id"], "output_path": []},
        progress,
        progress_event["id"],
    )


async def run(args):
    prefix = json.loads(args.prefix.read_text())
    articles, _, dataset = read_dataset(args.prefix.parent / "input")
    plan = json.loads((args.prefix.parent / "plan.json").read_text())
    if dataset["files"] != plan["files"]:
        raise ValueError("Frozen pilot input changed")
    partial_path = args.partial / "snapshot.json"
    partial = json.loads(partial_path.read_text())
    position, reference, processing, progress_event = continuation_state(
        prefix, partial, articles, plan, retry_failed=args.retry_failed
    )
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(args.prefix.parent / "input", args.output / "input")
    shutil.copy2(args.prefix.parent / "plan.json", args.output / "plan.json")
    revision = production_revision()
    manifest = {
        "purpose": "Explicit continuation across instruction revisions; not a uniform-prompt acquisition.",
        "prefix": str(args.prefix),
        "prefix_sha256": hashlib.sha256(args.prefix.read_bytes()).hexdigest(),
        "partial": str(partial_path),
        "partial_sha256": hashlib.sha256(partial_path.read_bytes()).hexdigest(),
        "prefix_production_revision": prefix["production_revision"],
        "production_revision": revision,
        "article_index": position,
        "reference": reference,
        "processing_event": progress_event,
        "retry_failed": args.retry_failed,
    }
    (args.output / "continuation.json").write_text(json.dumps(manifest, indent=2) + "\n")
    directory = args.output / "acquisition" / f"{position}-continued"
    directory.mkdir(parents=True)
    config = replace(SemanticConfig.load(Path.cwd()), jev=JevConfig(enabled=False))
    if asdict(config) != prefix["retrieval"]:
        raise ValueError("Continuation needs the same retrieval configuration")
    load_debug_environment(Path.cwd(), config)
    index = RedisSearchIndex(
        config,
        "acquisition-continuation-" + uuid4().hex,
        embeddings=CachedEmbeddings(config, args.cache),
    )
    provider = CodexProvider(state_dir=args.output / "codex")
    world = restore(partial, index, config)
    transcript = AcquisitionTranscript(world, directory, position)
    try:
        async with native_semantic_context(
            world,
            provider,
            directory,
            transcript,
            integration_context={"task": {"specification": TaskSpecification(OBJECTIVE).to_dict()}},
            operation_id=f"article:{position}",
            timeout_seconds=300,
        ) as ctx:
            result = await integrate(
                ctx, [reference], focus=prefix.get("focus"), processing=processing
            )
        (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        if result["result"]["processing"]["status"] != "processed":
            raise RuntimeError("Continuation retains unfinished source sections")
        if production_revision() != revision:
            raise RuntimeError("Production changed during continuation")
        record = {
            **prefix,
            "production_revision": revision,
            "completed": [*prefix["completed"], articles[position]["url"]],
            "references": {
                **prefix["references"],
                str(reference["event_ref"]): articles[position]["url"],
            },
            "snapshot": snapshot(world),
            "structure": structure(world),
            "continuation": manifest,
        }
        validate_seed(record, articles, plan)
        (args.output / "acquired.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            json.dumps({"acquired": len(record["completed"]), "nodes": len(world.graph.nodes())}),
            flush=True,
        )
    finally:
        (directory / "snapshot.json").write_text(
            json.dumps(snapshot(world), ensure_ascii=False, indent=2) + "\n"
        )
        (directory / "trace.json").write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2) + "\n"
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
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--partial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--cache", type=Path, default=Path("tmp/search-recall-embeddings"))
    asyncio.run(run(parser.parse_args()))
