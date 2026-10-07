from __future__ import annotations

import math
from dataclasses import replace
from functools import partial

import pytest

from evertree.core.beliefs import BeliefStore
from evertree.core.evaluation import (
    evaluate_prediction,
)
from evertree.core.graph import AccessView, Clause, GraphDelta, Predicate, RelationType, Slot
from evertree.core.learning import LearningBinding, LearningObjective, LearningSignal, LearningStore
from evertree.core.programs.lifecycle import LifecycleError, git
from evertree.core.runtime import Runtime
from tests.support.evaluation import dataset
from tests.support.experiments import PATH, evaluate_pair, prepare
from tests.support.lifecycle_backup import change
from tests.support.runtime import TestProcess

WORKER_RUNTIME = partial(Runtime, process_factory=TestProcess)


@pytest.mark.parametrize("operation", ["learning.learn", "learning.coordinate"])
async def test_eva02_ready_model_cannot_change_parameters_in_isolated_state(
    tmp_path, operation, monkeypatch
):
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
    isolated = []
    from_snapshot = LearningStore.from_snapshot

    def capture(snapshot):
        state = from_snapshot(snapshot)
        isolated.append(state)
        return state

    monkeypatch.setattr(LearningStore, "from_snapshot", capture)
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
    assert len(isolated) == 2
    assert all(state.snapshot() == initial for state in isolated)
    assert not list((tmp_path / "evaluation").iterdir())
    assert learning.snapshot() == initial


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
