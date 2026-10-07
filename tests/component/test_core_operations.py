from dataclasses import replace

import pytest

from evertree.application import EverTree
from evertree.core.attribution import AttributionRuntime, NormalizationRule, PropertyDefinition
from evertree.core.beliefs import BeliefStore
from evertree.core.datasets import DatasetRevision, DatasetStore, EvaluationCase
from evertree.core.evaluation import EvaluationStore, evaluate_prediction
from evertree.core.graph import GraphDelta, GraphStore, Node, RelationType, Slot
from evertree.core.learning import LearningBinding, LearningObjective, LearningSignal, LearningStore
from evertree.core.memory import TraceOutputRef, TraceStore
from evertree.core.operations import CoreOperations
from evertree.core.provider import ScriptedProvider


def environment():
    graph, memory, beliefs = GraphStore(), TraceStore(), BeliefStore()
    graph.apply(GraphDelta(creates=(Node(1, "property"),)), provenance="seed")
    attribution = AttributionRuntime(graph, beliefs)
    attribution.register(PropertyDefinition(1))
    attribution.register_normalization(NormalizationRule(1, "domain", mean=10, stddev=2))
    beliefs.register_binary("claim")
    learning = LearningStore()
    learning.create_state("beta_bernoulli", state_id="state")
    learning.register_binding(LearningBinding("target", "state", ("brier",)))
    return CoreOperations(graph, memory, beliefs, attribution, EvaluationStore(), learning, set())


def clone(source):
    graph = GraphStore.from_snapshot(source.graph.snapshot())
    beliefs = BeliefStore.from_snapshot(source.beliefs.snapshot())
    return CoreOperations(
        graph,
        TraceStore.from_snapshot(source.memory.snapshot()),
        beliefs,
        AttributionRuntime.from_snapshot(source.attribution.snapshot(), graph, beliefs),
        EvaluationStore.from_snapshot(source.evaluations.snapshot()),
        LearningStore.from_snapshot(source.learning.snapshot()),
        set(source.observation_ids),
    )


def invoke(operations, method, payload, role="exec"):
    return operations.execute(
        method,
        payload,
        metadata={
            "task_id": "task",
            "run_id": "run",
            "program": {"role": role, "revision": "commit"},
        },
    )


def test_same_read_contracts_and_effect_guards_in_independent_environments():
    live = environment()
    isolated = clone(live)
    for method, payload in (
        ("graph.get", {"id": 1}),
        ("belief.read", {"target": "claim"}),
        ("attribution.normalize", {"property_id": 1, "domain": "domain", "value": 12}),
    ):
        assert invoke(live, method, payload, "model") == invoke(isolated, method, payload, "model")
    for operations in (live, isolated):
        with pytest.raises(PermissionError, match="model Program"):
            invoke(operations, "graph.apply", {"deletes": [1]}, "model")
    invoke(isolated, "graph.apply", {"updates": [{"id": 1, "changes": {"name": "isolated"}}]})
    assert live.graph.get(1).name == "property"
    assert isolated.graph.get(1).name == "isolated"


def test_learning_requires_the_same_immutable_evaluation_in_each_environment():
    live = environment()
    evaluation = live.evaluations.add(
        evaluate_prediction(
            0.5, True, metrics=("brier",), outcome_ids=("observation",), provenance=("source",)
        )
    )
    isolated = clone(live)
    signal = LearningSignal(
        evaluation, LearningObjective(("brier",), "minimize"), {"observation": True}
    )
    forged = replace(signal, evaluation=replace(evaluation, evaluated_subject="forged"))
    for operations in (live, isolated):
        with pytest.raises(PermissionError, match="original Evaluation"):
            invoke(operations, "learning.learn", {"signal": forged.to_dict(), "target": "target"})
    invoke(isolated, "learning.learn", {"signal": signal.to_dict(), "target": "target"})
    assert isolated.learning.predict("state") == pytest.approx(2 / 3)
    assert live.learning.predict("state") == 0.5


def test_external_source_names_are_not_implicitly_memory_addresses(tmp_path, monkeypatch):
    app = EverTree(tmp_path, provider=ScriptedProvider([]))
    monkeypatch.setattr(app, "_program", lambda *args, **kwargs: None)
    external = EvaluationCase("external", {}, 1, "exact", ("123",))
    dataset = app.datasets.create("external", [external], target_metrics=("accuracy",))
    app.bind_evaluation(1, dataset.revision)
    run = app.memory.start_run("sensor", "commit", {})
    event = app.memory.record(run, "observation", output={"measurement": 1})
    ref = TraceOutputRef(event.id, ("measurement",))
    case = replace(external, id="internal", source_refs=(ref,))
    internal = app.datasets.create("internal", [case], target_metrics=("accuracy",))
    app.bind_evaluation(1, internal.revision)
    restored = DatasetStore.from_snapshot(app.datasets.snapshot()).get(internal.revision)
    assert restored.cases[0].source_refs == (ref,)
    assert app.memory.resolve(restored.cases[0].source_refs[0]) == 1
    assert "trace:" + str(event.id) in restored.cases[0].independence_keys
    with pytest.raises(ValueError, match="accessible through agent memory"):
        app.datasets.require_holdout("candidate", internal.revision)


def test_dataset_rule_is_fixed_and_internal_sources_affect_independence():
    case = EvaluationCase("one", {}, 1, "exact", ("external",), source_refs=(TraceOutputRef(1),))
    other = replace(case, id="two", source_ids=("another",))
    assert case.independence_keys & other.independence_keys == {"trace:1"}
    dataset = DatasetRevision("data", "name", "evaluation", (case,))
    assert DatasetRevision.from_dict(dataset.to_dict()).revision == dataset.revision
    with pytest.raises(ValueError, match="aggregation"):
        DatasetRevision.from_dict({**dataset.to_dict(), "aggregation_policy": "invented"})


def test_binding_facts_cannot_bypass_lifecycle_and_mutations_keep_run_mode():
    operations = environment()
    binding = RelationType(2, "PROGRAM_FOR_PROCESS", signature=(Slot("program"), Slot("process")))
    operations.graph.apply(GraphDelta(creates=(binding,)), provenance="bootstrap")
    fact = operations.graph.new_fact("PROGRAM_FOR_PROCESS", {"program": 1, "process": 1})
    with pytest.raises(PermissionError, match="lifecycle"):
        operations.apply_delta(GraphDelta(creates=(fact,)), task_id="task", revision="commit")
    operations.execute(
        "graph.apply",
        {"creates": [{"id": 4, "name": "new"}]},
        metadata={
            "task_id": "task",
            "run_id": "run",
            "run_mode": "evaluation",
            "program": {"role": "exec", "revision": "commit"},
        },
    )
    mutation = next(event for event in operations.memory.events if event.operator == "graph_delta")
    assert operations.memory.get_run(mutation.program_run).run_mode == "evaluation"
