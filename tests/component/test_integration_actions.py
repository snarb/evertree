"""Semantic choices compile to real graph invariants without model bookkeeping."""

from copy import deepcopy

import pytest

from evertree.common.integration_actions import IntegrationDraft, validate_action
from evertree.core.semantics.reading import describe
from evertree.core.values import ContractError, json_value
from tests.support.semantics import semantic_world

REF = {"event_ref": 1, "output_path": []}


def draft_for(content="Pump P1 was noisy after startup.", *, intent=False, analytical=False):
    material = {
        "experience": [{"reference": REF, "content": content}],
        "context": {"preservation_intents": []},
    }
    if analytical:
        material["experience"][0]["origin"] = {
            "operator": "analytical_note",
            "output_type": "evertree.AnalyticalNote",
        }
    if intent:
        material["context"]["preservation_intents"] = [
            {
                "id": "keep",
                "source_ref": REF,
                "text": content["text"] if analytical else content,
            }
        ]
    world = semantic_world()
    draft = IntegrationDraft(material, [json_value(node) for node in world.graph.nodes()])
    return draft, world


def create(draft, action, name, **fields):
    return draft.apply(
        {
            "action": action,
            "name": name,
            "description": None,
            "sources": [REF],
            **fields,
        }
    )["object"]


def test_actions_supply_identity_links_and_valid_atomic_delta():
    draft, world = draft_for()
    prototype = create(draft, "create_prototype", "Pump", parent=None)
    instance = create(draft, "create_instance", "P1", prototype=prototype)
    facet = create(
        draft,
        "create_facet",
        "P1 after startup",
        instance=instance,
        valid_from=None,
        valid_until=None,
    )
    relation = create(
        draft,
        "define_relation",
        "HAS_NOISE",
        roles=[
            {"label": "state", "value_type": "facet", "arity": "one"},
            {"label": "noise", "value_type": "string", "arity": "one"},
        ],
    )
    fact = draft.apply(
        {
            "action": "relate",
            "conditions": [],
            "relation": relation,
            "description": None,
            "arguments": [{"role": "state", "value": facet}, {"role": "noise", "value": "noisy"}],
            "sources": [REF],
        }
    )["object"]

    delta = world.service._proposal(draft.proposal)
    world.graph.apply(delta, provenance="test")
    assert len(delta.creates) == 7
    assert len(draft.snapshot()["objects"]) == 5
    assert {node["id"] for node in draft.proposal["creates"]} == {
        identity for decision in draft.decisions for identity in decision["affected_ids"]
    }
    assert all("reason" not in decision for decision in draft.decisions)
    assert [d["affected_ids"] for d in draft.decisions][-1] == [fact]
    schema = world.graph.find("HAS_NOISE")
    assert [view.name for view in schema.views] == ["get_state", "get_noise"]
    assert all(view.output_arity == "list0" for view in schema.views)


def test_required_reads_request_schema_after_search_card():
    draft, world = draft_for()
    draft.nodes.clear()
    relation = world.graph.find("IDENTITY_TYPE")
    draft.remember_read(
        {"items": [{"id": relation.id, "name": relation.name, "kind": relation.kind}]}
    )
    action = {
        "action": "relate",
        "conditions": [],
        "relation": relation.id,
        "description": None,
        "arguments": [],
        "sources": [REF],
    }
    assert draft.required_reads(action) == [relation.id]
    draft.remember_read(describe(world.graph, world.attribution, relation.id))
    assert draft.required_reads(action) == []
    assert draft.nodes[relation.id]["signature"][0]["label"] == "instance"


def test_required_any_role_must_be_supplied_even_when_null_is_valid():
    draft, world = draft_for()
    relation = create(
        draft,
        "define_relation",
        "RECORDED_VALUE",
        roles=[{"label": "value", "value_type": "any", "arity": "one"}],
    )
    action = {
        "action": "relate",
        "relation": relation,
        "arguments": [],
        "conditions": [],
        "description": None,
        "sources": [REF],
    }
    before = draft.proposal
    with pytest.raises(ContractError, match="required role value"):
        draft.apply(action)
    assert draft.proposal == before
    draft.apply({**action, "arguments": [{"role": "value", "value": None}]})
    assert len(world.service._proposal(draft.proposal).creates) == 2


def test_note_copies_complete_analysis_and_fulfills_matching_intent():
    text = "The filter may be blocked; pressure data is missing. Check flow first."
    draft, _ = draft_for({"text": text, "preserve": True}, intent=True, analytical=True)
    result = draft.apply(
        {"action": "save_note", "name": "Diagnostic plan", "source": REF, "sources": []}
    )
    note = draft.proposal["creates"][0]
    assert note["description"] == text
    assert note["properties"]["source_ref"] == REF
    assert draft.decisions[0]["source_refs"] == [REF]
    assert draft.decisions[0]["preservation_ids"] == ["keep"]
    assert draft.snapshot()["pending_preservation_ids"] == []
    draft.apply({"action": "discard", "object": result["object"]})
    assert draft.snapshot()["pending_preservation_ids"] == ["keep"]
    assert not draft.proposal["creates"] and not draft.decisions


def test_untyped_dictionary_text_does_not_lose_conditions_or_fragment_offsets():
    content = {
        "text": "P1 is noisy",
        "only_if": "after startup",
        "offset": 12000,
        "total_characters": 20000,
    }
    draft, _ = draft_for(content)
    draft.apply({"action": "save_note", "name": "Observation", "source": REF, "sources": [REF]})
    description = draft.proposal["creates"][0]["description"]
    assert '"only_if": "after startup"' in description
    assert '"offset": 12000' in description


def test_selected_analytical_text_child_remains_readable():
    draft, _ = draft_for({"text": "Keep the qualifying condition."}, analytical=True)
    child = {"event_ref": 1, "output_path": ["text"]}
    draft.material["experience"][0].update(
        reference=child, content="Keep the qualifying condition."
    )
    draft.apply({"action": "save_note", "name": "Condition", "source": child, "sources": [child]})
    assert draft.proposal["creates"][0]["description"] == "Keep the qualifying condition."


def test_runtime_analytical_fragment_copies_text_and_fulfills_its_preservation_intent():
    fragment = {
        "text": "Remaining explanation",
        "source_ref": REF,
        "offset": 12000,
        "total_characters": 23000,
        "encoding": "analytical_text",
    }
    draft, _ = draft_for(fragment)
    draft.material["experience"][0]["origin"] = {
        "program": "ExperienceFragments",
        "operator": "experience_fragment",
    }
    draft.intents["keep_fragment"] = {
        "id": "keep_fragment",
        "source_ref": REF,
        "text": fragment["text"],
    }
    draft.apply(
        {"action": "save_note", "name": "Partial explanation", "source": REF, "sources": []}
    )
    note = draft.proposal["creates"][0]
    assert note["description"] == fragment["text"]
    assert note["properties"]["source_ref"] == REF
    assert draft.decisions[0]["source_refs"] == [REF]
    assert draft.decisions[0]["preservation_ids"] == ["keep_fragment"]
    assert draft.snapshot()["pending_preservation_ids"] == []


@pytest.mark.parametrize(
    ("origin", "encoding"),
    [
        ({"operator": "experience_fragment"}, "analytical_text"),
        ({"program": "Other", "operator": "experience_fragment"}, "analytical_text"),
        ({"program": "ExperienceFragments", "operator": "other"}, "analytical_text"),
        ({"program": "ExperienceFragments", "operator": "experience_fragment"}, "json"),
    ],
)
def test_untrusted_or_nonanalytical_fragment_keeps_its_complete_content(origin, encoding):
    draft, _ = draft_for(
        {
            "text": "P1 is noisy",
            "only_if": "after startup",
            "offset": 12000,
            "total_characters": 23000,
            "encoding": encoding,
        }
    )
    draft.material["experience"][0]["origin"] = origin
    draft.apply({"action": "save_note", "name": "Observation", "source": REF, "sources": []})
    description = draft.proposal["creates"][0]["description"]
    assert '"only_if": "after startup"' in description
    assert '"offset": 12000' in description


def test_note_additional_grounds_do_not_replace_its_copied_source():
    draft, _ = draft_for()
    other = {"event_ref": 2, "output_path": []}
    draft.material["experience"].append({"reference": other, "content": "Follow-up check."})
    draft.apply({"action": "save_note", "name": "Observation", "source": REF, "sources": [other]})
    assert draft.decisions[0]["source_refs"] == [other, REF]
    before = draft.snapshot()
    with pytest.raises(ContractError, match="outside supplied"):
        draft.apply(
            {
                "action": "save_note",
                "name": "Invalid grounds",
                "source": REF,
                "sources": [{"event_ref": 3, "output_path": []}],
            }
        )
    assert draft.snapshot() == before


def test_node_role_aliases_match_core_prototype_and_concept_semantics():
    draft, world = draft_for()
    relation_type = world.graph.find("IDENTITY_TYPE").id
    instance = create(draft, "create_instance", "A relation object", prototype=relation_type)
    relation = create(
        draft,
        "define_relation",
        "RELATED_CONCEPT",
        roles=[
            {"label": "concept", "value_type": "concept", "arity": "one"},
        ],
    )
    draft.apply(
        {
            "action": "relate",
            "conditions": [],
            "relation": relation,
            "description": None,
            "arguments": [{"role": "concept", "value": instance}],
            "sources": [REF],
        }
    )
    delta = world.service._proposal(draft.proposal)
    assert len(delta.creates) == 4


def test_source_descendants_resolve_without_accessing_unsupplied_material():
    draft, _ = draft_for({"observations": ["noisy", "warm"]})
    selected = {"event_ref": 1, "output_path": ["observations", 1]}
    draft.apply(
        {"action": "save_note", "name": "Temperature", "source": selected, "sources": [selected]}
    )
    assert draft.proposal["creates"][0]["description"] == "warm"
    before = draft.proposal
    for ref in (
        {"event_ref": 2, "output_path": []},
        {"event_ref": 1, "output_path": ["observations", -1]},
    ):
        with pytest.raises(ContractError):
            draft.apply({"action": "save_note", "name": "Invalid", "source": ref, "sources": [REF]})
    assert draft.proposal == before


def test_failed_action_rolls_back_allocations_and_attribution():
    draft, _ = draft_for()
    before = deepcopy(draft.snapshot())
    with pytest.raises(ContractError, match="Unknown"):
        create(draft, "create_instance", "P1", prototype=987654)
    assert draft.snapshot() == before
    assert create(draft, "create_concept", "Noise") == -1


def test_fulfillment_requires_grounded_selected_objects_and_is_not_inferred_from_creation():
    draft, _ = draft_for(intent=True)
    identity = create(draft, "create_concept", "Post-start noise")
    assert draft.snapshot()["pending_preservation_ids"] == ["keep"]
    draft.apply({"action": "fulfill", "intent": "keep", "objects": [identity]})
    assert draft.snapshot()["pending_preservation_ids"] == []
    draft.apply({"action": "discard", "object": identity})
    assert draft.snapshot()["pending_preservation_ids"] == ["keep"]

    other = {"event_ref": 2, "output_path": []}
    draft.material["experience"].append({"reference": other, "content": "unrelated"})
    identity = draft.apply(
        {"action": "create_concept", "name": "Other", "description": None, "sources": [other]}
    )["object"]
    with pytest.raises(ContractError, match="grounded"):
        draft.apply({"action": "fulfill", "intent": "keep", "objects": [identity]})


def test_discard_keeps_dependents_consistent_and_removes_automatic_identity_fact():
    draft, _ = draft_for()
    prototype = create(draft, "create_prototype", "Pump", parent=None)
    instance = create(draft, "create_instance", "P1", prototype=prototype)
    with pytest.raises(ContractError, match="dependent"):
        draft.apply({"action": "discard", "object": prototype})
    result = draft.apply({"action": "discard", "object": instance})
    assert len(result["discarded"]) == 2
    assert len(draft.proposal["creates"]) == 1
    draft.apply({"action": "discard", "object": prototype})
    assert draft.proposal["creates"] == []


def test_role_types_and_state_end_are_checked_before_staging_changes():
    draft, world = draft_for()
    prototype = create(draft, "create_prototype", "Pump", parent=None)
    instance = create(draft, "create_instance", "P1", prototype=prototype)
    facet = create(
        draft,
        "create_facet",
        "Initial state",
        instance=instance,
        valid_from="2026-10-01T12:00:00+00:00",
        valid_until=None,
    )
    relation = create(
        draft,
        "define_relation",
        "TEMPERATURE",
        roles=[
            {"label": "state", "value_type": "facet", "arity": "one"},
            {"label": "value", "value_type": "number", "arity": "one"},
        ],
    )
    before = draft.proposal
    with pytest.raises(ContractError, match="facet"):
        draft.apply(
            {
                "action": "relate",
                "conditions": [],
                "relation": relation,
                "description": None,
                "arguments": [{"role": "state", "value": instance}, {"role": "value", "value": 20}],
                "sources": [REF],
            }
        )
    with pytest.raises(ContractError, match="end after"):
        draft.apply(
            {
                "action": "change_state_end",
                "object": facet,
                "valid_until": "2026-09-01T12:00:00+00:00",
                "sources": [REF],
            }
        )
    assert draft.proposal == before
    draft.apply(
        {
            "action": "change_state_end",
            "object": facet,
            "valid_until": "2026-10-02T12:00:00+00:00",
            "sources": [REF],
        }
    )
    delta = world.service._proposal(draft.proposal)
    assert next(node for node in delta.creates if node.kind == "facet").valid_until.day == 2


def test_action_contract_excludes_storage_fields_and_requires_obstacle_explanation():
    action = {"action": "create_concept", "name": "Noise", "description": None, "sources": [REF]}
    for field, value in (("id", -10), ("belief_target", "x"), ("reason", "unneeded")):
        with pytest.raises(ValueError, match="unexpected"):
            validate_action({**action, field: value})
    with pytest.raises(ValueError, match="missing"):
        validate_action({"action": "unresolved", "sources": [REF]})


def test_retract_supersedes_reuse_without_leaving_an_unrepairable_receipt():
    draft, world = draft_for(intent=True)
    concept = create(draft, "create_concept", "Temporary interpretation")
    delta = world.service._proposal(draft.proposal)
    world.graph.apply(delta, provenance="test")
    identity = delta.creates[0].id
    draft = IntegrationDraft(draft.material, [json_value(node) for node in world.graph.nodes()])
    draft.apply({"action": "reuse", "object": identity, "sources": [REF]})
    draft.apply({"action": "fulfill", "intent": "keep", "objects": [identity]})
    draft.apply({"action": "retract", "object": identity, "sources": [REF]})
    assert concept < 0
    assert draft.snapshot()["pending_preservation_ids"] == ["keep"]
    assert [decision["disposition"] for decision in draft.decisions] == [
        "trace_only",
        "materialize",
    ]
    assert draft.proposal["deletes"] == [identity]
    assert not draft.proposal["updates"]
    draft.apply({"action": "discard", "object": identity})
    assert draft.proposal["deletes"] == []
    assert draft.decisions[-1]["disposition"] == "trace_only"


def test_conditions_distinguish_equal_relation_arguments_without_generic_properties():
    draft, world = draft_for()
    relation = create(
        draft,
        "define_relation",
        "EXPECTED_NOISE",
        roles=[
            {"label": "noise", "value_type": "string", "arity": "one"},
        ],
    )
    for state in ("after startup", "after cleaning"):
        draft.apply(
            {
                "action": "relate",
                "relation": relation,
                "arguments": [{"role": "noise", "value": "quiet"}],
                "conditions": [{"parameter": "state", "value": state}],
                "description": None,
                "sources": [REF],
            }
        )
    delta = world.service._proposal(draft.proposal)
    facts = [node for node in delta.creates if node.kind == "relation_instance"]
    assert [dict(fact.properties["conditions"]) for fact in facts] == [
        {"state": "after startup"},
        {"state": "after cleaning"},
    ]
    assert all(fact.belief_target is None for fact in facts)


def test_compiled_conditions_constrain_property_reads():
    from evertree.core.values import UNKNOWN

    draft, world = draft_for("Flow is 3 only under high load")
    prototype = create(draft, "create_prototype", "Pump", parent=None)
    instance = create(draft, "create_instance", "P1", prototype=prototype)
    property_id = create(draft, "create_concept", "Flow")
    draft.apply(
        {
            "action": "relate",
            "relation": world.graph.find("HAS_NUMERIC_VALUE").id,
            "arguments": [
                {"role": "entity", "value": instance},
                {"role": "property", "value": property_id},
                {"role": "value", "value": 3},
            ],
            "description": None,
            "conditions": [{"parameter": "load", "value": "high"}],
            "sources": [REF],
        }
    )
    world.graph.apply(world.service._proposal(draft.proposal), provenance="observation")
    instance, property_node = world.graph.find("P1"), world.graph.find("Flow")
    assert world.attribution.read_property(instance, property_node) is UNKNOWN
    assert world.attribution.read_property(instance, property_node, load="low") is UNKNOWN
    assert world.attribution.read_property(instance, property_node, load="high").value_U == 3
