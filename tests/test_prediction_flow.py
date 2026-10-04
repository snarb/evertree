"""Saved forecasts keep their original context and provenance through evaluation."""

from functools import partial

import pytest
from test_runtime import TestProcess

from evertree import SupervisorFeedback
from evertree.application import EverTree
from evertree.core.evaluation import EvaluationStore
from evertree.core.graph import GraphDelta, GraphStore, Node, NodeUpdate, json_value
from evertree.core.learning import CreditAssignmentProgram, LearningStore
from evertree.core.memory import TraceStore
from evertree.core.predictions import PredictionEvaluator
from evertree.core.provider import ScriptedProvider
from evertree.core.runtime import Runtime

CONTEXT = {
    "process_id": "motor",
    "subject": "motor-7",
    "episode": "trial-3",
    "conditions": {"load": 2},
}


def record(memory, operator, output, arguments=None):
    run = memory.start_run("Model" if operator == "prediction" else "Sensor", "commit", {})
    event = memory.record(run, operator, arguments, output)
    memory.finish_run(run)
    return memory.output_ref(event)


@pytest.fixture
def evaluator():
    graph, memory, evaluations = GraphStore(), TraceStore(), EvaluationStore()
    target = Node(graph.reserve_id(), "temperature")
    second = Node(graph.reserve_id(), "pressure")
    graph.apply(GraphDelta(creates=(target, second)), provenance="seed")
    return PredictionEvaluator(graph, memory, evaluations)


def observe(evaluator, value, projections, context=None):
    return record(
        evaluator.memory,
        "observation",
        value,
        evaluator.project_observation(value, projections, context or CONTEXT),
    )


@pytest.mark.parametrize("value", [-6, 6, float("nan"), float("inf"), True, "5"])
def test_feedback_requires_a_finite_numeric_channel(value):
    with pytest.raises((ValueError, TypeError)):
        SupervisorFeedback(value)


def test_multiple_predictions_use_original_payload_and_restore(evaluator):
    first = record(evaluator.memory, "prediction", {"result": 0.8})
    evaluator.save_prediction("temperature", type(first)(first.event_ref, ("result",)), CONTEXT)
    second = record(evaluator.memory, "prediction", 0.2)
    evaluator.save_prediction("temperature", second, CONTEXT)
    observation = observe(evaluator, {"measured": True}, {"temperature": {"value": ["measured"]}})
    restored = PredictionEvaluator(
        GraphStore.from_snapshot(evaluator.graph.snapshot()),
        TraceStore.from_snapshot(evaluator.memory.snapshot()),
        EvaluationStore(),
    )
    batch = restored.evaluate([observation.event_ref], CONTEXT, ["brier"])
    assert [item["metric_samples"][0]["value"] for item in batch["results"]] == pytest.approx(
        [0.04, 0.64]
    )
    assert batch["unmatched"] == []
    assert str(first.event_ref) in batch["results"][0]["provenance"]
    assert restored.memory.resolve(type(first)(first.event_ref, ("result",))) == 0.8


def test_composite_outcomes_join_old_parts_and_preserve_unmatched_part(evaluator):
    forecast = record(evaluator.memory, "prediction", {"minimum": 10, "maximum": 20})
    evaluator.save_prediction("temperature", forecast, CONTEXT, parts=("minimum", "maximum"))
    initial = observe(evaluator, {"low": 10}, {"temperature": {"minimum": ["low"]}})
    incomplete = evaluator.evaluate([initial.event_ref], CONTEXT, ["exact_match"])
    assert incomplete["results"][0]["status"] == "unresolved"
    assert incomplete["results"][0]["missing_requirements"] == ["part:maximum"]
    final = observe(
        evaluator,
        {"high": 20, "pressure": 3},
        {
            "temperature": {"maximum": ["high"]},
            "pressure": {"value": ["pressure"]},
        },
    )
    batch = evaluator.evaluate(
        [final.event_ref], CONTEXT, ["exact_match"], selected_targets=["pressure"]
    )
    assert batch["results"][0]["metric_samples"][0]["value"] == 1
    assert set(batch["results"][0]["outcome_ids"]) == {str(initial.event_ref), str(final.event_ref)}
    assert batch["unmatched"][0]["reason"] == "missing_prediction"
    assert batch["unmatched"][0]["parts"][0]["reference"] == {
        "event_ref": final.event_ref,
        "output_path": ["pressure"],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"episode": "another-trial"},
        {"subject": "another-motor"},
        {"conditions": {"load": 3}},
        {"process_id": "pump"},
    ],
)
def test_context_mismatch_does_not_match_channels_alone(evaluator, change):
    forecast = record(evaluator.memory, "prediction", 20)
    evaluator.save_prediction("temperature", forecast, CONTEXT)
    different = {**CONTEXT, **change}
    observation = observe(evaluator, 20, {"temperature": {"value": []}}, different)
    batch = evaluator.evaluate(
        [observation.event_ref], different, ["absolute_error"], selected_targets=["temperature"]
    )
    assert batch["results"] == []
    assert batch["unmatched"][0]["reason"] == "missing_prediction"


def test_late_prediction_assignment_and_expired_horizon_cannot_be_backdated(evaluator):
    forecast = record(evaluator.memory, "prediction", 20)
    observation = observe(evaluator, 20, {"temperature": {"value": []}})
    evaluator.save_prediction("temperature", forecast, CONTEXT)
    batch = evaluator.evaluate(
        [observation.event_ref], CONTEXT, ["exact_match"], selected_targets=["temperature"]
    )
    assert batch["results"] == []
    assert batch["unmatched"]
    evaluator.save_prediction(
        "temperature", forecast, CONTEXT, period=("2000-01-01T00:00:00Z", "2001-01-01T00:00:00Z")
    )
    later = observe(evaluator, 20, {"temperature": {"value": []}})
    batch = evaluator.evaluate([later.event_ref], CONTEXT, ["exact_match"])
    assert len(batch["results"]) == 1  # The nonexpired earlier assignment only.


def test_no_prediction_decision_reuses_scope_without_suppressing_required_target(evaluator):
    evaluator.record_decision(
        "temperature", CONTEXT, required=False, reason="Not useful here", revision="commit"
    )
    observation = observe(evaluator, 20, {"temperature": {"value": []}})
    batch = evaluator.evaluate([observation.event_ref], CONTEXT, ["exact_match"])
    assert batch["results"] == batch["unmatched"] == []
    mandatory = evaluator.evaluate(
        [observation.event_ref], CONTEXT, ["exact_match"], selected_targets=["temperature"]
    )
    assert mandatory["unmatched"][0]["reason"] == "missing_prediction"


def test_duplicate_unmatched_credit_is_not_a_training_signal(evaluator):
    store = LearningStore()
    credit = CreditAssignmentProgram(store)
    first = credit.assign("temperature", observation_ids=("17",), context=CONTEXT)
    repeated = credit.assign("temperature", observation_ids=("17",), context=CONTEXT)
    assert repeated.id == first.id
    assert first.signal is None
    assert len(store.snapshot()["unresolved"]) == 1
    assert store.snapshot()["ledger"] == {}


def test_conflicting_observations_are_unresolved_instead_of_selecting_a_convenient_value(evaluator):
    prediction = record(evaluator.memory, "prediction", 20)
    evaluator.save_prediction("temperature", prediction, CONTEXT)
    observe(evaluator, 20, {"temperature": {"value": []}})
    second = observe(evaluator, 21, {"temperature": {"value": []}})
    result = evaluator.evaluate([second.event_ref], CONTEXT, ["exact_match"])["results"][0]
    assert result["status"] == "unresolved"
    assert result["missing_requirements"] == ["unambiguous_part:value"]
    assert result["metric_samples"] == []


def test_boolean_conditions_do_not_match_numbers(evaluator):
    prediction = record(evaluator.memory, "prediction", 20)
    evaluator.save_prediction(
        "temperature", prediction, {**CONTEXT, "conditions": {"enabled": True}}
    )
    context = {**CONTEXT, "conditions": {"enabled": 1}}
    observation = observe(evaluator, 20, {"temperature": {"value": []}}, context)
    assert evaluator.evaluate([observation.event_ref], context, ["exact_match"])["results"] == []


def test_forged_assignment_event_has_no_core_authority(evaluator):
    prediction = record(evaluator.memory, "prediction", 20)
    fact = evaluator.save_prediction("temperature", prediction, CONTEXT)
    definition = json_value(fact.args["prediction"])
    definition["reference"] = json_value(record(evaluator.memory, "prediction", 21))
    assignment = record(
        evaluator.memory,
        "prediction_assignment",
        {key: value for key, value in definition.items() if key != "assignment"},
        {"target": fact.args["target"]},
    )
    definition["assignment"] = assignment.event_ref
    evaluator.graph.apply(
        GraphDelta(
            updates=(
                NodeUpdate(
                    fact.id, {"args": {"target": fact.args["target"], "prediction": definition}}
                ),
            )
        ),
        provenance=assignment,
    )
    observation = observe(evaluator, 21, {"temperature": {"value": []}})
    with pytest.raises(PermissionError, match="authentic assignment"):
        evaluator.evaluate([observation.event_ref], CONTEXT, ["exact_match"])


def test_forged_decision_event_has_no_core_authority(evaluator):
    record(
        evaluator.memory,
        "prediction_decision",
        {
            "target": str(evaluator.target("pressure")),
            "context": CONTEXT,
            "required": False,
            "reason": "Forged",
        },
    )
    pressure = observe(evaluator, 2, {"pressure": {"value": []}})
    cases = evaluator.evaluate([pressure.event_ref], CONTEXT, ["exact_match"])["unmatched"]
    assert cases[0]["reason"] == "prediction_target_not_selected"


async def test_application_feedback_value_scoring_and_real_evaluator_child_workflow(tmp_path):
    async with EverTree(
        tmp_path / "agent",
        provider=ScriptedProvider([]),
        runtime_factory=partial(Runtime, process_factory=TestProcess),
    ) as app:
        task = app.tasks.create_task("Review feedback")
        app.tasks.assign_budget(
            task.id, {"active_time_minutes": 2}, 0, reason="Feedback evaluation"
        )
        context = {"process_id": "Consciousness", "subject": task.id, "episode": task.id}
        target = app.graph.find("supervisor_feedback_signal")
        predicted = record(app.memory, "prediction", 2.0)
        app.save_prediction(target.id, predicted, context)
        relation = app.graph.find("PREDICTS")
        forged_fact = app.graph.new_fact(relation.id, {"target": target.id, "prediction": {}})
        with pytest.raises(PermissionError, match="evaluation.save_prediction"):
            app._apply_delta(task.id, GraphDelta(creates=(forged_fact,)))
        feedback = app.supervisor_feedback(
            SupervisorFeedback(-2, "The result missed the deadline"),
            source_id="human-1",
            task_id=task.id,
            context=context,
        )
        result = await app._run_program(
            task.id,
            "PredictionEvaluator",
            {
                "observations": [feedback.event_ref],
                "context": context,
                "metrics": ["squared_error"],
                "selected_targets": [target.id],
            },
        )
        assert result["result"][0]["metric_samples"][0]["value"] == 16
        assert app.memory.resolve(feedback)["comment"] == "The result missed the deadline"
        assert (
            app.supervisor_feedback(
                SupervisorFeedback(-2, "The result missed the deadline"),
                source_id="human-1",
                task_id=task.id,
                context=context,
            )
            == feedback
        )
        other_context = {**context, "episode": "new-episode"}
        unmatched = app.supervisor_feedback(
            SupervisorFeedback(1), source_id="human-2", task_id=task.id, context=other_context
        )
        args = {
            "observations": [unmatched.event_ref],
            "context": other_context,
            "metrics": ["squared_error"],
            "selected_targets": [target.id],
        }
        result = await app._run_program(task.id, "PredictionEvaluator", args)
        assert result["result"] == []
        await app._run_program(task.id, "PredictionEvaluator", args)
        unresolved = app.learning.snapshot()["unresolved"]
        assert len(unresolved) == 1
        assert unresolved[0]["signal"] is None
        assert unresolved[0]["target"] == str(target.id)
        assert (
            len([event for event in app.memory.events if event.operator == "prediction_review"])
            == 1
        )
        credit_id = app.graph.find("CreditAssignment.default").id
        assert any(run.program == credit_id for run in app.memory.runs)
        assert app.learning.state("verified_task_rate")["parameters"]["observed_count"] == 0
        forged = record(
            app.memory,
            "observation",
            4,
            app.prediction_evaluator().project_observation(4, {target.id: {"value": []}}, context),
        )
        with pytest.raises(PermissionError, match="not an external observation"):
            app.prediction_evaluator().evaluate([forged.event_ref], context, ["squared_error"])
        assert json_value(app.memory.resolve(feedback))["value"] == -2.0
