from functools import partial

import pytest

from evertree.application import EverTree
from evertree.core.evaluation.contracts import SupervisorFeedback
from evertree.core.graph.types import GraphDelta
from evertree.core.provider import ScriptedProvider
from evertree.core.runtime.controller import Runtime
from evertree.core.values import json_value
from tests.support.runtime import TestProcess

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


async def test_application_feedback_value_scoring_and_real_evaluator_child_workflow(tmp_path):
    """A real child workflow proves feedback and scoring cross the worker gateway correctly."""
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
        forged_fact = app.graph.new_fact(relation.id, {"target": target.id, "assignment_ref": 1})
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
        credit_id = app.graph.find("CreditAssignment.exec").id
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


pytestmark = pytest.mark.usefixtures("offline_application")
