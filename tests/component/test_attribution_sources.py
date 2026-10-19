"""Property results preserve semantic bindings, shape and shared belief reads."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from evertree.core.attribution import AttributionRuntime
from evertree.core.attribution_sources import (
    finish_program_read,
    prepare_program_read,
    prepare_selection,
    typed_value,
)
from evertree.core.contracts import ProgramResult
from evertree.core.graph.api import read
from evertree.core.graph.store import GraphStore
from evertree.core.graph.types import (
    AccessView,
    Facet,
    GraphDelta,
    Instance,
    Node,
    NodeUpdate,
    Prototype,
    RelationType,
    Slot,
)
from evertree.core.values import UNKNOWN, ContractError, json_value, utcnow
from tests.support.semantics import recorded_experience, semantic_world, write_action

AT = datetime(2026, 1, 2, tzinfo=UTC)


def source_world(source="program", **binding):
    world = semantic_world()
    prototype = Prototype(world.graph.reserve_id(), "Parcel")
    subject = Instance(world.graph.reserve_id(), "Alpha")
    program = Node(
        world.graph.reserve_id(),
        "Mass.model",
        kind="program",
        properties={"role": "model", "active": True},
    )
    prop = Node(
        world.graph.reserve_id(),
        "Mass",
        kind="property",
        properties={
            "attribution": {
                "source": source,
                "scale": "numeric",
                "unit": "kg",
                "applies_to": [subject.id],
                **({"program": program.id} if source == "program" else {}),
                **binding,
            }
        },
    )
    identity = world.graph.new_fact("IDENTITY_TYPE", {"instance": subject.id, "type": prototype.id})
    world.graph.apply(
        GraphDelta(creates=(prototype, subject, identity, program, prop)), provenance="source"
    )
    world.subject, world.property, world.program = subject.id, prop.id, program.id
    return world


def output_for(request, value=2000, unit="g"):
    arguments = request["arguments"]
    return {key: arguments[key] for key in ("subject", "property", "valid_at", "known_at")} | {
        "conditions": arguments["parameters"],
        "value_U": value,
        "unit": unit,
    }


def save_result(world, value, *, conditions=None, **fields):
    result = Node(
        world.graph.reserve_id(),
        "Saved estimate",
        kind="result",
        properties={
            "attribution_result": {
                "subject": world.subject,
                "property": world.property,
                "conditions": conditions or {},
                "value_U": value,
                "unit": "g",
                **fields,
            }
        },
    )
    world.graph.apply(GraphDelta(creates=(result,)), provenance="measurement")
    return result


def relation_world(*, value_type="any", scale="numeric", arity="one", outputs=("value",)):
    world = semantic_world()
    subject = Node(world.graph.reserve_id(), "Parcel")
    classes = [Node(world.graph.reserve_id(), name) for name in ("Low", "High", "Other")]
    relation = RelationType(
        world.graph.reserve_id(),
        "MEASURED_AS",
        signature=(Slot("subject"), Slot("value", value_type, arity)),
        views=(AccessView("value", ("subject",), outputs),),
    )
    prop = Node(
        world.graph.reserve_id(),
        "Observed property",
        kind="property",
        properties={
            "attribution": {
                "source": "relation",
                "scale": scale,
                "relation_type": relation.id,
                "view": "value",
                "subject_slot": "subject",
                **({"classes": [node.id for node in classes[:2]]} if scale == "ordinal" else {}),
            }
        },
    )
    world.graph.apply(GraphDelta(creates=(subject, relation, prop, *classes)), provenance="source")
    world.subject, world.property, world.relation = subject.id, prop.id, relation.id
    world.classes = [node.id for node in classes]
    return world


@pytest.mark.parametrize("value_type", ["string", "node", "boolean"])
def test_relation_numeric_declaration_rejects_incompatible_view_atomically(value_type):
    world = relation_world(value_type=value_type, scale="nominal")
    prop = world.graph.get(world.property)
    before = world.graph.snapshot()
    with pytest.raises(ContractError, match="does not match its scale"):
        world.graph.apply(
            GraphDelta(
                updates=(
                    NodeUpdate(
                        prop.id,
                        {
                            "properties": {
                                "attribution": {
                                    **prop.properties["attribution"],
                                    "scale": "numeric",
                                }
                            }
                        },
                    ),
                )
            ),
            provenance="invalid binding",
        )
    assert world.graph.snapshot() == before


@pytest.mark.parametrize("arity,outputs", [("list1", ("value",)), ("one", ("subject", "value"))])
def test_relation_projection_requires_one_scalar_output(arity, outputs):
    with pytest.raises(ContractError, match="one scalar output"):
        relation_world(value_type="number", arity=arity, outputs=outputs)


@pytest.mark.parametrize("value", ["fragile", True, [2]])
def test_relation_any_output_must_still_match_numeric_scale(value):
    world = relation_world()
    fact = world.graph.new_fact(world.relation, {"subject": world.subject, "value": value})
    world.graph.apply(GraphDelta(creates=(fact,)), provenance="source")
    with pytest.raises(ContractError, match="finite numeric value"):
        world.attribution.read_property(world.subject, world.property)


@pytest.mark.parametrize("value_type", ["any", "integer"])
def test_relation_numeric_output_preserves_value_and_source(value_type):
    world = relation_world(value_type=value_type)
    fact = world.graph.new_fact(world.relation, {"subject": world.subject, "value": 7})
    world.graph.apply(GraphDelta(creates=(fact,)), provenance="source")
    reading = world.attribution.read_property(world.subject, world.property)
    assert reading.value_U == 7 and reading.source_facts == (fact.id,)


def test_relation_optional_unknown_is_not_a_numeric_zero():
    world = relation_world(value_type="number", arity="optional")
    fact = world.graph.new_fact(world.relation, {"subject": world.subject})
    world.graph.apply(GraphDelta(creates=(fact,)), provenance="source")
    assert world.attribution.read_property(world.subject, world.property) is UNKNOWN


def test_open_nominal_relation_preserves_node_identity_and_source_belief():
    world = relation_world(value_type="node", scale="nominal")
    fact = world.graph.new_fact(
        world.relation, {"subject": world.subject, "value": world.classes[2]}
    )
    world.graph.apply(GraphDelta(creates=(fact,)), provenance="source")
    world.beliefs.register_binary(f"graph:{fact.id}", prior=0.3)
    reading = world.attribution.read_property(world.subject, world.property)
    assert reading.value_U == world.classes[2]
    assert reading.source_facts == (fact.id,) and reading.belief_data.strength == 0.3


def test_relation_ordinal_value_requires_declared_class():
    world = relation_world(value_type="node", scale="ordinal")
    fact = world.graph.new_fact(
        world.relation, {"subject": world.subject, "value": world.classes[2]}
    )
    world.graph.apply(GraphDelta(creates=(fact,)), provenance="source")
    with pytest.raises(ContractError, match="outside.*declared scale"):
        world.attribution.read_property(world.subject, world.property)


def test_categorical_relation_reads_full_scope_without_implicit_point_selection():
    world = relation_world(value_type="node", scale="ordinal")
    facts = [
        world.graph.new_fact(world.relation, {"subject": world.subject, "value": label})
        for label in world.classes[:2]
    ]
    world.graph.apply(GraphDelta(creates=tuple(facts)), provenance="source")
    targets = [f"graph:{fact.id}" for fact in facts]
    world.beliefs.declare_scope("relation alternatives", "Which class?", targets)
    world.beliefs.assess_likelihoods(
        "relation alternatives", "report", dict(zip(targets, (0.2, 0.8))), backed=False
    )
    expected = world.beliefs.read("relation alternatives")
    reading = world.attribution.read_property(world.subject, world.property)
    assert reading.value_U is None
    assert reading.belief_data.profile == {
        str(label): expected.profile[target] for label, target in zip(world.classes[:2], targets)
    }
    assert reading.belief_data.support == expected.support
    assert (
        world.attribution.read_property(
            world.subject, world.property, point_policy="argmax"
        ).value_U
        == world.classes[1]
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        (2000, 2),
        (
            {"kind": "interval", "lower": 1000, "upper": 3000},
            {"kind": "interval", "lower": 1, "upper": 3},
        ),
        (
            {"kind": "normal", "mean": 2000, "stddev": 100},
            {"kind": "normal", "mean": 2, "stddev": 0.1},
        ),
        (
            {
                "kind": "quantiles",
                "quantiles": [{"p": 0.1, "value": 1000}, {"p": 0.9, "value": 3000}],
            },
            {"kind": "quantiles", "quantiles": [{"p": 0.1, "value": 1}, {"p": 0.9, "value": 3}]},
        ),
    ],
)
def test_saved_typed_result_survives_snapshot_and_retains_units(value, expected):
    world = source_world("result")
    result = save_result(world, value)
    graph = GraphStore.from_snapshot(world.graph.snapshot())
    runtime = AttributionRuntime.from_snapshot(world.attribution.snapshot(), graph, world.beliefs)
    reading = runtime.read_property(world.subject, world.property, valid_at=AT)
    assert json_value(reading.value_U) == expected
    assert reading.unit == "kg" and reading.source_facts == (result.id,)
    assert reading.belief_data is None


def test_saved_result_conditions_time_and_current_belief_are_not_replaced():
    world = source_world("result", required_parameters=["loaded"])
    result = save_result(
        world,
        {"kind": "interval", "lower": 1000, "upper": 3000},
        conditions={"loaded": True},
        valid_from=AT.isoformat(),
        valid_until=(AT + timedelta(days=1)).isoformat(),
    )
    world.beliefs.register_binary(f"graph:{result.id}", prior=0.3)
    reading = world.attribution.read_property(
        world.subject, world.property, valid_at=AT, loaded=True
    )
    assert reading.belief_data.strength == 0.3
    assert (
        world.attribution.read_property(world.subject, world.property, valid_at=AT, loaded=1)
        is UNKNOWN
    )
    assert (
        world.attribution.read_property(
            world.subject, world.property, valid_at=AT + timedelta(days=1), loaded=True
        )
        is UNKNOWN
    )


@pytest.mark.parametrize("selection", ["latest", "max_support"])
async def test_public_saved_result_metadata_edits_do_not_override_later_value(selection):
    world = source_world("result", selection=selection)
    refs, metadata = recorded_experience(world, "A revised estimate of parcel mass")
    sequence = 0

    def write(action, **fields):
        nonlocal sequence
        sequence += 1
        result = write_action(
            world, refs, metadata, {"action": action, "sources": refs, **fields}, key=str(sequence)
        )
        assert "error" not in result, result
        return result["object"]

    async def step(method, payload, *, journal=True):
        return world.operations.execute(method, payload, metadata=metadata)

    async def current():
        return await read(
            SimpleNamespace(step=step),
            "read_property",
            {"subject": world.subject, "property": world.property, "at": AT.isoformat()},
        )

    results = [
        write(
            "save_property_result",
            name=name,
            description=None,
            subject=world.subject,
            property=world.property,
            conditions={},
            value_U=value,
            unit="kg",
        )
        for name, value in (("First estimate", 2), ("Second estimate", 3))
    ]
    assert (await current())["value_U"] == 3
    write("update", object=results[0], changes={"description": "Clarified wording only"})
    assert (await current())["value_U"] == 3
    record = json_value(world.graph.get(results[0]).properties["attribution_result"])
    write(
        "update",
        object=results[0],
        changes={"properties": {"attribution_result": {**record, "value_U": 4}}},
    )
    corrected = await current()
    assert corrected["value_U"] == 4 and corrected["source_facts"] == [results[0]]
    write("update", object=results[1], changes={"name": "Renamed estimate"})
    assert (await current())["value_U"] == 4


@pytest.mark.parametrize(
    "bounds,expected",
    [
        ({}, 2),
        ({"valid_from": AT.isoformat()}, 2),
        ({"valid_until": (AT + timedelta(days=1)).isoformat()}, 2),
        ({"valid_from": None}, UNKNOWN),
        ({"valid_until": None}, UNKNOWN),
        ({"valid_from": AT.isoformat(), "valid_until": None}, UNKNOWN),
    ],
)
def test_saved_result_distinguishes_omitted_and_unknown_temporal_bounds(bounds, expected):
    world = source_world("result")
    save_result(world, 2000, **bounds)
    result = world.attribution.read_property(world.subject, world.property, valid_at=AT)
    assert (result if result is UNKNOWN else result.value_U) == expected


@pytest.mark.parametrize("kind,value", [("integer", True), ("node", 99999)])
def test_saved_result_rejects_wrong_parameter_type_or_unknown_identity(kind, value):
    world = source_world("result", required_parameters=["load"], parameter_types={"load": kind})
    with pytest.raises(ContractError, match="requires integer|existing graph identities"):
        save_result(world, 2000, conditions={"load": value})


def test_saved_categorical_results_read_the_entire_shared_profile():
    world = source_world("result", selection="unique")
    classes = [Node(world.graph.reserve_id(), name) for name in ("Low", "High")]
    prop = world.graph.get(world.property)
    world.graph.apply(
        GraphDelta(
            creates=tuple(classes),
            updates=(
                NodeUpdate(
                    prop.id,
                    {
                        "properties": {
                            "attribution": {
                                **prop.properties["attribution"],
                                "scale": "ordinal",
                                "classes": [node.id for node in classes],
                                "unit": None,
                            }
                        }
                    },
                ),
            ),
        ),
        provenance="scale",
    )
    results = [save_result(world, node.id, unit=None) for node in classes]
    targets = [f"graph:{node.id}" for node in results]
    world.beliefs.declare_scope("classification", "Which class?", targets)
    world.beliefs.assess_likelihoods(
        "classification", "report", dict(zip(targets, (0.2, 0.8))), backed=False
    )
    expected = world.beliefs.read("classification")
    result = world.attribution.read_property(world.subject, prop.id, valid_at=AT)
    assert result.value_U is None
    assert result.belief_data.profile == {
        str(node.id): expected.profile[target] for node, target in zip(classes, targets)
    }
    assert result.belief_data.support == expected.support
    assert (
        world.attribution.read_property(
            world.subject, prop.id, valid_at=AT, point_policy="argmax"
        ).value_U
        == classes[1].id
    )


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "interval", "lower": 3, "upper": 1},
        {"kind": "normal", "mean": 1, "stddev": -1},
        {"kind": "quantiles", "quantiles": [{"p": 0.9, "value": 1}, {"p": 0.1, "value": 3}]},
        {"kind": "interval", "lower": True, "upper": 3},
        {"kind": "normal", "mean": float("nan"), "stddev": 1},
    ],
)
def test_malformed_estimates_are_rejected_atomically(value):
    world = source_world("result")
    before = world.graph.snapshot()
    with pytest.raises(ContractError):
        save_result(world, value)
    assert world.graph.snapshot()["nodes"] == before["nodes"]


async def test_program_read_calls_model_child_then_validates_without_materialization():
    world = source_world(required_parameters=["loaded"])
    calls = []
    before = world.graph.snapshot()

    async def step(method, payload, *, journal=True):
        calls.append((method, journal))
        return world.operations.execute(
            method,
            payload,
            metadata={"task_id": "task", "program": {"role": "model", "revision": "test"}},
        )

    async def call(program, arguments):
        assert program == world.program
        calls.append(("child", arguments["parameters"]))
        return ProgramResult(output_for({"arguments": arguments}))

    result = await read(
        SimpleNamespace(step=step, call=call),
        "read_property",
        {
            "subject": world.subject,
            "property": world.property,
            "at": AT.isoformat(),
            "parameters": {"loaded": True},
        },
    )
    assert result["value_U"] == 2 and result["belief_data"] is None
    assert calls == [
        ("attribution.prepare_read", False),
        ("child", {"loaded": True}),
        ("attribution.finish_read", True),
    ]
    assert world.graph.snapshot() == before


def test_unavailable_computation_is_unknown_but_malformed_output_is_an_error():
    world = source_world()
    request = prepare_program_read(world.attribution, world.subject, world.property, valid_at=AT)
    malformed = output_for(request)
    malformed["subject"] += 1
    with pytest.raises(ContractError, match="different subject"):
        finish_program_read(world.attribution, request, malformed)
    assert finish_program_read(world.attribution, request, {"$unknown": True}) is UNKNOWN
    world.graph.apply(
        GraphDelta(
            updates=(NodeUpdate(world.program, {"properties": {"role": "model", "active": False}}),)
        ),
        provenance="deactivate",
    )
    assert (
        prepare_program_read(world.attribution, world.subject, world.property, valid_at=AT)
        is UNKNOWN
    )


def test_inapplicable_subject_or_facet_cannot_schedule_a_computation():
    world = source_world()
    other = Node(world.graph.reserve_id(), "Outside domain")
    facet = Facet(world.graph.reserve_id(), "Unknown parcel state", valid_from=AT)
    identity = world.graph.new_fact(
        "STATE_IDENTITY", {"facet": facet.id, "instance": world.subject}
    )
    world.graph.apply(GraphDelta(creates=(other, facet, identity)), provenance="source")
    assert prepare_program_read(world.attribution, other.id, world.property, valid_at=AT) is UNKNOWN
    assert (
        prepare_program_read(
            world.attribution, facet.id, world.property, valid_at=AT + timedelta(days=1)
        )
        is UNKNOWN
    )
    assert (
        prepare_program_read(world.attribution, facet.id, world.property, valid_at=AT)["status"]
        == "requires_computation"
    )


async def test_computed_selection_uses_the_same_model_read_and_preserves_unknowns():
    world = source_world(applies_to=[])
    second = Node(world.graph.reserve_id(), "Beta")
    missing = Node(world.graph.reserve_id(), "Unknown estimate")
    world.graph.apply(GraphDelta(creates=(second, missing)), provenance="source")
    calls = []

    async def step(method, payload, *, journal=True):
        calls.append(method)
        return world.operations.execute(
            method,
            payload,
            metadata={"task_id": "task", "program": {"role": "model", "revision": "test"}},
        )

    async def call(program, arguments):
        assert program == world.program
        if arguments["subject"] == missing.id:
            return ProgramResult({"$unknown": True})
        return ProgramResult(
            output_for(
                {"arguments": arguments}, 28000 if arguments["subject"] == second.id else 15000
            )
        )

    before = world.graph.snapshot(), world.beliefs.snapshot()
    result = await read(
        SimpleNamespace(step=step, call=call),
        "select_properties",
        {
            "subjects": [world.subject, second.id, missing.id],
            "filters": [{"property": world.property, "op": ">=", "value": 10}],
            "order_by": {"property": world.property, "direction": "nearest", "value": 25},
            "limit": 1,
            "at": AT.isoformat(),
        },
    )
    assert result["items"][0]["subject"] == second.id
    assert result["items"][0]["score"] == 3
    assert result["total"] == 2 and result["unknown"] == [missing.id]
    assert calls == ["attribution.prepare_selection", "attribution.finish_selection"]
    assert before == (world.graph.snapshot(), world.beliefs.snapshot())


@pytest.mark.parametrize("op,value", [(">", "heavy"), ("approx", True), ("in", [2, "heavy"])])
async def test_invalid_numeric_selection_is_rejected_before_executing_program(op, value):
    world = source_world()
    executed = []

    async def step(method, payload, *, journal=True):
        return world.operations.execute(
            method,
            payload,
            metadata={"task_id": "task", "program": {"role": "model", "revision": "test"}},
        )

    async def call(program, arguments):
        executed.append(program)
        return ProgramResult(output_for({"arguments": arguments}))

    with pytest.raises(ContractError, match="finite numeric value"):
        await read(
            SimpleNamespace(step=step, call=call),
            "select_properties",
            {
                "subjects": [world.subject],
                "filters": [{"property": world.property, "op": op, "value": value}],
            },
        )
    assert executed == []


def test_computed_contract_change_and_historical_code_cannot_be_substituted():
    world = source_world()
    request = prepare_program_read(world.attribution, world.subject, world.property, valid_at=AT)
    assert (
        prepare_program_read(
            world.attribution, world.subject, world.property, valid_at=AT, known_at=AT
        )
        is UNKNOWN
    )
    node = world.graph.get(world.property)
    world.graph.apply(
        GraphDelta(
            updates=(
                NodeUpdate(
                    node.id,
                    {
                        "properties": {
                            "attribution": {**node.properties["attribution"], "unit": "g"}
                        }
                    },
                ),
            )
        ),
        provenance="change",
    )
    with pytest.raises(ContractError, match="changed during"):
        finish_program_read(world.attribution, request, output_for(request))


def test_newer_retained_unknown_does_not_resurrect_an_older_computation():
    world = source_world()
    request = prepare_program_read(world.attribution, world.subject, world.property, valid_at=AT)
    for output in (output_for(request), UNKNOWN):
        run = world.memory.start_run(world.program, "revision", request["arguments"])
        world.memory.record(
            run, "run_finished", output={"type": "run_finished", "result": {"result": output}}
        )
        world.memory.finish_run(run)
    world.graph.known_at = utcnow()
    assert (
        prepare_program_read(
            world.attribution,
            world.subject,
            world.property,
            valid_at=AT,
            known_at=world.graph.known_at,
        )
        is UNKNOWN
    )


def test_selection_fixes_one_world_time_for_all_computed_and_ordinary_reads(monkeypatch):
    world = source_world(applies_to=[])
    second = Node(world.graph.reserve_id(), "Beta")
    world.graph.apply(GraphDelta(creates=(second,)), provenance="source")
    times = iter((AT, AT + timedelta(days=1)))
    monkeypatch.setattr("evertree.core.attribution_sources.utcnow", lambda: next(times))
    plan = prepare_selection(
        world.attribution,
        [world.subject, second.id],
        order_by={"property": world.property, "direction": "asc"},
    )
    assert plan["arguments"]["valid_at"] == AT.isoformat()
    assert [request["arguments"]["valid_at"] for request in plan["requests"]] == [
        AT.isoformat(),
        AT.isoformat(),
    ]
    assert next(times) == AT + timedelta(days=1)


def test_saved_result_requires_matching_declared_source_and_subject():
    world = source_world()
    with pytest.raises(ContractError, match="source=result"):
        save_result(world, 1)
    world = source_world("result")
    with pytest.raises(ContractError, match="existing subject"):
        save_result(world, 1, subject=99999)


def test_typed_numeric_value_is_not_an_ordinal_distance():
    from evertree.core.attribution import PropertyDefinition

    with pytest.raises(ContractError, match="outside"):
        typed_value(
            3,
            PropertyDefinition(1, source="result", scale="ordinal", classes=("low", "high")),
            None,
        )
