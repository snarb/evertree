"""SelfTaskOutcome.model forecasts verification; TaskFraming uses it and Core trains it on outcomes."""

from __future__ import annotations

import asyncio
import json

from evertree.core.contracts import task_outcome_context
from tests.support.application import IntegrationScriptedProvider as ScriptedProvider
from tests.support.application import decision, framing, verification
from tests.support.component import component_app


def forecasts(provider):
    """Outcome forecasts TaskFraming passed to its model call, in order."""
    found = []
    for request in provider.task_requests:
        try:
            data = json.loads(request.prompt)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and "outcome_forecast" in data:
            found.append(data["outcome_forecast"])
    return found


async def test_verified_tasks_train_the_declared_estimator_through_their_forecast(tmp_path):
    provider = ScriptedProvider(
        [framing(), decision(), verification(), framing(), decision(), verification()]
    )
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        model = agent.graph.find("SelfTaskOutcome.model")
        process = agent.graph.get(model.properties["process"])
        target = agent.graph.find("TaskVerified")
        assert any(
            fact.args == {"process": process.id, "variable": target.id}
            for fact in agent.graph.facts("PROCESS_VARIABLE")
        )
        (binding,) = agent.learning.bindings("TaskVerified")
        assert binding["owner"] == str(model.id)

        first = await asyncio.wait_for(agent.run("Count r in strawberry"), 60)
        assert first["status"] == "succeeded", first
        statistics = agent.learning_statistics("TaskVerified")
        assert statistics["observed_count"] == 1
        assert statistics["probability"] == 1.0
        (prediction,) = agent.graph.facts("PREDICTS")
        assert prediction.args["target"] == target.id
        scored = next(
            result
            for result in agent.evaluations.snapshot()["results"]
            if result["evaluated_subject"] == str(prediction.id)
        )
        assert scored["metric_samples"][0]["value"] == 0.25

        second = await asyncio.wait_for(agent.run("Count r in strawberry again"), 60)
        assert second["status"] == "succeeded", second
        assert forecasts(provider) == [
            {"verified": 0.5, "observed": 0},
            {"verified": 2 / 3, "observed": 1},
        ]
        assert agent.learning_statistics("TaskVerified")["observed_count"] == 2


async def test_task_outcome_is_learned_once_and_a_missing_forecast_stays_unresolved(tmp_path):
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        done = await asyncio.wait_for(agent.run("Count r in strawberry"), 60)
        assert done["status"] == "succeeded", done
        before = agent.learning.snapshot()
        (outcome,) = [
            event
            for event in agent.memory.events
            if event.operator == "observation" and event.arguments.get("projections")
        ]
        agent._learn_task_outcome(done["task_id"], True, outcome.output["reason"])
        assert agent.learning.snapshot()["states"] == before["states"]
        assert agent.learning_statistics("TaskVerified")["observed_count"] == 1

        agent._learn_task_outcome("unforecast-task", False, "no framing ran")
        unresolved = agent.learning.snapshot()["unresolved"]
        assert [(item["target"], item["reason"]) for item in unresolved] == [
            ("TaskVerified", "missing_prediction")
        ]
        assert unresolved[0]["context"] == task_outcome_context("unforecast-task")
        assert agent.learning_statistics("TaskVerified")["observed_count"] == 1
