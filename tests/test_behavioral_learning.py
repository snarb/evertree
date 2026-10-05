"""Behavioral learning catalog: real estimators, credit and transaction boundaries."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from evertree.core.evaluation import (
    EvaluatedResult,
    EvaluationStore,
    MetricSample,
    SupervisorFeedback,
    evaluate_prediction,
)
from evertree.core.graph import GraphDelta, GraphStore, Node
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
from evertree.core.memory import TraceStore
from evertree.core.predictions import PredictionEvaluator


def measured(value, identity, *, subject="A", prediction=0):
    evaluation = evaluate_prediction(
        prediction,
        value,
        metrics=("squared_error",),
        outcome_ids=(identity,),
        provenance=("prediction:" + identity, "observation:" + identity),
        subject=subject,
    )
    return LearningSignal(
        evaluation, LearningObjective(("squared_error",), "minimize"), {identity: value}
    )


def mean_learner():
    store = LearningStore()
    state = store.create_state("mean", state_id="shared", prior=0)
    store.register_binding(LearningBinding("duration", state, ("squared_error",), subject="A"))
    coordinator = LearningCoordinator(store)
    for index in range(2):
        assert coordinator.learn(measured(10, f"initial-{index}"), "duration").status == "applied"
    return store, state, coordinator


def prepared(coordinator, value=20, identity="new-observation", *, subject="A"):
    credit = coordinator.credit_assignment.assign(
        "duration", measured(value, identity, subject=subject)
    )
    update = coordinator.planner.prepare(credit)
    assert isinstance(update, PreparedUpdate)
    return update


def test_lrn03_shared_state_transfers_learning_without_changing_local_state():
    """LRN-03: declared shared bindings, not just equal parameter values, transfer learning."""
    store, state, coordinator = mean_learner()
    store.register_binding(LearningBinding("duration", state, ("squared_error",), subject="B"))
    local = store.create_state("mean", state_id="C", prior=10)
    store.register_binding(LearningBinding("duration", local, ("squared_error",), subject="C"))
    local_before = store.state(local)

    assert coordinator.learn(measured(20, "observed-by-A"), "duration").status == "applied"
    bindings = {binding["subject"]: binding["state"] for binding in store.snapshot()["bindings"]}
    assert store.predict(bindings["A"]) == pytest.approx(40 / 3)
    assert store.predict(bindings["B"]) == pytest.approx(40 / 3)
    assert store.predict(bindings["C"]) == 10
    assert store.state(local) == local_before
    ledger = store.snapshot()["ledger"]
    assert any(entry["sample"]["outcome_id"] == "observed-by-A" for entry in ledger.values())


def test_lrn10_evaluation_does_not_train_or_rewrite_saved_prediction():
    """LRN-10: evaluation is separate from the explicitly invoked learning pipeline."""
    store = LearningStore()
    state = store.create_state("beta_bernoulli", alpha=7, beta=3)
    before = store.snapshot()
    graph, memory, evaluations = GraphStore(), TraceStore(), EvaluationStore()
    target = Node(graph.reserve_id(), "success")
    graph.apply(GraphDelta(creates=(target,)), provenance="target-contract")
    evaluator = PredictionEvaluator(graph, memory, evaluations)
    context = {"process_id": "trial", "subject": "unit", "episode": "trial-1"}
    run = memory.start_run("model", "v1", {})
    forecast = memory.record(run, "forecast", output=store.predict(state))
    memory.finish_run(run)
    evaluator.save_prediction(target.id, memory.output_ref(forecast), context)
    observed_run = memory.start_run("sensor", "v1", {})
    observation = memory.record(
        observed_run,
        "observation",
        arguments=evaluator.project_observation(1, {target.id: {"value": []}}, context),
        output=1,
    )
    memory.finish_run(observed_run)
    batch = evaluator.evaluate([observation.id], context, ["brier"])
    assert batch["unmatched"] == [] and len(batch["results"]) == 1
    result = evaluations.get(batch["results"][0]["id"])
    assert result.metrics()["brier"] == pytest.approx(0.09)
    assert result.outcome_ids == (str(observation.id),)
    assert str(forecast.id) in result.provenance
    assert memory.resolve(memory.output_ref(forecast)) == 0.7
    assert store.snapshot() == before
    assert not store.snapshot()["receipts"]


def test_lrn11_credit_updates_only_participating_estimator():
    """LRN-11: matching target names do not authorize updating every estimator."""
    store, state, coordinator = mean_learner()
    other = store.create_state("mean", state_id="other-model", prior=10)
    store.register_binding(LearningBinding("duration", other, ("squared_error",), subject="B"))
    other_before = store.state(other)
    memory = TraceStore()
    run = memory.start_run("A", "revision-A", {})
    forecast = memory.record(run, "forecast", output=store.predict(state))
    memory.finish_run(run)
    original_event = memory.get_event(forecast.id)
    update = prepared(coordinator)

    assert update.state == state
    assert update.source_credit.signal.evaluation.evaluated_subject == "A"
    assert coordinator.transactions.apply(update).status == "applied"
    assert store.state(other) == other_before
    assert memory.get_event(forecast.id) == original_event
    assert memory.resolve(memory.output_ref(forecast)) == 10
    assert store.predict(state) == pytest.approx(40 / 3)


def test_lrn12_ambiguous_attribution_preserves_signal_without_arbitrary_weights():
    """LRN-12: two simultaneous changes are not silently assigned 50/50 credit."""
    store, _, coordinator = mean_learner()
    other = store.create_state("mean", state_id="segmentation", prior=0)
    store.register_binding(LearningBinding("segmentation", other, ("squared_error",)))
    signal = measured(20, "improved-combined-result")
    before = store.snapshot()
    unresolved = [
        coordinator.learn(signal, target, ambiguous=True) for target in ("duration", "segmentation")
    ]
    assert all(isinstance(item, UnresolvedCredit) for item in unresolved)
    assert all(item.reason == "ambiguous_attribution" for item in unresolved)
    assert all(item.signal is signal for item in unresolved)
    after = store.snapshot()
    for key in ("states", "credits", "ledger", "receipts"):
        assert after[key] == before[key]
    with pytest.raises(TypeError, match="Unresolved"):
        coordinator.planner.prepare(unresolved[0])


def test_lrn13_missing_binding_preserves_resolved_semantic_credit():
    """LRN-13: missing update wiring is not uncertain attribution."""
    store = LearningStore()
    store.create_state("mean", prior=0)
    coordinator = LearningCoordinator(store)
    states = store.snapshot()["states"]
    result = coordinator.learn(measured(20, "outcome"), "duration")
    assert isinstance(result, UpdateBlocked)
    assert result.reason == "no_learning_binding"
    assert result.source_credit.target == "duration"
    assert store.snapshot()["credits"] == [result.source_credit.to_dict()]
    assert not store.snapshot()["unresolved"]
    assert store.snapshot()["states"] == states


def test_lrn14_retry_returns_original_receipt_even_after_backup_restore():
    """LRN-14: one operation contributes once, including retry after restoration."""
    store, state, coordinator = mean_learner()
    update = prepared(coordinator)
    first = coordinator.transactions.apply(update)
    before_retry = store.snapshot()
    assert coordinator.transactions.apply(update) == first
    assert store.snapshot() == before_retry
    restored = LearningStore.from_snapshot(json.loads(json.dumps(before_retry)))
    assert UpdateTransactionManager(restored).apply(update) == first
    params = restored.state(state)["parameters"]
    assert (params["sum"], params["observed_count"]) == (40, 3)
    assert restored.snapshot() == before_retry


def test_lrn15_distinct_concurrent_requests_cannot_count_one_outcome_twice():
    """LRN-15: duplicate experience is protected inside the transaction, not just planning."""
    store, state, coordinator = mean_learner()
    requests = [prepared(coordinator) for _ in range(2)]
    assert requests[0].id != requests[1].id
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(coordinator.transactions.apply, requests))
    assert sorted(receipt.status for receipt in receipts) == ["applied", "rejected"]
    assert (
        next(item for item in receipts if item.status == "rejected").reason == "already_accounted"
    )
    params = store.state(state)["parameters"]
    assert (params["sum"], params["observed_count"]) == (40, 3)


def test_lrn16_correction_replaces_wrong_value_and_preserves_history():
    """LRN-16: correcting 100 to 20 leaves two observations, not three."""
    store = LearningStore()
    state = store.create_state("mean", state_id="mean", prior=0)
    store.register_binding(LearningBinding("duration", state, ("squared_error",)))
    coordinator = LearningCoordinator(store)
    coordinator.learn(measured(10, "good"), "duration")
    wrong = prepared(coordinator, 100, "wrong")
    applied = coordinator.transactions.apply(wrong)
    retraction = CreditRetraction(wrong.source_credit, state)
    retracted = coordinator.transactions.retract(retraction)
    corrected = coordinator.learn(
        measured(20, "corrected"), "duration", context={"correction_of": {"corrected": "wrong"}}
    )
    assert retracted.status == "retracted" and corrected.status == "applied"
    assert store.predict(state) == 15
    params = store.state(state)["parameters"]
    assert (params["sum"], params["observed_count"]) == (30, 2)
    snapshot = store.snapshot()
    assert snapshot["receipts"][applied.request_id] == applied.to_dict()
    assert snapshot["receipts"][retraction.id]["status"] == "retracted"
    correction = next(
        entry
        for entry in snapshot["ledger"].values()
        if entry["sample"]["outcome_id"] == "corrected"
    )
    assert correction["previous"]["status"] == "retracted"
    assert correction["previous"]["sample"]["value"] == 100
    replay = coordinator.learn(measured(100, "wrong"), "duration")
    assert isinstance(replay, UpdateBlocked) and replay.reason == "already_accounted"
    assert store.predict(state) == 15


@pytest.mark.parametrize("operation", ["apply", "retract"])
def test_lrn17_commit_failure_restores_state_ledger_receipt_and_retry(operation, monkeypatch):
    """LRN-17: fail after authoritative writes, not merely inside the updater."""
    store, state, coordinator = mean_learner()
    update = prepared(coordinator)
    if operation == "retract":
        coordinator.transactions.apply(update)
        request = CreditRetraction(update.source_credit, state)
    else:
        request = update
    before = store.snapshot()
    original = coordinator.transactions._receipt

    def fail_after_receipt(*args, **kwargs):
        original(*args, **kwargs)
        assert store.state(state) != before["states"][state]
        raise RuntimeError("Injected failure before transaction completes")

    monkeypatch.setattr(coordinator.transactions, "_receipt", fail_after_receipt)
    with pytest.raises(RuntimeError, match="Injected failure"):
        getattr(coordinator.transactions, operation)(request)
    assert store.snapshot() == before
    monkeypatch.setattr(coordinator.transactions, "_receipt", original)
    receipt = getattr(coordinator.transactions, operation)(request)
    assert receipt.status == ("applied" if operation == "apply" else "retracted")
    params = store.state(state)["parameters"]
    assert (params["sum"], params["observed_count"]) == (
        (40, 3) if operation == "apply" else (20, 2)
    )
    assert getattr(coordinator.transactions, operation)(request) == receipt


@pytest.mark.parametrize("operation", ["rejected", "skipped"])
def test_lrn17_nonchanging_receipt_and_retry_identity_are_atomic(operation, monkeypatch):
    """LRN-17: rejected/skipped updates also preserve the receipt/identity invariant."""
    store, state, coordinator = mean_learner()
    update = prepared(coordinator)
    if operation == "rejected":
        request = replace(update, state="missing-state")
        execute = coordinator.transactions.apply
    else:
        request = CreditRetraction(update.source_credit, state)
        execute = coordinator.transactions.retract
    before = store.snapshot()

    class FailOnce(dict):
        failed = False

        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if not self.failed:
                self.failed = True
                raise RuntimeError("Injected fingerprint write failure")

    monkeypatch.setattr(store, "_requests", FailOnce(store._requests))
    with pytest.raises(RuntimeError, match="fingerprint write"):
        execute(request)
    assert store.snapshot() == before
    receipt = execute(request)
    assert receipt.status == operation
    assert execute(request) == receipt


@pytest.mark.parametrize("ambiguous", [False, True])
def test_int05_supervisor_comment_does_not_become_numeric_outcome(ambiguous):
    """INT-05, contract coverage: explicit format attribution; cause discovery is not supplied."""
    feedback = SupervisorFeedback(-2, "Data are correct, but the answer exceeds the length limit")
    memory = TraceStore()
    run = memory.start_run("supervisor", "external-v1", {})
    event = memory.record(run, "feedback", output=feedback.to_dict())
    memory.finish_run(run)
    evaluation = EvaluatedResult(
        (MetricSample("supervisor_feedback", feedback.value, "supervisor_feedback_signal"),),
        (str(event.id),),
        evaluated_subject="formatting",
        provenance=(str(event.id),),
    )
    signal = LearningSignal(
        evaluation,
        LearningObjective(("supervisor_feedback",), "maximize"),
        {str(event.id): feedback.value},
    )
    store = LearningStore()
    state = store.create_state("mean", prior=0)
    store.register_binding(
        LearningBinding(
            "format_compliance",
            state,
            ("supervisor_feedback",),
            "maximize",
            "formatting",
        )
    )
    result = LearningCoordinator(store).learn(signal, "format_compliance", ambiguous=ambiguous)
    assert memory.resolve(memory.output_ref(event)) == feedback.to_dict()
    if ambiguous:
        assert isinstance(result, UnresolvedCredit)
        assert store.statistics(state)["observed_count"] == 0
    else:
        assert result.status == "applied"
        assert store.predict(state) == -2
        entry = next(iter(store.snapshot()["ledger"].values()))
        assert entry["sample"]["value"] == -2
