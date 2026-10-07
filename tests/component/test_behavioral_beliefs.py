import json
import math
from dataclasses import replace

import pytest

from evertree.core.attribution import AttributionRuntime, PropertyDefinition
from evertree.core.beliefs import BeliefStore
from evertree.core.graph import UNKNOWN, ContractError, GraphDelta, GraphStore, Node
from evertree.core.learning import LearningStore
from evertree.core.memory import TraceOutputRef, TraceStore


@pytest.fixture
def lamp():
    beliefs = BeliefStore()
    beliefs.register_binary("lamp-on", prior=0.5)
    return beliefs


def observe(beliefs, source, likelihoods=(0.2, 0.8), **kwargs):
    return beliefs.assess_likelihoods(
        "lamp-on", source, likelihoods, backed=kwargs.pop("backed", True), **kwargs
    )


def property_runtime(beliefs):
    graph = GraphStore()
    graph.bootstrap(provenance="behavioral-fixture")
    subject = Node(graph.reserve_id(), "Agent A")
    prop = Node(graph.reserve_id(), "Test property", kind="property")
    graph.apply(GraphDelta(creates=(subject, prop)), provenance="behavioral-fixture")
    return AttributionRuntime(graph, beliefs), subject, prop


@pytest.mark.parametrize(
    "likelihoods",
    [(0.2, 0.8), {"false": 0.2, "true": 0.8}, {"true": 0.8, "false": 0.2}],
    ids=["ordered-sequence", "named-states", "reversed-key-order"],
)
def test_bel_01_likelihood_ratio_identifies_states_not_dictionary_order(lamp, likelihoods):
    """BEL-01: a positive observation has the same meaning in both map orders."""
    assignment = observe(lamp, "sensor-reading-1", likelihoods)
    reading = lamp.read("lamp-on")
    assert assignment.contribution == pytest.approx((math.log(4),))
    assert reading.strength == pytest.approx(0.8)
    assert reading.support == pytest.approx(math.log(4))
    assert reading.prior_support == 0
    assert reading.stats.evidence_count == 1


def test_bel_01_ambiguous_binary_state_names_do_not_mutate_belief(lamp):
    """BEL-01 boundary: a map must identify both binary states explicitly."""
    before = lamp.snapshot()
    with pytest.raises(ContractError, match="false.*true"):
        observe(lamp, "ambiguous", {"first": 0.2, "second": 0.8})
    assert lamp.snapshot() == before


def test_bel_02_conditionally_independent_observations_accumulate(lamp):
    """BEL-02: the fixture model declares independence given each H state."""
    observe(lamp, "first-observation")
    observe(lamp, "second-observation")
    reading = lamp.read("lamp-on")
    assert reading.strength == pytest.approx(16 / 17)
    assert reading.support == pytest.approx(2 * math.log(4))
    assert reading.stats.evidence_count == 2


def test_bel_03_redelivery_and_reads_preserve_one_logical_observation(lamp):
    first = observe(lamp, "delivered-event")
    before = lamp.snapshot()
    for _ in range(3):
        assert observe(lamp, "delivered-event") is first
        reading = lamp.read("lamp-on")
        assert reading.strength == pytest.approx(0.8)
        assert reading.support == pytest.approx(math.log(4))
        assert reading.stats.evidence_count == 1
    assert lamp.snapshot() == before


def test_bel_04_retellings_preserve_sources_without_extra_support(lamp):
    observe(lamp, "original-report")
    for index in range(3):
        observe(
            lamp,
            f"retelling-{index}",
            dependency_root="original-report",
            dependency_depth=1,
        )
    reading = lamp.read("lamp-on")
    assert reading.strength == pytest.approx(0.8)
    assert reading.support == pytest.approx(math.log(4))
    sources = {
        component.source_ref
        for assignment in lamp.active_assignments("lamp-on")
        for component in assignment.components
    }
    assert sources == {"original-report", "retelling-0", "retelling-1", "retelling-2"}


def test_bel_05_conflicting_evidence_cancels_effect_but_not_support(lamp):
    positive = observe(lamp, "positive")
    negative = observe(lamp, "negative", (0.8, 0.2))
    reading = lamp.read("lamp-on")
    assert reading.strength == pytest.approx(0.5)
    assert reading.support == pytest.approx(2 * math.log(4))
    assert reading.stats.evidence_count == 2
    assert lamp.active_assignments("lamp-on") == (positive, negative)


def test_bel_06_nondiscriminating_check_is_distinct_from_no_check(lamp):
    assert lamp.read("lamp-on").stats.evidence_count == 0
    assignment = observe(lamp, "uninformative-check", (0.5, 0.5))
    reading = lamp.read("lamp-on")
    assert assignment.contribution == (0.0,)
    assert assignment.evidence_mass == 0
    assert reading.strength == 0.5
    assert reading.support == 0
    assert reading.stats.evidence_count == 1


@pytest.mark.parametrize("proposal, expected", [(0.99, 0.75), (0.01, 0.25)])
def test_bel_07_unsupported_prior_is_bounded_without_creating_backing(proposal, expected):
    beliefs = BeliefStore()
    beliefs.register_binary("proposal", prior=proposal)
    reading = beliefs.read("proposal")
    assert reading.strength == pytest.approx(expected)
    assert reading.support == reading.prior_support == 0
    assert reading.stats.evidence_count == 0


def test_bel_08_approximate_assessments_share_one_influence_cap(lamp):
    assignments = [observe(lamp, source, backed=False) for source in ("first", "second")]
    reading = lamp.read("lamp-on")
    assert reading.strength == pytest.approx(0.75)
    assert reading.support == pytest.approx(math.log(3))
    assert reading.prior_support == 0
    assert reading.stats.evidence_count == 2
    assert reading.stats.max_component_mass == pytest.approx(math.log(3) / 2)
    assert all(item.evidence_mass == pytest.approx(math.log(4)) for item in assignments)


def test_bel_09_revision_replaces_contribution_and_preserves_immutable_history(lamp):
    """BEL-09 partial: store revision/history; automatic TraceEvent is a gap."""
    old = observe(lamp, "corrected-reading", created_by="assessment-v1")
    revision = lamp.revise(
        "lamp-on", "corrected-reading", -math.log(4), backed=True, created_by="assessment-v2"
    )
    reading = lamp.read("lamp-on")
    assert reading.strength == pytest.approx(0.2)
    assert reading.support == pytest.approx(math.log(4))
    assert reading.stats.evidence_count == 1
    assert lamp.active_assignments("lamp-on") == (revision,)
    assert old.contribution == pytest.approx((math.log(4),))
    assert old.created_by == "assessment-v1"
    history = {item["id"]: item for item in lamp.snapshot()["assignments"]}
    assert old.id in history and revision.id in history


def test_bel_09_revision_of_consolidated_component_replaces_whole_aggregate(lamp):
    """BEL-09/BEL-18: an obsolete aggregate cannot remain active after revise."""
    observe(lamp, "A")
    observe(lamp, "B")
    old = lamp.consolidate("lamp-on")
    lamp.revise("lamp-on", "A", -math.log(4), backed=True)
    reading = lamp.read("lamp-on")
    assert reading.strength == pytest.approx(0.5)
    assert reading.support == pytest.approx(2 * math.log(4))
    assert reading.stats.evidence_count == 2
    active = lamp.active_assignments("lamp-on")
    assert old not in active
    assert sum(item.contribution[0] for item in active) == pytest.approx(0)
    assert sum(item.evidence_mass for item in active) == pytest.approx(reading.support)
    assert old.contribution == pytest.approx((2 * math.log(4),))


def test_bel_10_retraction_removes_evidence_without_negating_it(lamp):
    """BEL-10 partial: numeric retraction/history; automatic TraceEvent is a gap."""
    original = observe(lamp, "withdrawn")
    before = lamp.snapshot()["assignments"]
    lamp.retract("lamp-on", "withdrawn")
    reading = lamp.read("lamp-on")
    assert reading.strength == 0.5
    assert reading.support == reading.prior_support == 0
    assert reading.stats.evidence_count == 0
    assert lamp.active_assignments("lamp-on") == ()
    assert lamp.snapshot()["assignments"] == before
    assert original.contribution == pytest.approx((math.log(4),))
    assert set(lamp.snapshot()["current"]["lamp-on"].values()) == {None}


def test_bel_11_categorical_property_returns_full_scope_without_fact_materialization():
    beliefs = BeliefStore()
    alternatives = ("Low", "Medium", "High")
    beliefs.register_scope("sql-level", alternatives)
    assignment = beliefs.assess_likelihoods(
        "sql-level", "sql-test", {"Low": 0.1, "Medium": 0.1, "High": 0.8}, backed=True
    )
    runtime, subject, prop = property_runtime(beliefs)
    runtime.register(
        PropertyDefinition(prop.id, scale="ordinal", classes=alternatives, source="classification")
    )
    runtime.bind_scope(subject.id, prop.id, "sql-level")
    before = runtime.graph.snapshot()
    reading = runtime.read_property(subject, prop)
    assert reading.value_U is None
    assert reading.belief_data.profile == pytest.approx({"Low": 0.1, "Medium": 0.1, "High": 0.8})
    assert sum(reading.belief_data.profile.values()) == pytest.approx(1)
    assert reading.belief_data.support == pytest.approx(math.log(8))
    assert beliefs.active_assignments("sql-level") == (assignment,)
    assert runtime.graph.snapshot() == before


def test_bel_12_compatible_skills_remain_independent_binary_questions():
    beliefs = BeliefStore()
    for skill in ("sql", "python"):
        beliefs.register_binary(skill)
        beliefs.assess_likelihoods(skill, f"{skill}-test", (0.2, 0.8), backed=True)
    assert beliefs.read("sql").strength == pytest.approx(0.8)
    assert beliefs.read("python").strength == pytest.approx(0.8)
    assert beliefs.read("sql").profile is beliefs.read("python").profile is None


def test_bel_13_process_variability_and_model_belief_use_different_states():
    learning = LearningStore()
    state = learning.create_state("categorical", categories=("Success", "Failure"))
    beliefs = BeliefStore()
    beliefs.register_binary("model-correct")
    beliefs.assign("model-correct", "independent-validation", math.log(19), backed=True)
    assert learning.predict(state) == {"Success": 0.5, "Failure": 0.5}
    assert beliefs.read("model-correct").strength == pytest.approx(0.95)
    assert beliefs.read("model-correct").support == pytest.approx(math.log(19))


def test_bel_14_own_evidence_cannot_return_through_prototype_as_extra_backing():
    beliefs = BeliefStore()
    beliefs.register_binary("instance")
    beliefs.register_binary("prototype")
    source = TraceOutputRef(1, ("observation",))
    for target in ("instance", "prototype"):
        beliefs.assign(target, source, math.log(4), backed=True)
    beliefs.set_prior_source("instance", "prototype")
    reading = beliefs.read("instance")
    assert reading.prior_support == 0
    assert reading.support == pytest.approx(math.log(4))
    assert reading.strength == pytest.approx(0.8)


def test_bel_15_hypothetical_property_result_retains_its_conditions():
    """BEL-15 partial: reads preserve an existing conditional result, not inference."""
    runtime, subject, prop = property_runtime(BeliefStore())
    runtime.register(PropertyDefinition(prop.id, unit="h"))
    conditions = {"assumed_speed_kmh": 50, "distance_km": 100}
    fact = runtime.graph.new_fact(
        "HAS_NUMERIC_VALUE",
        {"entity": subject.id, "property": prop.id, "value": 2, "unit": "h"},
    )
    fact = replace(fact, properties={"conditions": conditions})
    runtime.graph.apply(GraphDelta(creates=(fact,)), provenance="hypothetical-result")
    before = runtime.graph.snapshot()
    reading = runtime.read_property(subject, prop, **conditions)
    assert reading.value_U == 2
    assert reading.conditions == conditions
    assert runtime.read_property(subject, prop) is UNKNOWN
    assert runtime.graph.snapshot() == before


def test_bel_18_consolidation_preserves_logical_count_and_resolvable_sources(lamp):
    memory = TraceStore()
    run = memory.start_run("sensor", "fixture-revision", {})
    events = [memory.record(run, "observe", output={"light": True}) for _ in range(2)]
    for event in events:
        observe(lamp, TraceOutputRef(event.id))
    before = lamp.read("lamp-on")
    merged = lamp.consolidate("lamp-on")
    reading = lamp.read("lamp-on")
    assert reading == before
    assert reading.strength == pytest.approx(16 / 17)
    assert reading.support == pytest.approx(2 * math.log(4))
    assert reading.stats.evidence_count == 2
    assert lamp.active_assignments("lamp-on") == (merged,)
    assert all(
        memory.resolve(TraceOutputRef(**component.source_ref)) == {"light": True}
        for component in merged.components
    )


def test_mem_08_consolidation_and_retraction_match_uncompressed_control(lamp):
    """MEM-08: exact retained components support a source-specific withdrawal."""
    observe(lamp, "A")
    observe(lamp, "B", (0.25, 0.75))
    control = BeliefStore.from_snapshot(json.loads(json.dumps(lamp.snapshot())))
    aggregate = lamp.consolidate("lamp-on")
    assert lamp.read("lamp-on") == control.read("lamp-on")
    lamp.retract("lamp-on", "A")
    control.retract("lamp-on", "A")
    assert lamp.read("lamp-on") == control.read("lamp-on")
    active = lamp.active_assignments("lamp-on")
    assert aggregate not in active
    assert [component.source_ref for item in active for component in item.components] == ["B"]
    assert sum(item.evidence_mass for item in active) == pytest.approx(math.log(3))
    restored = BeliefStore.from_snapshot(json.loads(json.dumps(lamp.snapshot())))
    assert restored.read("lamp-on") == control.read("lamp-on")


def test_bel_18_partial_reconsolidation_does_not_leave_overlapping_active_aggregates(lamp):
    """BEL-18: regrouping a retained component preserves one representation per unit."""
    for source in ("A", "B", "C"):
        observe(lamp, source)
    old = lamp.consolidate("lamp-on", ("A", "B"))
    before = lamp.read("lamp-on")
    lamp.consolidate("lamp-on", ("B", "C"))
    assert lamp.read("lamp-on") == before
    active = lamp.active_assignments("lamp-on")
    assert old not in active
    assert sorted(component.source_ref for item in active for component in item.components) == [
        "A",
        "B",
        "C",
    ]
    assert sum(item.evidence_mass for item in active) == pytest.approx(before.support)


def test_bel_19_likelihood_model_does_not_apply_a_second_reliability_penalty(lamp):
    """BEL-19 partial: assessment uses supplied likelihoods; no source-model training."""
    runtime, source, reliability = property_runtime(lamp)
    runtime.register(PropertyDefinition(reliability.id))
    fact = runtime.graph.new_fact(
        "HAS_NUMERIC_VALUE",
        {"entity": source.id, "property": reliability.id, "value": 0.75},
    )
    runtime.graph.apply(GraphDelta(creates=(fact,)), provenance="source-reliability")
    observe(lamp, f"source-{source.id}-report")
    assert runtime.read_property(source, reliability).value_U == 0.75
    assert lamp.read("lamp-on").strength == pytest.approx(0.8)
    assert lamp.read("lamp-on").support == pytest.approx(math.log(4))
    assert lamp.read("lamp-on").stats.evidence_count == 1


def test_bel_20_scope_identity_cannot_be_reused_with_new_alternatives():
    """BEL-20 partial: target contract guard; automatic semantic revision is a gap."""
    beliefs = BeliefStore()
    beliefs.register_scope("alarm-v1", ("Fire", "Intrusion"))
    old = beliefs.assess_likelihoods(
        "alarm-v1", "observation", {"Fire": 0.8, "Intrusion": 0.2}, backed=True
    )
    before = beliefs.read("alarm-v1")
    with pytest.raises(ContractError, match="different contract"):
        beliefs.register_scope("alarm-v1", ("Fire", "Intrusion", "NoTrigger"))
    beliefs.register_scope("alarm-v2", ("Fire", "Intrusion", "NoTrigger"))
    assert beliefs.read("alarm-v1") == before
    assert beliefs.active_assignments("alarm-v1") == (old,)
    assert beliefs.read("alarm-v2").support == 0
    assert beliefs.active_assignments("alarm-v2") == ()
    assert beliefs.read("alarm-v2").profile == pytest.approx(
        {"Fire": 1 / 3, "Intrusion": 1 / 3, "NoTrigger": 1 / 3}
    )


def test_int_03_current_property_read_observes_retraction():
    """INT-03 partial: current attribution read; automatic plan verification is a gap."""
    beliefs = BeliefStore()
    beliefs.register_binary("bridge-open")
    beliefs.assign("bridge-open", "report", math.log(4), backed=True)
    runtime, bridge, opened = property_runtime(beliefs)
    runtime.register(PropertyDefinition(opened.id))
    fact = runtime.graph.new_fact(
        "HAS_NUMERIC_VALUE",
        {"entity": bridge.id, "property": opened.id, "value": 1},
        belief_target="bridge-open",
    )
    runtime.graph.apply(GraphDelta(creates=(fact,)), provenance="report")
    historical = runtime.read_property(bridge, opened)
    beliefs.retract("bridge-open", "report")
    current = runtime.read_property(bridge, opened)
    assert current.belief_data.strength == 0.5
    assert current.belief_data.support == 0
    assert historical.belief_data.strength == pytest.approx(0.8)


def test_int_04_choice_probability_is_preserved_without_self_confirmation():
    """INT-04 partial: trace round trip; no probabilistic choice policy is executed."""
    beliefs = BeliefStore()
    beliefs.register_binary("A-succeeds", prior=0.6)
    before = beliefs.snapshot()
    memory = TraceStore()
    run = memory.start_run("choice", "fixture-revision", {"belief": beliefs.read("A-succeeds")})
    event = memory.record(run, "select", output={"chosen": "A", "behavior_probability": 0.8})
    restored = TraceStore.from_snapshot(json.loads(json.dumps(memory.snapshot())))
    assert restored.resolve(TraceOutputRef(event.id))["behavior_probability"] == 0.8
    assert beliefs.read("A-succeeds").strength == pytest.approx(0.6)
    assert beliefs.read("A-succeeds").support == 0
    assert beliefs.snapshot() == before
