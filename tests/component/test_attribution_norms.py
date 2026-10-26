"""Retained qualitative criteria fitted from source-backed numeric graph observations."""

import json

import pytest

from evertree.core.attribution import AttributionRuntime
from evertree.core.attribution_norms import (
    interpret_norm,
    norm_context,
    prepare_norm,
    refresh_norm,
    revise_norm,
    semantic_revision,
)
from evertree.core.beliefs import BeliefStore
from evertree.core.graph.store import GraphStore
from evertree.core.graph.types import GraphDelta, NodeUpdate
from evertree.core.values import UNKNOWN, ContractError, json_value
from tests.support.attribution import Population


def fitted(population, *, name="Relative size", **fields):
    classes = fields.pop("classes", None) or [
        population.create("create_concept", name) for name in ("Small", "Medium", "Large")
    ]
    delta, identity = prepare_norm(
        population.world.attribution,
        name,
        "Relative to retained measurements, not a universal size definition",
        {
            "property": population.property,
            "domain": population.domain,
            "classes": classes,
            **fields,
        },
    )
    population.world.graph.apply(delta, provenance="explicit criterion fit")
    return identity, classes


def refresh(population, identity):
    delta = refresh_norm(population.world.attribution, identity)
    if delta.updates:
        population.world.graph.apply(delta, provenance="explicit batch refresh")
    return delta


def test_three_source_reports_fit_relative_classes_without_inventing_belief_or_read_effects():
    population = Population()
    for name, value in (("Jack", 8), ("Tanya", 5), ("Newspaper dog", 10)):
        population.measurement(value, name=name)
    identity, classes = fitted(population)
    runtime = population.world.attribution
    context = norm_context(runtime, identity)
    assert context["state"]["count"] == 3
    assert context["state"]["boundaries"] == pytest.approx([7, 26 / 3])
    assert context["model_belief_data"] is None
    assert len(context["source_refs"]) >= 3
    assert all(set(item) == {"object", "revision"} for item in context["state"]["dependencies"])
    before = population.world.graph.snapshot(), runtime.beliefs.snapshot()
    assert interpret_norm(runtime, identity, 6000, unit="g")["class"] == classes[0]
    assert interpret_norm(runtime, identity, 8, unit="kg")["class"] == classes[1]
    assert interpret_norm(runtime, identity, 10, unit="kg")["class"] == classes[2]
    hypothetical = interpret_norm(runtime, identity, 7, unit="kg")
    assert hypothetical["class"] == classes[0]
    assert hypothetical["count"] == 3
    assert hypothetical["model_belief_status"] == "unassessed"
    assert hypothetical["model_belief_data"] is None
    assert before == (population.world.graph.snapshot(), runtime.beliefs.snapshot())


def test_fit_uses_full_population_and_one_latest_measurement_per_individual():
    population = Population()
    subjects = [population.measurement(i, name=f"Dog {i}")[0] for i in range(1, 31)]
    population.measurement(1000, subject=subjects[0], unit="g")
    identity, _ = fitted(population)
    context = norm_context(population.world.attribution, identity)
    assert len(population.report()["observations"]["items"]) == 20
    assert context["state"]["count"] == len(context["observations"]) == 30
    assert context["state"]["boundaries"] == pytest.approx([32 / 3, 61 / 3])
    interpreted = interpret_norm(population.world.attribution, identity, 7, unit="kg")
    assert len(interpreted["source_refs"]) == 20
    assert interpreted["source_refs_total"] > 30


def test_refresh_is_explicit_idempotent_and_hysteresis_holds_small_drift():
    population = Population()
    facts = [population.measurement(value, name=f"Dog {value}")[1] for value in (0, 10, 20)]
    identity, _ = fitted(population)
    runtime = population.world.attribution
    first = norm_context(runtime, identity)["state"]
    assert not refresh(population, identity).updates
    fact = population.world.graph.get(facts[-1])
    assert "error" not in population.write(
        "update", object=fact.id, changes={"args": {**fact.args, "value": 20.1}}
    )
    assert norm_context(runtime, identity) is UNKNOWN
    refresh(population, identity)
    second = norm_context(runtime, identity)["state"]
    assert second["revision"] == first["revision"] + 1
    assert second["hysteresis_applied"]
    assert second["boundaries"] == first["boundaries"]
    assert second["semantic_revision"] == first["semantic_revision"]
    fact = population.world.graph.get(facts[-1])
    population.write("update", object=fact.id, changes={"args": {**fact.args, "value": 50}})
    refresh(population, identity)
    third = norm_context(runtime, identity)["state"]
    assert not third["hysteresis_applied"]
    assert third["boundaries"] != second["boundaries"]
    assert third["semantic_revision"] == first["semantic_revision"]


def test_correction_invalidates_current_fit_while_restored_checkpoint_keeps_original_result():
    population = Population()
    for value in (5, 8, 10):
        _, fact = population.measurement(value, name=f"Dog {value}")
    identity, _ = fitted(population, hysteresis=0)
    world = population.world
    old_graph = GraphStore.from_snapshot(json.loads(json.dumps(world.graph.snapshot())))
    old_runtime = AttributionRuntime.from_snapshot(
        world.attribution.snapshot(), old_graph, BeliefStore()
    )
    old = interpret_norm(old_runtime, identity, 9, unit="kg")
    node = world.graph.get(fact)
    population.write("update", object=fact, changes={"args": {**node.args, "value": 100}})
    assert interpret_norm(world.attribution, identity, 9, unit="kg") is UNKNOWN
    refresh(population, identity)
    new = interpret_norm(world.attribution, identity, 9, unit="kg")
    assert old["class"] != new["class"]
    assert interpret_norm(old_runtime, identity, 9, unit="kg") == old
    assert old["semantic_revision"] == new["semantic_revision"]


def test_explicit_external_distribution_uses_frequencies_and_converts_units_without_pooling():
    population = Population()
    population.measurement(1000, name="Unrelated individual")
    reference = population.reference(
        "distribution",
        samples=[
            {"lower": value, "upper": value, "count": count}
            for value, count in ((1000, 1), (5000, 2), (10000, 3))
        ],
        unit="g",
    )
    identity, _ = fitted(population, reference=reference, quantiles=[0.2, 0.8])
    context = norm_context(population.world.attribution, identity)
    assert context["state"]["count"] == 6
    assert context["observations"] == []
    assert context["state"]["status"] == "ready"
    assert context["state"]["boundaries"] == [5, 10]
    assert interpret_norm(population.world.attribution, identity, 5, unit="kg") is not UNKNOWN


def test_interval_reference_retains_boundary_precision_and_marks_approximation():
    population = Population()
    reference = population.reference(
        "distribution",
        samples=[
            {"lower": low, "upper": high, "count": 1} for low, high in ((1, 2), (4, 6), (9, 12))
        ],
    )
    identity, _ = fitted(population, reference=reference)
    context = norm_context(population.world.attribution, identity)
    assert context["state"]["boundary_bounds"][0] == pytest.approx([3, 14 / 3])
    assert context["state"]["approximate"]
    assert interpret_norm(population.world.attribution, identity, 5, unit="kg")["approximate"]
    ambiguous = interpret_norm(population.world.attribution, identity, 4, unit="kg")
    assert len(ambiguous["possible_classes"]) == 2


def test_conditions_and_subtype_population_keep_separate_norms():
    population = Population()
    breed = population.create("create_prototype", "Toy dog", parent=population.domain)
    for value in (1, 2, 3):
        population.measurement(
            value, name=f"Resting {value}", prototype=breed, conditions={"mode": "rest"}
        )
    for value in (10, 20, 30):
        population.measurement(value, name=f"Working {value}", conditions={"mode": "work"})
    identity, classes = fitted(population, domain=breed, conditions={"mode": "rest"})
    context = norm_context(population.world.attribution, identity)
    assert context["state"]["count"] == 3
    assert context["state"]["boundaries"] == pytest.approx([5 / 3, 7 / 3])
    runtime = population.world.attribution
    assert interpret_norm(runtime, identity, 2, unit="kg") is UNKNOWN
    assert interpret_norm(runtime, identity, 2, unit="kg", parameters={"mode": "work"}) is UNKNOWN
    assert (
        interpret_norm(runtime, identity, 2, unit="kg", parameters={"mode": "rest"})["class"]
        == classes[1]
    )
    other, _ = fitted(population, name="Working size", classes=classes, conditions={"mode": "work"})
    assert norm_context(population.world.attribution, other)["state"][
        "boundaries"
    ] == pytest.approx([50 / 3, 70 / 3])


@pytest.mark.parametrize(
    "values,status", [([], "needs_data"), ([0], "needs_data"), ([3, 3, 3], "degenerate")]
)
def test_sparse_or_indistinguishable_data_does_not_invent_ordered_classes(values, status):
    population = Population()
    for index, value in enumerate(values):
        population.measurement(value, name=f"Dog {index}")
    identity, _ = fitted(population)
    assert norm_context(population.world.attribution, identity)["state"]["status"] == status
    assert interpret_norm(population.world.attribution, identity, 0, unit="kg") is UNKNOWN


def test_meaning_changes_with_quantile_criterion_but_not_fit_policy():
    population = Population()
    for value in (1, 5, 10):
        population.measurement(value, name=f"Dog {value}")
    identity, _ = fitted(population)
    context = norm_context(population.world.attribution, identity)
    definition, meanings = context["definition"], context["state"]["class_meanings"]
    assert semantic_revision(definition, meanings) == semantic_revision(
        {**definition, "min_samples": 10, "hysteresis": 0}, meanings
    )
    assert semantic_revision(definition, meanings) != semantic_revision(
        {**definition, "quantiles": [0.2, 0.8]}, meanings
    )
    old_state = norm_context(population.world.attribution, identity)["state"]
    delta = revise_norm(
        population.world.attribution, identity, {**definition, "quantiles": [0.2, 0.8]}
    )
    population.world.graph.apply(delta, provenance="explicit criterion redefinition")
    revised = norm_context(population.world.attribution, identity)["state"]
    assert revised["semantic_revision"] != old_state["semantic_revision"]
    assert revised["revision"] == old_state["revision"] + 1
    assert not revised["hysteresis_applied"]
    assert (
        population.world.graph.changes_of(identity)[0]
        .after[identity]
        .properties["norm_state"]["semantic_revision"]
        == old_state["semantic_revision"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "Lightest retained"},
        {"description": "Low body mass relative to the retained population, not physical height"},
    ],
)
def test_class_meaning_edit_requires_refresh_and_retains_the_previous_meaning(changes):
    population = Population()
    for value in (1, 5, 10):
        population.measurement(value, name=f"Dog {value}")
    identity, classes = fitted(population)
    world = population.world
    old_state = norm_context(world.attribution, identity)["state"]
    old_graph = GraphStore.from_snapshot(json.loads(json.dumps(world.graph.snapshot())))
    old_runtime = AttributionRuntime.from_snapshot(
        world.attribution.snapshot(), old_graph, BeliefStore()
    )
    old_result = interpret_norm(old_runtime, identity, 2, unit="kg")

    assert "error" not in population.write("update", object=classes[0], changes=changes)
    assert norm_context(world.attribution, identity) is UNKNOWN
    assert interpret_norm(world.attribution, identity, 2, unit="kg") is UNKNOWN
    assert (
        world.graph.get(identity).properties["norm_state"]["class_meanings"][0]
        == (old_state["class_meanings"][0])
    )

    refresh(population, identity)
    state = norm_context(world.attribution, identity)["state"]
    assert state["semantic_revision"] != old_state["semantic_revision"]
    assert state["revision"] == old_state["revision"] + 1
    assert state["class_meanings"][0] == {**old_state["class_meanings"][0], **changes}
    assert not state["hysteresis_applied"]
    assert not refresh(population, identity).updates
    assert interpret_norm(old_runtime, identity, 2, unit="kg") == old_result
    assert (
        norm_context(old_runtime, identity)["state"]["class_meanings"]
        == old_state["class_meanings"]
    )


def test_invalid_checkpoint_and_binding_are_rejected_atomically():
    population = Population()
    for value in (1, 5, 10):
        population.measurement(value, name=f"Dog {value}")
    identity, _ = fitted(population)
    graph = population.world.graph
    properties = json_value(graph.get(identity).properties)
    before = graph.snapshot()
    properties["norm_state"]["boundaries"] = [10, 1]
    with pytest.raises(ContractError, match="boundaries"):
        graph.apply(
            GraphDelta(updates=(NodeUpdate(identity, {"properties": properties}),)),
            provenance="invalid",
        )
    assert before == graph.snapshot()

    properties = json_value(graph.get(identity).properties)
    properties["norm_state"]["class_meanings"].reverse()
    with pytest.raises(ContractError, match="pinned class meanings"):
        graph.apply(
            GraphDelta(updates=(NodeUpdate(identity, {"properties": properties}),)),
            provenance="invalid",
        )
    assert before == graph.snapshot()

    properties = json_value(graph.get(identity).properties)
    properties["attribution"]["classes"] = list(reversed(properties["attribution"]["classes"]))
    with pytest.raises(ContractError, match="criterion"):
        graph.apply(
            GraphDelta(updates=(NodeUpdate(identity, {"properties": properties}),)),
            provenance="invalid",
        )
    assert before == graph.snapshot()


def test_public_creation_revision_refresh_and_read_use_the_same_retained_criterion():
    population = Population()
    for value in (5, 8, 10):
        population.measurement(value, name=f"Dog {value}")
    classes = [population.create("create_concept", name) for name in ("Small", "Medium", "Large")]
    identity = population.create(
        "create_qualitative_property",
        "Relative size",
        property=population.property,
        domain=population.domain,
        classes=classes,
        conditions={},
    )
    world = population.world
    metadata = {"task_id": "test", "program": {"role": "exec", "revision": "test"}}
    result = world.operations.execute(
        "graph.interpret_property",
        {
            "property": identity,
            "value": 8,
            "unit": "kg",
        },
        metadata=metadata,
    )
    assert result["class"] == classes[1]
    assert world.operations.execute("attribution.refresh_norms", {}, metadata=metadata) == {
        "refreshed": []
    }
    population.measurement(20, name="New dog")
    assert norm_context(world.attribution, identity) is UNKNOWN
    assert world.operations.execute("attribution.refresh_norms", {}, metadata=metadata) == {
        "refreshed": [identity]
    }
    before = norm_context(world.attribution, identity)["state"]
    result = population.write(
        "revise_property_norm",
        object=identity,
        property=population.property,
        domain=population.domain,
        classes=classes,
        conditions={},
        quantiles=[0.2, 0.8],
    )
    assert "error" not in result, result
    after = norm_context(world.attribution, identity)["state"]
    assert after["semantic_revision"] != before["semantic_revision"]
    assert after["revision"] == before["revision"] + 1
    properties = json_value(world.graph.get(identity).properties)
    properties["norm_state"]["boundaries"] = [1, 2]
    rejected = population.write("update", object=identity, changes={"properties": properties})
    assert "error" in rejected
    assert norm_context(world.attribution, identity)["state"] == after


def test_source_unit_redefinition_stales_fit_until_refresh_without_reusing_old_unit_hysteresis():
    population = Population()
    for value in (5, 8, 10):
        population.measurement(value, name=f"Dog {value}")
    identity, classes = fitted(population)
    world = population.world
    properties = json_value(world.graph.get(population.property).properties)
    properties["attribution"]["unit"] = "g"
    changed = population.write(
        "update", object=population.property, changes={"properties": properties}
    )
    assert "error" not in changed, changed
    assert norm_context(world.attribution, identity) is UNKNOWN
    refresh(population, identity)
    context = norm_context(world.attribution, identity)
    assert context["state"]["unit"] == "g"
    assert context["state"]["boundaries"] == pytest.approx([7000, 26000 / 3])
    assert interpret_norm(world.attribution, identity, 8, unit="kg")["class"] == classes[1]


def test_numeric_contract_change_cannot_leave_a_norm_with_missing_or_wrong_typed_conditions():
    population = Population()
    for value in (5, 8, 10):
        population.measurement(value, name=f"Dog {value}", conditions={"loaded": True})
    identity, _ = fitted(population, conditions={"loaded": True})
    world = population.world
    properties = json_value(world.graph.get(population.property).properties)
    properties["attribution"].update(
        required_parameters=["loaded"], parameter_types={"loaded": "boolean"}
    )
    assert "error" not in population.write(
        "update", object=population.property, changes={"properties": properties}
    )
    refresh(population, identity)
    before = world.graph.snapshot()
    properties["attribution"]["parameter_types"] = {"loaded": "integer"}
    wrong_type = population.write(
        "update", object=population.property, changes={"properties": properties}
    )
    assert "requires integer" in wrong_type["error"]
    assert before == world.graph.snapshot()
    properties["attribution"]["parameter_types"] = {"loaded": "boolean", "temperature": "number"}
    properties["attribution"]["required_parameters"] = ["loaded", "temperature"]
    missing = population.write(
        "update", object=population.property, changes={"properties": properties}
    )
    assert "required property parameters" in missing["error"]
    assert before == world.graph.snapshot()
    assert norm_context(world.attribution, identity) is not UNKNOWN


@pytest.mark.parametrize(
    "conditions,expected",
    [({}, "required property parameters"), ({"loaded": 1}, "requires boolean")],
)
def test_source_references_share_the_norms_required_parameter_validation(conditions, expected):
    population = Population()
    prop = population.world.graph.get(population.property)
    declaration = {
        **prop.properties["attribution"],
        "required_parameters": ["loaded"],
        "parameter_types": {"loaded": "boolean"},
    }
    assert "error" not in population.write(
        "update", object=prop.id, changes={"properties": {"attribution": declaration}}
    )
    before = population.world.graph.snapshot()
    result = population.write(
        "create_property_reference",
        name="Load sample",
        description=None,
        property=prop.id,
        domain=population.domain,
        unit="kg",
        reference_kind="distribution",
        boundaries=[],
        classes=[],
        samples=[{"lower": 1, "upper": 1, "count": 3}],
        conditions=conditions,
    )
    assert expected in result["error"]
    assert before == population.world.graph.snapshot()
    valid = population.reference(
        "distribution",
        name="Valid sample",
        samples=[{"lower": 1, "upper": 1, "count": 3}],
        conditions={"loaded": True},
    )
    assert (
        population.world.graph.get(valid).properties["numeric_reference"]["conditions"]["loaded"]
        is True
    )


async def test_knowledge_integration_refreshes_a_stale_norm_even_when_it_adds_no_more_facts():
    from evertree.processes.self_semantic_processing.self_knowledge_integration._exec import run
    from tests.support.semantics import context, recorded_experience

    population = Population()
    for value in (5, 8, 10):
        population.measurement(value, name=f"Dog {value}")
    identity, _ = fitted(population)
    world = population.world
    previous = norm_context(world.attribution, identity)["state"]
    population.measurement(20, name="New dog")
    assert norm_context(world.attribution, identity) is UNKNOWN
    sources, _ = recorded_experience(world, "The new dog's measurement is already saved.")

    async def no_more_writes(payload, call_tool):
        return {"text": "The recorded fact already expresses this observation."}

    outcome = await run(context(world, no_more_writes, role="exec"), sources)
    assert outcome["result"]["writes"] == []
    refreshed = norm_context(world.attribution, identity)["state"]
    assert refreshed["count"] == 4
    assert refreshed["revision"] == previous["revision"] + 1
    assert refreshed["data_revision"] != previous["data_revision"]
