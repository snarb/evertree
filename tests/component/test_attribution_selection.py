"""Property selection uses scale semantics and shared beliefs, never missing-as-zero values."""

import pytest

from evertree.core.attribution import PropertyDefinition
from evertree.core.attribution_selection import select_properties
from evertree.core.beliefs import element_target
from evertree.core.graph.types import GraphDelta
from evertree.core.values import UNKNOWN, ContractError
from tests.support.attribution import Population


def test_numeric_filters_nearest_and_top_k_preserve_unknowns_and_read_only_state():
    population = Population()
    subjects = [population.measurement(v, name=f"Dog {v}")[0] for v in (7, 15, 28)]
    missing = population.create("create_instance", "Unknown dog", prototype=population.domain)
    runtime = population.world.attribution
    before = population.world.graph.snapshot(), population.world.beliefs.snapshot()
    result = select_properties(
        runtime,
        [*subjects, missing],
        filters=[
            {"property": population.property, "op": ">=", "value": 10},
            {"property": population.property, "op": "<", "value": 30},
        ],
        order_by={"property": population.property, "direction": "nearest", "value": 25},
        limit=1,
    )
    assert result["total"] == 2
    assert result["items"][0]["subject"] == subjects[-1]
    assert result["items"][0]["score"] == 3
    assert result["unknown"] == [missing]
    assert result["truncated"]
    assert before == (population.world.graph.snapshot(), population.world.beliefs.snapshot())


def test_ordinal_ranking_and_circular_distance_use_declared_scale():
    population = Population()
    low, high = [population.create("create_concept", n) for n in ("Low", "High")]
    rank = population.create(
        "create_property",
        "Priority",
        unit=None,
        applies_to=[population.domain],
        scale="ordinal",
        classes=[low, high],
    )
    phase = population.create(
        "create_property",
        "Phase",
        unit="deg",
        applies_to=[population.domain],
        scale="circular",
        period=360,
    )
    subjects = [
        population.create("create_instance", n, prototype=population.domain)
        for n in ("First", "Second")
    ]
    graph = population.world.graph
    graph.apply(
        GraphDelta(
            creates=tuple(
                graph.new_fact("CLASSIFIED_AS", {"entity": subject, "class": label})
                for subject, label in zip(subjects, (low, high))
            )
            + tuple(
                graph.new_fact(
                    "HAS_NUMERIC_VALUE",
                    {"entity": subject, "property": phase, "value": angle, "unit": "deg"},
                )
                for subject, angle in zip(subjects, (350, 180))
            )
        ),
        provenance="source",
    )
    runtime = population.world.attribution
    ordered = select_properties(runtime, subjects, order_by={"property": rank, "direction": "desc"})
    assert [row["subject"] for row in ordered["items"]] == subjects[::-1]
    nearby = select_properties(
        runtime,
        subjects,
        filters=[{"property": phase, "op": "approx", "value": 10, "tolerance": 20}],
        order_by={"property": phase, "direction": "nearest", "value": 10},
    )
    assert [row["subject"] for row in nearby["items"]] == [subjects[0]]
    assert nearby["items"][0]["score"] == 20


def test_profile_filter_and_ranking_require_explicit_alternative_without_argmax():
    population = Population()
    low, high = [population.create("create_concept", n) for n in ("Low", "High")]
    prop = population.create(
        "create_property",
        "Risk",
        unit=None,
        applies_to=[population.domain],
        scale="ordinal",
        classes=[low, high],
    )
    subjects = [
        population.create("create_instance", n, prototype=population.domain)
        for n in ("First", "Second")
    ]
    runtime = population.world.attribution
    for subject, probability in zip(subjects, (0.8, 0.3)):
        target = f"risk:{subject}"
        runtime.beliefs.register_scope(
            target, [str(low), str(high)], prior={str(low): 1 - probability, str(high): probability}
        )
        runtime.bind_scope(subject, prop, target)
    assert runtime.read_property(subjects[0], prop).value_U is None
    assert runtime.read_property(subjects[0], prop, point_policy="argmax").value_U == high
    result = select_properties(
        runtime,
        subjects,
        filters=[{"property": prop, "op": ">=", "value": 0.6, "alternative": high}],
        order_by={"property": prop, "direction": "desc", "alternative": high},
    )
    assert [row["subject"] for row in result["items"]] == [subjects[0]]
    unselected = select_properties(
        runtime, subjects, filters=[{"property": prop, "op": "==", "value": high}]
    )
    assert unselected["unknown"] == subjects


def test_implicit_graph_evidence_flows_into_numeric_reads_and_support_selection():
    population = Population()
    subject, first = population.measurement(8, name="Jack")
    _, second = population.measurement(9, subject=subject)
    world = population.world
    target = element_target(world.graph.get(first))
    world.beliefs.register_binary(target)
    world.beliefs.assign(target, "measured", 4, backed=True)
    world.attribution.register(
        PropertyDefinition(population.property, unit="kg", selection="max_support")
    )
    # Graph declarations remain authoritative, so update the declaration rather than shadow it.
    node = world.graph.get(population.property)
    assert "error" not in population.write(
        "update",
        object=node.id,
        changes={
            "properties": {
                "attribution": {**node.properties["attribution"], "selection": "max_support"}
            }
        },
    )
    reading = world.attribution.read_property(subject, population.property)
    assert reading.source_facts == (first,)
    assert reading.belief_data.support == 4
    assert reading.value_U == 8
    world.beliefs.retract(target, "measured")
    assert world.attribution.read_property(subject, population.property).source_facts == (second,)


def test_domain_and_typed_parameters_apply_to_reads():
    population = Population()
    subject, _ = population.measurement(8, name="Jack", conditions={"load": 2})
    node = population.world.graph.get(population.property)
    definition = {
        **node.properties["attribution"],
        "required_parameters": ["load"],
        "parameter_types": {"load": "integer"},
    }
    assert "error" not in population.write(
        "update", object=node.id, changes={"properties": {"attribution": definition}}
    )
    runtime = population.world.attribution
    assert runtime.read_property(subject, node.id) is UNKNOWN
    with pytest.raises(ContractError, match="requires integer"):
        runtime.read_property(subject, node.id, load=True)
    assert runtime.read_property(subject, node.id, load=2).value_U == 8
    other = population.create("create_prototype", "Parcel", parent=None)
    parcel, _ = population.measurement(2, name="Box", prototype=other, conditions={"load": 2})
    assert runtime.read_property(parcel, node.id, load=2) is UNKNOWN


def test_graph_evidence_scope_is_projected_to_classes_without_copying_support():
    population = Population()
    low, high = [population.create("create_concept", n) for n in ("Low", "High")]
    prop = population.create(
        "create_property",
        "Risk",
        unit=None,
        applies_to=[population.domain],
        scale="ordinal",
        classes=[low, high],
    )
    subject = population.create("create_instance", "Jack", prototype=population.domain)
    world = population.world
    facts = tuple(
        world.graph.new_fact("CLASSIFIED_AS", {"entity": subject, "class": label})
        for label in (low, high)
    )
    world.graph.apply(GraphDelta(creates=facts), provenance="source")
    targets = [element_target(fact) for fact in facts]
    world.beliefs.declare_scope("risk", "Which risk class?", targets)
    world.beliefs.assess_likelihoods(
        "risk", "one source", {targets[0]: 0.2, targets[1]: 0.8}, backed=False
    )
    expected = world.beliefs.read("risk")
    reading = world.attribution.read_property(subject, prop)
    assert reading.value_U is None
    assert reading.belief_data.profile == {
        str(low): expected.profile[targets[0]],
        str(high): expected.profile[targets[1]],
    }
    assert reading.belief_data.support == expected.support
    assert world.attribution.read_property(subject, prop, point_policy="argmax").value_U == high


@pytest.mark.parametrize("direction", ["asc", "desc", "nearest"])
def test_nominal_has_no_implicit_distance_or_order(direction):
    population = Population()
    red = population.create("create_concept", "Red")
    color = population.create(
        "create_property",
        "Color",
        unit=None,
        applies_to=[population.domain],
        scale="nominal",
        classes=[red],
    )
    with pytest.raises(ContractError):
        select_properties(
            population.world.attribution,
            [],
            order_by={"property": color, "direction": direction, "value": 1},
        )


def test_shared_class_label_requires_a_matching_property_criterion():
    population = Population()
    low, high = [population.create("create_concept", n) for n in ("Low", "High")]
    props = [
        population.create(
            "create_property",
            name,
            unit=None,
            applies_to=[population.domain],
            scale="ordinal",
            classes=[low, high],
        )
        for name in ("Risk", "Priority")
    ]
    subject = population.create("create_instance", "Jack", prototype=population.domain)
    result = population.write(
        "relate",
        relation=population.world.graph.find("CLASSIFIED_AS").id,
        arguments=[{"role": "entity", "value": subject}, {"role": "class", "value": high}],
        conditions=[],
        description=None,
    )
    assert "error" not in result
    runtime = population.world.attribution
    assert all(runtime.read_property(subject, prop) is UNKNOWN for prop in props)
    assert "error" not in population.write(
        "update", object=result["object"], changes={"properties": {"criterion": props[0]}}
    )
    assert runtime.read_property(subject, props[0]).value_U == high
    assert runtime.read_property(subject, props[1]) is UNKNOWN


def test_invalid_property_source_or_class_kind_is_rejected_before_commit():
    population = Population()
    label = population.create("create_concept", "High")
    subject = population.create("create_instance", "Jack", prototype=population.domain)
    for fields in (
        {"scale": "ordinal", "source": "numeric", "classes": [label]},
        {"scale": "nominal", "source": "classification", "classes": [subject]},
    ):
        before = population.world.graph.snapshot()
        result = population.write(
            "create_property",
            name="Invalid property",
            description=None,
            unit=None,
            applies_to=[population.domain],
            **fields,
        )
        assert "error" in result
        assert population.world.graph.snapshot() == before
