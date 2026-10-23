"""Interrupted acquisition keeps its source, saved history and explicit unfinished queue."""

import importlib.util
import json
from pathlib import Path

import pytest

from tests.support.semantics import semantic_world


@pytest.fixture
def continuation(monkeypatch):
    root = Path(__file__).resolve().parents[2] / "artifacts/search-recall"
    monkeypatch.syspath_prepend(str(root))
    spec = importlib.util.spec_from_file_location(
        "acquisition_continuation", root / "resume_acquisition.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def interrupted(continuation):
    world = semantic_world()
    article = {"url": "https://example.test/article", "body": "A repaired device D."}
    plan = {"files": {"articles.json": "frozen"}}
    prefix = {
        "plan": plan,
        "completed": [],
        "references": {},
        "snapshot": continuation.snapshot(world),
    }
    run = world.memory.start_run("CorpusArticle", "revision", {})
    world.memory.record(run, "observation", output={"article": article})
    unit = {"parts": [{"source": 0, "path": ["article", "body"]}]}
    progress = {
        "completed": [],
        "pending": [unit],
        "failed": [
            {"unit": {**unit, "remaining_work": ["Verify saved fact"]}, "error": "Unfinished"}
        ],
        "attempts": {"first": 1},
        "status": "incomplete",
    }
    world.memory.record(run, "integration_processing", output=progress)
    world.memory.finish_run(run)
    return prefix, continuation.snapshot(world), [article], plan


def test_continuation_reuses_original_and_explicitly_requeues_failed_units(continuation):
    prefix, partial, articles, plan = interrupted(continuation)
    before = json.dumps(partial, sort_keys=True)
    position, reference, progress, _ = continuation.continuation_state(
        prefix, partial, articles, plan, retry_failed=True
    )
    assert position == 0 and reference == {"event_ref": 1, "output_path": []}
    assert progress["failed"] == [] and len(progress["pending"]) == 2
    assert progress["pending"][0]["remaining_work"] == ["Verify saved fact"]
    assert progress["attempts"] == {"first": 1}
    assert json.dumps(partial, sort_keys=True) == before
    with pytest.raises(ValueError, match="explicit --retry-failed"):
        continuation.continuation_state(prefix, partial, articles, plan)


@pytest.mark.parametrize("change", ["history", "source", "progress", "source_index"])
def test_continuation_rejects_mixed_history_source_or_queue(continuation, change):
    prefix, partial, articles, plan = interrupted(continuation)
    if change == "history":
        partial["graph"]["history"][0]["seq"] += 1
    elif change == "source":
        partial["memory"]["events"][0]["output"]["article"]["body"] = "Different source"
    elif change == "progress":
        partial["memory"]["events"] = partial["memory"]["events"][:1]
    else:
        partial["memory"]["events"][-1]["output"]["pending"][0]["parts"][0]["source"] = 1
    with pytest.raises(ValueError):
        continuation.continuation_state(prefix, partial, articles, plan, retry_failed=True)
