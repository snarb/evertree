import json
import math

import pytest

from evertree.core.beliefs import BeliefStore
from evertree.core.memory.types import TraceOutputRef
from evertree.core.values import ContractError


def test_binary_dedup_revision_retraction_and_zero_evidence():
    beliefs = BeliefStore()
    beliefs.register_binary("claim")
    first = beliefs.assign("claim", TraceOutputRef(1), math.log(4), backed=True)
    assert beliefs.read("claim").strength == pytest.approx(0.8)
    assert beliefs.assign("claim", TraceOutputRef(1), math.log(4), backed=True) is first
    beliefs.assign("claim", TraceOutputRef(2), 0, backed=True)
    assert beliefs.read("claim").stats.evidence_count == 2
    beliefs.revise("claim", TraceOutputRef(1), -math.log(4), backed=True)
    assert beliefs.read("claim").strength == pytest.approx(0.2)
    beliefs.retract("claim", TraceOutputRef(1))
    assert beliefs.read("claim").strength == 0.5
    assert beliefs.read("claim").stats.evidence_count == 1
    assert beliefs.read("claim").support == 0


def test_shared_approximate_influence_cap_is_not_posterior_clipping():
    beliefs = BeliefStore()
    beliefs.register_binary("claim", 0.999)
    for index in range(20):
        beliefs.assign("claim", f"source-{index}", 10)
    reading = beliefs.read("claim")
    assert reading.strength <= 0.750000001
    assert reading.support <= math.log(3)
    beliefs.assign("claim", "independent-verified", 10, backed=True)
    assert beliefs.read("claim").strength > 0.99
    assert beliefs.read("claim").prior_support == 0


def test_scope_centering_and_conservation_through_consolidation():
    beliefs = BeliefStore()
    beliefs.register_scope("state", ["low", "normal", "high"])
    beliefs.assign("state", "zero", {"low": 5, "normal": 5, "high": 5}, backed=True)
    beliefs.assign("state", "one", {"low": 2, "normal": 0, "high": -2}, backed=True)
    beliefs.assign("state", "two", {"low": -2, "normal": 0, "high": 2}, backed=True)
    before = beliefs.read("state")
    assert before.support == 8
    assert before.stats.evidence_count == 3
    assert sum(before.profile.values()) == pytest.approx(1)
    consolidated = beliefs.consolidate("state")
    assert consolidated.evidence_mass == 8
    assert consolidated.contribution == (0, 0, 0)
    assert beliefs.read("state") == before
    beliefs.retract("state", "one")
    assert beliefs.read("state").profile["high"] > beliefs.read("state").profile["low"]


def test_consolidation_preserves_approximate_cap_and_source_dependencies():
    beliefs = BeliefStore()
    beliefs.register_binary("claim")
    beliefs.assign("claim", "original", 3, dependency_root="report", dependency_depth=0)
    beliefs.assign("claim", "retelling", 100, dependency_root="report", dependency_depth=1)
    beliefs.assign("claim", "other", -2)
    before = beliefs.read("claim")
    assert before.stats.evidence_count == 2
    beliefs.consolidate("claim")
    assert beliefs.read("claim") == before
    beliefs.assign("claim", "original", -3, dependency_root="report", dependency_depth=0)
    assert beliefs.read("claim").strength < before.strength


def test_prior_transfer_excludes_own_source_and_has_separate_support():
    beliefs = BeliefStore()
    beliefs.register_binary("type")
    beliefs.register_binary("instance")
    beliefs.assign("type", "source", 2, backed=True)
    beliefs.set_prior_source("instance", "type", applicability=0.5)
    assert beliefs.read("instance").support == 0
    assert beliefs.read("instance").prior_support == 1
    beliefs.assign("instance", "source", 2, backed=True)
    assert beliefs.read("instance").support == 2
    assert beliefs.read("instance").prior_support == 0
    with pytest.raises(ContractError, match="cycle"):
        beliefs.set_prior_source("type", "instance")


def test_likelihood_assessment_and_snapshot_round_trip():
    beliefs = BeliefStore()
    beliefs.register_binary("claim")
    beliefs.assess_likelihoods(
        "claim", TraceOutputRef(2, ("observation",)), [0.2, 0.8], backed=True
    )
    restored = BeliefStore.from_snapshot(json.loads(json.dumps(beliefs.snapshot())))
    assert restored.read("claim") == beliefs.read("claim")
    restored.retract("claim", TraceOutputRef(2, ("observation",)))
    assert restored.read("claim").strength == 0.5
    with pytest.raises(ContractError):
        beliefs.register_binary("impossible", 0)
    with pytest.raises(ContractError):
        beliefs.register_scope("invalid", ["x", "y"], {"x": 0.8, "y": 0.8})


def test_categorical_unsupported_prior_and_evidence_never_exceed_cap():
    beliefs = BeliefStore()
    beliefs.register_scope(
        "state", ["a", "b", "c", "d"], {"a": 0.997, "b": 0.001, "c": 0.001, "d": 0.001}
    )
    for index in range(10):
        beliefs.assign("state", index, {"a": 100, "b": 0, "c": 0, "d": 0})
    reading = beliefs.read("state")
    assert max(reading.profile.values()) <= 0.750000001
    assert reading.support <= math.log(9)


def test_prior_transfer_preserves_unsupported_prior_without_creating_support():
    beliefs = BeliefStore()
    beliefs.register_binary("type", 0.7)
    beliefs.register_binary("instance")
    beliefs.set_prior_source("instance", "type")
    reading = beliefs.read("instance")
    assert reading.strength == pytest.approx(0.7)
    assert reading.support == reading.prior_support == 0
