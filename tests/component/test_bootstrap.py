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
        "initial_step": {
            "local_goal": "Inspect the available task inputs",
            "expected_result": "Identify the first testable explanation",
            "active_time_minutes": 1,
        },
    }


def test_all_installed_seed_programs_are_callable_and_metadata_has_no_model_meta_mix(app):
    repository = Path(__file__).resolve().parents[2]
    entries = bootstrap_catalog()
    assert len({entry["name"] for entry in entries}) == len(entries)
    for entry in entries:
        assert (repository / entry["git_path"]).is_file()
        module_name = entry["git_path"].removeprefix("src/").removesuffix(".py").replace("/", ".")
        function = getattr(importlib.import_module(module_name), entry["entrypoint"])
        assert callable(function)
        assert "meta" not in entry["roles"] or "exec" in entry["roles"]
        assert inspect.signature(function)
        program = app.graph.find(entry["name"] + "." + entry["role"])
        assert program.description == entry["description"]


async def test_framing_keeps_task_specific_budget_and_uses_only_provider_gateway():
    context = Context(framed())
    result = await frame(context, "Solve the request", {"hard_limits": {"active_time_minutes": 20}})
    assert result["result"]["execution_budget"] == {"active_time_minutes": 11}
    assert result["result"]["self_improvement_budget"] == 35
    assert result["result"]["initial_step"] == framed()["initial_step"]
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


async def test_framing_requires_a_bounded_initial_step_and_resource_review_does_not():
    from evertree.processes.cognitive_control.resource_control._exec import run as review

    missing_step = framed()
    del missing_step["initial_step"]
    with pytest.raises(ValueError, match="initial_step"):
        await frame(Context(missing_step), "Task")
    oversized = framed()
    oversized["initial_step"]["active_time_minutes"] = 12
    with pytest.raises(ValueError, match="cannot exceed"):
        await frame(Context(oversized), "Task")
    budget = {
        key: missing_step[key]
        for key in ("execution_budget", "self_improvement_budget", "budget_reason")
    }
    reviewed = await review(Context(budget), {"progress": "First hypothesis tested"})
    assert reviewed["result"] == budget


async def test_task_prompts_keep_requirements_and_budget_evidence_without_runtime_bookkeeping():
    from evertree.processes.cognitive_control.resource_control._exec import run as review

    state = {
        "id": "runtime-task-id",
        "specification": {
            "objective": "Find the pump fault",
            "success_criteria": ["Explain the observed stop"],
            "constraints": ["Keep the pump offline"],
            "preferences": ["Prefer a simple check"],
            "revision": 12,
            "source_ids": ["source-id"],
        },
        "inputs": [
            {"role": "user", "content": "Keep it offline", "source_id": "older-id"},
            {"role": "user", "content": "Inspect the pump", "source_ref": {"event_ref": 2}},
        ],
        "execution_budget": {
            "resources": {"active_time_minutes": 8},
            "reason": "A previous estimate",
        },
        "spent": {"active_time_minutes": 3},
        "hard_limits": {"active_time_minutes": 12},
        "progress": "Power supply checked",
        "plan": [{"action": "Inspect the control relay"}],
        "unresolved_questions": ["Did the controller request a stop?"],
        "deadline": "2026-10-12T12:00:00Z",
        "step_state": {"pending_integration": {"operation_id": "private-op"}},
        "budget_history": [{"execution_budget": 99}],
        "program_run_ids": ["private-run"],
    }
    framing = Context(framed())
    await frame(framing, "Inspect the pump", state)
    prompt = json.loads(framing.calls[0][1]["prompt"])
    prepared = prompt["context"]
    assert prompt["request"] == "Inspect the pump"
    assert prepared["inputs"] == [{"role": "user", "content": "Keep it offline"}]
    assert prepared["specification"] == {
        key: state["specification"][key]
        for key in ("objective", "success_criteria", "constraints", "preferences")
    }
    assert prepared["execution_budget"] == {"active_time_minutes": 8}
    for field in ("spent", "hard_limits", "progress", "plan", "unresolved_questions", "deadline"):
        assert prepared[field] == state[field]
    for field in ("id", "step_state", "budget_history", "program_run_ids"):
        assert field not in prepared

    budget = {
        "execution_budget": {"active_time_minutes": 10},
        "self_improvement_budget": 0,
        "budget_reason": "Check the relay next",
    }
    budgeting = Context(budget)
    await review(
        budgeting,
        state,
        {
            "trace": [
                {
                    "id": 4,
                    "program_run": "private-run",
                    "created_at": "execution-clock",
                    "operator": "inspect",
                    "output": {"relay": "unchecked", "supply": "normal"},
                    "output_type": "builtins.dict",
                }
            ]
        },
    )
    payload = budgeting.calls[0][1]
    assert json.loads(payload["prompt"])["evidence"] == {
        "trace": [{"operator": "inspect", "output": {"relay": "unchecked", "supply": "normal"}}]
    }
    assert set(payload["output_schema"]["properties"]) == set(budget)


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
