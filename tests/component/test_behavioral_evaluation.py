import math

import pytest

from evertree.core.datasets import DatasetStore, EvaluationCase
from evertree.core.evaluation import (
    NotApplicableResult,
    UnresolvedEvaluationResult,
    evaluate_prediction,
)
from evertree.core.learning import LearningObjective, LearningSignal
from evertree.core.programs.experiments import evaluate_pair
from tests.support.evaluation import evaluation_state


def test_eva01_inapplicable_and_missing_outcomes_never_create_learning_signal():
    """EVA-01: neither unevaluated variant can masquerade as zero prediction error."""
    inapplicable = evaluate_prediction(
        0.7,
        None,
        metrics=("brier",),
        outcome_ids=(),
        provenance=("trace",),
        applicable=False,
    )
    missing = evaluate_prediction(
        0.7,
        None,
        metrics=("brier",),
        outcome_ids=(),
        provenance=("trace",),
    )
    assert isinstance(inapplicable, NotApplicableResult)
    assert isinstance(missing, UnresolvedEvaluationResult)
    for result in (inapplicable, missing):
        assert result.metrics() == {}
        with pytest.raises(ValueError, match="only use evaluated"):
            LearningSignal(result, LearningObjective(("brier",), "minimize"), {"missing": 1})


def test_eva03_binary_log_loss_is_not_entropy_subtracted():
    """EVA-03: a fair-probability forecast of an observed success has ln(2) loss."""
    losses = [
        evaluate_prediction(
            prediction,
            1,
            metrics=("log_loss",),
            outcome_ids=("actual-success",),
            provenance=("saved-prediction", "observed-success"),
        ).metrics()["log_loss"]
        for prediction in (0.5, 0.8)
    ]
    assert losses == pytest.approx([math.log(2), -math.log(0.8)])
    assert losses[0] > losses[1] > 0


def test_lrn09_reslicing_a_seen_source_does_not_create_independent_holdout():
    """LRN-09: dataset independence follows the original history, not fragment ids."""
    store = DatasetStore()
    training = store.create(
        "Engine story",
        [
            EvaluationCase(
                "whole",
                {"prefix": "temperature 110"},
                "stopped",
                "exact",
                ("engine-history",),
            )
        ],
        purpose="training",
    )
    store.mark_training("candidate-lineage", training.revision)
    holdout = store.create(
        "Different slice",
        [
            EvaluationCase(
                "new-fragment",
                {"prefix": "temperature 110"},
                "stopped",
                "exact",
                ("engine-history",),
            )
        ],
    )
    with pytest.raises(ValueError, match="overlap"):
        store.require_holdout("candidate-lineage", holdout.revision)
    store.inherit_exposure("candidate-lineage", "refined-candidate")
    with pytest.raises(ValueError, match="overlap"):
        store.require_holdout("refined-candidate", holdout.revision)


@pytest.mark.parametrize("source_kind", ["event_ref", "external_source_id"])
async def test_lrn09_eva02_known_holdout_source_cannot_leak_through_initial_memory(
    tmp_path, source_kind
):
    """LRN-09/EVA-02: hidden arguments are insufficient when retrieval exposes the source."""
    repo, branch, spec, graph, memory, learning = evaluation_state(tmp_path)
    run = memory.start_run("observation", "source-revision", {})
    outcome = memory.record(
        run,
        "future_engine_outcome",
        arguments={"source_id": "host-future-source"},
        output="stopped",
    )
    memory.finish_run(run)
    revision = branch.base_revision
    store = DatasetStore()
    holdout = store.create(
        "Engine transition",
        [
            EvaluationCase(
                "engine",
                {"prefix": "temperature 110 C"},
                "stopped",
                "exact",
                (str(outcome.id) if source_kind == "event_ref" else "host-future-source",),
            )
        ],
    )
    # No training exposure was registered, but the initial memory still contains the answer.
    store.require_holdout(branch.id, holdout.revision)
    with pytest.raises(ValueError, match="initial.*memory"):
        await evaluate_pair(
            branch,
            revision,
            spec,
            holdout,
            tmp_path / "evaluation",
            repo,
            graph,
            memory,
            learning,
            lambda _: spec,
        )
