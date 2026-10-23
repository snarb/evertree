"""Evaluate production query guidance without exposing corpus or gold labels to the model."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from audit import add_dataset_arguments
from diagnose import corpus

from evertree.core.codex.configuration import EFFORT, MODEL
from evertree.core.codex.provider import CodexProvider
from evertree.core.provider import LLMRequest
from evertree.core.semantics.tools import SEARCH_QUERIES


async def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    _cards, _urls, questions, selected, manifest = corpus(args, "full-text")
    selected = selected[args.start :]
    manifest["planning_indices"] = selected
    inputs = [{"index": i, "question": questions[i]["query"]} for i in selected]
    instructions = (
        "Prepare search tool arguments for each question; do not answer it. Follow the search tool's query guidance exactly:\n"
        + SEARCH_QUERIES["description"]
        + "\nUse only the question; no documents or relevance labels are available. Return one queries array per input index. Avoid guessing absent entity names or article titles."
    )
    plans = {}
    input_path = args.output / "input.json"
    if args.resume:
        previous = json.loads(input_path.read_text())
        if (
            previous["inputs"] != inputs
            or previous["instructions"] != instructions
            or previous["model"] != MODEL
            or previous["effort"] != EFFORT
        ):
            raise ValueError("Cannot resume a different query-planning experiment")
        plans = json.loads((args.output / "plans.json").read_text())
    (args.output / "input.json").write_text(
        json.dumps(
            {
                "inputs": inputs,
                "instructions": instructions,
                "model": MODEL,
                "effort": EFFORT,
                "manifest": manifest,
                "questions_per_invocation": args.batch_size,
                "resumed_after_questions": len(plans),
            },
            indent=2,
        )
        + "\n"
    )
    calls_dir = args.output / "calls"
    calls_dir.mkdir(exist_ok=True)
    provider = CodexProvider(state_dir=args.output / "codex")
    selected = [i for i in selected if str(i) not in plans]
    try:
        for start in range(0, len(selected), args.batch_size):
            indices = selected[start : start + args.batch_size]
            schema = {
                "type": "object",
                "properties": {
                    str(i): {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 6,
                    }
                    for i in indices
                },
                "required": [str(i) for i in indices],
                "additionalProperties": False,
            }
            request = LLMRequest(
                json.dumps([{"index": i, "question": questions[i]["query"]} for i in indices]),
                args.output.resolve(),
                instructions=instructions,
                mode="model",
                output_schema=schema,
                model=MODEL,
                effort=EFFORT,
                timeout_seconds=180,
            )
            events, result = [], None
            try:
                async for event in provider.run(uuid4().hex, request):
                    if event.kind in {"usage", "error", "completed"}:
                        events.append({"kind": event.kind, "data": event.data})
                    if event.kind == "error":
                        raise RuntimeError(event.data)
                    if event.kind == "completed":
                        result = event.data["parsed"]
            finally:
                (calls_dir / f"{start}-{uuid4().hex}.json").write_text(
                    json.dumps({"indices": indices, "events": events}, indent=2) + "\n"
                )
            if result is None:
                raise RuntimeError("Query planner did not complete")
            plans.update(result)
            (args.output / "plans.json").write_text(json.dumps(plans, indent=2) + "\n")
            print(
                json.dumps(
                    {"questions": len(plans), "queries": sum(len(v) for v in plans.values())}
                ),
                flush=True,
            )
    finally:
        await provider.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    add_dataset_arguments(parser)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--pilot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    asyncio.run(main(parser.parse_args()))
