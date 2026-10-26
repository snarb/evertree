"""Qualitative assessment uses real retained sources and the shared belief updater."""

import json
from datetime import UTC, datetime

import pytest

from evertree.core.attribution import AttributionRuntime
from evertree.core.attribution_evidence import AttributionEvidence
from evertree.core.attribution_norms import refresh_norm
from evertree.core.beliefs import BeliefStore, element_target
from evertree.core.evidence import GraphEvidence, origin_target
from evertree.core.graph.store import GraphStore
from evertree.core.memory.store import TraceStore
from evertree.core.memory.types import TraceOutputRef
from evertree.core.semantics.reading import describe
from evertree.core.values import UNKNOWN, ContractError
from evertree.processes.self_learning.self_evidence_assessment.self_graph_evidence_assessment._exec import (
    _assess_properties,
    run,
)
from tests.support.semantics import (
    context,
    recorded_experience,
    recorded_messages,
    semantic_world,
    write_action,
)


class QualitativeWorld:
    def __init__(self):
        self.world = semantic_world()
        self.sequence = 0
        self.domain = self.create("create_prototype", "Dog", parent=None)
        self.numeric = self.create(
            "create_property", "Body mass", unit="kg", applies_to=[self.domain]
        )
        self.classes = [
            self.create("create_concept", name) for name in ("Small", "Medium", "Large")
        ]
        self.subjects, self.facts, self.sources = [], [], []
        for name, value in (("Jack", 2), ("Luna", 5), ("Rex", 8)):
            self.measurement(name, value)
        self.property = self.create(
            "create_qualitative_property",
            "Relative size",
            property=self.numeric,
            domain=self.domain,
            classes=self.classes,
            conditions={},
        )
        self.assessment = AttributionEvidence(self.world.attribution, self.world.memory)

    def write(self, action, *, text=None, **fields):
        self.sequence += 1
        sources = recorded_messages(self.world, text or f"Definition: {fields}")
        _, metadata = recorded_experience(self.world)
        result = write_action(
            self.world,
            sources,
            metadata,
            {"action": action, "sources": sources, **fields},
            key=str(self.sequence),
        )
        assert "error" not in result, result
        return result["object"], sources[0]

    def create(self, action, name, **fields):
        return self.write(action, name=name, description=None, **fields)[0]

    def measurement(self, name, value, *, subject=None, prototype=None):
        if subject is None:
            subject = self.create("create_instance", name, prototype=prototype or self.domain)
        fact, source = self.write(
            "relate",
            text=f"{name} weighs {value} kg, according to its owner.",
            relation=self.world.graph.find("HAS_NUMERIC_VALUE").id,
            arguments=[
                {"role": key, "value": item}
                for key, item in {
                    "entity": subject,
                    "property": self.numeric,
                    "value": value,
                    "unit": "kg",
                }.items()
            ],
            conditions=[],
            description="An owner's reported measurement",
        )
        self.subjects.append(subject)
        self.facts.append(fact)
        self.sources.append(source)
        return subject

    def prepare(self, index=0):
        return self.assessment.prepare(self.subjects[index], self.property)

    def record(self, prepared=None, *, assign=None):
        prepared = prepared or self.prepare()
        if assign is None:
            source = next(item for item in prepared["sources"] if item["role"] == "measurement")
            chosen = prepared["conditional_interpretation"]["class"]
            assign = [
                {
                    "source_ref": source["ref"],
                    "likelihoods": {
                        str(identity): 0.75 if identity == chosen else 0.25
                        for identity in self.classes
                    },
                    "dependency_root": source["dependency_root"],
                }
            ]
        return self.assessment.record(
            prepared["subject"],
            self.property,
            prepared["input_revision"],
            assign=assign,
            parameters=prepared["parameters"],
            at=prepared["at"],
        )


def test_preparation_and_reads_do_not_assess_or_count_norm_rows_as_evidence():
    data = QualitativeWorld()
    world = data.world
    before = world.graph.snapshot(), world.beliefs.snapshot(), world.attribution.snapshot()
    prepared = data.prepare()
    assert prepared["norm"]["belief_status"] == "unassessed"
    assert len([source for source in prepared["sources"] if source["role"] == "measurement"]) == 1
    assert prepared["norm"]["state"]["count"] == 3
    assert world.attribution.read_property(data.subjects[0], data.property) is UNKNOWN
    assert before == (
        world.graph.snapshot(),
        world.beliefs.snapshot(),
        world.attribution.snapshot(),
    )
    data.record(prepared)
    reading = world.attribution.read_property(data.subjects[0], data.property)
    assert reading is not UNKNOWN
    assert reading.value_U is None
    assert set(reading.belief_data.profile) == set(map(str, data.classes))
    assert max(reading.belief_data.profile.values()) <= 0.75
    assert reading.belief_data.stats.evidence_count == 1
    assert reading.source_facts == (data.facts[0],)
    assert reading.provenance["norm_revision"] == 1
    before = world.graph.snapshot(), world.beliefs.snapshot(), world.attribution.snapshot()
    assert world.attribution.read_property(data.subjects[0], data.property) == reading
    assert before == (
        world.graph.snapshot(),
        world.beliefs.snapshot(),
        world.attribution.snapshot(),
    )


def test_repeat_is_idempotent_and_changed_norm_requires_reassessment_of_same_question():
    data = QualitativeWorld()
    first = data.prepare()
    data.record(first)
    assignments = data.world.beliefs.snapshot()["assignments"]
    data.record(first)
    assert data.world.beliefs.snapshot()["assignments"] == assignments
    data.measurement("Grom", 30)
    assert data.world.attribution.read_property(data.subjects[0], data.property) is UNKNOWN
    delta = refresh_norm(data.world.attribution, data.property)
    data.world.graph.apply(delta, provenance="batch refresh")
    second = data.prepare()
    assert first["target"] == second["target"]
    assert first["input_revision"] != second["input_revision"]
    with pytest.raises(ContractError, match="inputs changed"):
        data.record(first)
    assert data.world.attribution.read_property(data.subjects[0], data.property) is UNKNOWN
    data.record(second)
    assert data.world.attribution.read_property(data.subjects[0], data.property) is not UNKNOWN


def test_changing_class_meaning_creates_new_target_without_erasing_old_profile():
    data = QualitativeWorld()
    first = data.prepare()
    data.record(first)
    old = data.world.beliefs.read(first["target"])
    data.write(
        "revise_property_norm",
        object=data.property,
        property=data.numeric,
        domain=data.domain,
        classes=data.classes,
        conditions={},
        quantiles=[0.2, 0.8],
    )
    second = data.prepare()
    assert second["target"] != first["target"]
    assert data.world.beliefs.read(first["target"]) == old
    assert data.world.attribution.read_property(data.subjects[0], data.property) is UNKNOWN


def test_class_description_change_requires_new_semantic_scope_after_refresh():
    data = QualitativeWorld()
    first = data.prepare()
    data.record(first)
    previous = data.world.beliefs.read(first["target"])
    data.write(
        "update",
        object=data.classes[0],
        changes={"description": "The smallest third by mass within this retained population."},
    )
    assert data.prepare() is UNKNOWN
    data.world.graph.apply(
        refresh_norm(data.world.attribution, data.property), provenance="criterion refresh"
    )
    revised = data.prepare()
    assert revised["target"] != first["target"]
    assert revised["prior"] is None
    assert data.world.beliefs.read(first["target"]) == previous
    assert data.world.attribution.read_property(data.subjects[0], data.property) is UNKNOWN


def test_withdrawn_measurement_invalidates_profile_and_empty_reassessment_returns_prior():
    data = QualitativeWorld()
    prepared = data.prepare()
    data.record(prepared)
    [withdrawal] = recorded_messages(data.world, "I withdraw Jack's reported weight.")
    source = TraceOutputRef(**data.sources[0])
    data.world.beliefs.withdraw(source, TraceOutputRef(**withdrawal))
    assert data.world.attribution.read_property(data.subjects[0], data.property) is UNKNOWN
    changed = data.prepare()
    assert changed["input_revision"] != prepared["input_revision"]
    with pytest.raises(ContractError, match="primary measurement source"):
        data.record(changed)
    data.record(changed, assign=[])
    reading = data.world.attribution.read_property(data.subjects[0], data.property)
    assert reading.belief_data.stats.evidence_count == 0
    assert reading.belief_data.support == 0
    assert list(reading.belief_data.profile.values()) == pytest.approx([1 / 3] * 3)


def test_training_sources_cannot_become_independent_votes_about_the_subject():
    data = QualitativeWorld()
    prepared = data.prepare()
    source = next(item for item in prepared["sources"] if item["role"] == "norm_context")
    before = data.world.beliefs.snapshot(), data.world.attribution.snapshot()
    with pytest.raises(ContractError, match="primary measurement source"):
        data.record(
            prepared,
            assign=[
                {
                    "source_ref": source["ref"],
                    "likelihoods": {str(value): 0.5 for value in data.classes},
                }
            ],
        )
    assert before == (data.world.beliefs.snapshot(), data.world.attribution.snapshot())


def test_serialized_restore_keeps_scope_and_freshness_without_manual_binding():
    data = QualitativeWorld()
    data.record()
    world = data.world
    graph = GraphStore.from_snapshot(json.loads(json.dumps(world.graph.snapshot())))
    beliefs = BeliefStore.from_snapshot(json.loads(json.dumps(world.beliefs.snapshot())))
    runtime = AttributionRuntime.from_snapshot(
        json.loads(json.dumps(world.attribution.snapshot())), graph, beliefs
    )
    runtime.memory = TraceStore.from_snapshot(json.loads(json.dumps(world.memory.snapshot())))
    restored = runtime.read_property(data.subjects[0], data.property)
    original = world.attribution.read_property(data.subjects[0], data.property)
    assert restored.belief_data == original.belief_data
    assert restored.provenance == original.provenance


def test_default_explicit_time_and_describe_share_the_same_state_profile():
    data = QualitativeWorld()
    prepared = data.prepare()
    data.record(prepared)
    explicit = data.assessment.prepare(
        data.subjects[0], data.property, at=datetime(2026, 10, 19, tzinfo=UTC)
    )
    assert explicit["target"] == prepared["target"]
    assert explicit["input_revision"] == prepared["input_revision"]
    reading = data.world.attribution.read_property(
        data.subjects[0], data.property, valid_at=datetime(2026, 10, 19, tzinfo=UTC)
    )
    assert reading is not UNKNOWN
    description = describe(data.world.graph, data.world.attribution, data.subjects[0])
    item = next(item for item in description["properties"] if item["id"] == data.property)
    assert item["status"] == "known"


def test_instants_within_a_facet_share_a_question_but_distinct_states_do_not():
    data = QualitativeWorld()
    dog = data.create("create_instance", "Nora", prototype=data.domain)
    for name, start, end, value in (
        ("Spring state", "2026-03-01T00:00:00Z", "2026-06-01T00:00:00Z", 4),
        ("Summer state", "2026-06-01T00:00:00Z", "2026-09-01T00:00:00Z", 7),
    ):
        facet = data.create("create_facet", name, instance=dog, valid_from=start, valid_until=end)
        data.measurement(name, value, subject=facet)
    data.world.graph.apply(
        refresh_norm(data.world.attribution, data.property), provenance="refresh"
    )
    spring = data.assessment.prepare(dog, data.property, at="2026-04-01T00:00:00Z")
    data.record(spring)
    later = data.assessment.prepare(dog, data.property, at="2026-05-01T00:00:00Z")
    summer = data.assessment.prepare(dog, data.property, at="2026-07-01T00:00:00Z")
    assert spring["target"] == later["target"]
    assert spring["input_revision"] == later["input_revision"]
    assert spring["target"] != summer["target"]
    facet = spring["question"]["states"][0]
    facet_question = data.assessment.prepare(facet, data.property, at="2026-04-01T00:00:00Z")
    assert facet_question["target"] == spring["target"]
    assert facet_question["input_revision"] == spring["input_revision"]
    assert (
        data.world.attribution.read_property(
            facet, data.property, valid_at="2026-04-01T00:00:00Z"
        ).belief_data
        == data.world.attribution.read_property(
            dog, data.property, valid_at="2026-04-01T00:00:00Z"
        ).belief_data
    )
    assert (
        data.world.attribution.read_property(dog, data.property, valid_at="2026-05-01T00:00:00Z")
        is not UNKNOWN
    )
    assert (
        data.world.attribution.read_property(dog, data.property, valid_at="2026-07-01T00:00:00Z")
        is UNKNOWN
    )


def test_breed_norm_assessment_excludes_other_dogs_even_with_numeric_measurements():
    data = QualitativeWorld()
    breed = data.create("create_prototype", "Chihuahua", parent=data.domain)
    subjects = [
        data.measurement(name, value, prototype=breed)
        for name, value in (("Tiny", 1), ("Mini", 2), ("Milo", 3))
    ]
    specific = data.create(
        "create_qualitative_property",
        "Chihuahua size",
        property=data.numeric,
        domain=breed,
        classes=data.classes,
        conditions={},
    )
    assert data.assessment.prepare(data.subjects[0], specific) is UNKNOWN
    pending = data.assessment.pending()["scopes"]
    assert {item["subject"] for item in pending if item["property"] == specific} == set(subjects)


def test_initial_norm_assessment_includes_the_pinned_training_sources():
    data = QualitativeWorld()
    batch = GraphEvidence(data.world.graph, data.world.memory, data.world.beliefs).pending(
        candidates=[data.property]
    )
    norm = next(item for item in batch["targets"] if item["element"] == data.property)
    sources = {item["key"]: item["text"] for item in batch["sources"]}
    texts = [sources[key] for key in norm["grounds"]]
    assert all(
        any(f"{name} weighs {value} kg" in text for text in texts)
        for name, value in (("Jack", 2), ("Luna", 5), ("Rex", 8))
    )


def test_saved_result_card_exposes_claim_binding_and_bounded_quantiles_without_mutation():
    data = QualitativeWorld()
    property_id = data.create(
        "create_property",
        "Estimated mass",
        source="result",
        unit="kg",
        applies_to=[data.domain],
    )
    result_id = data.create(
        "save_property_result",
        "Jack estimate",
        subject=data.subjects[0],
        property=property_id,
        conditions={},
        unit="kg",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2027-01-01T00:00:00Z",
        value_U={
            "kind": "quantiles",
            "quantiles": [{"p": index / 30, "value": index + 1} for index in range(31)],
        },
    )
    graph = data.world.graph
    before = graph.snapshot()
    evidence = GraphEvidence(graph, data.world.memory, data.world.beliefs)
    assert evidence.assessable(graph.get(result_id))
    result = evidence._card(graph.get(result_id))["attribution_result"]
    assert result["subject"] == data.subjects[0]
    assert result["property"] == property_id
    assert result["conditions"] == {} and result["unit"] == "kg"
    assert result["valid_from"] == "2026-01-01T00:00:00Z"
    assert result["valid_until"] == "2027-01-01T00:00:00Z"
    assert len(result["value_U"]["quantiles"]) == 20
    assert result["value_U"]["quantiles_total"] == 31
    assert result["value_U"]["truncated"] is True
    assert graph.snapshot() == before


def test_origin_reassessment_invalidates_profile_and_input_dependency_is_reused():
    data = QualitativeWorld()
    beliefs = data.world.beliefs
    target = element_target(data.world.graph.get(data.facts[0]))
    beliefs.register_binary(target)
    source = TraceOutputRef(**data.sources[0])
    [root] = recorded_messages(data.world, "Original measurement report")
    beliefs.assess_likelihoods(
        target,
        source,
        {"false": 0.25, "true": 0.75},
        dependency_root=TraceOutputRef(**root),
        backed=False,
    )
    prepared = data.prepare()
    measurement = next(item for item in prepared["sources"] if item["role"] == "measurement")
    assert measurement["dependency_root"] == root
    data.record(
        prepared,
        assign=[
            {
                "source_ref": measurement["ref"],
                "likelihoods": {str(identity): 0.5 for identity in data.classes},
            }
        ],
    )
    assert beliefs.active_sources(prepared["target"])[0].dependency_root == json.dumps(
        root, sort_keys=True, separators=(",", ":")
    )
    beliefs.register_binary(origin_target("user"))
    assert data.world.attribution.read_property(data.subjects[0], data.property) is UNKNOWN
    assert data.prepare()["input_revision"] != prepared["input_revision"]


async def test_graph_assessment_automatically_assesses_property_scopes_after_graph_evidence():
    data = QualitativeWorld()
    batches = []

    async def judge(payload, call_tool=None):
        batch = json.loads(payload["prompt"])
        batches.append(batch)
        if "questions" in batch:
            return {
                "scopes": [
                    {
                        "scope": item["scope"],
                        "evidence": [
                            {
                                "source": source["key"],
                                "stances": [
                                    {
                                        "class": label["id"],
                                        "stance": "supports"
                                        if label["id"]
                                        == item["conditional_interpretation"]["class"]
                                        else "opposes",
                                    }
                                    for label in item["classes"]
                                ],
                                "repeats": None,
                                "reason": "Scripted source assessment",
                            }
                            for source in item["sources"]
                            if source["role"] == "measurement"
                        ],
                    }
                    for item in batch["questions"]
                ]
            }
        return {
            "targets": [
                {"element": item["element"], "prior": None, "evidence": [], "unresolved": None}
                for item in batch["targets"]
            ],
            "origins": [],
            "scopes": [],
        }

    result = await run(context(data.world, judge, role="exec"))
    assert len(result["result"]["properties"]) == 3
    assert any("questions" in batch for batch in batches)
    graph_batch = next(batch for batch in batches if "targets" in batch)
    norm = next(item for item in graph_batch["targets"] if item["element"] == data.property)
    assert norm["card"]["fitted_norm"]["count"] == 3
    assert "rows" not in norm["card"]["fitted_norm"]
    assert data.world.attribution.read_property(data.subjects[0], data.property) is not UNKNOWN
    assert (await run(context(data.world, judge, role="exec")))["result"]["properties"] == []


@pytest.mark.parametrize("external_reference", [False, True])
def test_changed_training_belief_stales_profile_even_for_another_subject(external_reference):
    data = QualitativeWorld()
    if external_reference:
        dependency = data.create(
            "create_property_reference",
            "Published masses",
            property=data.numeric,
            domain=data.domain,
            unit="kg",
            reference_kind="distribution",
            conditions={},
            boundaries=[],
            classes=[],
            samples=[{"lower": value, "upper": value, "count": 1} for value in (2, 5, 8)],
        )
        data.property = data.create(
            "create_qualitative_property",
            "Published relative size",
            property=data.numeric,
            domain=data.domain,
            classes=data.classes,
            conditions={},
            reference=dependency,
        )
    else:
        # The final training input is beyond the model preview, but still affects freshness.
        for index in range(25):
            data.measurement(f"Dog {index}", 10 + index)
        data.world.graph.apply(
            refresh_norm(data.world.attribution, data.property), provenance="refresh"
        )
        dependency = data.facts[-1]
    original = data.prepare()
    data.record(original)
    target = element_target(data.world.graph.get(dependency))
    beliefs = data.world.beliefs
    beliefs.register_binary(target)
    [source] = recorded_messages(data.world, "This training input is unreliable.")
    beliefs.assign(target, TraceOutputRef(**source), -4, backed=False)
    changed = data.prepare()
    assert changed["target"] == original["target"]
    assert changed["input_revision"] != original["input_revision"]
    evidence = next(
        item for item in changed["norm"]["training_evidence"] if item["object"] == dependency
    )
    assert evidence["role"] == ("reference" if external_reference else "measurement")
    assert evidence["belief"]["data"]["strength"] < 0.5
    if not external_reference:
        assert len(changed["norm"]["training_evidence"]) > 20
    assert data.world.attribution.read_property(data.subjects[0], data.property) is UNKNOWN
    with pytest.raises(ContractError, match="inputs changed"):
        data.record(original)
    data.record(changed)
    assert data.world.attribution.read_property(data.subjects[0], data.property) is not UNKNOWN


async def test_assessment_model_sees_weak_training_input_beyond_normal_preview():
    data = QualitativeWorld()
    for index in range(25):
        data.measurement(f"Dog {index}", 10 + index)
    data.world.graph.apply(
        refresh_norm(data.world.attribution, data.property), provenance="refresh"
    )
    dependency = data.facts[-1]
    beliefs = data.world.beliefs
    target = element_target(data.world.graph.get(dependency))
    beliefs.register_binary(target)
    [source] = recorded_messages(data.world, "The last input is unreliable.")
    beliefs.assign(target, TraceOutputRef(**source), -4, backed=False)
    batches = []

    async def judge(payload, call_tool=None):
        batch = json.loads(payload["prompt"])
        batches.append(batch)
        return {"scopes": []}

    await _assess_properties(context(data.world, judge, role="exec"))
    assert batches
    for question in batches[0]["questions"]:
        norm = question["norm"]
        assert len(norm["training_evidence"]) == 20
        assert norm["training_evidence_total"] > 20
        first = norm["training_evidence"][0]
        assert first["object"] == dependency
        assert first["belief"]["data"]["strength"] < 0.5
        assert (
            len([source for source in question["sources"] if source["role"] == "norm_context"])
            == 20
        )
        assert any(source["role"] == "measurement" for source in question["sources"])
        assert question["sources_total"] > len(question["sources"])
        assert any("Dog 24 weighs 34 kg" in source["text"] for source in question["sources"])
