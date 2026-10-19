"""Direct semantic writes preserve graph invariants and the grounds of corrections."""

from dataclasses import replace
from datetime import timedelta

import pytest

from evertree.core.graph.types import GraphDelta, Node
from evertree.core.memory.types import TraceOutputRef
from evertree.core.semantics.tools import TOOLS_BY_NAME, validate_action
from evertree.core.values import UNKNOWN, ContractError
from tests.support.semantics import recorded_experience, semantic_world, write_action


class Writer:
    def __init__(self, *contents):
        self.world = semantic_world()
        self.refs, self.metadata = recorded_experience(
            self.world, *(contents or ["Pump P1 was noisy after startup."])
        )
        self.sequence = 0

    def apply(self, action, **fields):
        self.sequence += 1
        return write_action(
            self.world,
            self.refs,
            self.metadata,
            {"action": action, "sources": self.refs, **fields},
            key=str(self.sequence),
        )

    def create(self, action, name, **fields):
        result = self.apply(action, name=name, description=None, **fields)
        assert "error" not in result, result
        identity = result["object"]
        assert type(identity) is int and identity > 0
        assert self.world.graph.get(identity).name == name
        return identity

    def equipment(self):
        prototype = self.create("create_prototype", "Pump", parent=None)
        instance = self.create("create_instance", "P1", prototype=prototype)
        return prototype, instance


def test_creation_immediately_supplies_identity_links_and_relation_views():
    writer = Writer()
    prototype, instance = writer.equipment()
    facet = writer.create(
        "create_facet", "P1 after startup", instance=instance, valid_from=None, valid_until=None
    )
    relation = writer.create(
        "define_relation",
        "HAS_NOISE",
        roles=[
            {"label": "state", "value_type": "facet", "arity": "one"},
            {"label": "noise", "value_type": "string", "arity": "one"},
        ],
    )
    result = writer.apply(
        "relate",
        relation=relation,
        arguments=[{"role": "state", "value": facet}, {"role": "noise", "value": "noisy"}],
        conditions=[],
        description=None,
    )
    graph = writer.world.graph
    assert "error" not in result, result
    assert graph.get(result["object"]).args["state"] == facet
    assert (
        next(
            fact for fact in graph.facts("IDENTITY_TYPE") if fact.args["instance"] == instance
        ).args["type"]
        == prototype
    )
    assert (
        next(fact for fact in graph.facts("STATE_IDENTITY") if fact.args["facet"] == facet).args[
            "instance"
        ]
        == instance
    )
    schema = graph.get(relation)
    assert [view.name for view in schema.views] == ["get_state", "get_noise"]
    assert all(view.output_arity == "list0" for view in schema.views)


def test_required_any_role_is_distinct_from_explicit_null():
    writer = Writer()
    relation = writer.create(
        "define_relation",
        "RECORDED_VALUE",
        roles=[{"label": "value", "value_type": "any", "arity": "one"}],
    )
    fields = {"relation": relation, "arguments": [], "conditions": [], "description": None}
    before = writer.world.graph.snapshot()
    assert "required slot value" in writer.apply("relate", **fields)["error"]
    assert writer.world.graph.snapshot() == before
    fields["arguments"] = [{"role": "value", "value": None}]
    result = writer.apply("relate", **fields)
    assert "error" not in result, result
    assert writer.world.graph.get(result["object"]).args["value"] is None


def test_claim_preserves_checkable_meaning_and_grounds_without_creating_belief():
    statement = (
        "Switching servers may cause reconnect failures only while requests are in flight; "
        "this is a hypothesis, not an established cause. Test with a controlled switch."
    )
    writer = Writer(statement, "Unrelated observation")
    beliefs = writer.world.operations.beliefs.snapshot()
    result = writer.apply(
        "create_claim",
        name="Server switch may cause reconnect failures",
        description=statement,
        sources=writer.refs[:1],
    )
    assert "error" not in result, result
    claim = writer.world.graph.get(result["object"])
    assert claim.id > 0 and claim.kind == "claim"
    assert claim.description == statement
    assert not claim.properties
    assert writer.world.operations.beliefs.snapshot() == beliefs
    change = writer.world.graph.changes_of(claim.id)[0]
    assert claim.id not in change.before and change.after[claim.id] == claim
    mutation = writer.world.memory.get_event(change.provenance["event_ref"])
    assert [ref.event_ref for ref in mutation.dependencies] == [writer.refs[0]["event_ref"]]


@pytest.mark.parametrize("description", [None, ""])
def test_claim_requires_full_assertion_not_only_a_title(description):
    writer = Writer()
    before = writer.world.graph.snapshot()
    result = writer.apply("create_claim", name="Possible cause", description=description)
    assert result["error"]
    assert writer.world.graph.snapshot() == before


@pytest.mark.parametrize("analytical", [False, True])
def test_note_copies_source_without_losing_qualifications(analytical):
    text = "The filter may be blocked; pressure data is missing. Check flow first."
    writer = Writer({"text": text, "only_if": "after startup", "offset": 12000})
    source = writer.refs[0]
    if analytical:
        source = writer.world.operations.execute(
            "memory.note", {"text": text, "source_refs": writer.refs}, metadata=writer.metadata
        )
        writer.refs.append(source)
    result = writer.apply("save_note", name="Diagnostic plan", source=source, sources=[])
    assert "error" not in result, result
    note = writer.world.graph.get(result["object"])
    assert note.properties["source_ref"]["event_ref"] == source["event_ref"]
    if analytical:
        assert note.description == text
    else:
        assert '"only_if": "after startup"' in note.description
        assert '"offset": 12000' in note.description


def test_note_additional_grounds_do_not_replace_copied_source():
    writer = Writer("Original reading", "Follow-up check")
    result = writer.apply(
        "save_note", name="Observation", source=writer.refs[0], sources=writer.refs[1:]
    )
    assert "error" not in result, result
    change = writer.world.graph._history[-1]
    event = writer.world.memory.get_event(change.provenance["event_ref"])
    assert {ref.event_ref for ref in event.dependencies} == {
        ref["event_ref"] for ref in writer.refs
    }
    before = writer.world.graph.snapshot()
    result = writer.apply(
        "save_note",
        name="Invalid grounds",
        source=writer.refs[0],
        sources=[{"event_ref": 999999, "output_path": []}],
    )
    assert result["error"]
    assert writer.world.graph.snapshot() == before


def test_source_descendants_resolve_without_accessing_unsupplied_material():
    writer = Writer({"observations": ["noisy", "warm"]}, "Unavailable to this write")
    source = {**writer.refs[0], "output_path": ["observations", 1]}
    result = writer.apply("save_note", name="Temperature", source=source, sources=[])
    assert writer.world.graph.get(result["object"]).description == "warm"
    before = writer.world.graph.snapshot()
    writer.refs = writer.refs[:1]
    for source in (
        {"event_ref": 999999, "output_path": []},
        {**writer.refs[0], "output_path": ["observations", -1]},
    ):
        result = writer.apply("save_note", name="Invalid", source=source, sources=[])
        assert result["error"]
    assert writer.world.graph.snapshot() == before


def test_update_preserves_identity_and_separate_correction_history():
    writer = Writer("The pump appears hot", "A measurement shows it is cool", "Corrected reading")
    result = writer.apply("save_note", name="Temperature", source=writer.refs[0], sources=[])
    identity = result["object"]
    for description, sources in (
        ("The pump is cool", writer.refs[1:2]),
        ("It is 20 C", writer.refs[2:]),
    ):
        result = writer.apply(
            "update", object=identity, changes={"description": description}, sources=sources
        )
        assert result["object"] == identity
        assert writer.world.graph.get(identity).description == description
    changes = writer.world.graph._history[-3:]
    assert identity not in changes[0].before
    assert changes[1].before[identity].description == "The pump appears hot"
    assert changes[1].after[identity].description == "The pump is cool"
    assert changes[2].before[identity].description == "The pump is cool"
    assert changes[2].after[identity].description == "It is 20 C"
    for change, source in zip(changes, writer.refs, strict=True):
        assert change.at is not None
        event = writer.world.memory.get_event(change.provenance["event_ref"])
        assert [ref.event_ref for ref in event.dependencies] == [source["event_ref"]]
    memory = writer.world.memory
    source_run = memory.get_run(memory.get_event(writer.refs[0]["event_ref"]).program_run)
    retained = tuple(ref["event_ref"] for ref in writer.refs)
    memory.compact(source_run.id, retained, at=changes[-1].at + timedelta(days=90))
    assert [memory.resolve(TraceOutputRef(ref)) for ref in retained] == [
        "The pump appears hot",
        "A measurement shows it is cool",
        "Corrected reading",
    ]
    memory.validate()


def test_update_replaces_composite_fields_and_validates_types():
    writer = Writer()
    identity = writer.create("create_concept", "Temperature")
    for properties in (
        {"units": {"symbol": "C", "scale": "celsius"}, "old": True},
        {"units": {"symbol": "K"}},
    ):
        result = writer.apply("update", object=identity, changes={"properties": properties})
        assert "error" not in result, result
    assert writer.world.graph.get(identity).properties == {"units": {"symbol": "K"}}
    before = writer.world.graph.snapshot()
    for changes in (
        {"id": 999},
        {"kind": "program"},
        {"belief_target": "x"},
        {"valid_until": None},
        {"description": 42},
        {"properties": []},
    ):
        result = writer.apply("update", object=identity, changes=changes)
        assert result["error"], changes
        assert writer.world.graph.snapshot() == before


def test_general_update_corrects_both_facet_boundaries_and_rejects_empty_interval():
    writer = Writer()
    _, instance = writer.equipment()
    facet = writer.create(
        "create_facet",
        "Initial state",
        instance=instance,
        valid_from="2026-10-01T12:00:00+00:00",
        valid_until=None,
    )
    result = writer.apply(
        "update",
        object=facet,
        changes={
            "valid_from": "2026-10-01T10:00:00+00:00",
            "valid_until": "2026-10-02T12:00:00+00:00",
        },
    )
    assert result["object"] == facet
    assert writer.world.graph.get(facet).valid_from.hour == 10
    assert writer.world.graph.get(facet).valid_until.day == 2
    before = writer.world.graph.snapshot()
    invalid = writer.apply(
        "update", object=facet, changes={"valid_until": "2026-09-01T12:00:00+00:00"}
    )
    assert invalid["error"]
    assert writer.world.graph.snapshot() == before
    assert "error" not in writer.apply("update", object=facet, changes={"valid_until": None})
    assert writer.world.graph.get(facet).valid_until is None


def test_delete_rejects_live_dependencies_and_keeps_removed_objects_history():
    writer = Writer()
    prototype, instance = writer.equipment()
    graph = writer.world.graph
    link = next(fact for fact in graph.facts("IDENTITY_TYPE") if fact.args["instance"] == instance)
    before = graph.snapshot()
    assert writer.apply("delete", objects=[prototype])["error"]
    assert graph.snapshot() == before
    result = writer.apply("delete", objects=[prototype, instance, link.id])
    assert set(result["deleted"]) == {prototype, instance, link.id}
    assert not graph.lookup("P1") and not graph.lookup("Pump")
    assert set(graph._history[-1].before) == {prototype, instance, link.id}
    assert not graph._history[-1].after
    assert writer.world.memory.resolve(TraceOutputRef(**writer.refs[0]))


def test_protected_objects_program_authority_and_evaluated_facts_remain_guarded():
    writer = Writer()
    graph = writer.world.graph
    protected = Node(graph.reserve_id(), "Protected")
    program = Node(graph.reserve_id(), "Executable", kind="program")
    fact = replace(
        graph.new_fact("PART_WHOLE", {"part": protected.id, "whole": program.id}),
        belief_target="evaluated-target",
    )
    graph.apply(GraphDelta(creates=(protected, program, fact)), provenance="seed")
    writer.world.operations.protected_nodes = {protected.id}
    for identity in (protected.id, program.id, fact.id):
        before = graph.snapshot()
        assert writer.apply("update", object=identity, changes={"properties": {"changed": True}})[
            "error"
        ]
        assert writer.apply("delete", objects=[identity])["error"]
        assert graph.snapshot() == before
    for identity in (fact.id, fact.relation_type):
        before = (graph.snapshot(), writer.world.memory.snapshot())
        result = writer.apply(
            "update", object=identity, changes={"description": "Changed qualification"}
        )
        assert "requires evidence assessment" in result["error"]
        assert (graph.snapshot(), writer.world.memory.snapshot()) == before


def test_conditions_distinguish_equal_arguments_and_constrain_property_reads():
    writer = Writer("Flow is 3 only under high load")
    _, instance = writer.equipment()
    property_id = writer.create("create_concept", "Flow")
    relation = writer.world.graph.find("HAS_NUMERIC_VALUE").id
    for load, value in (("high", 3), ("low", 1)):
        result = writer.apply(
            "relate",
            relation=relation,
            arguments=[
                {"role": "entity", "value": instance},
                {"role": "property", "value": property_id},
                {"role": "value", "value": value},
            ],
            description=None,
            conditions=[{"parameter": "load", "value": load}],
        )
        assert "error" not in result, result
    read = writer.world.attribution.read_property
    assert read(instance, property_id) is UNKNOWN
    assert read(instance, property_id, load="high").value_U == 3
    assert read(instance, property_id, load="low").value_U == 1
    assert all(fact.belief_target is None for fact in writer.world.graph.facts(relation))


def test_action_contract_has_no_status_protocol_or_storage_fields():
    assert not set(TOOLS_BY_NAME) & {
        "finish",
        "reuse",
        "trace_only",
        "unresolved",
        "fulfill",
        "discard",
        "retract",
        "change_state_end",
    }
    action = {
        "action": "create_concept",
        "name": "Noise",
        "description": None,
        "sources": [{"event_ref": 1, "output_path": []}],
    }
    for field, value in (("id", -10), ("belief_target", "x"), ("reason", "unneeded")):
        with pytest.raises(ValueError, match="unexpected"):
            validate_action({**action, field: value})
    for identity in (-1, 0, True, 1.5):
        with pytest.raises((ValueError, ContractError)):
            validate_action(
                {
                    "action": "update",
                    "object": identity,
                    "changes": {"description": "x"},
                    "sources": action["sources"],
                }
            )


def test_general_update_replaces_relation_signature_views_and_checks_existing_facts():
    writer = Writer()
    relation = writer.create(
        "define_relation",
        "READING",
        roles=[{"label": "value", "value_type": "number", "arity": "one"}],
    )
    result = writer.apply(
        "update",
        object=relation,
        changes={
            "signature": [{"label": "value", "value_type": "string", "arity": "list1"}],
            "views": [
                {"name": "read_values", "inputs": [], "outputs": ["value"], "output_arity": "list0"}
            ],
        },
    )
    assert "error" not in result, result
    schema = writer.world.graph.get(relation)
    assert schema.signature[0].value_type == "string"
    assert schema.signature[0].arity == "list1"
    assert [view.name for view in schema.views] == ["read_values"]
    fields = {
        "relation": relation,
        "arguments": [{"role": "value", "value": ["warm", "noisy"]}],
        "description": None,
        "conditions": [],
    }
    fact = writer.apply("relate", **fields)
    assert "error" not in fact, fact
    before = writer.world.graph.snapshot()
    assert writer.apply(
        "update",
        object=relation,
        changes={"signature": [{"label": "value", "value_type": "number", "arity": "one"}]},
    )["error"]
    assert writer.apply(
        "update",
        object=relation,
        changes={"views": [{"name": "invalid", "inputs": [], "outputs": ["missing"]}]},
    )["error"]
    assert writer.apply("update", object=fact["object"], changes={"args": {"value": []}})["error"]
    assert writer.world.graph.snapshot() == before


def test_duplicate_fact_and_update_rejected_but_distinct_conditions_are_valid():
    writer = Writer()
    relation = writer.create(
        "define_relation",
        "NOISE",
        roles=[{"label": "noise", "value_type": "string", "arity": "one"}],
    )
    fields = {
        "relation": relation,
        "arguments": [{"role": "noise", "value": "quiet"}],
        "description": None,
    }
    first = writer.apply(
        "relate", **fields, conditions=[{"parameter": "state", "value": "after startup"}]
    )
    second = writer.apply(
        "relate", **fields, conditions=[{"parameter": "state", "value": "after cleaning"}]
    )
    assert first["object"] != second["object"]
    before = writer.world.graph.snapshot()
    duplicate = writer.apply(
        "relate", **fields, conditions=[{"parameter": "state", "value": "after startup"}]
    )
    assert "Fact already exists" in duplicate["error"]
    duplicate_update = writer.apply(
        "update",
        object=second["object"],
        changes={"properties": {"conditions": {"state": "after startup"}}},
    )
    assert "Fact already exists" in duplicate_update["error"]
    assert writer.world.graph.snapshot() == before


@pytest.mark.parametrize(
    ("program", "operator", "encoding", "text_only"),
    [
        ("ExperienceFragments", "experience_fragment", "analytical_text", True),
        ("Other", "experience_fragment", "analytical_text", False),
        ("ExperienceFragments", "other", "analytical_text", False),
        ("ExperienceFragments", "experience_fragment", "json", False),
    ],
)
def test_only_trusted_analytical_fragments_use_text_as_note_content(
    program, operator, encoding, text_only
):
    writer = Writer()
    memory = writer.world.memory
    source_run = memory.start_run(program, "revision", {})
    event = memory.record(
        source_run,
        operator,
        output={
            "text": "Noisy",
            "only_if": "after startup",
            "offset": 12000,
            "total_characters": 23000,
            "encoding": encoding,
        },
    )
    memory.finish_run(source_run)
    from evertree.core.values import json_value

    source = json_value(memory.output_ref(event))
    writer.refs.append(source)
    result = writer.apply("save_note", name="Partial observation", source=source, sources=[])
    assert "error" not in result, result
    description = writer.world.graph.get(result["object"]).description
    if text_only:
        assert description == "Noisy"
    else:
        assert '"only_if": "after startup"' in description
        assert '"offset": 12000' in description
