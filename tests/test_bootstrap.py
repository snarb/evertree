from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import pytest

from evertree.core.programs.bootstrap import bootstrap_catalog
from evertree.processes.memory_processing.experience_compaction._exec import run as compact
from evertree.processes.task_management.episode_step_selection._exec import (
    run as episode_step,
)
from evertree.processes.task_management.task_framing._exec import run as frame


class Context:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def step(self, method, payload):
        self.calls.append((method, payload))
        return {"parsed": self.answer, "text": json.dumps(self.answer)}


def framed(minutes=11, improvement=35):
    return {
        "objective": "Solve this particular task",
        "success_criteria": [],
        "constraints": [],
        "preferences": [],
        "execution_budget": {"active_time_minutes": minutes},
        "self_improvement_budget": improvement,
        "budget_reason": "Specific scope and benefit",
    }


def test_all_installed_seed_programs_are_callable_and_metadata_has_no_model_meta_mix():
    repository = Path(__file__).resolve().parents[1]
    entries = bootstrap_catalog()
    assert len({entry["name"] for entry in entries}) == len(entries)
    for entry in entries:
        assert (repository / entry["git_path"]).is_file()
        module_name = entry["git_path"].removeprefix("src/").removesuffix(".py").replace("/", ".")
        function = getattr(importlib.import_module(module_name), entry["entrypoint"])
        assert callable(function)
        assert "meta" not in entry["roles"] or "exec" in entry["roles"]
        assert inspect.signature(function)


async def test_framing_keeps_task_specific_budget_and_uses_only_provider_gateway():
    context = Context(framed())
    result = await frame(context, "Solve the request", {"hard_limits": {"active_time_minutes": 20}})
    assert result["result"]["execution_budget"] == {"active_time_minutes": 11}
    assert result["result"]["self_improvement_budget"] == 35
    assert len(context.calls) == 1
    method, payload = context.calls[0]
    assert method == "agent.run"
    assert payload["mode"] == "model"
    assert json.loads(payload["prompt"])["request"] == "Solve the request"
    assert payload["output_schema"]["required"]


async def test_framing_rejects_nonfinite_or_missing_budget_instead_of_inserting_default():
    with pytest.raises(ValueError):
        await frame(Context(framed(minutes=0)), "Task")
    malformed = framed()
    del malformed["execution_budget"]
    with pytest.raises(ValueError, match="missing"):
        await frame(Context(malformed), "Task")


async def test_next_episode_step_cannot_access_unavailable_sources():
    invalid = {
        "sources": [{"source_id": "future", "start": 0, "end": 3}],
        "done": False,
        "reason": "next data",
    }
    with pytest.raises(ValueError, match="unavailable"):
        await episode_step(
            Context(invalid), "Read next word", [{"source_id": "current", "content": "abc"}]
        )
    valid = {
        "sources": [{"source_id": "current", "start": 0, "end": 3}],
        "done": False,
        "reason": "complete word",
    }
    result = await episode_step(
        Context(valid), "Read next word", [{"source_id": "current", "content": "abc"}]
    )
    assert result["result"] == valid


async def test_compaction_preserves_exact_counts_and_only_proposes_retention():
    context = Context({"summary": "Three observations", "keep_event_ids": [1], "lost_details": []})
    result = await compact(context, [{"id": 1}, {"id": 2}], {"total": 3, "positive": 2})
    assert result["result"]["observation_counts"] == {"total": 3, "positive": 2}
    assert result["result"]["source_event_ids"] == [1, 2]
    assert [method for method, _ in context.calls] == ["agent.run"]
