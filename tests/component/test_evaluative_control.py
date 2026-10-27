"""Evaluative control across the agent lifecycle: supervisor feedback, calibrated
prediction_unexpectedness, ExplanatoryTension, tension_reduction and Task outcome statistics.

Tasks run through the real coordinator, gateway, trace and stores with a scripted model.
Aggregates are read through the host API, the Program gateway and conscious tools, which
must agree. History older than a test is supplied as saved evaluation results or Task
transitions with explicit times, because Core never backdates the outcomes it observes.
"""

from __future__ import annotations

import asyncio
import math
import random
from datetime import timedelta

import pytest

from evertree.core.evaluation.contracts import (
    EvaluatedResult,
    MetricSample,
    SupervisorFeedback,
)
from evertree.core.evaluation.scoring import prediction_unexpectedness
from evertree.core.learning.contracts import LearningObjective, LearningSignal
from evertree.core.learning.declaration import ForecastTarget
from evertree.core.values import json_value
from tests.support.application import IntegrationScriptedProvider as ScriptedProvider
from tests.support.application import decision, framing, is_integration_request, verification
from tests.support.component import REVISION, component_app
from tests.support.evaluative import (
    FOREVER,
    around,
    checked_forecast,
    finished_task,
    now,
    process_id,
    seeded_unexpectedness,
    tool_calls,
    tool_results,
    window,
)


def unexpectedness_results(agent, process):
    return [
        result
        for result in agent.evaluations.all()
        if result.process_id == process
        and any(sample.channel == "prediction_unexpectedness" for sample in result.metric_samples)
    ]


def gateway(agent, task_id, method, payload, *, role="model"):
    metadata = {
        "task_id": task_id,
        "run_mode": "live",
        "program": {"role": role, "revision": REVISION, "program_id": "1"},
    }
    return agent._gateway(method, {**payload, "_runtime": metadata})


# Task lifecycle → TaskVerified forecast → calibrated unexpectedness


async def test_evc01_completed_task_records_calibrated_unexpectedness_for_its_forecast(tmp_path):
    """EVC-01: a verified Task's outcome scores the framing forecast with a model-based rarity."""
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        started = now()
        done = await asyncio.wait_for(agent.run("Count r in strawberry"), 60)
        assert done["status"] == "succeeded", done
        outcome = process_id(agent, "SelfTaskOutcome")
        (result,) = unexpectedness_results(agent, outcome)
        metrics = result.metrics()
        assert metrics["brier"] == 0.25
        # p = 0.5 on a binary outcome: either result is wholly ordinary under the norm.
        assert metrics["prediction_unexpectedness"] == 0
        assert result.basis["method"] == "model"
        assert result.basis["kind"] == "bernoulli"
        assert result.comparison_key.startswith("TaskVerified:bernoulli:")
        tension = agent.explanatory_tension(window(started, now()), ["SelfTaskManagement"])
        assert tension["value"] == 0
        assert tension["by_process"][outcome] == {"name": "SelfTaskOutcome", "mean": 0, "count": 1}
        stats = agent.task_outcome_stats(window(started, now()), ["Process"])
        assert stats["success_rate"] == {"value": 1.0, "numerator": 1, "denominator": 1}
        task = agent.tasks.get(done["task_id"])
        assert task.process_id == process_id(agent, "Process")


async def test_evc02_failed_verification_after_a_confident_forecast_is_unusual(tmp_path):
    """EVC-02: a failure after two verified Tasks is rarer under the learned forecast."""
    provider = ScriptedProvider(
        [framing(), decision(), verification()] * 2
        + [framing(), decision(), verification(False), decision(status="failed")]
    )
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        for text in ("Count r in strawberry", "Count r in raspberry"):
            assert (await asyncio.wait_for(agent.run(text), 60))["status"] == "succeeded"
        failed = await asyncio.wait_for(agent.run("Count r in cranberry"), 60)
        assert failed["status"] == "failed", failed
        values = [
            result.metrics()["prediction_unexpectedness"]
            for result in sorted(
                unexpectedness_results(agent, process_id(agent, "SelfTaskOutcome")),
                key=lambda result: result.observed_at,
            )
        ]
        # Forecasts 1/2, 2/3, 3/4: successes are ordinary, the failure has rarity p = 3/4.
        assert values == [0, 0, pytest.approx(0.75)]
        assert all(0 <= value <= 1 for value in values)


async def test_evc03_cancelled_task_is_not_an_outcome_and_is_reported_apart(tmp_path):
    """EVC-03: cancellation keeps its decision reason and creates no verification outcome."""
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        started = now()
        state = await agent.submit("Count r in strawberry")
        await agent.cancel(state.id, reason="Supervisor withdrew the request")
        task = agent.tasks.get(state.id)
        assert task.status == "cancelled"
        assert task.outcome_reason == "Supervisor withdrew the request"
        assert unexpectedness_results(agent, process_id(agent, "SelfTaskOutcome")) == []
        stats = agent.task_outcome_stats(window(started, now()), ["Process"])
        assert stats["cancelled"] == 1
        assert stats["success_rate"] == {"value": None, "numerator": 0, "denominator": 0}
        with pytest.raises(ValueError, match="reason"):
            await agent.cancel(state.id, reason=" ")


# supervisor_feedback_signal


async def test_evc04_feedback_on_an_open_task_reaches_its_next_conscious_step(tmp_path):
    """EVC-04: feedback is a channel value; its comment reaches the Task's work as input."""
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        planning = process_id(agent, "SelfPlanning")
        task = agent.tasks.create_task("Count r in strawberry", process_id=planning)
        feedback = SupervisorFeedback(-3, "Explain how you counted")
        assert feedback.normalized() == pytest.approx(-0.6)
        reference = agent.supervisor_feedback(feedback, source_id="supervisor-1", task_id=task.id)
        assert agent.attention._queue[task.id] is not None
        (result,) = [
            result
            for result in agent.evaluations.all()
            if any(
                sample.channel == "supervisor_feedback_signal" for sample in result.metric_samples
            )
        ]
        assert result.metrics() == {"supervisor_feedback": -3.0}
        assert result.process_id == planning
        assert result.evaluated_subject == task.id
        # The comment stays in the original observation, reachable through provenance.
        assert "Explain" not in str(result.to_dict()["metric_samples"])
        source = agent.memory.get_event(int(result.provenance[0]))
        assert source.output["comment"] == "Explain how you counted"
        assert reference.event_ref == source.id

        done = await asyncio.wait_for(agent.run("Count r in strawberry", task_id=task.id), 60)
        assert done["status"] == "succeeded", done
        conscious = [r for r in provider.task_requests if "Explain how you counted" in r.prompt]
        assert conscious, "The conscious step must see the supervisor's comment"
        history = agent.supervisor_feedback_history(FOREVER, ["SelfTaskManagement"])
        assert [(item["value"], item["comment"]) for item in history["items"]] == [
            (-3.0, "Explain how you counted")
        ]
        assert history["by_process"][planning]["mean"] == -3.0


async def test_evc05_feedback_after_completion_is_recorded_once_and_cannot_be_minted(tmp_path):
    """EVC-05: late feedback is evidence only; repeats count once and agents cannot write it."""
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        done = await asyncio.wait_for(agent.run("Count r in strawberry"), 60)
        messages = len(agent._inputs[done["task_id"]])
        first = agent.supervisor_feedback(
            SupervisorFeedback(4, "Concise"), source_id="review-1", task_id=done["task_id"]
        )
        again = agent.supervisor_feedback(
            SupervisorFeedback(4, "Concise"), source_id="review-1", task_id=done["task_id"]
        )
        assert first == again
        assert len(agent._inputs[done["task_id"]]) == messages
        history = agent.supervisor_feedback_history(FOREVER, ["Process"])
        assert [item["value"] for item in history["items"]] == [4.0]
        with pytest.raises(ValueError, match="different contents"):
            agent.supervisor_feedback(
                SupervisorFeedback(-4), source_id="review-1", task_id=done["task_id"]
            )
        for value in (5.5, math.nan, True):
            with pytest.raises((TypeError, ValueError)):
                SupervisorFeedback(value)
        open_task = agent.tasks.create_task("Open", process_id=process_id(agent, "Process"))
        open_task.execution_budget = agent.tasks.get(done["task_id"]).execution_budget
        open_task.self_improvement_budget = 0
        with pytest.raises(PermissionError, match="Unsupported core operation"):
            await gateway(
                agent, open_task.id, "evaluation.supervisor_feedback", {"value": 5}, role="exec"
            )


async def test_evc06_a_forecast_of_feedback_is_checked_only_against_its_saved_norm(agent):
    """EVC-06: residual -0.8 is a prediction_error; rarity needs the declared dispersion."""
    framing_process = process_id(agent, "SelfTaskFraming")
    task = agent.tasks.create_task("Draft", process_id=framing_process)
    run = agent.memory.start_run("FeedbackForecaster", REVISION, {})
    forecast = agent.memory.record(run, "forecast", output={"value": 0.6})
    agent.memory.finish_run(run)
    context = {"process_id": "SelfTaskFraming", "subject": task.id, "episode": task.id}
    from evertree.core.memory.types import TraceOutputRef

    agent.save_prediction(
        "supervisor_feedback_signal",
        TraceOutputRef(forecast.id, ("value",)),
        context,
        calibration={"kind": "normal", "stddev": 0.5},
        comparison_key="feedback-normal",
    )
    reference = agent.supervisor_feedback(
        SupervisorFeedback(-0.2), source_id="s", task_id=task.id, context=context
    )
    batch = agent.prediction_evaluator().evaluate(
        [reference.event_ref], context, ["residual", "squared_error"]
    )
    (result,) = batch["results"]
    metrics = {sample["metric"]: sample["value"] for sample in result["metric_samples"]}
    assert metrics["residual"] == pytest.approx(-0.8)
    assert metrics["prediction_unexpectedness"] == pytest.approx(math.erf(0.8 / (0.5 * 2**0.5)))
    assert result["process_id"] == framing_process

    without = checked_forecast(agent, framing_process, 0.6, -0.2, calibration=None)
    assert without["skipped_metrics"] == {"prediction_unexpectedness": "no_supported_calibration"}
    assert "prediction_unexpectedness" not in {m["metric"] for m in without["metric_samples"]}


async def test_evc07_an_omission_by_cost_is_kept_as_its_reason(agent):
    """EVC-07: a declared omission is retained and surfaces as the aggregate's skip reason."""
    planning = process_id(agent, "SelfPlanning")
    omitted = {"omit": "cost_not_justified"}
    result = checked_forecast(agent, planning, 1.0, 3.0, calibration=omitted)
    assert result["skipped_metrics"] == {"prediction_unexpectedness": "cost_not_justified"}
    assert result["metric_samples"] == [{"metric": "squared_error", "value": 4.0, "channel": None}]
    tension = agent.explanatory_tension(
        around(now() + timedelta(seconds=1), days=1), ["SelfPlanning"]
    )
    assert tension["value"] is None
    assert tension["skipped"][planning] == {"name": "SelfPlanning", "reason": "cost_not_justified"}
    declared = ForecastTarget(
        form="mean",
        result="steps",
        subject="plan",
        horizon="task end",
        check="count",
        metrics=["squared_error"],
        unexpectedness=omitted,
    )
    assert declared.unexpectedness == omitted
    with pytest.raises(ValueError, match="cannot use unexpectedness kind"):
        ForecastTarget(**{**declared.model_dump(), "unexpectedness": {"kind": "bernoulli"}})


def test_evc08_window_check_averages_parameter_uncertainty_and_keeps_its_bound():
    """EVC-08: beta-binomial windows; 520/1000 is ordinary, 600/1000 is a strong mismatch."""
    sharp = {"alpha": 1e6, "beta": 1e6, "n": 1000}
    calibration = {"kind": "beta_binomial"}
    assert prediction_unexpectedness(sharp, 520, calibration=calibration) < 0.8
    assert prediction_unexpectedness(sharp, 600, calibration=calibration) > 0.9999
    # A wide posterior makes the same count less unusual than its mean parameter would.
    wide = {"alpha": 5, "beta": 5, "n": 1000}
    assert prediction_unexpectedness(wide, 600, calibration=calibration) < 0.5
    with pytest.raises(ValueError, match="outside"):
        prediction_unexpectedness(sharp, 1001, calibration=calibration)
    # Under a correct Q and a check fixed in advance, P(u >= 1 - alpha) <= alpha.
    rng = random.Random(7)
    posterior = {"alpha": 3, "beta": 2, "n": 40}
    draws = []
    for _ in range(3000):
        p = rng.betavariate(3, 2)
        count = sum(rng.random() < p for _ in range(40))
        draws.append(prediction_unexpectedness(posterior, count, calibration=calibration))
    for alpha in (0.05, 0.1, 0.25):
        assert sum(value >= 1 - alpha for value in draws) / len(draws) <= alpha + 0.02


async def test_evc09_empirical_norm_needs_exchangeability_and_records_its_basis(agent):
    """EVC-09: an empirical rule is recorded with its norm; a new norm starts a new series."""
    memory_process = process_id(agent, "SelfMemoryRetrieval")
    started = now()
    rule = {"kind": "empirical_rank", "exchangeable": True, "reference_scores": [1, 2, 3]}
    assumed = checked_forecast(
        agent, memory_process, 0.0, 100.0, calibration={**rule, "exchangeable": False}
    )
    assert "prediction_unexpectedness" in assumed["skipped_metrics"]
    first = checked_forecast(agent, memory_process, 0.0, 100.0, calibration=rule)
    assert first["metric_samples"][-1]["value"] == pytest.approx(0.75)
    assert first["basis"]["method"] == "empirical"
    middle = now()
    renormed = {**rule, "reference_scores": [1, 2, 3, 200]}
    second = checked_forecast(agent, memory_process, 0.0, 100.0, calibration=renormed)
    assert second["basis"]["norm_digest"] != first["basis"]["norm_digest"]
    assert second["comparison_key"] != first["comparison_key"]
    reduction = agent.tension_reduction(
        window(middle, now()), ["SelfMemoryRetrieval"], baseline_period=window(started, middle)
    )
    assert reduction["value"] is None
    assert reduction["skipped"][memory_process]["reason"] == "incomparable_periods"


# ExplanatoryTension and tension_reduction


async def test_evc10_explanatory_tension_weights_processes_equally(agent):
    """EVC-10: mean of per-process means, independent of how many checks each produced."""
    planning, framing_process = (
        process_id(agent, "SelfPlanning"),
        process_id(agent, "SelfTaskFraming"),
    )
    moment = now() - timedelta(hours=1)
    for _ in range(9):
        seeded_unexpectedness(agent, planning, moment, 0.9)
    seeded_unexpectedness(agent, framing_process, moment, 0.1)
    tension = agent.explanatory_tension(around(now(), days=1), ["SelfTaskManagement"])
    assert tension["value"] == pytest.approx(0.5)
    assert tension["by_process"][planning]["count"] == 9
    assert tension["coverage"]["covered"] == 2
    empty = agent.explanatory_tension(around(now() - timedelta(days=30), days=1), ["SelfPlanning"])
    assert empty["value"] is None
    assert empty["skipped"][planning]["reason"] == "insufficient_data"


async def test_evc11_tension_reduction_compares_the_same_processes_in_both_periods(agent):
    """EVC-11: by_process shows a fall in one process and a rise in another."""
    planning, framing_process = (
        process_id(agent, "SelfPlanning"),
        process_id(agent, "SelfTaskFraming"),
    )
    end = now()
    before, after = end - timedelta(days=10), end - timedelta(days=3)
    for at, plan, frame in ((before, 0.9, 0.2), (after, 0.3, 0.4)):
        seeded_unexpectedness(agent, planning, at, plan)
        seeded_unexpectedness(agent, framing_process, at, frame)
    result = agent.tension_reduction(around(end, days=7), ["SelfTaskManagement"])
    assert result["baseline_period"][1] == result["period"][0]
    assert result["by_process"][planning]["delta"] == pytest.approx(0.6)
    assert result["by_process"][framing_process]["delta"] == pytest.approx(-0.2)
    assert result["value"] == pytest.approx(0.2)
    assert result["tension_before"] - result["tension_after"] == pytest.approx(result["value"])
    assert result["by_process"][planning]["before_count"] == 1


async def test_evc12_process_selection_expands_subtypes_once(agent):
    """EVC-12: a parent's own checks count once; [Process] covers the whole taxonomy."""
    learning, reflection = process_id(agent, "SelfLearning"), process_id(agent, "SelfReflection")
    evidence = process_id(agent, "SelfGraphEvidenceAssessment")
    end = now()
    for process in (learning, reflection, evidence):
        seeded_unexpectedness(agent, process, end - timedelta(days=10), 0.8)
        seeded_unexpectedness(agent, process, end - timedelta(days=2), 0.2)
    subtree = agent.tension_reduction(around(end, days=7), ["SelfLearning", "SelfReflection"])
    assert set(subtree["by_process"]) == {learning, reflection, evidence}
    assert subtree["value"] == pytest.approx(0.6)
    everything = agent.tension_reduction(around(end, days=7), ["Process"])
    assert set(everything["by_process"]) == {learning, reflection, evidence}
    assert everything["coverage"]["never_measured"] > 50
    unknown = agent.tension_reduction(around(end, days=7), ["NoSuchProcess", "SelfReflection"])
    assert unknown["skipped"]["NoSuchProcess"]["reason"] == "unknown_process"


async def test_evc13_missing_coverage_is_reported_and_never_an_improvement(agent):
    """EVC-13: a process absent from one period is skipped, not counted as reduced tension."""
    planning, framing_process = (
        process_id(agent, "SelfPlanning"),
        process_id(agent, "SelfTaskFraming"),
    )
    end = now()
    seeded_unexpectedness(agent, planning, end - timedelta(days=10), 0.4)
    seeded_unexpectedness(agent, planning, end - timedelta(days=2), 0.4)
    seeded_unexpectedness(agent, framing_process, end - timedelta(days=10), 0.95)
    result = agent.tension_reduction(around(end, days=7), ["SelfTaskManagement"])
    assert result["value"] == 0
    assert result["skipped"][framing_process] == {
        "name": "SelfTaskFraming",
        "reason": "insufficient_data",
    }
    only_gone = agent.tension_reduction(around(end, days=7), ["SelfTaskFraming"])
    assert only_gone["value"] is None


async def test_evc14_outcome_time_selects_the_period_and_a_fixed_baseline_is_kept(agent):
    """EVC-14: an explicit baseline is used as given; calculation time does not matter."""
    planning = process_id(agent, "SelfPlanning")
    end = now()
    baseline = around(end - timedelta(days=60), days=7)
    seeded_unexpectedness(agent, planning, end - timedelta(days=62), 0.9)
    seeded_unexpectedness(agent, planning, end - timedelta(days=20), 0.1)  # in neither period
    seeded_unexpectedness(agent, planning, end - timedelta(days=1), 0.5)
    result = agent.tension_reduction(
        around(end, days=7), ["SelfPlanning"], baseline_period=baseline
    )
    assert tuple(result["baseline_period"]) == baseline
    assert result["by_process"][planning]["before"] == pytest.approx(0.9)
    assert result["by_process"][planning]["after"] == pytest.approx(0.5)
    assert result["value"] == pytest.approx(0.4)


# Task outcome statistics


async def test_evc15_on_time_rate_counts_open_overdue_and_excludes_early_cancellation(agent):
    """EVC-15: deadlines in the period decide on_time_rate; Tasks without one are excluded."""
    planning = process_id(agent, "SelfPlanning")
    end = now()
    day = timedelta(days=1)
    start = end - 7 * day
    due = end - 3 * day
    finished_task(
        agent, "succeeded", process=planning, created=start, completed=due - day, deadline=due
    )
    finished_task(
        agent, "succeeded", process=planning, created=start, completed=due + day, deadline=due
    )
    finished_task(agent, None, process=planning, created=start, deadline=due)
    finished_task(
        agent, "cancelled", process=planning, created=start, completed=due - day, deadline=due
    )
    finished_task(agent, "failed", process=planning, created=start, completed=due)
    stats = agent.task_outcome_stats(window(start, end), ["SelfTaskManagement"])
    assert stats["on_time_rate"] == {
        "value": pytest.approx(1 / 3),
        "numerator": 1,
        "denominator": 3,
    }
    assert stats["success_rate"] == {
        "value": pytest.approx(2 / 3),
        "numerator": 2,
        "denominator": 3,
    }
    assert stats["cancelled"] == 1
    assert stats["open"] == 1
    assert stats["by_process"][planning]["name"] == "SelfPlanning"


async def test_evc16_a_missed_deadline_survives_later_revision_and_late_cancellation(agent):
    """EVC-16: the first passed deadline stays a miss; cancelling afterwards erases nothing."""
    planning = process_id(agent, "SelfPlanning")
    end = now()
    day = timedelta(days=1)
    start = end - 7 * day
    revised = finished_task(agent, None, process=planning, created=start, deadline=end - 5 * day)
    agent.tasks.revise_deadline(
        revised.id,
        (end + 30 * day).isoformat(),
        reason="scope grew",
        at=(end - 4 * day).isoformat(),
    )
    late = finished_task(agent, None, process=planning, created=start, deadline=end - 5 * day)
    agent.tasks.finish(
        late.id,
        "cancelled",
        reason="withdrawn",
        execution_stopped=True,
        completed_at=(end - 2 * day).isoformat(),
    )
    moved_early = finished_task(
        agent, None, process=planning, created=start, deadline=end - 2 * day
    )
    agent.tasks.revise_deadline(
        moved_early.id,
        (end + 30 * day).isoformat(),
        reason="agreed",
        at=(end - 4 * day).isoformat(),
    )
    stats = agent.task_outcome_stats(window(start, end), ["SelfPlanning"])
    assert stats["on_time_rate"] == {"value": 0.0, "numerator": 0, "denominator": 2}
    assert [event["kind"] for event in agent.tasks.snapshot()["events"]].count(
        "deadline_revised"
    ) == 2


async def test_evc17_parent_tasks_count_once_for_the_process_doing_the_work(agent):
    """EVC-17: subtasks are not counted again; overall rates sum process numerators."""
    planning, framing_process = (
        process_id(agent, "SelfPlanning"),
        process_id(agent, "SelfTaskFraming"),
    )
    end = now()
    start = end - timedelta(days=7)
    parent = finished_task(
        agent, "succeeded", process=planning, created=start, completed=end - timedelta(days=1)
    )
    child = finished_task(
        agent,
        "failed",
        process=planning,
        created=start,
        completed=end - timedelta(days=2),
        parent=parent.id,
    )
    finished_task(
        agent, "failed", process=framing_process, created=start, completed=end - timedelta(days=1)
    )
    stats = agent.task_outcome_stats(window(start, end), ["SelfTaskManagement"])
    assert stats["skipped"][child.id]["reason"] == "counted_at_parent_task_level"
    assert stats["success_rate"] == {"value": 0.5, "numerator": 1, "denominator": 2}
    assert stats["by_process"][framing_process]["success_rate"]["value"] == 0
    assert stats["on_time_rate"]["value"] is None
    nothing = agent.task_outcome_stats(window(start, end), ["SelfReflection"])
    assert nothing["success_rate"]["value"] is None and nothing["by_process"] == {}


# Access from Programs, consciousness and persistence


async def test_evc18_model_programs_read_the_same_aggregates_through_the_gateway(agent):
    """EVC-18: read-only aggregates are open to model Programs and match the host API."""
    planning = process_id(agent, "SelfPlanning")
    end = now()
    seeded_unexpectedness(agent, planning, end - timedelta(days=10), 0.7)
    seeded_unexpectedness(agent, planning, end - timedelta(days=2), 0.3)
    finished_task(
        agent,
        "succeeded",
        process=planning,
        created=end - timedelta(days=3),
        completed=end - timedelta(days=2),
    )
    task = agent.tasks.create_task("Reflect", process_id=planning)
    period = list(around(end, days=7))
    payload = {"period": period, "processes": ["SelfTaskManagement"]}
    tension = await gateway(agent, task.id, "evaluation.tension_reduction", payload)
    assert tension == json_value(agent.tension_reduction(tuple(period), ["SelfTaskManagement"]))
    assert tension["value"] == pytest.approx(0.4)
    stats = await gateway(agent, task.id, "tasks.outcome_stats", payload)
    assert stats["success_rate"]["value"] == 1.0
    assert (await gateway(agent, task.id, "evaluation.explanatory_tension", payload))[
        "value"
    ] == pytest.approx(0.3)
    feedback = await gateway(agent, task.id, "evaluation.feedback", payload)
    assert feedback["items"] == []


async def test_evc19_consciousness_loads_signals_and_attributes_its_task(tmp_path):
    """EVC-19: the conscious agent reads aggregates as tools and binds its Task to a process."""
    period = list(FOREVER)
    step = [
        *tool_calls(
            ("load_tool_set", {"name": "evaluative_signals"}),
            ("tension_reduction", {"period": period, "processes": ["SelfTaskManagement"]}),
            ("task_outcome_stats", {"period": period, "processes": ["SelfTaskManagement"]}),
            ("supervisor_feedback", {"period": period, "processes": ["Process"]}),
            ("assign_task_process", {"process": "SelfPlanning", "reason": "The task is planning"}),
        ),
        *decision(),
    ]
    provider = ScriptedProvider([framing(), step, verification()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        planning = process_id(agent, "SelfPlanning")
        seeded_unexpectedness(agent, planning, now() - timedelta(days=1), 0.6)
        done = await asyncio.wait_for(agent.run("Plan the counting"), 60)
        assert done["status"] == "succeeded", done
        (reduction,) = tool_results(agent, "tension_reduction")
        assert reduction["status"] == "completed"
        assert reduction["result"]["skipped"][planning]["reason"] == "insufficient_data"
        (stats,) = tool_results(agent, "task_outcome_stats")
        assert stats["result"]["success_rate"]["denominator"] == 0
        assert agent.tasks.get(done["task_id"]).process_id == planning
        after = agent.task_outcome_stats(FOREVER, ["SelfPlanning"])
        assert after["success_rate"] == {"value": 1.0, "numerator": 1, "denominator": 1}
        assert any('"now"' in request.prompt for request in provider.task_requests)
        # Aggregates are derived from saved experience, so integration does not re-learn them.
        integrated = [r.prompt for r in provider.requests if is_integration_request(r)]
        assert integrated and not any("tension_before" in prompt for prompt in integrated)


async def test_evc20_signals_survive_snapshot_and_restore(tmp_path):
    """EVC-20: results with their basis, deadlines and process assignment round-trip."""
    from evertree.core.cognition.tasks import TaskStore
    from evertree.core.evaluation.store import EvaluationStore

    async with component_app(tmp_path / "agent") as agent:
        planning = process_id(agent, "SelfPlanning")
        end = now()
        checked_forecast(
            agent, planning, {"mean": 0, "stddev": 1}, 2.0, calibration={"kind": "normal"}
        )
        seeded_unexpectedness(agent, planning, end - timedelta(days=10), 0.9)
        task = finished_task(
            agent,
            None,
            process=planning,
            created=end - timedelta(days=5),
            deadline=end - timedelta(days=4),
        )
        agent.tasks.assign_process(task.id, process_id(agent, "SelfTaskFraming"), reason="moved")
        evaluations = EvaluationStore.from_snapshot(agent.evaluations.snapshot())
        tasks = TaskStore.from_snapshot(agent.tasks.snapshot())
        assert evaluations.snapshot() == agent.evaluations.snapshot()
        period = around(end + timedelta(seconds=1), days=7)
        assert evaluations.get_tension_reduction(
            period, [planning]
        ) == agent.evaluations.get_tension_reduction(period, [planning])
        restored = tasks.get(task.id)
        assert restored.deadline_history == task.deadline_history
        assert restored.process_id == process_id(agent, "SelfTaskFraming")


def test_evc21_signals_never_become_learning_objectives_by_themselves():
    """EVC-21: unexpectedness is diagnostic; supervisor feedback may define an objective."""
    feedback = EvaluatedResult(
        (MetricSample("supervisor_feedback", -2.0, "supervisor_feedback_signal"),),
        ("o",),
        provenance=("o",),
    )
    signal = LearningSignal(
        feedback, LearningObjective(("supervisor_feedback",), "maximize"), {"o": -2}
    )
    assert signal.objective.metrics == ("supervisor_feedback",)
    rarity = EvaluatedResult(
        (MetricSample("prediction_unexpectedness", 0.9, "prediction_unexpectedness"),),
        ("o",),
        provenance=("o",),
    )
    with pytest.raises(ValueError):
        LearningSignal(
            rarity, LearningObjective(("prediction_unexpectedness",), "minimize"), {"o": 1}
        )


async def test_evc22_feedback_arriving_before_framing_does_not_replace_the_request(tmp_path):
    """EVC-22: framing reads the user's request even when feedback is the latest input."""
    provider = ScriptedProvider([framing(), decision(), verification()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        async with agent.events() as stream:
            state = await agent.submit("Count r in strawberry")
            agent.supervisor_feedback(
                SupervisorFeedback(-1, "Show the letters"), source_id="early", task_id=state.id
            )
            async for event in stream:
                if event.kind == "answer":
                    await agent.acknowledge_delivery(event.data["delivery_id"])
                if (
                    event.task_id == state.id
                    and event.kind.startswith("task_")
                    and event.kind != "task_started"
                ):
                    break
        assert agent.tasks.get(state.id).status == "succeeded"
        framed = provider.task_requests[0].prompt
        assert '"request": "Count r in strawberry"' in framed
        assert "Show the letters" in framed


async def test_evc23_a_reviewed_total_below_spending_extends_the_task(agent):
    """EVC-23: a budget review cannot fail a Task by proposing less than it already spent."""
    task = agent.tasks.create_task("Count", process_id=process_id(agent, "Process"))
    agent.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="initial")
    agent.tasks.record_usage(task.id, "active_time_minutes", 0.9, operation_id="spent")
    review = {"execution_budget": {"active_time_minutes": 0.5}, "self_improvement_budget": 0}
    agent._accept_frame(task, {"result": {**review, "budget_reason": "finish"}}, revise=False)
    assert task.execution_budget.resources["active_time_minutes"] == pytest.approx(1.4)


async def test_evc24_an_allowance_used_up_mid_operation_waits_for_budget_review(
    tmp_path, monkeypatch
):
    """EVC-24: exhaustion is a resumable wait, so it never becomes a failed Task outcome."""
    from evertree._application.execution import BudgetExhausted

    provider = ScriptedProvider([framing(), decision("Draft", "continue")])
    async with component_app(tmp_path / "agent", provider=provider) as agent:

        async def exhausted(state):
            raise BudgetExhausted("Consciousness must reassess the task's finite time budget")

        monkeypatch.setattr(agent, "_integrate_step", exhausted)
        result = await asyncio.wait_for(agent.run("Count r in strawberry"), 60)
        task = agent.tasks.get(result["task_id"])
        assert task.status == "waiting" and task.waiting_for == ["resume"]
        assert unexpectedness_results(agent, process_id(agent, "SelfTaskOutcome")) == []


async def test_evc25_a_timed_out_completion_check_leaves_the_task_open(tmp_path):
    """EVC-25: a provider time limit during verification is a wait, not a failed outcome."""
    from evertree.core.provider import LLMEvent

    timed_out = [LLMEvent("error", {"message": "wall-clock limit", "type": "TimeoutError"})]
    provider = ScriptedProvider([framing(), decision(), timed_out])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        result = await asyncio.wait_for(agent.run("Count r in strawberry"), 60)
        task = agent.tasks.get(result["task_id"])
        assert task.status == "waiting" and task.waiting_for == ["verification"]
        assert "wall-clock limit" in task.progress
        stats = agent.task_outcome_stats(FOREVER, ["Process"])
        assert stats["success_rate"]["denominator"] == 0 and stats["open"] == 1


async def test_evc26_cancelling_a_running_step_always_reports_the_cancellation(
    tmp_path, monkeypatch
):
    """EVC-26: a provider that ends its turn on cancel must not cut off the stop report."""
    from evertree.core.provider import LLMEvent

    class Interruptible(ScriptedProvider):
        def __init__(self, scripts):
            super().__init__(scripts)
            self.started, self.stop = asyncio.Event(), asyncio.Event()

        async def cancel(self, request_id):
            await super().cancel(request_id)
            self.stop.set()

        async def run(self, request_id, request, **kwargs):
            if (request.instructions or "").startswith("You perform one bounded"):
                self.requests.append(request)
                self.started.set()
                await self.stop.wait()
                yield LLMEvent("cancelled")
                return
            async for event in super().run(request_id, request, **kwargs):
                yield event

    provider = Interruptible([framing()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        discard = agent._discard_workspaces

        async def slow_discard(task_id=None):
            await asyncio.sleep(0.2)
            await discard(task_id)

        runtime_cancel = agent.runtime.cancel

        async def ipc_cancel(*args, **kwargs):
            # Worker IPC yields, so the step sees the provider's cancellation first.
            await asyncio.sleep(0.05)
            return await runtime_cancel(*args, **kwargs)

        monkeypatch.setattr(agent, "_discard_workspaces", slow_discard)
        monkeypatch.setattr(agent.runtime, "cancel", ipc_cancel)
        stop = agent._stop_task

        stops = []

        async def traced_stop(state, *args, **kwargs):
            stops.append("started")
            try:
                return await stop(state, *args, **kwargs)
            except BaseException:
                stops.append("interrupted")
                raise

        monkeypatch.setattr(agent, "_stop_task", traced_stop)
        async with agent.events() as stream:
            state = await agent.submit("Write a long essay")
            await asyncio.wait_for(provider.started.wait(), 30)
            await agent.cancel(state.id, reason="Withdrawn")
            kinds = []
            async with asyncio.timeout(10):
                async for event in stream:
                    if event.task_id == state.id:
                        kinds.append(event.kind)
                        if event.kind == "task_cancelled":
                            break
        assert agent.tasks.get(state.id).outcome_reason == "Withdrawn"
        assert kinds[-1] == "task_cancelled"
        assert stops == ["started"]
