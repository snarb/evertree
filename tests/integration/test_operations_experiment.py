from dataclasses import replace

import pytest

from evertree.core.attribution import AttributionRuntime, NormalizationRule, PropertyDefinition
from evertree.core.beliefs import BeliefStore
from evertree.core.graph.store import GraphStore
from evertree.core.graph.types import GraphDelta, Instance, Node, Prototype
from evertree.core.memory.types import TraceOutputRef
from evertree.core.programs.experiments import evaluate_pair
from tests.support.evaluation import dataset
from tests.support.experiments import TEST_RUNTIME, prepare
from tests.support.lifecycle_backup import change
from tests.support.runtime import TestProcess


async def test_evaluation_uses_complete_isolated_semantic_state(tmp_path):
    """Real workers verify the evaluation gateway exposes only isolated semantic state."""
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
    """Real workers verify the evaluation gateway exposes only isolated semantic state."""
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


async def test_population_read_uses_stored_sources_and_beliefs_in_worker_snapshot(tmp_path):
    """Real worker IPC and snapshot restoration preserve population, guide and table readings."""
    source = """
from evertree.core.semantics.api import summarize_property

async def run(value, ctx):
    report = await summarize_property(ctx, 'Dog', 'Body mass', value=value, unit='kg')
    observed = report['observations']
    guide = next(item for item in report['references'] if item['reference_kind'] == 'bands')
    table = next(item for item in report['references'] if item['reference_kind'] == 'distribution')
    return {'result': {
        'observed_mean': observed['mean'], 'observed_count': observed['count'],
        'guide_class': guide['interpretation']['class']['name'],
        'table_mean': table['summary']['mean'], 'table_count': table['summary']['count'],
        'source_retained': bool(guide['source']['provenance']['event_ref']),
        'measurement_assessed': observed['items'][0]['belief_status'] == 'assessed',
        'reference_assessed': table['belief_status'] == 'assessed',
        'reference_support': table['belief_data']['support'],
        'time_basis': report['time_basis'],
    }}
"""
    repo, _, branch, spec, _graph, memory, learning = prepare(tmp_path, source)
    graph = GraphStore()
    graph.bootstrap(provenance=memory.output_ref(1))
    run = memory.start_run("source reports", spec.revision, {})
    report = memory.record(
        run,
        "observation",
        output={"masses": [5, 15, 40], "guide": [10, 25], "table": [[10, 2], [20, 2]]},
    )
    memory.finish_run(run)
    provenance = memory.output_ref(report)
    domain = Prototype(graph.reserve_id(), "Dog")
    prop = Node(
        graph.reserve_id(),
        "Body mass",
        kind="property",
        properties={"attribution": {"unit": "kg", "applies_to": [domain.id]}},
    )
    dogs = tuple(Instance(graph.reserve_id(), f"Dog {index}") for index in range(3))
    classes = tuple(Node(graph.reserve_id(), name) for name in ("Small", "Medium", "Large"))
    common = {
        "property": prop.id,
        "domain": domain.id,
        "unit": "kg",
        "conditions": {},
    }
    guide = Node(
        graph.reserve_id(),
        "Dog guide",
        properties={
            "numeric_reference": {
                **common,
                "reference_kind": "bands",
                "boundaries": [10, 25],
                "classes": [node.id for node in classes],
                "samples": [],
            }
        },
    )
    table = Node(
        graph.reserve_id(),
        "Dog census",
        properties={
            "numeric_reference": {
                **common,
                "reference_kind": "distribution",
                "boundaries": [],
                "classes": [],
                "samples": [{"lower": value, "upper": value, "count": 2} for value in (10, 20)],
            }
        },
    )
    facts = [
        graph.new_fact("IDENTITY_TYPE", {"instance": dog.id, "type": domain.id}) for dog in dogs
    ]
    for index, (dog, value) in enumerate(zip(dogs, (5, 15, 40), strict=True)):
        facts.append(
            graph.new_fact(
                "HAS_NUMERIC_VALUE",
                {"entity": dog.id, "property": prop.id, "value": value, "unit": "kg"},
                belief_target="reported-mass" if index == 0 else None,
            )
        )
    graph.apply(
        GraphDelta(creates=(domain, prop, *dogs, *classes, guide, table, *facts)),
        provenance=provenance,
    )
    beliefs = BeliefStore()
    beliefs.register_binary("reported-mass")
    beliefs.assign("reported-mass", provenance, 1, backed=True)
    attribution = AttributionRuntime(graph, beliefs)
    initial_report = attribution.summarize_property(domain.id, prop.id)
    table_target = next(
        item["belief_target"] for item in initial_report["references"] if item["id"] == table.id
    )
    beliefs.register_binary(table_target)
    beliefs.assign(table_target, provenance, 0.75, backed=True)
    initial = (graph.snapshot(), memory.snapshot(), beliefs.snapshot(), attribution.snapshot())
    revision = change(branch, spec.git_path, source + "\n# independently evaluated candidate\n")
    expected = {
        "observed_mean": 20,
        "observed_count": 3,
        "guide_class": "Large",
        "table_mean": 15,
        "table_count": 4,
        "source_retained": True,
        "measurement_assessed": True,
        "reference_assessed": True,
        "reference_support": 0.75,
        "time_basis": "latest_recorded",
    }
    experiment = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"value": 28}, expected)),
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
    assert experiment.report.metrics == {"accuracy": 1}, experiment.traces
    assert experiment.report.baseline_metrics == {"accuracy": 1}, experiment.traces
    assert (
        graph.snapshot(),
        memory.snapshot(),
        beliefs.snapshot(),
        attribution.snapshot(),
    ) == initial
