from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from evertree.core.cognition import (
    AttentionRuntime,
    TaskSpecification,
    TaskStore,
    commitment_control,
    get_task_outcome_stats,
    prepare_context,
)
from evertree.core.datasets import DatasetStore, EvaluationCase
from evertree.core.evaluation import (
    AcceptanceCriteria,
    EvaluatedResult,
    EvaluationResult,
    EvaluationStore,
    MetricGuardrail,
    MetricSample,
    NotApplicableResult,
    UnresolvedEvaluationResult,
    VerificationResult,
    assess_candidate,
    evaluate_prediction,
    exact_json_equal,
    prediction_unexpectedness,
)
from evertree.core.learning import (
    CreditRetraction,
    LearningBinding,
    LearningCoordinator,
    LearningObjective,
    LearningSignal,
    LearningStore,
    PreparedUpdate,
    UnresolvedCredit,
    UpdateBlocked,
    UpdateTransactionManager,
)


def signal(value, outcome_id="outcome-1", *, prediction=0.5, metric="brier"):
    evaluated = evaluate_prediction(
        prediction,
        value,
        metrics=(metric,),
        outcome_ids=(outcome_id,),
        provenance=("saved-prediction", "actual-observation"),
        subject="model-v1",
    )
    return LearningSignal(evaluated, LearningObjective((metric,), "minimize"), {outcome_id: value})


def learner(kind="beta_bernoulli", metric="brier", **settings):
    store = LearningStore()
    state = store.create_state(kind, **settings)
    store.register_binding(LearningBinding("target", state, (metric,), subject="model-v1"))
    return store, state, LearningCoordinator(store)


def test_typed_evaluation_variants_preserve_one_serialization_contract():
    evaluated = evaluate_prediction(
        0.5, 1, metrics=("brier",), outcome_ids=("outcome",), provenance=("trace",)
    )
    inapplicable = evaluate_prediction(
        0.5, 1, metrics=("brier",), outcome_ids=(), provenance=(), applicable=False
    )
    unresolved = evaluate_prediction(0.5, 1, metrics=("brier",), outcome_ids=(), provenance=())
    for result, expected in (
        (evaluated, EvaluatedResult),
        (inapplicable, NotApplicableResult),
        (unresolved, UnresolvedEvaluationResult),
    ):
        assert isinstance(result, expected)
        assert EvaluationResult.from_dict(result.to_dict()) == result
    with pytest.raises(ValueError, match="does not match"):
        EvaluatedResult.from_dict(unresolved.to_dict())
    legacy = EvaluationResult("unresolved", reason="Missing observation")
    assert EvaluationResult.from_dict(legacy.to_dict()).to_dict() == legacy.to_dict()


@pytest.mark.parametrize(
    "prediction, observed, equal",
    [
        (True, 1, False),
        (False, 0.0, False),
        ({"values": [True, 2]}, {"values": [1, 2]}, False),
        ({"values": [1, 2.0]}, {"values": [1.0, 2]}, True),
        ([], {}, False),
        ([1], [1, 2], False),
        (None, None, True),
        ("1", 1, False),
    ],
)
def test_exact_json_scoring_keeps_booleans_distinct(prediction, observed, equal):
    assert exact_json_equal(prediction, observed) is equal
    result = evaluate_prediction(
        prediction,
        observed,
        metrics=("exact_match",),
        outcome_ids=("outcome",),
        provenance=("trace",),
    )
    assert result.metrics()["exact_match"] == float(equal)
    assert prediction_unexpectedness(
        prediction, observed, calibration={"kind": "deterministic"}
    ) == float(not equal)


def test_budget_is_conscious_choice_and_reassessment_preserves_usage():
    tasks = TaskStore()
    task = tasks.create_task("Analyse experiment", hard_limits={"active_time_minutes": 100})
    attention = AttentionRuntime(tasks)
    with pytest.raises(ValueError, match="assign both budgets"):
        attention.admit(task.id)
    tasks.assign_budget(task.id, {"active_time_minutes": 7}, 20, reason="Small bounded experiment")
    attention.admit(task.id)
    tasks.record_usage(task.id, "active_time_minutes", 7, operation_id="segment-1")
    tasks.record_usage(task.id, "active_time_minutes", 7, operation_id="segment-1")
    assert task.spent["active_time_minutes"] == 7
    attention.release(task.id, execution_stopped=True)
    with pytest.raises(ValueError, match="reassessment"):
        attention.admit(task.id)
    tasks.assign_budget(task.id, {"active_time_minutes": 12}, 0, reason="Five more minutes suffice")
    assert task.remaining("active_time_minutes") == 5
    assert task.self_improvement_budget == 0
    with pytest.raises(ValueError, match="hard limit"):
        tasks.assign_budget(task.id, {"active_time_minutes": 101}, 0, reason="Too much")


def test_only_one_task_executes_and_false_cancellation_ack_does_not_switch():
    tasks = TaskStore()
    one, two = tasks.create_task("One"), tasks.create_task("Two")
    for task in (one, two):
        tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Quick work")
    attention = AttentionRuntime(tasks)
    attention.request_attention(one.id, 1)
    attention.request_attention(two.id, 2)
    attention.request_attention(two.id, 3)
    assert attention.next_task() == two.id
    attention.admit(one.id)
    with pytest.raises(RuntimeError, match="confirmed stopped"):
        attention.admit(two.id, stop_current=lambda _: False)
    assert attention.running_task == one.id
    attention.admit(two.id, stop_current=lambda _: True)
    assert one.status == "suspended"
    assert attention.running_task == attention.focus == two.id
    with pytest.raises(ValueError, match="execution tree"):
        tasks.finish(two.id, "cancelled", reason="Stopped", execution_stopped=False)
    tasks.finish(two.id, "cancelled", reason="Stopped", execution_stopped=True)
    attention.release(two.id, execution_stopped=True)
    with pytest.raises(ValueError, match="Completed"):
        attention.admit(two.id)


def test_nested_task_usage_is_accounted_once_at_each_owner_and_restored():
    tasks = TaskStore()
    parent = tasks.create_task("Build a skill")
    child = tasks.create_task("Evaluate candidate", parent_task_id=parent.id)
    for task in (parent, child):
        tasks.assign_budget(task.id, {"active_time_minutes": 9}, 40, reason="Selected scope")
    tasks.record_usage(
        child.id, "active_time_minutes", 2, operation_id="child-op", self_improvement=True
    )
    restored = TaskStore.from_snapshot(json.loads(json.dumps(tasks.snapshot())))
    restored.record_usage(
        child.id, "active_time_minutes", 2, operation_id="child-op", self_improvement=True
    )
    assert restored.get(parent.id).spent == {"active_time_minutes": 2}
    assert restored.get(child.id).self_improvement_spent == {"active_time_minutes": 2}
    assert restored.get(child.id).remaining(
        "active_time_minutes", self_improvement=True
    ) == pytest.approx(1.6)


def test_context_keeps_complete_latest_input_and_exact_sources():
    tasks = TaskStore()
    task = tasks.create_task(
        TaskSpecification("Join previous parts and count r", source_ids=("request",))
    )
    latest = "Join the two previous messages without spaces and count r. " * 500
    context = prepare_context(
        task,
        "dialogue",
        latest,
        messages=(
            {"role": "user", "content": "straw", "source_id": "part-a"},
            {"role": "user", "content": "berry", "source_id": "part-b"},
        ),
        source_ids=("part-a", "part-b"),
    )
    assert context.incoming == latest
    assert context.source_ids == ("request", "part-a", "part-b")
    assert "".join(message["content"] for message in context.messages).count("r") == 3
    with pytest.raises(TypeError):
        context.messages[0]["content"] = "changed"


def test_success_requires_verification_and_failed_verification_escalates():
    tasks = TaskStore()
    task = tasks.create_task("Deliver result")
    with pytest.raises(ValueError, match="verified"):
        tasks.finish(task.id, "succeeded", reason="Program exited", execution_stopped=True)
    decision = commitment_control(verified=VerificationResult("failed"), familiar=True)
    assert decision.mode == "consciousness_selection"
    tasks.finish(
        task.id,
        "succeeded",
        reason="Objective verified",
        execution_stopped=True,
        verification=VerificationResult("verified"),
    )


def test_dataset_versions_frozen_and_leakage_tracks_sources_across_revisions():
    store = DatasetStore()
    case = EvaluationCase("case", {"x": [1]}, 2, "exact_match", ("episode-1",), "family-a")
    train = store.create("train", [case], purpose="training")
    holdout_case = EvaluationCase(
        "other-case", {"x": [2]}, 4, "exact_match", ("episode-2",), "family-a"
    )
    holdout = store.create("holdout", [holdout_case])
    store.mark_training("candidate-lineage", train.revision)
    with pytest.raises(ValueError, match="overlap"):
        store.require_holdout("candidate-lineage", holdout.revision)
    store.inherit_exposure("candidate-lineage", "new-revision")
    with pytest.raises(ValueError, match="overlap"):
        store.require_holdout("new-revision", holdout.revision)
    with pytest.raises(TypeError):
        case.inputs["x"] = (5,)
    original = train.revision
    next_version = store.create(
        "train", [holdout_case], purpose="training", dataset_id=train.dataset_id
    )
    assert store.get(original).cases == (case,)
    assert store.latest(train.dataset_id) == next_version
    assert (
        DatasetStore.from_snapshot(json.loads(json.dumps(store.snapshot()))).get(original).revision
        == original
    )
    assert "outcomes" not in case.program_inputs()


def test_prediction_metrics_do_not_fabricate_calibration():
    result = evaluate_prediction(
        0.8,
        0,
        metrics=("brier", "prediction_unexpectedness"),
        outcome_ids=("o",),
        provenance=("p",),
    )
    assert result.status == "evaluated"
    assert result.metrics() == {"brier": pytest.approx(0.64)}
    assert "prediction_unexpectedness" in result.skipped_metrics
    unresolved = evaluate_prediction(
        0.8, 0, metrics=("prediction_unexpectedness",), outcome_ids=("o",), provenance=("p",)
    )
    assert unresolved.status == "unresolved"
    with pytest.raises(ValueError, match="evaluated"):
        LearningSignal(
            unresolved, LearningObjective(("prediction_unexpectedness",), "minimize"), {"o": 0}
        )


def test_discrete_rarity_handles_ties_and_empirical_finite_sample_bound():
    # Fair coin: either equally likely outcome is wholly ordinary under the norm.
    assert prediction_unexpectedness(0.5, 0, calibration={"kind": "bernoulli"}) == 0
    assert prediction_unexpectedness(0.9, 0, calibration={"kind": "bernoulli"}) == pytest.approx(
        0.9
    )
    assert (
        prediction_unexpectedness(
            0,
            100,
            calibration={
                "kind": "empirical_rank",
                "exchangeable": True,
                "reference_scores": [1, 2, 3],
            },
        )
        == 0.75
    )
    assert (
        prediction_unexpectedness({"mean": 0, "stddev": 1}, 0, calibration={"kind": "normal"}) == 0
    )
    with pytest.raises(ValueError, match="exchangeability"):
        prediction_unexpectedness(
            0, 100, calibration={"kind": "empirical_rank", "reference_scores": [1]}
        )


def test_zero_probability_logloss_records_infinity_without_clipping():
    result = evaluate_prediction(
        0, 1, metrics=("log_loss", "brier"), outcome_ids=("o",), provenance=("p",)
    )
    assert result.metrics()["log_loss"] == {"kind": "positive_infinity"}
    json.dumps(result.to_dict(), allow_nan=False)


def test_acceptance_never_treats_missing_check_or_metric_as_success():
    criteria = AcceptanceCriteria(
        ("contracts", "regressions"),
        "score",
        threshold=0.8,
        guardrails=(MetricGuardrail("cost", "minimize", max_regression=0),),
    )
    common = {
        "criteria": criteria,
        "candidate_metrics": {"score": 0.9, "cost": 4},
        "baseline_metrics": {"score": 0.8, "cost": 4},
        "independent": True,
    }
    assert assess_candidate(checks={"contracts": True}, **common).status == "need_checks"
    assert assess_candidate(checks={"contracts": True, "regressions": True}, **common).verified
    assert (
        assess_candidate(checks={"contracts": True, "regressions": False}, **common).status
        == "failed"
    )
    common["candidate_metrics"] = {"score": 0.95, "cost": 5}
    assert (
        assess_candidate(checks={"contracts": True, "regressions": True}, **common).status
        == "failed"
    )


def test_uncertain_improvement_cannot_pass_by_point_estimate():
    result = assess_candidate(
        criteria=AcceptanceCriteria(("test",), "score"),
        checks={"test": True},
        candidate_metrics={"score": 0.9},
        baseline_metrics={"score": 0.8},
        independent=True,
        uncertainty={"score": (-0.1, 0.3)},
    )
    assert not result.verified


def test_learning_prior_is_not_observed_and_updates_use_outcome():
    store, state, coordinator = learner()
    assert store.predict(state) == 0.5
    assert store.statistics(state)["observed_count"] == 0
    assert store.statistics(state)["probability"] is None
    receipt = coordinator.learn(signal(1), "target")
    assert receipt.status == "applied"
    assert store.predict(state) == pytest.approx(2 / 3)
    assert store.statistics(state)["probability"] == 1


def test_retry_and_new_evaluation_of_same_experience_do_not_duplicate_learning():
    store, state, coordinator = learner()
    credit = coordinator.credit_assignment.assign("target", signal(1))
    prepared = coordinator.planner.prepare(credit)
    assert isinstance(prepared, PreparedUpdate)
    receipt = coordinator.transactions.apply(prepared)
    assert coordinator.transactions.apply(prepared) == receipt
    repeated = coordinator.learn(signal(1), "target")
    assert isinstance(repeated, UpdateBlocked) and repeated.reason == "already_accounted"
    assert store.statistics(state)["observed_count"] == 1
    restored = LearningStore.from_snapshot(json.loads(json.dumps(store.snapshot())))
    assert UpdateTransactionManager(restored).apply(prepared) == receipt
    assert restored.statistics(state)["observed_count"] == 1


def test_two_prepared_requests_racing_for_same_outcome_only_apply_once():
    store, state, coordinator = learner()
    one = coordinator.planner.prepare(coordinator.credit_assignment.assign("target", signal(1)))
    two = coordinator.planner.prepare(coordinator.credit_assignment.assign("target", signal(1)))
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(
            executor.map(lambda value: coordinator.transactions.apply(value).status, (one, two))
        )
    assert sorted(statuses) == ["applied", "rejected"]
    assert store.statistics(state)["observed_count"] == 1


def test_missing_prediction_and_ambiguous_credit_do_not_update():
    store, state, coordinator = learner()
    missing = coordinator.missing_prediction("target", ("o",))
    assert missing.reason == "missing_prediction" and missing.signal is None
    unresolved = coordinator.learn(signal(1), "target", ambiguous=True)
    assert isinstance(unresolved, UnresolvedCredit)
    assert unresolved.reason == "ambiguous_attribution"
    with pytest.raises(TypeError):
        coordinator.planner.prepare(missing)
    assert store.statistics(state)["observed_count"] == 0


def test_binding_target_match_does_not_update_another_model():
    store, state, coordinator = learner()
    second = store.create_state("beta_bernoulli")
    store.register_binding(LearningBinding("target", second, ("brier",), subject="another-model"))
    coordinator.learn(signal(1), "target")
    assert store.statistics(second)["observed_count"] == 0
    assert store.statistics(state)["observed_count"] == 1


def test_atomic_failure_rolls_back_state_ledger_and_receipt():
    store, _state, coordinator = learner()
    prepared = coordinator.planner.prepare(
        coordinator.credit_assignment.assign("target", signal(1))
    )
    original = store.dispatcher.get("beta_bernoulli")
    calls = 0

    class BrokenUpdater:
        def apply(self, parameters, data, settings):
            nonlocal calls
            calls += 1
            if calls == 1:  # The protected planner compatibility check succeeds.
                return original.apply(parameters, data, settings)
            parameters["positive"] = 999
            raise RuntimeError("Optimizer failed")

    store.dispatcher.register("beta_bernoulli", BrokenUpdater())
    before = store.snapshot()
    with pytest.raises(RuntimeError, match="Optimizer failed"):
        coordinator.transactions.apply(prepared)
    assert store.snapshot() == before


def test_request_identity_cannot_be_reused_with_different_contents():
    _store, _state, coordinator = learner()
    credit = coordinator.credit_assignment.assign("target", signal(1))
    prepared = coordinator.planner.prepare(credit)
    coordinator.transactions.apply(prepared)
    other = replace(prepared, state="different-state")
    with pytest.raises(ValueError, match="identity reused"):
        coordinator.transactions.apply(other)


def test_exact_retraction_keeps_history_and_does_not_touch_other_state():
    store, state, coordinator = learner("mean", "squared_error")
    first = coordinator.credit_assignment.assign(
        "target", signal(2, prediction=0, metric="squared_error")
    )
    second = coordinator.credit_assignment.assign(
        "target", signal(4, "outcome-2", prediction=0, metric="squared_error")
    )
    for credit in (first, second):
        coordinator.transactions.apply(coordinator.planner.prepare(credit))
    assert store.predict(state) == 3
    retraction = CreditRetraction(first, state)
    receipt = coordinator.transactions.retract(retraction)
    assert receipt.status == "retracted"
    assert store.predict(state) == 4
    assert coordinator.transactions.retract(retraction) == receipt
    assert store.statistics(state)["observed_count"] == 1


def test_unsupported_retraction_reports_skipped_not_fake_success():
    store, state, coordinator = learner("linear_regression", "squared_error", dimension=1)
    credit = coordinator.credit_assignment.assign(
        "target", signal(3, prediction=0, metric="squared_error"), context={"features": [2]}
    )
    coordinator.transactions.apply(coordinator.planner.prepare(credit))
    assert store.predict(state, [2]) > 0
    receipt = coordinator.transactions.retract(CreditRetraction(credit, state))
    assert receipt.status == "skipped" and receipt.reason == "unsupported_retraction"
    assert store.statistics(state)["observed_count"] == 1


def test_retracted_experience_is_not_relearned_until_explicitly_corrected():
    store, state, coordinator = learner()
    credit = coordinator.credit_assignment.assign("target", signal(1, "bad-observation"))
    coordinator.transactions.apply(coordinator.planner.prepare(credit))
    coordinator.transactions.retract(CreditRetraction(credit, state))
    repeated = coordinator.learn(signal(1, "bad-observation"), "target")
    assert isinstance(repeated, UpdateBlocked)
    corrected = coordinator.learn(
        signal(0, "correct-observation"),
        "target",
        context={"correction_of": {"correct-observation": "bad-observation"}},
    )
    assert corrected.status == "applied"
    assert store.statistics(state)["observed_count"] == 1
    assert store.predict(state) == pytest.approx(1 / 3)


def test_tension_uses_process_means_and_same_comparable_processes():
    store = EvaluationStore()
    for process, day, scores in (
        ("A", 1, [0.9]),
        ("A", 2, [0.3] * 5),
        ("B", 1, [0.2]),
        ("B", 2, [0.6]),
    ):
        for index, value in enumerate(scores):
            identity = f"{process}-{day}-{index}"
            store.add(
                EvaluationResult(
                    "evaluated",
                    (
                        MetricSample(
                            "prediction_unexpectedness", value, "prediction_unexpectedness"
                        ),
                    ),
                    (identity,),
                    evaluated_subject=identity,
                    provenance=(identity,),
                    process_id=process,
                    observed_at=f"2026-01-0{day}T12:00:00+00:00",
                    comparison_key="fixed-calibration",
                )
            )
    result = store.get_tension_reduction(
        ("2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"),
        ["root"],
        descendants={"root": ["A", "B", "missing"]},
    )
    assert result["value"] == pytest.approx(0.1)  # (.6 + -.4) / 2, not observation weighted.
    assert "missing" in result["skipped"]
    assert result["by_process"]["A"]["after_count"] == 5


def test_task_outcome_stats_include_open_overdue_but_not_early_cancellation():
    tasks = TaskStore()
    overdue = tasks.create_task("Overdue", process_id="P", deadline="2026-01-02T00:00:00Z")
    cancelled = tasks.create_task("Cancelled", process_id="P", deadline="2026-01-02T00:00:00Z")
    success = tasks.create_task("Success", process_id="P", deadline="2026-01-02T00:00:00Z")
    for task in (overdue, cancelled, success):
        task.created_at = "2026-01-01T00:00:00Z"
    tasks.finish(
        cancelled.id,
        "cancelled",
        reason="Obligation withdrawn",
        execution_stopped=True,
        completed_at="2026-01-01T12:00:00Z",
    )
    tasks.finish(
        success.id,
        "succeeded",
        reason="Verified",
        execution_stopped=True,
        verification=VerificationResult("verified"),
        completed_at="2026-01-01T12:00:00Z",
    )
    stats = get_task_outcome_stats(
        tasks.all(), ("2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z"), ["P"]
    )
    assert stats["on_time_rate"] == {"value": 0.5, "numerator": 1, "denominator": 2}
    assert stats["success_rate"]["value"] == 1
    assert stats["open"] == 1
    assert stats["cancelled"] == 1
