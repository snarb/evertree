from dataclasses import replace

import pytest
from test_experiments import TEST_RUNTIME, dataset, prepare
from test_lifecycle_backup import change
from test_runtime import TestProcess

from evertree.core.attribution import AttributionRuntime, NormalizationRule, PropertyDefinition
from evertree.core.beliefs import BeliefStore
from evertree.core.experiments import evaluate_pair
from evertree.core.memory import TraceOutputRef


async def test_evaluation_uses_complete_isolated_semantic_state(tmp_path):
    source = """
async def run(value, ctx):
    await ctx.step('belief.read', {'target': 'claim'})
    reading = await ctx.step('attribution.normalize', {
        'property_id': 1, 'domain': 'domain', 'value': value})
    return {'result': reading['value_U']}
"""
    repo, _, branch, spec, graph, memory, learning = prepare(tmp_path, source)
    beliefs = BeliefStore()
    beliefs.register_binary("claim")
    attribution = AttributionRuntime(graph, beliefs)
    attribution.register(PropertyDefinition(1))
    attribution.register_normalization(NormalizationRule(1, "domain", mean=10, stddev=2))
    initial = (beliefs.snapshot(), attribution.snapshot())
    revision = change(branch, spec.git_path, source + "\n# candidate\n")
    experiment = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"value": 12}, 1)),
        tmp_path / "evaluation",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=TEST_RUNTIME,
        test_process_factory=TestProcess,
        beliefs=beliefs,
        attribution=attribution,
    )
    assert experiment.report.metrics == {"accuracy": 1}
    assert experiment.report.baseline_metrics == {"accuracy": 1}
    assert (beliefs.snapshot(), attribution.snapshot()) == initial


async def test_direct_evaluator_cannot_use_outcomes_available_in_memory(tmp_path):
    repo, _, branch, spec, graph, memory, learning = prepare(tmp_path)
    fixed = dataset(({"value": 1}, 1))
    fixed = replace(fixed, cases=(replace(fixed.cases[0], source_refs=(TraceOutputRef(1),)),))
    with pytest.raises(ValueError, match="accessible through agent memory"):
        await evaluate_pair(
            branch,
            spec.revision,
            spec,
            fixed,
            tmp_path / "evaluation",
            repo,
            graph,
            memory,
            learning,
            lambda _: spec,
        )
