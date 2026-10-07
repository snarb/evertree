import pytest

from evertree.core.datasets import DatasetRevision, EvaluationCase
from evertree.core.evaluation import AcceptanceCriteria, assess_candidate
from evertree.core.programs.experiments import evaluate_pair
from tests.support.evaluation import dataset, evaluation_state, fixed_outcomes


async def test_unsupported_evaluation_rule_rejected_before_execution(tmp_path):
    repo, branch, spec, graph, memory, learning = evaluation_state(tmp_path)
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
        )


async def test_prediction_candidates_use_fixed_proper_scores_and_weighted_cases(
    tmp_path, monkeypatch
):
    """Score supplied worker results; Git and worker execution are separate contracts."""
    repo, branch, spec, graph, memory, learning = evaluation_state(tmp_path)
    revision = "1" * 40
    runtime = fixed_outcomes(monkeypatch, 0.2, 0.8)
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
        runtime_factory=runtime,
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


async def test_infinite_prediction_score_is_retained_but_cannot_pass_acceptance(
    tmp_path, monkeypatch
):
    """Score supplied worker results; Git and worker execution are separate contracts."""
    repo, branch, spec, graph, memory, learning = evaluation_state(tmp_path)
    revision = "1" * 40
    runtime = fixed_outcomes(monkeypatch, 0.5, 0.0)
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
            runtime_factory=runtime,
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


async def test_exact_holdout_cannot_certify_boolean_for_numeric_output(tmp_path, monkeypatch):
    """Score supplied worker results; Git and worker execution are separate contracts."""
    repo, branch, spec, graph, memory, learning = evaluation_state(tmp_path)
    revision = "1" * 40
    runtime = fixed_outcomes(monkeypatch, 3, {"nested": [True]})
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
        runtime_factory=runtime,
    )
    assert result.report.checks["contracts"] is True
    assert result.report.metrics == {"accuracy": 0}
