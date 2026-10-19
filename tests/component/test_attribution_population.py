"""Natural numeric knowledge through real source-backed writes and common reads."""

import json
import math
from datetime import UTC, datetime

import pytest

from evertree.core.attribution import AttributionRuntime
from evertree.core.beliefs import BeliefStore
from evertree.core.graph.store import GraphStore
from evertree.core.graph.types import GraphDelta, Node, NodeUpdate
from evertree.core.memory.types import TraceOutputRef
from evertree.core.semantics.api import summarize_property
from evertree.core.values import UNKNOWN, ContractError, json_value
from tests.support.attribution import Population
from tests.support.semantics import context, recorded_experience, write_action


def test_separate_observations_are_immediately_usable_without_training_or_read_mutation():
    population = Population()
    dachshund = population.create("create_prototype", "Dachshund", parent=population.domain)
    population.measurement(8, name="Jack")
    assert population.report()["observations"]["mean"] == 8
    population.measurement(5, name="Tanya's dog", prototype=dachshund)
    population.measurement(10, name="Newspaper dog")
    world = population.world
    before = (
        world.graph.snapshot(),
        world.attribution.snapshot(),
        world.operations.beliefs.snapshot(),
    )
    report = population.report(value=7, unit="kg")
    observations = report["observations"]
    assert observations["count"] == 3
    assert observations["mean"] == pytest.approx(23 / 3)
    assert observations["median"] == 8
    assert observations["comparison"]["difference_from_mean"] == pytest.approx(-2 / 3)
    assert observations["comparison"]["count_below_value"] == 1
    assert observations["comparison"]["count_above_value"] == 2
    assert observations["belief_data"] is None
    assert all(item["belief_status"] == "unassessed" for item in observations["items"])
    assert all(item["source"]["provenance"]["event_ref"] for item in observations["items"])
    assert report["references"] == []
    assert "interpretation" not in observations
    assert before == (
        world.graph.snapshot(),
        world.attribution.snapshot(),
        world.operations.beliefs.snapshot(),
    )


def test_reference_rules_and_weighted_tables_remain_separate_from_individuals_after_restore():
    population = Population()
    for name, value in (("Jack", 8), ("Tanya's dog", 5), ("Newspaper dog", 10)):
        population.measurement(value, name=name)
    classes = [population.create("create_concept", name) for name in ("Small", "Medium", "Large")]
    guide = population.reference("bands", name="Club guide", boundaries=[6, 9], classes=classes)
    population.reference(
        "distribution",
        name="Club survey",
        samples=[
            {"lower": value, "upper": value, "count": count}
            for value, count in ((3, 1), (6, 3), (9, 4), (12, 2))
        ],
    )
    report = population.report(value=7, unit="kg")
    assert report["observations"]["count"] == 3
    assert report["references"][0]["interpretation"]["class"]["id"] == classes[1]
    assert report["references"][1]["summary"]["count"] == 10
    assert report["references"][1]["summary"]["mean"] == pytest.approx(8.1)
    assert len(population.report(reference=guide)["references"]) == 1
    assert (
        population.report(value=6, unit="kg", reference=guide)["references"][0]["interpretation"][
            "class"
        ]["id"]
        == classes[0]
    )
    graph = GraphStore.from_snapshot(json.loads(json.dumps(population.world.graph.snapshot())))
    beliefs = BeliefStore.from_snapshot(
        json.loads(json.dumps(population.world.operations.beliefs.snapshot()))
    )
    restored = AttributionRuntime.from_snapshot(
        population.world.attribution.snapshot(), graph, beliefs
    )
    assert (
        restored.summarize_property(population.domain, population.property, value=7, unit="kg")
        == report
    )


def test_repeats_corrections_units_and_missing_units_do_not_inflate_sample():
    population = Population()
    jack, _ = population.measurement(8, name="Jack")
    population.measurement(8000, subject=jack, unit="g")
    tanya, _ = population.measurement(5000, name="Tanya's dog", unit="g")
    reading = population.world.attribution.read_property(tanya, population.property)
    assert reading.value_U == 5
    assert reading.unit == "kg"
    _, fact = population.measurement(100, name="Newspaper dog")
    population.measurement(9, name="Missing unit", unit=None)
    before = population.report()
    old = population.world.graph.get(fact)
    corrected = population.write("update", object=fact, changes={"args": {**old.args, "value": 10}})
    assert "error" not in corrected
    after = population.report(value=7000, unit="g")
    assert after["observations"]["count"] == 3
    assert after["observations"]["mean"] == pytest.approx(23 / 3)
    assert after["observations"]["comparison"]["value"] == 7
    assert len(after["excluded"]) == 1
    assert before["observations"]["belief_target"] != after["observations"]["belief_target"]
    with pytest.raises(ContractError, match="Cannot convert"):
        population.report(value=7, unit="s")


def test_source_belief_and_population_belief_are_separate_and_reads_keep_support():
    population = Population()
    _, fact_id = population.measurement(8, name="Jack")
    world = population.world
    beliefs = world.operations.beliefs
    beliefs.register_binary("jack-weighs-eight")
    beliefs.assess_likelihoods("jack-weighs-eight", "owner", {"false": 0.2, "true": 0.8})
    world.graph.apply(
        GraphDelta(updates=(NodeUpdate(fact_id, {"belief_target": "jack-weighs-eight"}),)),
        provenance="assessment",
    )
    report = population.report(value=7, unit="kg")
    assert report["observations"]["items"][0]["belief_data"]["strength"] > 0.5
    assert report["observations"]["belief_data"] is None
    target = report["observations"]["belief_target"]
    refs, metadata = recorded_experience(
        world, "One dog's weight is weak evidence for the whole dog population"
    )
    world.operations.execute(
        "evidence.assess",
        {
            "target": target,
            "source_ref": refs[0],
            "likelihoods": {"false": 0.8, "true": 0.2},
        },
        metadata=metadata,
    )
    learned = population.report(value=7, unit="kg")["observations"]
    assert learned["belief_data"]["strength"] < 0.5
    assert learned["mean"] == 8
    snapshot = beliefs.snapshot()
    assert (
        population.report(value=9, unit="kg")["observations"]["belief_data"]
        == learned["belief_data"]
    )
    assert beliefs.snapshot() == snapshot
    assert learned["belief_data"]["support"] != learned["count"]


def test_prior_only_beliefs_are_not_presented_as_evidence_assessments():
    population = Population()
    _, fact_id = population.measurement(8, name="Jack")
    world = population.world
    target = population.report()["observations"]["belief_target"]
    world.operations.beliefs.register_binary(target)
    assert population.report()["observations"]["belief_status"] == "prior_only"
    world.operations.beliefs.register_binary("jack-report")
    world.graph.apply(
        GraphDelta(updates=(NodeUpdate(fact_id, {"belief_target": "jack-report"}),)),
        provenance="prior binding",
    )
    assert population.report()["observations"]["items"][0]["belief_status"] == "prior_only"
    target = population.report()["observations"]["belief_target"]
    world.operations.beliefs.register_binary(target)
    world.operations.beliefs.assess_likelihoods(target, "checked", {"false": 1, "true": 1})
    report = population.report()["observations"]
    assert report["belief_data"]["support"] == 0
    assert report["belief_status"] == "assessed"


def test_explicit_world_time_preserves_unique_selection_and_non_numeric_source_contract():
    population = Population()
    dog, _ = population.measurement(5, name="Jack")
    population.measurement(10, subject=dog)
    graph = population.world.graph
    binding = dict(graph.get(population.property).properties["attribution"])
    binding["selection"] = "unique"
    graph.apply(
        GraphDelta(
            updates=(NodeUpdate(population.property, {"properties": {"attribution": binding}}),)
        ),
        provenance="selection contract",
    )
    at = datetime(2026, 1, 1, tzinfo=UTC)
    assert (
        population.world.attribution.read_property(dog, population.property, valid_at=at) is UNKNOWN
    )
    report = population.report(valid_at=at)
    assert report["observations"]["count"] == 0
    assert report["excluded"][0]["reason"] == "unresolved_property_reading"
    assert population.report()["observations"]["mean"] == 10
    binding["source"] = "program"
    graph.apply(
        GraphDelta(
            updates=(NodeUpdate(population.property, {"properties": {"attribution": binding}}),)
        ),
        provenance="computed property",
    )
    with pytest.raises(ContractError, match="numeric fact source"):
        population.report()


def test_reference_preserves_mixed_boundary_inclusion():
    population = Population()
    classes = [population.create("create_concept", name) for name in ("Small", "Medium", "Large")]
    population.reference(
        "bands", boundaries=[6, 9], classes=classes, boundary_inclusive=[False, True]
    )
    for value, expected in ((5.9, 0), (6, 1), (9, 1), (9.1, 2)):
        interpretation = population.report(value=value, unit="kg")["references"][0][
            "interpretation"
        ]
        assert interpretation["class"]["id"] == classes[expected]
        if expected == 1:
            assert interpretation["lower_bound"] == 6
            assert interpretation["lower_inclusive"] is True
            assert interpretation["upper_bound"] == 9
            assert interpretation["upper_inclusive"] is True


def test_reference_population_must_belong_to_property_domain():
    population = Population()
    cat = population.create("create_prototype", "Cat", parent=None)
    before = population.world.graph.snapshot()
    result = population.write(
        "create_property_reference",
        name="Cat survey",
        description=None,
        property=population.property,
        domain=cat,
        unit="kg",
        reference_kind="distribution",
        boundaries=[],
        classes=[],
        samples=[{"lower": 3, "upper": 3, "count": 2}],
        conditions={},
    )
    assert "error" in result
    assert population.world.graph.snapshot() == before


def test_historical_reports_are_learned_but_explicit_world_time_retains_unknown():
    population = Population()
    dog = population.create("create_instance", "Historical dog", prototype=population.domain)
    facet = population.create(
        "create_facet",
        "Past weight",
        instance=dog,
        valid_from="2000-01-01T00:00:00Z",
        valid_until="2001-01-01T00:00:00Z",
    )
    population.measurement(10, subject=facet)
    assert population.report()["observations"]["mean"] == 10
    assert population.report()["time_basis"] == "latest_recorded"
    assert (
        population.report(valid_at=datetime(2000, 6, 1, tzinfo=UTC))["observations"]["count"] == 1
    )
    assert (
        population.report(valid_at=datetime(2026, 1, 1, tzinfo=UTC))["observations"]["count"] == 0
    )
    world = population.world
    before = (world.graph.snapshot(), world.attribution.snapshot(), world.memory.snapshot())
    at = datetime(2000, 6, 1, tzinfo=UTC)
    public_report = world.operations.execute(
        "graph.summarize_property",
        {"domain": population.domain, "property": population.property, "at": at.isoformat()},
        metadata={"task_id": "reader", "program": {"role": "model", "revision": "test"}},
    )
    assert public_report == population.report(valid_at=at)
    assert public_report["at"] == at.isoformat()
    item = public_report["observations"]["items"][0]
    assert item["valid_from"] == "2000-01-01T00:00:00+00:00"
    assert item["valid_until"] == "2001-01-01T00:00:00+00:00"
    assert (world.graph.snapshot(), world.attribution.snapshot(), world.memory.snapshot()) == before


def test_grouped_distribution_reports_estimate_bounds_without_inventing_individuals():
    population = Population()
    population.reference(
        "distribution",
        samples=[
            {"lower": 0, "upper": 10, "count": 2},
            {"lower": 10, "upper": 20, "count": 3},
        ],
    )
    report = population.report(value=7, unit="kg")
    assert report["observations"]["count"] == 0
    summary = report["references"][0]["summary"]
    assert summary["mean"] == 11
    assert summary["mean_bounds"] == [6, 16]
    assert summary["approximate"] is True
    assert population.world.graph.nodes(kind="instance") == ()


@pytest.mark.parametrize(
    "invalid",
    [
        {"reference_kind": "bands", "boundaries": [10, 5], "samples": []},
        {"reference_kind": "distribution", "samples": [{"lower": 4, "upper": 3, "count": 2}]},
        {"reference_kind": "distribution", "samples": [{"lower": 3, "upper": 3, "count": 0}]},
        {"reference_kind": "distribution", "samples": [{"lower": 3, "upper": 3, "count": True}]},
    ],
)
def test_invalid_references_are_rejected_atomically(invalid):
    population = Population()
    before = population.world.graph.snapshot()
    result = population.write(
        "create_property_reference",
        name="Invalid reference",
        description=None,
        property=population.property,
        domain=population.domain,
        unit="kg",
        classes=[],
        conditions={},
        **{"boundaries": [], **invalid},
    )
    assert "error" in result
    assert population.world.graph.snapshot() == before


def test_reference_dependencies_cannot_be_deleted_or_retyped_silently():
    population = Population()
    reference = population.reference("distribution", samples=[{"lower": 3, "upper": 3, "count": 2}])
    before = population.world.graph.snapshot()
    result = population.write("delete", objects=[population.property])
    assert "error" in result
    assert population.world.graph.snapshot() == before
    assert population.world.graph.get(reference)


def test_missing_reference_conditions_are_discoverable_without_assuming_they_hold():
    population = Population()
    reference = population.reference(
        "distribution",
        conditions={"activity": "resting"},
        samples=[{"lower": 3, "upper": 3, "count": 2}],
    )
    report = population.report()
    assert report["references"] == []
    assert report["reference_candidates"][0]["id"] == reference
    assert report["reference_candidates"][0]["conditions"] == {"activity": "resting"}
    applied = population.report(activity="resting")
    assert applied["references"][0]["summary"]["mean"] == 3
    assert applied["reference_candidates"] == []


def test_evidence_preview_is_bounded_but_statistics_use_all_individuals():
    population = Population()
    for index in range(25):
        population.measurement(index, name=f"Dog {index}")
    report = population.report()["observations"]
    assert report["count"] == report["items_total"] == 25
    assert report["mean"] == 12
    assert len(report["items"]) == 20


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_nonfinite_or_boolean_values_are_rejected_at_write_and_read(value):
    population = Population()
    with pytest.raises(ContractError, match="finite numeric"):
        population.report(value=value, unit="kg")
    _, fact = population.measurement(8, name="Jack")
    graph = population.world.graph
    before = graph.snapshot()
    args = {**graph.get(fact).args, "value": value}
    with pytest.raises(ContractError, match="finite"):
        graph.apply(GraphDelta(updates=(NodeUpdate(fact, {"args": args}),)), provenance="invalid")
    assert graph.snapshot() == before


def test_conflicting_guides_remain_separate_and_explicit_reference_does_not_choose_evidence():
    population = Population()
    population.measurement(8, name="Jack")
    classes = [population.create("create_concept", name) for name in ("Small", "Large")]
    narrow = population.reference("bands", name="Narrow guide", boundaries=[6], classes=classes)
    broad = population.reference("bands", name="Broad guide", boundaries=[10], classes=classes)
    before = population.world.graph.snapshot()
    report = population.report(value=8, unit="kg")
    interpretations = {item["id"]: item for item in report["references"]}
    assert interpretations[narrow]["interpretation"]["class"]["id"] == classes[1]
    assert interpretations[broad]["interpretation"]["class"]["id"] == classes[0]
    assert interpretations[narrow]["source"] != interpretations[broad]["source"]
    selected = population.report(value=8, unit="kg", reference=broad)
    assert selected["references"] == [interpretations[broad]]
    assert selected["observations"] == report["observations"]
    assert selected["references"][0]["belief_data"] is None
    assert population.world.graph.facts("CLASSIFIED_AS") == ()
    assert population.world.graph.snapshot() == before


def test_breed_subtypes_supply_observations_but_never_inherit_a_population_reference():
    population = Population()
    dachshund = population.create("create_prototype", "Dachshund", parent=population.domain)
    miniature = population.create("create_prototype", "Miniature dachshund", parent=dachshund)
    terrier = population.create("create_prototype", "Terrier", parent=population.domain)
    for name, value, prototype in (
        ("Dog One", 20, population.domain),
        ("Dog Two", 7, dachshund),
        ("Dog Three", 3, miniature),
        ("Dog Four", 8, terrier),
    ):
        population.measurement(value, name=name, prototype=prototype)
    classes = [population.create("create_concept", name) for name in ("Small", "Large")]
    all_dogs = population.reference("bands", name="Dog guide", boundaries=[10], classes=classes)
    breed = population.reference(
        "bands", name="Dachshund guide", domain=dachshund, boundaries=[4], classes=classes
    )
    report = population.report(value=7, unit="kg")
    assert report["observations"]["count"] == 4
    assert report["observations"]["mean"] == 9.5
    assert [item["id"] for item in report["references"]] == [all_dogs]
    assert report["references"][0]["interpretation"]["class"]["id"] == classes[0]
    assert report["reference_candidates"] == [
        {
            "id": breed,
            "name": "Dachshund guide",
            "domain": {"id": dachshund, "name": "Dachshund"},
            "conditions": {},
            "status": "different_population",
        }
    ]
    local = population.report(domain=dachshund, value=7, unit="kg")
    assert local["observations"]["count"] == 2
    assert local["observations"]["mean"] == 5
    assert local["references"][0]["interpretation"]["class"]["id"] == classes[1]
    explicit_parent = population.report(domain=dachshund, reference=all_dogs)
    assert explicit_parent["references"] == []
    assert explicit_parent["reference_candidates"][0]["status"] == "different_population"
    assert explicit_parent["observations"]["items"] == local["observations"]["items"]
    assert (
        explicit_parent["observations"]["belief_target"] == local["observations"]["belief_target"]
    )


def test_reference_units_are_converted_for_reading_without_rewriting_the_source():
    population = Population()
    classes = [population.create("create_concept", name) for name in ("Small", "Medium", "Large")]
    guide = population.reference(
        "bands", name="Gram guide", unit="g", boundaries=[6000, 9000], classes=classes
    )
    table = population.reference(
        "distribution",
        name="Gram table",
        unit="g",
        samples=[
            {"lower": 5000, "upper": 5000, "count": 1},
            {"lower": 8000, "upper": 8000, "count": 2},
        ],
    )
    before = population.world.graph.snapshot()
    report = population.report(value=7000, unit="g")
    references = {item["id"]: item for item in report["references"]}
    assert report["unit"] == "kg"
    assert references[guide]["boundaries"] == [6, 9]
    assert references[guide]["interpretation"]["class"]["id"] == classes[1]
    assert references[guide]["interpretation"]["value"] == 7
    assert references[table]["summary"]["count"] == 3
    assert references[table]["summary"]["mean"] == 7
    assert references[table]["summary"]["comparison"]["count_below_value"] == 1
    assert references[table]["summary"]["comparison"]["count_above_value"] == 2
    assert population.world.graph.get(guide).properties["numeric_reference"]["unit"] == "g"
    assert population.world.graph.snapshot() == before


@pytest.mark.parametrize(
    ("unit", "canonical", "measurements"),
    [
        ("кг", "kg", [(1, "kg"), (2000, "g"), (3000, "г"), (4000000, "мг")]),
        ("м", "m", [(1, "m"), (200, "см"), (3000, "мм"), (0.004, "км")]),
        ("с", "s", [(1, "s"), (2000, "мс"), (3000000, "мкс"), (4000000, "µs"), (5000000, "μs")]),
    ],
)
async def test_public_reads_convert_russian_unit_symbols_without_rewriting_sources(
    unit, canonical, measurements
):
    population = Population()
    population.property = population.create(
        "create_property", "Measured quantity", unit=unit, applies_to=[population.domain]
    )
    facts = []
    for index, (value, source_unit) in enumerate(measurements):
        facts.append(population.measurement(value, name=f"Dog {index}", unit=source_unit))
    classes = [population.create("create_concept", name) for name in ("Lower", "Higher")]
    guide = population.reference(
        "bands", name="Source guide", unit=canonical, boundaries=[2.5], classes=classes
    )
    table = population.reference(
        "distribution",
        name="Source table",
        unit=canonical,
        samples=[{"lower": 1, "upper": 1, "count": 1}, {"lower": 3, "upper": 3, "count": 1}],
    )
    world = population.world
    before = (world.graph.snapshot(), world.attribution.snapshot(), world.memory.snapshot())
    ctx = context(world, None, role="model")
    report = await summarize_property(ctx, "Dog", "Measured quantity", value=3, unit=canonical)
    assert report["unit"] == unit
    assert report["observations"]["count"] == len(measurements)
    assert report["observations"]["mean"] == pytest.approx((len(measurements) + 1) / 2)
    assert report["observations"]["comparison"]["value"] == 3
    references = {item["id"]: item for item in report["references"]}
    assert references[guide]["interpretation"]["class"]["id"] == classes[1]
    assert references[table]["summary"]["mean"] == 2
    reading = await ctx.step(
        "graph.read_property", {"subject": facts[1][0], "property": population.property}
    )
    assert reading["value_U"] == 2 and reading["unit"] == unit
    for (_, fact), (_, source_unit) in zip(facts, measurements):
        assert world.graph.get(fact).args["unit"] == source_unit
    assert world.graph.get(guide).properties["numeric_reference"]["unit"] == canonical
    assert before == (world.graph.snapshot(), world.attribution.snapshot(), world.memory.snapshot())


def test_unknown_facet_time_is_retained_in_experience_but_cannot_be_claimed_at_an_instant():
    population = Population()
    unknown_dog = population.create("create_instance", "Undated dog", prototype=population.domain)
    unknown = population.create(
        "create_facet", "Undated weight", instance=unknown_dog, valid_from=None, valid_until=None
    )
    _, unknown_fact = population.measurement(3, subject=unknown)
    uncertain_dog = population.create(
        "create_instance", "Conflicted dog", prototype=population.domain
    )
    dated = population.create(
        "create_facet",
        "Dated weight",
        instance=uncertain_dog,
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2026-02-01T00:00:00Z",
    )
    population.measurement(5, subject=dated)
    undated = population.create(
        "create_facet",
        "Uncertain weight",
        instance=uncertain_dog,
        valid_from=None,
        valid_until=None,
    )
    _, conflicting_fact = population.measurement(7, subject=undated)
    known_dog, _ = population.measurement(8, name="Known dog")
    recorded = population.report()
    assert recorded["observations"]["count"] == 3
    assert recorded["observations"]["mean"] == 6
    assert recorded["observations"]["items"][0]["valid_from"] is None
    assert recorded["observations"]["items"][0]["valid_until"] is None
    dated_report = population.report(valid_at=datetime(2026, 1, 15, tzinfo=UTC))
    assert [item["subject"] for item in dated_report["observations"]["items"]] == [known_dog]
    temporal = {item["fact"] for item in dated_report["excluded"] if "fact" in item}
    assert temporal == {unknown_fact, conflicting_fact}
    assert {"subject": uncertain_dog, "reason": "unresolved_property_reading"} in dated_report[
        "excluded"
    ]


@pytest.mark.parametrize("selection", ["unique", "max_support"])
def test_overlapping_world_states_obey_selection_without_changing_latest_recorded(selection):
    """Only belief bindings use fixture setup; facts and selection use source-backed writes."""
    population = Population()
    dog = population.create("create_instance", "Jack", prototype=population.domain)
    facts = []
    for name, start, end, value in (
        ("January weight", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", 5),
        ("Later weight", "2026-01-15T00:00:00Z", "2026-02-15T00:00:00Z", 10),
    ):
        facet = population.create(
            "create_facet", name, instance=dog, valid_from=start, valid_until=end
        )
        facts.append(population.measurement(value, subject=facet)[1])
    graph, beliefs = population.world.graph, population.world.operations.beliefs
    definition = json_value(graph.get(population.property).properties["attribution"])
    result = population.write(
        "update",
        object=population.property,
        changes={"properties": {"attribution": {**definition, "selection": selection}}},
    )
    assert "error" not in result, result
    for fact, probability in zip(facts, (0.9, 0.6)):
        target = f"measurement:{fact}"
        refs, metadata = recorded_experience(population.world, f"Assessment of measurement {fact}")
        population.world.operations.execute(
            "evidence.assess",
            {
                "target": target,
                "source_ref": refs[0],
                "likelihoods": {"false": 1 - probability, "true": probability},
            },
            metadata=metadata,
        )
        graph.apply(
            GraphDelta(updates=(NodeUpdate(fact, {"belief_target": target}),)),
            provenance="belief binding",
        )
    assert (
        beliefs.read(f"measurement:{facts[0]}").support
        > beliefs.read(f"measurement:{facts[1]}").support
    )
    at = datetime(2026, 1, 20, tzinfo=UTC)
    report = population.report(valid_at=at)
    if selection == "unique":
        assert report["observations"]["count"] == 0
        assert report["excluded"] == [{"subject": dog, "reason": "unresolved_property_reading"}]
    else:
        assert report["observations"]["mean"] == 5
        assert report["observations"]["items"][0]["source_fact"] == facts[0]
    assert population.report()["observations"]["mean"] == 10
    assert (
        population.report(valid_at=datetime(2026, 2, 1, tzinfo=UTC))["observations"]["mean"] == 10
    )


def test_numeric_correction_after_a_duplicate_is_latest_but_description_changes_are_not():
    population = Population()
    dog, original = population.measurement(8, name="Jack")
    _, duplicate = population.measurement(8000, subject=dog, unit="g")
    graph = population.world.graph
    corrected = population.write(
        "update", object=original, changes={"args": {**graph.get(original).args, "value": 9}}
    )
    assert "error" not in corrected, corrected
    assert population.report()["observations"]["count"] == 1
    assert population.report()["observations"]["mean"] == 9
    assert population.world.attribution.read_property(dog, population.property).value_U == 9
    annotated = population.write(
        "update", object=duplicate, changes={"description": "The earlier report used grams"}
    )
    assert "error" not in annotated, annotated
    assert population.report()["observations"]["mean"] == 9
    assert population.world.attribution.read_property(dog, population.property).source_facts == (
        original,
    )


def test_retraction_changes_belief_not_values_and_correction_invalidates_population_assessment():
    """Retraction uses the real BeliefStore; it has no model write tool."""
    population = Population()
    population.measurement(8, name="Jack")
    _, correctable = population.measurement(12, name="Jill")
    world = population.world
    initial = population.report()["observations"]
    target = initial["belief_target"]
    refs, metadata = recorded_experience(world, "The sample is relevant to this dog population")
    world.operations.execute(
        "evidence.assess",
        {"target": target, "source_ref": refs[0], "likelihoods": {"false": 0.1, "true": 0.9}},
        metadata=metadata,
    )
    assessed = population.report()["observations"]
    assert assessed["belief_status"] == "assessed"
    assert assessed["belief_data"]["support"] > 0
    world.operations.beliefs.retract(target, TraceOutputRef(**refs[0]))
    retracted = population.report()["observations"]
    assert retracted["belief_target"] == target
    assert retracted["belief_status"] == "prior_only"
    assert retracted["belief_data"]["support"] == 0
    assert retracted["count"] == 2 and retracted["mean"] == 10
    corrected = population.write(
        "update",
        object=correctable,
        changes={"args": {**world.graph.get(correctable).args, "value": 14}},
    )
    assert "error" not in corrected, corrected
    report = population.report()
    assert report["observations"]["mean"] == 11
    assert report["observations"]["belief_target"] != target
    assert report["observations"]["belief_status"] == "unassessed"
    snapshots = (
        world.graph.snapshot(),
        world.attribution.snapshot(),
        world.operations.beliefs.snapshot(),
        world.memory.snapshot(),
    )
    for _ in range(3):
        assert population.report() == report
    assert snapshots == (
        world.graph.snapshot(),
        world.attribution.snapshot(),
        world.operations.beliefs.snapshot(),
        world.memory.snapshot(),
    )
    restored_graph = GraphStore.from_snapshot(json.loads(json.dumps(snapshots[0])))
    restored = AttributionRuntime.from_snapshot(
        snapshots[1],
        restored_graph,
        BeliefStore.from_snapshot(json.loads(json.dumps(snapshots[2]))),
    )
    assert restored.summarize_property(population.domain, population.property) == report


def test_conditions_select_distinct_samples_and_references_without_fallback():
    population = Population()
    dog, _ = population.measurement(5, name="Jack", conditions={"activity": "resting"})
    population.measurement(7, subject=dog, conditions={"activity": "active"})
    population.measurement(9, name="Jill", conditions={"activity": "active"})
    population.measurement(4, name="Unqualified dog")
    references = {}
    for name, condition, value in (
        ("General table", {}, 6),
        ("Resting table", {"activity": "resting"}, 5),
        ("Active table", {"activity": "active"}, 8),
    ):
        references[value] = population.reference(
            "distribution",
            name=name,
            conditions=condition,
            samples=[{"lower": value, "upper": value, "count": 3}],
        )
    for conditions, count, mean, reference_value in (
        ({}, 1, 4, 6),
        ({"activity": "resting"}, 1, 5, 5),
        ({"activity": "active"}, 2, 8, 8),
    ):
        report = population.report(**conditions)
        assert report["observations"]["count"] == count
        assert report["observations"]["mean"] == mean
        assert [item["id"] for item in report["references"]] == [references[reference_value]]
        assert all(
            item["status"] == "needs_matching_parameters" for item in report["reference_candidates"]
        )
    unmatched = population.report(activity="resting", load="high")
    assert unmatched["observations"]["count"] == 0
    assert unmatched["references"] == []
    assert unmatched["reference_candidates_total"] == 3


def test_structured_conditions_survive_storage_without_equating_boolean_and_numeric_values():
    population = Population()
    conditions = {"age_range": [1, 5], "mode": {"enabled": False}}
    dog, fact = population.measurement(7, name="Jack", conditions=conditions)
    reference = population.reference(
        "distribution", conditions=conditions, samples=[{"lower": 6, "upper": 6, "count": 3}]
    )
    reading = population.world.attribution.read_property(dog, population.property, **conditions)
    assert reading.source_facts == (fact,)
    assert reading.value_U == 7
    report = population.report(**conditions)
    assert report["observations"]["mean"] == 7
    assert report["references"][0]["id"] == reference
    different = {"age_range": [1, 5], "mode": {"enabled": 0}}
    assert (
        population.world.attribution.read_property(dog, population.property, **different) is UNKNOWN
    )
    unmatched = population.report(**different)
    assert unmatched["observations"]["count"] == 0
    assert unmatched["references"] == []
    assert unmatched["reference_candidates"][0]["conditions"] == conditions


@pytest.mark.parametrize("values", [[], [0], [4, 4, 4]])
def test_empty_single_zero_and_equal_samples_have_defined_statistics(values):
    population = Population()
    for index, value in enumerate(values):
        population.measurement(value, name=f"Dog {index}")
    expected = values[0] if values else None
    observations = population.report(value=expected or 0, unit="kg")["observations"]
    assert observations["count"] == len(values)
    assert observations["mean"] == observations["median"] == expected
    assert observations["min"] == observations["max"] == expected
    if values:
        assert observations["comparison"]["difference_from_mean"] == 0
        assert observations["comparison"]["count_below_value"] == 0
        assert observations["comparison"]["count_above_value"] == 0
        assert observations["comparison"]["count_overlapping_or_equal"] == len(values)
        assert observations["nearest"]["distance"] == 0
        assert observations["nearest"]["items_total"] == len(values)
    else:
        assert "comparison" not in observations
        assert observations["nearest"] is None
    assert population.report()["observations"]["nearest"] is None


async def test_public_nearest_selects_28_for_25_across_units_without_using_excluded_or_aggregate_data():
    population = Population()
    population.measurement(15, name="Vesta")
    closest, _ = population.measurement(28000, name="Grom", unit="г")
    population.measurement(25, name="Missing unit", unit=None)
    dog = population.create("create_instance", "Undated dog", prototype=population.domain)
    facet = population.create(
        "create_facet", "Undated state", instance=dog, valid_from=None, valid_until=None
    )
    population.measurement(25, subject=facet)
    population.reference("distribution", samples=[{"lower": 25, "upper": 25, "count": 100}])
    world = population.world
    before = (
        world.graph.snapshot(),
        world.attribution.snapshot(),
        world.memory.snapshot(),
        world.operations.beliefs.snapshot(),
    )
    ctx = context(world, None, role="model")
    report = await summarize_property(
        ctx, "Dog", "Body mass", value=25000, unit="g", at="2026-01-01T00:00:00Z"
    )
    assert report["observations"]["count"] == 2
    assert report["observations"]["nearest"] == {
        "distance": 3,
        "items": [{"subject": closest, "name": "Grom", "value": 28}],
        "items_total": 1,
    }
    assert report["references"][0]["summary"]["count"] == 100
    assert report["excluded_total"] == 2
    assert before == (
        world.graph.snapshot(),
        world.attribution.snapshot(),
        world.memory.snapshot(),
        world.operations.beliefs.snapshot(),
    )


async def test_public_nearest_keeps_decimal_ties_without_merging_distinguishable_values():
    population = Population()
    lower, _ = population.measurement(1.1, name="Lower dog")
    upper, _ = population.measurement(1300, name="Upper dog", unit="g")
    population.measurement(1.3 + 5 * math.ulp(1.3), name="Farther dog")
    ctx = context(population.world, None, role="model")
    report = await summarize_property(ctx, "Dog", "Body mass", value=1200, unit="g")
    nearest = report["observations"]["nearest"]
    assert nearest["distance"] == pytest.approx(0.1)
    assert {item["subject"] for item in nearest["items"]} == {lower, upper}
    assert nearest["items_total"] == 2
    exact, _ = population.measurement(1.2, name="Exact dog")
    population.measurement(math.nextafter(1.2, math.inf), name="Adjacent dog")
    report = await summarize_property(ctx, "Dog", "Body mass", value=1.2, unit="kg")
    assert report["observations"]["nearest"] == {
        "distance": 0,
        "items": [{"subject": exact, "name": "Exact dog", "value": 1.2}],
        "items_total": 1,
    }


async def test_public_nearest_uses_all_observations_and_bounds_the_tie_preview():
    population = Population()
    for index in range(20):
        population.measurement(index, name=f"Earlier dog {index}")
    tied = []
    for index in range(23):
        value = 24 if index % 2 == 0 else 26
        tied.append(population.measurement(value, name=f"Nearby dog {index}")[0])
    report = await summarize_property(
        context(population.world, None, role="model"), "Dog", "Body mass", value=25, unit="kg"
    )
    observations = report["observations"]
    assert observations["items_total"] == 43
    assert len(observations["items"]) == 20
    nearest = observations["nearest"]
    assert nearest["distance"] == 1
    assert nearest["items_total"] == 23
    assert [item["subject"] for item in nearest["items"]] == tied[:20]
    assert not {item["subject"] for item in observations["items"]}.intersection(tied)


@pytest.mark.parametrize(
    "invalid",
    [
        {"samples": [{"lower": 1, "upper": 3, "count": 2}, {"lower": 2, "upper": 4, "count": 1}]},
        {"unit": "s"},
        {"boundary_inclusive": [True]},
    ],
)
def test_malformed_reference_update_preserves_graph_memory_sources_and_prior_read(invalid):
    population = Population()
    reference = population.reference("distribution", samples=[{"lower": 3, "upper": 3, "count": 2}])
    world = population.world
    before_report = population.report()
    data = json_value(world.graph.get(reference).properties["numeric_reference"])
    refs, metadata = recorded_experience(world, "Proposed reference correction")
    before = (world.graph.snapshot(), world.memory.snapshot())
    rejected = write_action(
        world,
        refs,
        metadata,
        {
            "action": "update",
            "object": reference,
            "changes": {"properties": {"numeric_reference": {**data, **invalid}}},
            "sources": refs,
        },
        key="invalid-correction",
    )
    assert "error" in rejected
    assert (world.graph.snapshot(), world.memory.snapshot()) == before
    assert population.report() == before_report


@pytest.mark.parametrize("parameter", ["value", "subject", "runtime", "property_id", "self"])
@pytest.mark.parametrize("kind", ["reference", "measurement"])
def test_reserved_query_conditions_are_rejected_before_persisting_an_unreadable_source(
    parameter, kind
):
    population = Population()
    world = population.world
    if kind == "reference":
        action = {
            "action": "create_property_reference",
            "name": "Unusable table",
            "description": None,
            "property": population.property,
            "domain": population.domain,
            "unit": "kg",
            "reference_kind": "distribution",
            "boundaries": [],
            "classes": [],
            "samples": [{"lower": 3, "upper": 3, "count": 2}],
            "conditions": {parameter: "resting"},
        }
    else:
        dog = population.create("create_instance", "Jack", prototype=population.domain)
        action = {
            "action": "relate",
            "relation": world.graph.find("HAS_NUMERIC_VALUE").id,
            "arguments": [
                {"role": key, "value": value}
                for key, value in {
                    "entity": dog,
                    "property": population.property,
                    "value": 3,
                    "unit": "kg",
                }.items()
            ],
            "conditions": [{"parameter": parameter, "value": "resting"}],
            "description": None,
        }
    refs, metadata = recorded_experience(world, "A source with a reserved condition")
    if kind == "reference":
        world.service.results(
            action["name"], None, [], [], 20, metadata["task_id"], scope=metadata["semantic_scope"]
        )
    before = (world.graph.snapshot(), world.memory.snapshot())
    rejected = write_action(
        world, refs, metadata, {**action, "sources": refs}, key="reserved-condition", searched=False
    )
    assert "reserved" in rejected["error"]
    assert (world.graph.snapshot(), world.memory.snapshot()) == before


@pytest.mark.parametrize(
    "definition", [None, {"scale": "numeric", "source": "program", "unit": "kg"}]
)
def test_reference_requires_a_declared_numeric_fact_property(definition):
    """Native setup represents legacy or computed properties unavailable to create_property."""
    population = Population()
    world = population.world
    property_node = Node(
        world.graph.reserve_id(),
        "Other mass",
        kind="property",
        properties={} if definition is None else {"attribution": definition},
    )
    world.graph.apply(GraphDelta(creates=(property_node,)), provenance="legacy fixture")
    before = world.graph.snapshot()
    result = population.write(
        "create_property_reference",
        name="Unusable reference",
        description=None,
        property=property_node.id,
        domain=population.domain,
        unit="kg",
        reference_kind="distribution",
        boundaries=[],
        classes=[],
        samples=[{"lower": 3, "upper": 3, "count": 2}],
        conditions={},
    )
    assert "declared numeric" in result["error"]
    assert world.graph.snapshot() == before
