from __future__ import annotations

import math

import pytest

from evertree.core.evaluation.acceptance import AcceptanceCriteria, assess_candidate, meta_criteria
from evertree.core.evaluation.scoring import evaluate_policy
from evertree.core.operations import authorize_operation
from evertree.core.policy.contracts import (
    certain,
    greedy_distribution,
    probability_of,
    softmax_distribution,
    validate_distribution,
)
from evertree.core.programs.design import PolicyDesign, check_design, design_profile
from evertree.core.runtime.controller import ProgramSpec

ANSWERS = {
    "applicability": "Known routes only.",
    "adaptation": "Inputs carry current travel times.",
    "learning": "Fixed rule checked by protected evaluation.",
    "exploration": "Not used; times are observed directly.",
}


@pytest.mark.parametrize(
    ("distribution", "allowed", "message"),
    [
        ({"choices": []}, None, "nonempty"),
        ({"choices": [["a", 0.5], ["a", 0.5]]}, None, "unique"),
        ({"choices": [["a", 0.7], ["b", 0.2]]}, None, "sum to 1"),
        ({"choices": [["a", -0.5], ["b", 1.5]]}, None, "nonnegative"),
        ({"choices": [["a", math.nan]]}, None, "finite"),
        ({"choices": [["c", 1.0]]}, ["a", "b"], "outside the allowed set"),
        ({"choices": [["a", 1.0]], "fallback": "b"}, None, "exactly"),
        ("a", None, "exactly"),
    ],
)
def test_action_distribution_contract_has_no_implicit_fallback(distribution, allowed, message):
    with pytest.raises(ValueError, match=message):
        validate_distribution(distribution, allowed)


def test_distribution_helpers_compare_structured_candidates_canonically():
    move = {"to": [1, 2], "piece": "rook"}
    distribution = validate_distribution(
        {"choices": [[{"piece": "rook", "to": [1, 2]}, 0.25], ["pass", 0.75]]}, [move, "pass"]
    )
    assert probability_of(distribution, move) == 0.25
    assert probability_of(distribution, "resign") == 0.0
    assert certain("pass") == {"choices": [["pass", 1.0]]}
    assert greedy_distribution(["a", "b", "c"], [2, 5, 5]) == {"choices": [["b", 0.5], ["c", 0.5]]}
    soft = softmax_distribution(["a", "b"], [0.0, 1.0], temperature=0.1)
    assert probability_of(soft, "b") > 0.99
    assert sum(p for _, p in soft["choices"]) == pytest.approx(1.0, abs=1e-12)
    with pytest.raises(ValueError, match="positive"):
        softmax_distribution(["a"], [1.0], temperature=0)


def test_policy_scores_are_proper_and_bounded_by_the_utility_table():
    distribution = {"choices": [["A", 0.25], ["B", 0.75]]}
    scores = evaluate_policy(
        distribution,
        {"reference": "B", "utilities": [["A", -30], ["B", -20]]},
        ("action_log_loss", "reference_probability", "expected_utility"),
    )
    assert scores == pytest.approx(
        {
            "action_log_loss": -math.log(0.75),
            "reference_probability": 0.75,
            "expected_utility": -22.5,
        }
    )
    assert evaluate_policy(certain("A"), {"reference": "B"}, ("action_log_loss",)) == {
        "action_log_loss": math.inf
    }
    with pytest.raises(ValueError, match="outside the allowed set"):
        evaluate_policy(certain("C"), {"utilities": [["A", 1]]}, ("expected_utility",))


def test_policy_and_meta_programs_need_a_complete_policy_design():
    path = "src/evertree/processes/route/_exec.py"
    assert design_profile(meta=False, policy=False) is None
    assert design_profile(meta=True, policy=False) is PolicyDesign
    check_design(f"DESIGN = {ANSWERS!r}\n\ndef run():\n    pass\n", path, PolicyDesign)
    with pytest.raises(ValueError, match="must declare DESIGN"):
        check_design("def run():\n    pass\n", path, PolicyDesign)
    with pytest.raises(ValueError, match="Invalid PolicyDesign"):
        check_design(f"DESIGN = {dict(ANSWERS, exploration='')!r}\n", path, PolicyDesign)
    with pytest.raises(ValueError, match="Invalid PolicyDesign"):
        check_design(f"DESIGN = {dict(ANSWERS, extra='x')!r}\n", path, PolicyDesign)
    with pytest.raises(ValueError, match="literal mapping"):
        check_design("DESIGN = dict(applicability='x')\n", path, PolicyDesign)


def test_only_meta_exec_programs_hold_lifecycle_authority():
    authorize_operation("program.create_candidate", "exec", meta=True)
    with pytest.raises(PermissionError, match="meta exec"):
        authorize_operation("program.create_candidate", "exec")
    with pytest.raises(PermissionError):
        authorize_operation("program.list_programs", "model", meta=True)
    with pytest.raises(PermissionError):
        authorize_operation("policy.sample", "model")
    with pytest.raises(ValueError, match="Only an exec Program"):
        ProgramSpec(1, "src/evertree/processes/x/_model.py", "0" * 40, role="model", meta=True)


def test_meta_candidates_cannot_regress_the_improvement_history():
    criteria = meta_criteria(
        AcceptanceCriteria(("contracts", "tests", "holdout"), target_metric="accuracy")
    )
    assert "improvement_history" in criteria.required_checks
    checks = {"contracts": True, "tests": True, "holdout": True, "improvement_history": True}

    def assess(candidate, baseline):
        return assess_candidate(
            criteria=criteria,
            checks=checks,
            candidate_metrics=candidate,
            baseline_metrics=baseline,
            independent=True,
        )

    baseline = {"accuracy": 0.25, "history:accuracy": 1.0}
    assert assess({"accuracy": 1.0, "history:accuracy": 1.0}, baseline).verified
    regression = assess({"accuracy": 1.0, "history:accuracy": 0.75}, baseline)
    assert regression.reasons == ("Guardrail regression: history:accuracy",)
    assert assess({"accuracy": 1.0}, baseline).missing_checks == ("guardrail:history:accuracy",)
    assert not assess({"accuracy": 0.25, "history:accuracy": 1.0}, baseline).verified
