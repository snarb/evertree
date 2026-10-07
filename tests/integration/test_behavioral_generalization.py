from __future__ import annotations

import ast
from dataclasses import replace

import pytest

from evertree.core.evaluation import AcceptanceCriteria, MetricGuardrail
from evertree.core.graph import GraphStore
from evertree.core.learning import (
    LearningStore,
)
from evertree.core.memory import TraceStore
from evertree.core.programs.lifecycle import (
    LifecycleError,
    ProgramLifecycleRuntime,
    git,
    initialize_seed_repository,
)
from evertree.core.runtime import ProgramExecutionError, ProgramSpec
from tests.support.evaluation import dataset
from tests.support.experiments import PATH, evaluate_pair
from tests.support.experiments import TEST_RUNTIME as WORKER_RUNTIME
from tests.support.lifecycle_backup import change


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
