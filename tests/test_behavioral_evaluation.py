"""Catalog checks through fixed evaluation, isolated workers and program lifecycle.

Candidate source and provider replies are fixtures. These tests verify assessment,
activation and use, not autonomous discovery of the proposed rule.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from functools import partial

import pytest
from test_experiments import PATH, dataset, evaluate_pair, prepare
from test_lifecycle_backup import change
from test_runtime import TestProcess

from evertree.core.beliefs import BeliefStore
from evertree.core.datasets import DatasetStore, EvaluationCase
from evertree.core.evaluation import (
    NotApplicableResult,
    UnresolvedEvaluationResult,
    evaluate_prediction,
)
from evertree.core.graph import AccessView, Clause, GraphDelta, Predicate, RelationType, Slot
from evertree.core.learning import LearningBinding, LearningObjective, LearningSignal
from evertree.core.lifecycle import LifecycleError, git
from evertree.core.runtime import Runtime

WORKER_RUNTIME = partial(Runtime, process_factory=TestProcess)


def test_eva01_inapplicable_and_missing_outcomes_never_create_learning_signal():
    """EVA-01: neither unevaluated variant can masquerade as zero prediction error."""
    inapplicable = evaluate_prediction(
        0.7,
        None,
        metrics=("brier",),
        outcome_ids=(),
        provenance=("trace",),
        applicable=False,
    )
    missing = evaluate_prediction(
        0.7,
        None,
        metrics=("brier",),
        outcome_ids=(),
        provenance=("trace",),
    )
    assert isinstance(inapplicable, NotApplicableResult)
    assert isinstance(missing, UnresolvedEvaluationResult)
    for result in (inapplicable, missing):
        assert result.metrics() == {}
        with pytest.raises(ValueError, match="only use evaluated"):
            LearningSignal(result, LearningObjective(("brier",), "minimize"), {"missing": 1})


def test_eva03_binary_log_loss_is_not_entropy_subtracted():
    """EVA-03: a fair-probability forecast of an observed success has ln(2) loss."""
    losses = [
        evaluate_prediction(
            prediction,
            1,
            metrics=("log_loss",),
            outcome_ids=("actual-success",),
            provenance=("saved-prediction", "observed-success"),
        ).metrics()["log_loss"]
        for prediction in (0.5, 0.8)
    ]
    assert losses == pytest.approx([math.log(2), -math.log(0.8)])
    assert losses[0] > losses[1] > 0


@pytest.mark.parametrize("operation", ["learning.learn", "learning.coordinate"])
async def test_eva02_ready_model_cannot_change_parameters_in_isolated_state(tmp_path, operation):
    """EVA-02: isolation alone is insufficient; ready-model parameters must stay frozen."""
    repo, _, branch, spec, graph, memory, learning = prepare(
        tmp_path, "def run(signal): return {'result': 0.5}\n"
    )
    learning.register_binding(LearningBinding("coin", "known", ("brier",), subject="coin-model"))
    training_run = memory.start_run("training", spec.revision, {})
    forecast = memory.record(training_run, "forecast", output=0.5)
    outcome = memory.record(training_run, "observation", output=1)
    memory.finish_run(training_run)
    signal = LearningSignal(
        evaluate_prediction(
            0.5,
            1,
            metrics=("brier",),
            outcome_ids=("old-training-outcome",),
            provenance=(str(forecast.id), str(outcome.id)),
            subject="coin-model",
        ),
        LearningObjective(("brier",), "minimize"),
        {"old-training-outcome": 1},
    ).to_dict()
    if operation == "learning.learn":
        command = "await ctx.step('learning.learn', {'signal': signal, 'target': 'coin'})"
    else:
        command = """evaluation = await ctx.step('evaluation.predict', {
        'prediction': 0.5, 'observed': 1, 'metrics': ['brier'],
        'outcome_ids': ['old-training-outcome'], 'provenance': signal['evaluation']['provenance'],
        'subject': 'coin-model'})
    await ctx.step('learning.coordinate', {
        'evaluation_id': evaluation['id'], 'objective': signal['objective'],
        'outcome_values': signal['outcome_values'], 'target': 'coin'})"""
    source = f"""async def run(signal, ctx):
    {command}
    return {{'result': await ctx.step('learning.predict', {{'state_id': 'known'}})}}
"""
    revision = change(branch, PATH, source)
    initial = learning.snapshot()
    experiment = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"signal": signal}, 2 / 3)),
        tmp_path / "evaluation",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=WORKER_RUNTIME,
    )
    assert experiment.report.checks["contracts"] is False
    failed = next(trace for trace in experiment.traces if trace.get("side") == "candidate")
    assert "Learning is disabled" in failed["error"]
    for path in (tmp_path / "evaluation").glob("*/candidate/final-state.json"):
        assert json.loads(path.read_text())["learning"] == initial
    assert learning.snapshot() == initial


def test_lrn09_reslicing_a_seen_source_does_not_create_independent_holdout():
    """LRN-09: dataset independence follows the original history, not fragment ids."""
    store = DatasetStore()
    training = store.create(
        "Engine story",
        [
            EvaluationCase(
                "whole",
                {"prefix": "temperature 110"},
                "stopped",
                "exact",
                ("engine-history",),
            )
        ],
        purpose="training",
    )
    store.mark_training("candidate-lineage", training.revision)
    holdout = store.create(
        "Different slice",
        [
            EvaluationCase(
                "new-fragment",
                {"prefix": "temperature 110"},
                "stopped",
                "exact",
                ("engine-history",),
            )
        ],
    )
    with pytest.raises(ValueError, match="overlap"):
        store.require_holdout("candidate-lineage", holdout.revision)
    store.inherit_exposure("candidate-lineage", "refined-candidate")
    with pytest.raises(ValueError, match="overlap"):
        store.require_holdout("refined-candidate", holdout.revision)


async def test_lrn09_eva02_outcome_is_not_passed_to_model_before_prediction(tmp_path):
    """LRN-09/EVA-02: the real worker and model adapter receive only permitted case input."""
    source = """async def run(prefix, ctx):
    response = await ctx.step('agent.run', {'prompt': prefix})
    return {'result': response['parsed']}
"""
    repo, _, branch, spec, graph, memory, learning = prepare(tmp_path, source)
    revision = change(branch, PATH, source + "\n# fixed candidate\n")
    requests = []

    async def model_call(payload, context):
        assert payload == {"prompt": "temperature 110 C", "mode": "model"}
        requests.append((context.label, context.learning.snapshot()))
        return {"parsed": "stopped"}

    experiment = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"prefix": "temperature 110 C"}, "stopped")),
        tmp_path / "evaluation",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=WORKER_RUNTIME,
        model_call=model_call,
    )
    assert len(requests) == 2
    assert experiment.report.metrics == {"accuracy": 1}
    cases = [trace for trace in experiment.traces if trace.get("kind") == "case"]
    assert all(trace["inputs"] == {"prefix": "temperature 110 C"} for trace in cases)
    assert all(trace["result"] == "stopped" and trace["correct"] for trace in cases)
    assert all(any(event["type"] == "run_finished" for event in trace["events"]) for trace in cases)


@pytest.mark.parametrize("source_kind", ["event_ref", "external_source_id"])
async def test_lrn09_eva02_known_holdout_source_cannot_leak_through_initial_memory(
    tmp_path, source_kind
):
    """LRN-09/EVA-02: hidden arguments are insufficient when retrieval exposes the source."""
    source = """async def run(prefix, ctx):
    groups = await ctx.step('memory.retrieve', {'query': 'future_engine_outcome'})
    return {'result': groups[0]['events'][0]['output']}
"""
    repo, _, branch, spec, graph, memory, learning = prepare(tmp_path, source)
    run = memory.start_run("observation", "source-revision", {})
    outcome = memory.record(
        run,
        "future_engine_outcome",
        arguments={"source_id": "host-future-source"},
        output="stopped",
    )
    memory.finish_run(run)
    revision = change(branch, PATH, source + "\n# candidate can retrieve the future\n")
    store = DatasetStore()
    holdout = store.create(
        "Engine transition",
        [
            EvaluationCase(
                "engine",
                {"prefix": "temperature 110 C"},
                "stopped",
                "exact",
                (str(outcome.id) if source_kind == "event_ref" else "host-future-source",),
            )
        ],
    )
    # No training exposure was registered, but the initial memory still contains the answer.
    store.require_holdout(branch.id, holdout.revision)
    with pytest.raises(ValueError, match="initial.*memory"):
        await evaluate_pair(
            branch,
            revision,
            spec,
            holdout,
            tmp_path / "evaluation",
            repo,
            graph,
            memory,
            learning,
            lambda _: spec,
            runtime_factory=WORKER_RUNTIME,
        )


async def test_eva04_program_tests_do_not_replace_independent_evaluation(tmp_path):
    """EVA-04: the protected lifecycle refuses activation without independent evidence."""
    repo, lifecycle, branch, spec, graph, memory, learning = prepare(tmp_path)
    change(branch, PATH, "def run(value): return {'result': value * 2}\n")

    async def evaluator(candidate, actual):
        evaluated = await evaluate_pair(
            candidate,
            actual,
            spec,
            dataset(({"value": 3}, 6)),
            tmp_path / "evaluation",
            repo,
            graph,
            memory,
            learning,
            lambda _: spec,
            runtime_factory=WORKER_RUNTIME,
        )
        # Trusted evaluator marks these inspected cases as exposed during refinement.
        return replace(evaluated.report, independent=False)

    report = await lifecycle.evaluate(branch.id, evaluator)
    assert report.checks["tests"] is True
    assert report.metrics == {"accuracy": 1}
    with pytest.raises(LifecycleError, match="Acceptance checks failed"):
        await lifecycle.choose(branch.id, "merge_branch", reason="Program tests passed")
    assert git(repo, "rev-parse", "main") == branch.base_revision
    assert lifecycle.candidate(branch.id).status == "active"


async def test_eva02_belief_filtered_views_read_the_same_isolated_initial_beliefs(tmp_path):
    """EVA-02 extension: candidate and baseline must see equivalent initial belief filters."""
    source = """async def run(value, ctx):
    await ctx.step('agent.run', {'prompt': 'start evaluation'})
    matches = await ctx.step('graph.query', {
        'relation': 'VERIFIED_LABEL', 'view': 'read', 'inputs': {'subject': value}})
    belief = await ctx.step('belief.read', {'target': 'supported-label'})
    return {'result': {'labels': [match['value'] for match in matches],
                       'strength': round(belief['data']['strength'], 6)}}
"""
    repo, _, branch, spec, graph, memory, learning = prepare(tmp_path, source)
    relation = RelationType(
        graph.reserve_id(),
        "VERIFIED_LABEL",
        signature=(Slot("subject"), Slot("label", "string")),
        views=(
            AccessView(
                "read",
                ("subject",),
                ("label",),
                constraints=Predicate((Clause("strength", ">=", 0.8),)),
            ),
        ),
    )
    graph.apply(GraphDelta(creates=(relation,)), provenance="independent-context")
    fact = graph.new_fact(
        relation.id, {"subject": 1, "label": "trusted"}, belief_target="supported-label"
    )
    graph.apply(GraphDelta(creates=(fact,)), provenance="independent-context")
    beliefs = BeliefStore()
    beliefs.register_binary("supported-label")
    beliefs.assign("supported-label", "independent-check", math.log(9), backed=True)
    graph.belief_reader = beliefs.read
    revision = change(branch, PATH, source + "\n# evaluated candidate\n")
    contexts = []

    async def model_call(payload, context):
        contexts.append(context)
        if len(contexts) == 1:
            beliefs.retract("supported-label", "independent-check")
        return {"parsed": None}

    experiment = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"value": 1}, {"labels": ["trusted"], "strength": 0.9})),
        tmp_path / "evaluation",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=WORKER_RUNTIME,
        model_call=model_call,
        beliefs=beliefs,
    )
    assert experiment.report.metrics == experiment.report.baseline_metrics == {"accuracy": 1}
    assert contexts[0].beliefs is not contexts[1].beliefs
    assert contexts[0].beliefs is not beliefs
    assert beliefs.read("supported-label").strength == 0.5
