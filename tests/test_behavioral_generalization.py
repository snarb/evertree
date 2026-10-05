"""Prepared generalizations and insights through existing product boundaries.

There is no autonomous consolidation-to-program or canonical-principle revision
orchestrator here. Proposal tests state that boundary explicitly; lifecycle,
estimator transfer, retained provenance and subsequent execution use real APIs.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from test_behavioral_evaluation import WORKER_RUNTIME
from test_experiments import PATH, dataset, evaluate_pair
from test_lifecycle_backup import change

from evertree.core.beliefs import BeliefStore
from evertree.core.evaluation import AcceptanceCriteria, MetricGuardrail, evaluate_prediction
from evertree.core.graph import GraphDelta, GraphStore, Node
from evertree.core.learning import (
    LearningBinding,
    LearningCoordinator,
    LearningObjective,
    LearningSignal,
    LearningStore,
)
from evertree.core.lifecycle import (
    LifecycleError,
    ProgramLifecycleRuntime,
    git,
    initialize_seed_repository,
)
from evertree.core.memory import TraceStore
from evertree.core.runtime import ProgramExecutionError, ProgramSpec
from evertree.processes.reflection._programs.default.implementation import run as reflect


async def no_gateway(method, payload):
    raise AssertionError("The fixed calculation needs no external operations")


def prepare(tmp_path, source):
    """Use the product's trusted Git setup, independent of host newline filters."""
    seed = tmp_path / "seed"
    path = seed / PATH
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    repo = tmp_path / "repository"
    initialize_seed_repository(seed, repo)
    local_tests = repo / "tests" / "test_entrypoint.py"
    local_tests.parent.mkdir()
    local_tests.write_text(
        """import importlib.util
from pathlib import Path
import unittest

class EntrypointTest(unittest.TestCase):
    def test_declared_entrypoint_imports(self):
        path = Path(__file__).parents[1] / 'src/evertree/processes/example.py'
        spec = importlib.util.spec_from_file_location('example_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.run))
""",
        encoding="utf-8",
    )
    git(repo, "add", "tests")
    git(repo, "commit", "-m", "Add candidate entrypoint test fixture")
    revision = git(repo, "rev-parse", "HEAD")
    lifecycle = ProgramLifecycleRuntime(
        repo,
        tmp_path / "lifecycle",
        AcceptanceCriteria(("contracts", "tests", "holdout"), "accuracy", threshold=1),
    )
    branch = lifecycle.create_candidate("program", "Evaluate the prepared improvement")
    return (
        repo,
        lifecycle,
        branch,
        ProgramSpec("program", PATH, revision),
        GraphStore(),
        TraceStore(),
        LearningStore(),
    )


async def test_lrn01_prepared_common_rule_passes_transfer_and_simplification_gate(tmp_path):
    """LRN-01 partial: check/activate a prepared shared implementation; no pattern discovery."""
    baseline = """def run(shop, quantity):
    if shop == 'A':
        return {'result': 2 * quantity}
    if shop == 'B':
        return {'result': 2 * quantity}
    raise ValueError('Outside A/B tariff scope')
"""
    candidate = """def price(quantity):
    return 2 * quantity

def run(shop, quantity):
    if shop not in ('A', 'B'):
        raise ValueError('Outside A/B tariff scope')
    return {'result': price(quantity)}
"""
    repo, lifecycle, branch, spec, graph, memory, learning = prepare(tmp_path, baseline)
    # The fixture's explicit simplification metric counts independently implemented
    # tariff expressions. Actual output quality remains measured by isolated runs.
    lifecycle.criteria = AcceptanceCriteria(
        ("contracts", "tests", "holdout"),
        "tariff_implementations",
        "minimize",
        min_improvement=1,
        guardrails=(MetricGuardrail("accuracy", threshold=1),),
    )
    revision = change(branch, PATH, candidate)
    observed = None

    async def evaluator(selected, actual):
        nonlocal observed
        observed = await evaluate_pair(
            selected,
            actual,
            spec,
            dataset(({"shop": "A", "quantity": 4}, 8), ({"shop": "B", "quantity": 7}, 14)),
            tmp_path / "evaluation",
            repo,
            graph,
            memory,
            learning,
            lambda _: spec,
            runtime_factory=WORKER_RUNTIME,
        )
        old_count = sum(isinstance(node, ast.Mult) for node in ast.walk(ast.parse(baseline)))
        new_count = sum(isinstance(node, ast.Mult) for node in ast.walk(ast.parse(candidate)))
        return replace(
            observed.report,
            metrics={**observed.report.metrics, "tariff_implementations": new_count},
            baseline_metrics={
                **observed.report.baseline_metrics,
                "tariff_implementations": old_count,
            },
        )

    await lifecycle.evaluate(branch.id, evaluator)
    assert observed.report.metrics == observed.report.baseline_metrics == {"accuracy": 1}
    assert git(repo, "rev-parse", "main") == branch.base_revision
    assert (
        await lifecycle.choose(branch.id, "merge_branch", reason="Shared A/B tariff verified")
        == revision
    )
    assert git(repo, "rev-parse", "main") == revision
    runtime = WORKER_RUNTIME(tmp_path / "next-task", repo, no_gateway)
    try:
        result = await runtime.execute(
            "new-shop-order", replace(spec, revision=revision), {"shop": "A", "quantity": 9}
        )
        assert result.result == 18
        with pytest.raises(ProgramExecutionError, match="Outside A/B tariff scope"):
            await runtime.execute(
                "outside-scope", replace(spec, revision=revision), {"shop": "C", "quantity": 9}
            )
    finally:
        await runtime.close()


async def test_lrn02_missing_discount_counterexample_prevents_activation(tmp_path):
    """LRN-02: a simpler rule cannot replace the baseline after losing an exception."""
    baseline = """def run(shop, quantity):
    total = 2 * quantity
    if shop == 'B' and quantity >= 10:
        total *= 0.9
    return {'result': total}
"""
    repo, lifecycle, branch, spec, graph, memory, learning = prepare(tmp_path, baseline)
    change(branch, PATH, "def run(shop, quantity): return {'result': 2 * quantity}\n")
    experiment = None

    async def evaluator(selected, revision):
        nonlocal experiment
        experiment = await evaluate_pair(
            selected,
            revision,
            spec,
            dataset(({"shop": "B", "quantity": 10}, 18)),
            tmp_path / "evaluation",
            repo,
            graph,
            memory,
            learning,
            lambda _: spec,
            runtime_factory=WORKER_RUNTIME,
        )
        return experiment.report

    await lifecycle.evaluate(branch.id, evaluator)
    outputs = {
        item["side"]: item["result"] for item in experiment.traces if item.get("kind") == "case"
    }
    assert outputs == {"baseline": 18, "candidate": 20}
    with pytest.raises(LifecycleError, match="Acceptance checks failed"):
        await lifecycle.choose(branch.id, "merge_branch", reason="Attempt simpler rule")
    assert git(repo, "rev-parse", "main") == branch.base_revision


async def test_lrn05_lrn07_checked_parser_is_activated_and_used_by_a_new_task(tmp_path):
    """LRN-05/LRN-07: evaluate independent boundary cases, then actually run active code."""
    repo, lifecycle, branch, spec, graph, memory, learning = prepare(
        tmp_path,
        "def run(value): return {'result': float(value)}\n",
    )
    revision = change(
        branch, PATH, "def run(value): return {'result': float(value.replace(',', '.'))}\n"
    )

    async def evaluator(selected, actual):
        return (
            await evaluate_pair(
                selected,
                actual,
                spec,
                dataset(
                    ({"value": "2,5"}, 2.5), ({"value": "7,25"}, 7.25), ({"value": "3.5"}, 3.5)
                ),
                tmp_path / "evaluation",
                repo,
                graph,
                memory,
                learning,
                lambda _: spec,
                runtime_factory=WORKER_RUNTIME,
            )
        ).report

    report = await lifecycle.evaluate(branch.id, evaluator)
    assert report.metrics == {"accuracy": 1}
    assert report.baseline_metrics["accuracy"] == pytest.approx(1 / 3)
    assert git(repo, "rev-parse", "main") == branch.base_revision
    await lifecycle.choose(branch.id, "merge_branch", reason="Comma and dot cases verified")
    events = []

    async def record(event):
        events.append(event)

    runtime = WORKER_RUNTIME(tmp_path / "next-task", repo, no_gateway, record)
    try:
        active = replace(spec, revision=git(repo, "rev-parse", "main"))
        assert (await runtime.execute("new-price-task", active, {"value": "4,5"})).result == 4.5
    finally:
        await runtime.close()
    started = next(event for event in events if event["type"] == "run_started")
    assert started["program"]["revision"] == revision
    assert started["arguments"] == {"value": "4,5"}


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
