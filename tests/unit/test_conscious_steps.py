from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from evertree.core.cognition.attention import prepare_context
from evertree.core.cognition.steps import AnalyticalNote, ConsciousStepResult, ConsciousStepSpec
from evertree.core.cognition.tasks import TaskStore
from evertree.core.memory.types import TraceOutputRef


def step_spec(**overrides):
    return {
        "local_goal": "Test whether reconnecting explains the failure",
        "expected_result": "One controlled comparison and remaining uncertainties",
        "active_time_minutes": 2,
        **overrides,
    }


@pytest.mark.parametrize("minutes", [0, -1, float("inf"), float("nan"), True, "2"])
def test_step_budget_must_be_positive_finite_and_explicit(minutes):
    with pytest.raises(ValidationError):
        ConsciousStepSpec.model_validate(step_spec(active_time_minutes=minutes))


def test_partial_result_is_an_explicit_product_without_a_user_answer():
    result = ConsciousStepResult(
        analysis=AnalyticalNote(
            text="A and B support reconnecting as a factor; C is still unexplained.",
            source_refs=[TraceOutputRef(7, ("observations", 0))],
        ),
        findings=[
            AnalyticalNote(
                text="Reconnect may cause the failure only with an old connection.",
                kind="claim",
            )
        ],
        disposition="continue",
        next_step=ConsciousStepSpec.model_validate(step_spec()),
        unresolved_questions=["Does forcing a new connection prevent the failure?"],
    )
    encoded = json.loads(result.model_dump_json())
    assert encoded["user_message"] is None
    assert encoded["analysis"]["source_refs"] == [
        {"event_ref": 7, "output_path": ["observations", 0]}
    ]
    assert set(encoded["findings"][0]) == {"text", "source_refs", "kind"}
    assert "belief" not in encoded["findings"][0]
    assert ConsciousStepResult.model_validate(encoded) == result


def test_continuation_and_completion_have_different_required_products():
    with pytest.raises(ValidationError, match="next_step"):
        ConsciousStepResult(
            analysis=AnalyticalNote(text="Plan established"), disposition="continue"
        )
    with pytest.raises(ValidationError, match="user_message"):
        ConsciousStepResult(
            analysis=AnalyticalNote(text="All required checks passed"),
            disposition="propose_completion",
        )
    with pytest.raises(ValidationError):
        ConsciousStepResult(
            analysis=AnalyticalNote(text="All required checks passed"),
            disposition="propose_completion",
            user_message="   ",
        )
    waiting = ConsciousStepResult(
        analysis=AnalyticalNote(text="Need the experiment result before selecting an explanation"),
        disposition="waiting",
    )
    assert waiting.next_step is None


@pytest.mark.parametrize(
    "reference",
    [
        {"event_ref": True},
        {"event_ref": "7"},
        {"event_ref": 0},
        {"event_ref": 7, "output_path": [False]},
        {"event_ref": 7, "output_path": [-1]},
        {"event_ref": 7, "extra": "source"},
    ],
)
def test_note_references_reject_coerced_or_invalid_trace_identities(reference):
    with pytest.raises(ValidationError):
        AnalyticalNote(text="A hypothesis", source_refs=[reference])


def test_step_checkpoint_survives_snapshot_and_is_available_without_graph_materialization():
    tasks = TaskStore()
    task = tasks.create_task("Explain the failure")
    task.current_step = step_spec()
    task.last_step_ref = {"event_ref": 19, "output_path": []}
    task.plan = [{"goal": "Separate load from connection reuse", "status": "in_progress"}]
    task.step_state = {
        "phase": "integrating",
        "last_result": {
            "analysis": {"text": "The high-load-only explanation does not fit C."},
            "disposition": "continue",
        },
        "integration": {"operation_id": "task-step-1", "experience_refs": [21, 22]},
    }
    snapshot = json.loads(json.dumps(tasks.snapshot()))
    restored = TaskStore.from_snapshot(snapshot).get(task.id)
    context = prepare_context(restored, "investigation", None).to_dict()
    assert context["messages"] == []
    assert context["state"]["plan"] == task.plan
    assert context["state"]["current_step"] == task.current_step
    assert context["state"]["last_step_ref"] == task.last_step_ref
    assert context["state"]["step_state"] == task.step_state
    restored.step_state["integration"]["experience_refs"].clear()
    assert task.step_state["integration"]["experience_refs"] == [21, 22]


def test_response_schema_is_closed_at_every_object_and_preserves_empty_values():
    schema = ConsciousStepResult.response_schema()

    def check(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value.get("properties", {}))
            assert "default" not in value
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(schema)
    assert schema["$defs"]["PlanStep"]["required"] == ["step", "status"]
    result = ConsciousStepResult(
        analysis=AnalyticalNote(text="Need input"),
        disposition="waiting",
        plan=[{"step": "Collect observations", "status": "waiting"}],
    )
    payload = result.model_dump(mode="json")
    assert payload["findings"] == [] and payload["next_step"] is None
    assert payload["plan"] == [{"step": "Collect observations", "status": "waiting"}]
    assert ConsciousStepResult.model_validate(payload) == result


def test_plan_rejects_undefined_fields_instead_of_silently_dropping_them():
    with pytest.raises(ValidationError):
        ConsciousStepResult(
            analysis=AnalyticalNote(text="Plan"),
            disposition="waiting",
            plan=[{"arbitrary": "data"}],
        )
