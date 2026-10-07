from __future__ import annotations

from pathlib import Path

import pytest

from evertree.core.evaluation import EvaluationStore
from evertree.core.graph import GraphDelta, Node
from evertree.core.predictions import PredictionEvaluator
from evertree.core.runtime import ProgramSpec
from tests.support.evaluation import dataset
from tests.support.experiments import PATH, TEST_RUNTIME, evaluate_pair, prepare
from tests.support.lifecycle_backup import change


async def test_prediction_matching_uses_isolated_memory_and_trusted_observation_ids(tmp_path):
    """Run exact committed candidates through real workers to verify evaluation boundaries."""
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


@pytest.mark.parametrize("factory", [TEST_RUNTIME], ids=["dbos"])
async def test_isolated_pair_pins_helpers_and_keeps_outcomes_hidden(tmp_path, factory):
    """Run exact committed candidates through real workers to verify evaluation boundaries."""
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
    """Run exact committed candidates through real workers to verify evaluation boundaries."""
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
    """Run exact committed candidates through real workers to verify evaluation boundaries."""
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
    """Run exact committed candidates through real workers to verify evaluation boundaries."""
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
    """Run exact committed candidates through real workers to verify evaluation boundaries."""
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


async def test_nested_program_registry_is_frozen_before_either_side_executes(tmp_path):
    """Run exact committed candidates through real workers to verify evaluation boundaries."""
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
