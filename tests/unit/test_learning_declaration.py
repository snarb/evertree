"""A Program's LEARNING literal: forecast contracts and the estimator state Core owns for it."""

from __future__ import annotations

import pytest

from evertree.core.evaluation.scoring import evaluate_prediction
from evertree.core.learning.contracts import LearningObjective, LearningSignal
from evertree.core.learning.declaration import check_forecast, read_learning
from evertree.core.learning.state import LearningStore
from evertree.core.learning.updates import CreditAssignmentProgram, UpdatePlanner


def target(**changes):
    return {
        "form": "probability",
        "result": "",
        "subject": "a parcel",
        "horizon": "delivery",
        "check": "carrier scan",
        "metrics": ["brier"],
        **changes,
    }


def source(targets, estimators=None):
    return f"LEARNING = {{'targets': {targets!r}, 'estimators': {estimators or {}!r}}}\n"


def declaration(prior=4):
    return read_learning(
        source(
            {"Late": target()},
            {
                "post": {
                    "kind": "beta_bernoulli",
                    "target": "Late",
                    "settings": {"alpha": prior, "beta": 6},
                },
                "courier": {
                    "kind": "beta_bernoulli",
                    "target": "Late",
                    "settings": {"alpha": 1, "beta": 9},
                },
            },
        ),
        "late.py",
    )


def test_absent_literal_declares_nothing():
    assert read_learning("def run():\n    pass\n", "x.py") is None


@pytest.mark.parametrize(
    ("targets", "estimators", "match"),
    [
        ({"Late": target(metrics=["squared_error"])}, {}, "probability forecasts use"),
        ({"Weather": target(form="distribution", metrics=["log_loss"])}, {}, "categories exactly"),
        ({"Late": target(form="mean", metrics=["log_loss"])}, {}, "mean forecasts use"),
        (
            {"Late": target()},
            {"rate": {"kind": "mean", "target": "Late"}},
            "cannot learn a probability",
        ),
        ({"Late": target()}, {"rate": {"kind": "beta_bernoulli", "target": "Other"}}, "undeclared"),
        (
            {"Late": target()},
            {"rate": {"kind": "beta_bernoulli", "target": "Late", "settings": {"alpha": 0}}},
            "positive",
        ),
        ({"Late": {**target(), "extra": 1}}, {}, "Extra inputs"),
    ],
)
def test_invalid_declarations_name_their_error(targets, estimators, match):
    with pytest.raises(ValueError, match=match):
        read_learning(source(targets, estimators), "x.py")


def test_forecast_targets_belong_to_model_programs():
    exec_target = read_learning(source({"Late": target(result=None)}), "x.py")
    exec_target.check_role("exec")
    with pytest.raises(ValueError, match="must name its result key"):
        exec_target.check_role("model")
    with pytest.raises(ValueError, match="Only a model Program"):
        declaration().check_role("exec")


def test_returned_forecasts_must_match_their_declared_form():
    weather = read_learning(
        source(
            {
                "Weather": target(
                    form="distribution",
                    result="weather",
                    categories=["rain", "dry"],
                    metrics=["log_loss"],
                )
            }
        ),
        "x.py",
    )
    check_forecast(weather, {"weather": {"rain": 0.25, "dry": 0.75}})
    for result, match in [
        ({"weather": {"rain": 0.5, "dry": 0.6}}, "sum to 1"),
        ({"weather": {"rain": 1.0}}, "declared categories"),
        ({}, "lacks 'weather'"),
    ]:
        with pytest.raises(ValueError, match=match):
            check_forecast(weather, result)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        check_forecast(declaration(), 1.3)


def test_installed_estimators_keep_trained_state_until_their_declaration_changes():
    store = LearningStore()
    states = store.install("7", declaration())
    assert store.estimate("7", declaration(), "post")["value"] == 0.4
    assert {binding["owner"] for binding in store.bindings("Late")} == {"7"}
    store._states[states["post"]]["parameters"]["positive"] = 3.0
    store._states[states["post"]]["parameters"]["observed_count"] = 3
    assert store.install("7", declaration()) == states
    assert store.estimate("7", declaration(), "post")["observed_count"] == 3
    changed = store.install("7", declaration(prior=2))
    assert changed["post"] != states["post"] and changed["courier"] == states["courier"]
    assert store.estimate("7", declaration(prior=2), "post")["observed_count"] == 0
    assert {binding["state"] for binding in store.bindings("Late")} == set(changed.values())
    store.release("7")
    assert store.bindings("Late") == []
    assert states["post"] in store.snapshot()["states"]


def test_an_outcome_trains_only_the_estimator_its_forecast_read():
    store = LearningStore()
    states = store.install("7", declaration())
    evaluated = evaluate_prediction(
        0.1, 1, metrics=("brier",), outcome_ids=("o1",), provenance=("forecast", "observation")
    )
    signal = LearningSignal(evaluated, LearningObjective(("brier",), "minimize"), {"o1": 1})
    credit = CreditAssignmentProgram(store).assign(
        "Late", signal, context={"estimator_states": [states["courier"]]}
    )
    update = UpdatePlanner(store).prepare(credit)
    assert update.state == states["courier"]
    unbound = CreditAssignmentProgram(store).assign("Late", signal)
    assert UpdatePlanner(store).prepare(unbound).reason == "ambiguous_learning_binding"
