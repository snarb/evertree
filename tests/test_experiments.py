from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest
from test_lifecycle_backup import change
from test_runtime import TestProcess, commit_programs

from evertree.core.datasets import DatasetRevision, EvaluationCase
from evertree.core.evaluation import AcceptanceCriteria, EvaluationStore, assess_candidate
from evertree.core.experiments import evaluate_pair as core_evaluate_pair
from evertree.core.graph import GraphDelta, GraphStore, Node
from evertree.core.learning import LearningStore
from evertree.core.lifecycle import ProgramLifecycleRuntime
from evertree.core.memory import TraceStore
from evertree.core.predictions import PredictionEvaluator
from evertree.core.runtime import ProgramSpec, Runtime

PATH = "src/evertree/processes/example.py"
TEST_RUNTIME = partial(Runtime, process_factory=TestProcess)


async def evaluate_pair(*args, **kwargs):
    kwargs.setdefault(
        "test_process_factory", None if kwargs.get("runtime_factory") is Runtime else TestProcess
    )
    return await core_evaluate_pair(*args, **kwargs)


def prepare(tmp_path, source="def run(value): return {'result': value}\n", helpers=None):
    repo = tmp_path / "repo"
    local_tests = """
import importlib.util
from pathlib import Path
import unittest

class EntrypointTest(unittest.TestCase):
    def test_declared_entrypoint_imports(self):
        path = Path(__file__).parents[1] / 'src/evertree/processes/example.py'
        spec = importlib.util.spec_from_file_location('example_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.run))
"""
    revision = commit_programs(
        repo, {PATH: source, "tests/test_entrypoint.py": local_tests, **(helpers or {})}
    )
    lifecycle = ProgramLifecycleRuntime(
        repo,
        tmp_path / "lifecycle",
        AcceptanceCriteria(
            ("contracts", "tests", "holdout"), target_metric="accuracy", threshold=1
        ),
    )
    branch = lifecycle.create_candidate("program", "Correct the calculation")
    graph, memory, learning = GraphStore(), TraceStore(), LearningStore()
    run = memory.start_run("seed", revision, {})
    event = memory.record(run, "seed", output={})
    graph.apply(GraphDelta(creates=(Node(1, "original"),)), provenance=memory.output_ref(event))
    memory.finish_run(run)
    learning.create_state("beta_bernoulli", state_id="known")
    return repo, lifecycle, branch, ProgramSpec("program", PATH, revision), graph, memory, learning


def dataset(*cases):
    return DatasetRevision(
        "holdout",
        "Fixed independent examples",
        "evaluation",
        tuple(
            EvaluationCase(str(index), inputs, outcome, "exact", ("source-" + str(index),))
            for index, (inputs, outcome) in enumerate(cases)
        ),
        ("accuracy",),
    )


async def test_prediction_candidates_use_fixed_proper_scores_and_weighted_cases(tmp_path):
    repo, _, branch, spec, graph, memory, learning = prepare(
        tmp_path, "def run(value): return {'result': 0.2}\n"
    )
    revision = change(branch, PATH, "def run(value): return {'result': 0.8}\n")
    fixed = DatasetRevision(
        "probabilities",
        "Independent binary outcomes",
        "evaluation",
        (
            EvaluationCase("positive", {"value": 1}, True, "prediction", ("episode-a",), weight=3),
            EvaluationCase("negative", {"value": 2}, False, "prediction", ("episode-b",)),
        ),
        ("brier", "log_loss"),
    )
    experiment = await evaluate_pair(
        branch,
        revision,
        spec,
        fixed,
        tmp_path / "evaluation",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=TEST_RUNTIME,
    )
    report = experiment.report
    assert report.metrics["brier"] == pytest.approx(0.19)
    assert report.baseline_metrics["brier"] == pytest.approx(0.49)
    assert report.metrics["log_loss"] < report.baseline_metrics["log_loss"]
    assert assess_candidate(
        criteria=AcceptanceCriteria(("contracts", "tests", "holdout"), "brier", "minimize", 0.2),
        checks=report.checks,
        candidate_metrics=report.metrics,
        baseline_metrics=report.baseline_metrics,
        independent=report.independent,
    ).verified
    assert all(
        trace["evaluation"]["outcome_ids"] for trace in experiment.traces if "evaluation" in trace
    )


async def test_infinite_prediction_score_is_retained_but_cannot_pass_acceptance(tmp_path):
    repo, _, branch, spec, graph, memory, learning = prepare(
        tmp_path, "def run(value): return {'result': 0.5}\n"
    )
    revision = change(branch, PATH, "def run(value): return {'result': 0.0}\n")
    fixed = DatasetRevision(
        "probabilities",
        "Independent binary outcomes",
        "evaluation",
        (EvaluationCase("positive", {"value": 1}, True, "prediction", ("episode-a",)),),
        ("log_loss",),
    )
    report = (
        await evaluate_pair(
            branch,
            revision,
            spec,
            fixed,
            tmp_path / "evaluation",
            repo,
            graph,
            memory,
            learning,
            lambda _: spec,
            runtime_factory=TEST_RUNTIME,
        )
    ).report
    assert "log_loss" not in report.metrics
    verification = assess_candidate(
        criteria=AcceptanceCriteria(("contracts",), "log_loss", "minimize", 1.0),
        checks=report.checks,
        candidate_metrics=report.metrics,
        baseline_metrics=report.baseline_metrics,
        independent=True,
    )
    assert not verification.verified
    assert "log_loss" in verification.missing_checks


async def test_prediction_matching_uses_isolated_memory_and_trusted_observation_ids(tmp_path):
    source = """
async def run(observations, context, ctx):
    batch = await ctx.step('evaluation.match', {
        'observations': observations, 'context': context, 'metrics': ['brier']})
    return {'result': batch['results'][0]['metric_samples'][0]['value']}
"""
    repo, _, branch, spec, graph, memory, learning = prepare(tmp_path, source)
    evaluator = PredictionEvaluator(graph, memory, EvaluationStore())
    context = {"process_id": "forecast", "subject": "unit", "episode": "episode-1"}
    prediction_run = memory.start_run("forecast", spec.revision, {})
    prediction = memory.record(prediction_run, "predict", output=0.5)
    memory.finish_run(prediction_run)
    evaluator.save_prediction(1, memory.output_ref(prediction), context)
    observation_run = memory.start_run("environment", spec.revision, {})
    observation = memory.record(
        observation_run,
        "observation",
        arguments=evaluator.project_observation(True, {1: {"value": []}}, context),
        output=True,
    )
    memory.finish_run(observation_run)
    snapshot = memory.snapshot()
    revision = change(branch, PATH, source + "\n# Candidate revision\n")
    fixed = dataset(({"observations": [observation.id], "context": context}, 0.25))
    result = await evaluate_pair(
        branch,
        revision,
        spec,
        fixed,
        tmp_path / "evaluation",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=TEST_RUNTIME,
        observation_ids=frozenset({observation.id}),
    )
    assert result.report.metrics == result.report.baseline_metrics == {"accuracy": 1.0}
    assert memory.snapshot() == snapshot


@pytest.mark.parametrize("factory", [TEST_RUNTIME, Runtime], ids=["dbos", "native"])
async def test_isolated_pair_pins_helpers_and_keeps_outcomes_hidden(tmp_path, factory):
    source = """
async def run(value, ctx):
    from evertree.common.calculation import calculate
    node = await ctx.step('graph.get', {'id': 1})
    assert node['name'] == 'original'
    await ctx.step('graph.apply', {'updates': [{'id': 1, 'changes': {'name': 'changed'}}]})
    assert await ctx.step('learning.predict', {'state_id': 'known'}) == 0.5
    answer = await ctx.step('agent.run', {'prompt': str(value), 'mode': 'exec'})
    return {'result': calculate(value) + answer['parsed']}
"""
    repo, _, branch, spec, graph, memory, learning = prepare(
        tmp_path,
        source,
        {
            "src/evertree/common/calculation.py": "def calculate(value): return value\n",
            "src/evertree/common/__init__.py": "",
        },
    )
    # Baseline helper is committed before branching so both sides can run.
    initial_helper = Path(branch.workspace) / "src/evertree/common/calculation.py"
    revision = change(
        branch, "src/evertree/common/calculation.py", "def calculate(value): return value * 2\n"
    )
    assert initial_helper.is_file()
    snapshots = graph.snapshot(), memory.snapshot(), learning.snapshot()
    prepared = []

    async def model_call(payload, context):
        assert payload == {"prompt": "3", "mode": "model"}
        assert context.graph.get(1).name == "changed"
        assert context.workspace.exists()
        prepared.append(context)
        return {"parsed": 0}

    experiment = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"value": 3}, 6)),
        tmp_path / "evaluations",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=factory,
        model_call=model_call,
    )
    assert experiment.report.baseline_metrics == {"accuracy": 0}
    assert experiment.report.metrics == {"accuracy": 1}
    assert all(experiment.report.checks.values())
    assert (graph.snapshot(), memory.snapshot(), learning.snapshot()) == snapshots
    assert len(prepared) == 2
    assert experiment.report.trace_ids


async def test_both_sides_receive_separate_full_state_and_model_context(tmp_path):
    source = """
async def run(value, ctx):
    before = await ctx.step('graph.get', {'id': 1})
    await ctx.step('graph.apply', {'updates': [{'id': 1, 'changes': {'name': 'mutated'}}]})
    await ctx.step('agent.run', {'prompt': 'input-only'})
    return {'result': before['name']}
"""
    repo, _, branch, spec, graph, memory, learning = prepare(tmp_path, source)
    revision = change(branch, PATH, source + "\n# revised\n")
    contexts = []

    async def model_call(payload, context):
        assert payload == {"prompt": "input-only", "mode": "model"}
        contexts.append(context)
        return {"parsed": True}

    experiment = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"value": 9}, "original")),
        tmp_path / "evaluations",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=TEST_RUNTIME,
        model_call=model_call,
    )
    assert experiment.report.metrics == experiment.report.baseline_metrics == {"accuracy": 1}
    assert contexts[0].graph is not contexts[1].graph
    assert contexts[0].memory is not contexts[1].memory
    assert contexts[0].learning is not contexts[1].learning
    assert contexts[0].workspace != contexts[1].workspace
    assert graph.get(1).name == "original"
    assert experiment.traces
    assert not list((tmp_path / "evaluations").iterdir())
    assert all(not context.workspace.exists() for context in contexts)


@pytest.mark.parametrize(
    "candidate_source, expected",
    [
        ("def run(value): return value\n", "Program must return"),
        (
            "async def run(value,ctx):\n await ctx.step('actions.take', {})\n return {'result': value}\n",
            "Live effects",
        ),
    ],
)
async def test_invalid_contract_or_live_effect_cannot_pass(tmp_path, candidate_source, expected):
    repo, _, branch, spec, graph, memory, learning = prepare(tmp_path)
    revision = change(branch, PATH, candidate_source)
    result = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"value": 3}, 3)),
        tmp_path / "evaluations",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=TEST_RUNTIME,
    )
    assert result.report.checks["contracts"] is False
    # The committed import test succeeds; the independent contract gate rejects the run.
    assert result.report.checks["tests"] is True
    assert not all(result.report.checks.values())
    assert expected in next(
        trace["error"] for trace in result.traces if trace.get("side") == "candidate"
    )


async def test_new_program_requires_absolute_criterion_and_static_errors_fail(tmp_path):
    repo, _, branch, spec, graph, memory, learning = prepare(tmp_path)
    new_path = "src/evertree/processes/new_program.py"
    change(branch, new_path, "def run(value): return {'result': value}\n")
    revision = change(branch, "src/evertree/common/broken.py", "def invalid(\n")
    spec = ProgramSpec(spec.program_id, new_path, revision)
    result = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"value": 3}, 3)),
        tmp_path / "evaluations",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=TEST_RUNTIME,
    )
    assert result.report.baseline_metrics is None
    assert result.report.metrics == {"accuracy": 1}
    assert result.report.checks == {"contracts": True, "tests": False, "holdout": True}


async def test_baseline_error_is_retained_without_aborting_candidate(tmp_path):
    repo, _, branch, spec, graph, memory, learning = prepare(
        tmp_path, "def run(value): raise RuntimeError('baseline failed')\n"
    )
    revision = change(branch, PATH, "def run(value): return {'result': value}\n")
    result = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"value": 3}, 3)),
        tmp_path / "evaluations",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=TEST_RUNTIME,
    )
    assert result.report.baseline_metrics == {"accuracy": 0}
    assert result.report.metrics == {"accuracy": 1}
    assert "baseline failed" in next(
        trace["error"] for trace in result.traces if trace.get("side") == "baseline"
    )


async def test_exact_holdout_cannot_certify_boolean_for_numeric_output(tmp_path):
    repo, _, branch, spec, graph, memory, learning = prepare(tmp_path)
    revision = change(branch, PATH, "def run(value): return {'result': {'nested': [True]}}\n")
    result = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"value": 3}, {"nested": [1]})),
        tmp_path / "evaluations",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=TEST_RUNTIME,
    )
    assert result.report.checks["contracts"] is True
    assert result.report.metrics == {"accuracy": 0}


async def test_nested_program_registry_is_frozen_before_either_side_executes(tmp_path):
    child_path = "src/evertree/processes/child.py"
    source = """
async def run(value, ctx):
    await ctx.step('agent.run', {'prompt': 'execution has started'})
    return await ctx.call('RegisteredChild', {'value': value})
"""
    repo, _, branch, spec, graph, memory, learning = prepare(
        tmp_path, source, {child_path: "def run(value): return {'result': value * 2}\n"}
    )
    run = memory.start_run("registry", spec.revision, {})
    event = memory.record(run, "register_child", output={})
    graph.apply(
        GraphDelta(
            creates=(
                Node(
                    2,
                    "RegisteredChild",
                    kind="program",
                    properties={"git_path": child_path, "active": True},
                ),
            )
        ),
        provenance=memory.output_ref(event),
    )
    memory.finish_run(run)
    revision = change(branch, PATH, source + "\n# candidate\n")
    execution_started = False
    resolved = []

    def resolve(identity):
        assert not execution_started, "Evaluation consulted the live registry after execution began"
        resolved.append(identity)
        return ProgramSpec(identity, child_path, spec.revision)

    async def model_call(payload, context):
        nonlocal execution_started
        execution_started = True
        return {"parsed": None}

    result = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"value": 3}, 6)),
        tmp_path / "evaluations",
        repo,
        graph,
        memory,
        learning,
        resolve,
        runtime_factory=TEST_RUNTIME,
        model_call=model_call,
    )
    assert resolved == [2]
    assert result.report.metrics == result.report.baseline_metrics == {"accuracy": 1}
    assert all(result.report.checks.values())


async def test_unsupported_evaluation_rule_rejected_before_execution(tmp_path):
    repo, _, branch, spec, graph, memory, learning = prepare(tmp_path)
    invalid = DatasetRevision(
        "d", "d", "evaluation", (EvaluationCase("c", {}, 0, "made_up", ("s",)),)
    )
    with pytest.raises(ValueError, match="fixed evaluation rule"):
        await evaluate_pair(
            branch,
            branch.base_revision,
            spec,
            invalid,
            tmp_path / "eval",
            repo,
            graph,
            memory,
            learning,
            lambda _: spec,
            runtime_factory=TEST_RUNTIME,
        )
