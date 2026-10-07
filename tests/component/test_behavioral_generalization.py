from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from evertree.core.beliefs import BeliefStore
from evertree.core.evaluation.scoring import evaluate_prediction
from evertree.core.graph.store import GraphStore
from evertree.core.graph.types import GraphDelta, Node
from evertree.core.learning.contracts import LearningBinding, LearningObjective, LearningSignal
from evertree.core.learning.coordinator import LearningCoordinator
from evertree.core.learning.state import LearningStore
from evertree.core.memory.store import TraceStore
from evertree.processes.learning.reflection._exec import run as reflect


@pytest.mark.parametrize("catalog_id", ["LRN-04", "LRN-08"])
async def test_reflection_proposal_boundary_does_not_establish_or_rewrite_belief(catalog_id):
    """LRN-04/LRN-08 partial: actual Reflection returns a proposal; lifecycle is caller-owned."""
    graph, beliefs = GraphStore(), BeliefStore()
    principle = Node(
        1, "Decimal comma principle", kind="claim", properties={"scope": "all numeric fields"}
    )
    graph.apply(GraphDelta(creates=(principle,)), provenance="original-principle")
    beliefs.register_binary("parser-hypothesis")
    before = graph.snapshot(), beliefs.snapshot()
    if catalog_id == "LRN-04":
        source_ids = ["parse-error-1", "parse-error-2"]
        statement = "Parser lacks decimal comma support"
    else:
        source_ids = ["english-1000-counterexample"]
        statement = "Decimal comma interpretation requires a compatible locale"
    proposal = {
        "incidents": [],
        "hypotheses": [
            {
                "statement": statement,
                "source_ids": source_ids,
                "independent_check": "Evaluate previously unused locale examples",
            }
        ],
        "proposed_changes": [
            {
                "description": statement,
                "target": "number-parser",
                "expected_benefit": "Correct numeric interpretation",
                "verification": "Independent dot, comma and thousands cases",
            }
        ],
    }
    calls = []

    class ModelContext:
        async def step(self, method, payload):
            calls.append((method, payload))
            assert method == "agent.run"
            assert json.loads(payload["prompt"])["source_ids"] == source_ids
            return {"parsed": proposal}

    result = await reflect(ModelContext(), {"source_ids": source_ids, "problem": statement})
    assert result["result"]["hypotheses"][0]["source_ids"] == source_ids
    assert len(calls) == 1 and calls[0][1]["mode"] == "model"
    assert (graph.snapshot(), beliefs.snapshot()) == before
    assert beliefs.read("parser-hypothesis").support == 0


def test_lrn06_compaction_preserves_auditable_path_to_an_active_insight():
    """LRN-06: keep actual source-to-check dependencies, while dropping unrelated detail."""
    memory = TraceStore()
    start = datetime(2025, 1, 1, tzinfo=UTC)
    run = memory.start_run("parser-investigation", "verified-revision", {}, at=start)
    failures = [
        memory.record(run, "parse_failure", output={"input": value, "error": "comma"}, at=start)
        for value in ("1,5", "1,75")
    ]
    irrelevant = memory.record(run, "routine_detail", output="no relevant change", at=start)
    hypothesis = memory.record(
        run,
        "hypothesis",
        output="Missing decimal comma support",
        at=start,
        dependencies=tuple(memory.output_ref(event) for event in failures),
    )
    checked = memory.record(
        run,
        "evaluate",
        output={"passed": ["2,5", "7,25", "3.5"]},
        at=start,
        dependencies=(memory.output_ref(hypothesis),),
    )
    active = memory.record(
        run,
        "activate",
        output={"revision": "verified-revision", "scope": "decimal-comma numbers"},
        at=start,
        dependencies=(memory.output_ref(checked),),
    )
    memory.finish_run(run, at=start)
    memory.retain(active.id, "Audit basis for active parser change")
    protected = memory.retention_closure()
    trace = memory.compact(
        run.id,
        tuple(event.id for event in memory.events if event.id in protected),
        at=start + timedelta(days=60),
    )
    assert irrelevant.id not in trace.events
    path = {event.id: event for event in memory.provenance_of(memory.output_ref(active))}
    assert set(path) == {event.id for event in (*failures, hypothesis, checked, active)}
    assert path[failures[0].id].output["input"] == "1,5"
    assert path[hypothesis.id].output == "Missing decimal comma support"
    assert path[checked.id].output["passed"] == ("2,5", "7,25", "3.5")
    assert path[active.id].output["revision"] == "verified-revision"


def test_int02_learned_model_transfers_after_compaction_and_restoration():
    """INT-02: existing regression learning + retained verified scope, not autonomous synthesis."""
    learning = LearningStore()
    state = learning.create_state("linear_regression", dimension=1, learning_rate=0.5)
    learning.register_binding(LearningBinding("next_number", state, ("squared_error",)))
    evaluation = evaluate_prediction(
        learning.predict(state, [1]),
        2,
        metrics=("squared_error",),
        outcome_ids=("training-example",),
        provenance=("training-input", "training-outcome"),
    )
    signal = LearningSignal(
        evaluation, LearningObjective(("squared_error",), "minimize"), {"training-example": 2}
    )
    assert (
        LearningCoordinator(learning).learn(signal, "next_number", context={"features": [1]}).status
        == "applied"
    )
    scores = [
        evaluate_prediction(
            learning.predict(state, [value]),
            outcome,
            metrics=("squared_error",),
            outcome_ids=(identity,),
            provenance=("independent:" + identity,),
        )
        for identity, value, outcome in (("holdout-a", 2, 3), ("holdout-b", 4, 5))
    ]
    assert all(score.metrics()["squared_error"] == 0 for score in scores)
    memory = TraceStore()
    start = datetime(2025, 1, 1, tzinfo=UTC)
    run = memory.start_run("rule-validation", "revision", {}, at=start)
    detail = memory.record(run, "unnecessary_detail", output="temporary formatting", at=start)
    result = memory.record(
        run,
        "verified_model",
        output={
            "state": state,
            "scope": "integer inputs from 0 through 10",
            "evaluation": [score.to_dict() for score in scores],
        },
        at=start,
    )
    memory.finish_run(run, at=start)
    memory.retain(result.id, "Active program requires model scope and evaluation")
    graph = GraphStore()
    model = Node(
        1,
        "Verified next-number model",
        kind="claim",
        properties={
            "state": state,
            "scope": "integer inputs from 0 through 10",
            "evaluation_event": result.id,
        },
    )
    graph.apply(GraphDelta(creates=(model,)), provenance=memory.output_ref(result))
    memory.compact(run.id, (result.id,), at=start + timedelta(days=60))
    assert detail.id not in memory.semantic_trace(run.id).events
    restored_memory = TraceStore.from_snapshot(json.loads(json.dumps(memory.snapshot())))
    restored_learning = LearningStore.from_snapshot(json.loads(json.dumps(learning.snapshot())))
    restored_graph = GraphStore.from_snapshot(json.loads(json.dumps(graph.snapshot())))
    active_model = restored_graph.get(model.id)
    retained = restored_memory.resolve(
        restored_memory.output_ref(active_model.properties["evaluation_event"])
    )
    assert retained["scope"] == "integer inputs from 0 through 10"
    assert active_model.properties["scope"] == retained["scope"]
    assert len(retained["evaluation"]) == 2
    assert restored_learning.predict(active_model.properties["state"], [7]) == 8
