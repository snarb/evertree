"""Graph evidence assessment over real graph, trace and belief stores; only the model is scripted."""

import json
import math

import pytest

from evertree.core.beliefs import BeliefStore
from evertree.core.graph.types import GraphDelta
from evertree.core.memory.types import TraceOutputRef
from evertree.core.semantics.reading import describe
from evertree.core.values import json_value
from evertree.processes.learning.evidence_assessment._exec import run as assess_all
from evertree.processes.learning.evidence_assessment.graph_evidence_assessment._exec import run
from tests.support.semantics import (
    context,
    recorded_experience,
    recorded_messages,
    semantic_world,
    write_action,
)


class Judge:
    """Answer the assessment request from (source text, stance, options) rules per element."""

    def __init__(self, rules=None, *, prior=None, origins=None, origin_priors=None, scopes=None):
        self.rules = rules or {}
        self.prior = prior
        # origin name -> [(source text, stance, {withdraws})], and new-origin priors.
        self.origins = origins or {}
        self.origin_priors = origin_priors or {}
        # Scope answers; source texts in their evidence are replaced by source keys.
        self.scopes = scopes or []
        self.batches = []

    async def __call__(self, payload, call_tool=None):
        batch = json.loads(payload["prompt"])
        self.batches.append(batch)
        texts = {source["key"]: source["text"] for source in batch["sources"]}
        keys = {text: key for key, text in texts.items()}
        answers = []
        for item in batch["targets"]:
            evidence = []
            for text, stance, *options in self.rules.get(item["element"], ()):
                if text not in keys:
                    continue
                extra = dict(options[0]) if options else {}
                evidence.append(
                    {
                        "source": keys[text],
                        "stance": stance,
                        "repeats": keys.get(extra.get("repeats")),
                        "withdraws": keys.get(extra.get("withdraws")),
                        "reason": "scripted",
                    }
                )
            answers.append(
                {
                    "element": item["element"],
                    "prior": self.prior if item["new_target"] else None,
                    "evidence": evidence,
                    "unresolved": None,
                }
            )
        origins = []
        for item in batch["origins"]:
            evidence = [
                {
                    "source": keys[text],
                    "stance": stance,
                    "withdraws": keys.get((options[0] if options else {}).get("withdraws")),
                    "reason": "scripted",
                }
                for text, stance, *options in self.origins.get(item["origin"], ())
                if text in keys
            ]
            prior = self.origin_priors.get(item["origin"]) if item["reliability"] is None else None
            if evidence or prior is not None:
                origins.append({"origin": item["key"], "prior": prior, "evidence": evidence})
        scopes = [
            {
                **scope,
                "evidence": [
                    {**entry, "source": keys[entry["source"]]}
                    for entry in scope["evidence"]
                    if entry["source"] in keys
                ],
            }
            for scope in self.scopes
        ]
        return {"targets": answers, "origins": origins, "scopes": scopes}


class FixedIndex:
    """Return chosen element ids from both search channels."""

    def __init__(self):
        self.ids = []

    async def lexical(self, *args):
        return list(self.ids)

    async def vector(self, *args):
        return list(self.ids)

    async def close(self):
        pass


def claim(world, metadata, sources, name="Pump stopped", description=None):
    action = {
        "action": "create_claim",
        "name": name,
        "description": description or "Pump N-1 was off from 09:00 to 09:10 UTC.",
        "sources": sources,
    }
    result = write_action(world, sources, metadata, action, key=name)
    assert "error" not in result, result
    return result["object"]


def reading(world, element):
    return world.beliefs.read(f"graph:{element}")


async def assess(world, judge, experience_refs=None):
    return (await run(context(world, judge, role="exec"), experience_refs))["result"]


async def test_new_user_claim_gets_capped_belief_and_unchanged_graph_needs_no_model():
    """S1, S10, S11: a stated claim gains support within the unsupported cap, once."""
    world = semantic_world()
    _, metadata = recorded_experience(world)
    [message] = recorded_messages(world, "Pump N-1 was off from 09:00 to 09:10 UTC.")
    element = claim(world, metadata, [message])
    judge = Judge({element: [("Pump N-1 was off from 09:00 to 09:10 UTC.", "supports")]}, prior=0.6)
    result = await assess(world, judge, [message])
    assert [item["element"] for item in result["assessed"]] == [element]
    belief = reading(world, element)
    assert 0.6 < belief.strength <= 0.75 + 1e-9
    assert belief.support > 0 and belief.prior_support == 0
    assert belief.stats.evidence_count == 1
    assert world.beliefs.target(f"graph:{element}").prior == (0.6,)
    batch = judge.batches[0]
    assert [source["kind"] for source in batch["sources"]] == ["user"]
    assert batch["targets"][0]["grounds"] == ["S1"]

    before = world.beliefs.snapshot()
    assert (await assess(world, judge))["assessed"] == []
    assert len(judge.batches) == 1
    after = world.beliefs.snapshot()
    assert after["assignments"] == before["assignments"] and after["current"] == before["current"]
    assert after["assessment_cursor"] == world.graph.revision


async def test_independent_confirmation_adds_support_but_a_repeat_does_not():
    """S2, S3: search finds an unchanged claim; a restatement shares its source's dependency."""
    index = FixedIndex()
    world = semantic_world(index=index)
    _, metadata = recorded_experience(world)
    first, repeat = recorded_messages(
        world, "The pump was off at 09:05.", "Again: pump off at 9:05."
    )
    element = claim(world, metadata, [first])
    await assess(world, Judge({element: [("The pump was off at 09:05.", "supports")]}), [first])
    once = reading(world, element)
    [sensor] = recorded_messages(world, "N-1 current 0 A at 09:05", kind="observation")
    index.ids = [element]
    sensor_text = json.dumps({"reading": "N-1 current 0 A at 09:05"}, ensure_ascii=False)
    judge = Judge({element: [(sensor_text, "supports")]})
    result = await assess(world, judge, [sensor])
    [related] = [item for item in judge.batches[0]["targets"] if not item["changed"]]
    assert related["element"] == element
    assert [item["element"] for item in result["assessed"]] == [element]
    twice = reading(world, element)
    assert twice.stats.evidence_count == 2 and twice.support > once.support
    assert twice.strength >= once.strength

    judge = Judge(
        {
            element: [
                ("Again: pump off at 9:05.", "supports", {"repeats": "The pump was off at 09:05."})
            ]
        }
    )
    judge.rules[element].append(("The pump was off at 09:05.", "supports"))
    await assess(world, judge, [repeat, first])
    repeated = reading(world, element)
    assert repeated.stats.evidence_count == 2
    assert math.isclose(repeated.support, twice.support)


async def test_agent_reasoning_is_expanded_to_the_experience_it_cites():
    """S4: a claim grounded only in an analytical Note is assessed against the user message."""
    world = semantic_world()
    _, metadata = recorded_experience(world)
    [message] = recorded_messages(world, "The valve leaked after the restart.")
    note_ref = json_value(
        world.operations.execute(
            "memory.note",
            {"text": "The restart probably caused the leak.", "source_refs": [message]},
            metadata={**metadata, "run_id": "analysis"},
        )
    )
    element = claim(world, metadata, [note_ref], name="Valve leak")
    judge = Judge({element: [("The valve leaked after the restart.", "supports")]})
    await assess(world, judge, [note_ref])
    sources = judge.batches[0]["sources"]
    assert [source["text"] for source in sources] == ["The valve leaked after the restart."]
    [component] = world.beliefs.active_sources(f"graph:{element}")
    assert component.source_ref["event_ref"] == message["event_ref"]


async def test_contradiction_lowers_strength_and_withdrawal_retracts_the_earlier_source():
    """S5, S6: opposing evidence keeps both sides; a correction removes the corrected source."""
    index = FixedIndex()
    world = semantic_world(index=index)
    _, metadata = recorded_experience(world)
    [said] = recorded_messages(world, "Pump N-1 was off from 09:00 to 09:10 UTC.")
    element = claim(world, metadata, [said])
    await assess(
        world, Judge({element: [("Pump N-1 was off from 09:00 to 09:10 UTC.", "supports")]})
    )
    supported = reading(world, element)
    index.ids = [element]
    [sensor] = recorded_messages(world, "N-1 current 12 A at 09:04", kind="observation")
    sensor_text = json.dumps({"reading": "N-1 current 12 A at 09:04"}, ensure_ascii=False)
    await assess(world, Judge({element: [(sensor_text, "opposes")]}), [sensor])
    contested = reading(world, element)
    assert contested.strength < supported.strength
    assert contested.support > supported.support and contested.stats.evidence_count == 2

    [correction] = recorded_messages(world, "I was wrong: the pump was off only until 09:03.")
    rules = {
        element: [
            (
                "I was wrong: the pump was off only until 09:03.",
                "opposes",
                {"withdraws": "Pump N-1 was off from 09:00 to 09:10 UTC."},
            )
        ]
    }
    await assess(world, Judge(rules), [correction])
    assert world.beliefs.withdrawn_by(TraceOutputRef(said["event_ref"])) is not None
    corrected = reading(world, element)
    assert corrected.stats.evidence_count == 2 and corrected.strength < contested.strength
    sources = {
        component.source_ref["event_ref"]
        for component in world.beliefs.active_sources(f"graph:{element}")
    }
    assert sources == {sensor["event_ref"], correction["event_ref"]}


async def test_changed_element_reassesses_grounds_and_drops_ones_that_no_longer_apply():
    """S7: after an update, a ground judged not_addressed stops counting."""
    world = semantic_world()
    _, metadata = recorded_experience(world)
    old, new = recorded_messages(
        world, "Pump N-1 was off from 09:00 to 09:10 UTC.", "Pump N-1 was off from 09:00 to 09:03."
    )
    element = claim(world, metadata, [old])
    await assess(
        world, Judge({element: [("Pump N-1 was off from 09:00 to 09:10 UTC.", "supports")]})
    )
    update = {
        "action": "update",
        "object": element,
        "changes": {"description": "Pump N-1 was off from 09:00 to 09:03 UTC."},
        "sources": [new],
    }
    assert "error" not in write_action(world, [new], metadata, update, key="narrow")
    judge = Judge(
        {
            element: [
                ("Pump N-1 was off from 09:00 to 09:10 UTC.", "not_addressed"),
                ("Pump N-1 was off from 09:00 to 09:03.", "supports"),
            ]
        }
    )
    await assess(world, judge)
    [target] = judge.batches[0]["targets"]
    assert target["active"] == [{"source": "S1", "direction": "supports"}]
    [component] = world.beliefs.active_sources(f"graph:{element}")
    assert component.source_ref["event_ref"] == new["event_ref"]


@pytest.mark.parametrize(
    ("stance", "moves", "support"),
    [("supports", 2, True), ("weak_support", 1, True), ("non_discriminating", 0, False)],
)
async def test_stance_strength_orders_contributions(stance, moves, support):
    """S8, S9: hedged statements move less; a non-discriminating check counts but moves nothing."""
    world = semantic_world()
    _, metadata = recorded_experience(world)
    [message] = recorded_messages(world, "The pump might have been off around nine.")
    element = claim(world, metadata, [message])
    await assess(world, Judge({element: [("The pump might have been off around nine.", stance)]}))
    belief = reading(world, element)
    assert belief.stats.evidence_count == 1
    assert (belief.support > 0) is support
    assert {0: 0.5, 1: 0.6, 2: 0.75}[moves] == pytest.approx(belief.strength)


async def test_invalid_judgement_is_ignored_and_model_failure_leaves_elements_pending():
    """S12: unknown keys never become evidence; a failed request does not mark elements assessed."""
    world = semantic_world()
    _, metadata = recorded_experience(world)
    [message] = recorded_messages(world, "Tank T-2 is empty.")
    element = claim(world, metadata, [message], name="Tank empty", description="Tank T-2 is empty.")

    async def failing(payload, call_tool=None):
        raise RuntimeError("model unavailable")

    with pytest.raises(RuntimeError):
        await assess(world, failing)
    assert world.beliefs.assessed_revision(f"graph:{element}") is None

    async def garbage(payload, call_tool=None):
        return {
            "origins": [{"origin": "O99", "prior": 0.9, "evidence": []}],
            "scopes": [],
            "targets": [
                {"element": 999, "prior": 0.9, "evidence": [], "unresolved": None},
                {
                    "element": element,
                    "prior": 0.99,
                    "evidence": [
                        {
                            "source": "S77",
                            "stance": "supports",
                            "repeats": "S99",
                            "withdraws": "S98",
                            "reason": "invented",
                        }
                    ],
                    "unresolved": "not enough context",
                },
            ],
        }

    result = await assess(world, garbage)
    assert result["unresolved"] == [{"element": element, "reason": "not enough context"}]
    belief = reading(world, element)
    assert belief.stats.evidence_count == 0
    # The unsupported prior is bounded both on registration and by the read-time cap.
    assert belief.strength == pytest.approx(0.75)
    assert world.beliefs.assessed_revision(f"graph:{element}") == world.graph.revision


async def test_bootstrap_changes_need_no_assessment_and_describe_shows_assessed_beliefs():
    world = semantic_world()
    judge = Judge()
    assert (await assess(world, judge))["assessed"] == []
    assert judge.batches == []
    assert world.beliefs.assessment_cursor == world.graph.revision

    _, metadata = recorded_experience(world)
    [message] = recorded_messages(world, "Pump N-1 was off.")
    element = claim(world, metadata, [message], description="Pump N-1 was off.")
    assert "belief" not in describe(world.graph, world.attribution, element)["subject"]
    await assess(world, Judge({element: [("Pump N-1 was off.", "supports")]}))
    subject = describe(world.graph, world.attribution, element)["subject"]
    assert subject["belief"]["evidence_count"] == 1
    read = world.operations.execute(
        "belief.read",
        {"element": element},
        metadata={**metadata, "program": {"role": "model", "revision": "revision"}},
    )
    assert read["stats"]["evidence_count"] == 1


async def test_orchestrator_runs_graph_then_program_assessment_in_order():
    calls = []

    class Result:
        def __init__(self, result):
            self.result = result

    class Ctx:
        async def call(self, program, arguments):
            calls.append((program, arguments))
            return Result({"program": program})

    result = await assess_all(Ctx(), [{"event_ref": 1, "output_path": []}])
    assert calls == [
        ("graph_evidence_assessment", {"experience_refs": [{"event_ref": 1, "output_path": []}]}),
        ("program_evidence_assessment", {}),
    ]
    assert result["result"]["programs"] == {"program": "program_evidence_assessment"}


def test_assessment_state_survives_snapshot():
    store = BeliefStore()
    store.register_binary("graph:7")
    store.assign("graph:7", TraceOutputRef(3), 0.5)
    store.mark_assessed("graph:7", 12)
    store.advance_assessment_cursor(9)
    store.advance_assessment_cursor(4)
    restored = BeliefStore.from_snapshot(json.loads(json.dumps(store.snapshot())))
    assert restored.assessed_revision("graph:7") == 12
    assert restored.assessment_cursor == 9
    assert restored.read("graph:7") == store.read("graph:7")


async def test_new_state_of_an_instance_offers_the_competing_state_for_assessment():
    """S5 via graph neighbors: a new Facet of the same pump brings the old Facet into the batch."""
    world = semantic_world()
    _, metadata = recorded_experience(world)
    [first] = recorded_messages(world, "Pump N-1 was off from 09:00 to 09:10 UTC.")
    pump_type = write_action(
        world,
        [first],
        metadata,
        {
            "action": "create_prototype",
            "name": "Pump",
            "description": None,
            "parent": None,
            "sources": [first],
        },
        key="pump-type",
    )["object"]
    pump = write_action(
        world,
        [first],
        metadata,
        {
            "action": "create_instance",
            "name": "N-1",
            "description": "Pump",
            "prototype": pump_type,
            "sources": [first],
        },
        key="pump",
    )["object"]

    def facet(source, name, description, start, end):
        action = {
            "action": "create_facet",
            "name": name,
            "description": description,
            "instance": pump,
            "valid_from": start,
            "valid_until": end,
            "sources": [source],
        }
        result = write_action(world, [source], metadata, action, key=name)
        assert "error" not in result, result
        return result["object"]

    off = facet(first, "N-1 off", "Pump is off", "2026-10-12T09:00:00Z", "2026-10-12T09:10:00Z")
    await assess(world, Judge({off: [("Pump N-1 was off from 09:00 to 09:10 UTC.", "supports")]}))
    [second] = recorded_messages(world, "N-1 was running at 09:05 UTC.", kind="observation")
    running = facet(second, "N-1 running", "Pump is running", "2026-10-12T09:05:00Z", None)
    second_text = json.dumps({"reading": "N-1 was running at 09:05 UTC."}, ensure_ascii=False)
    judge = Judge({running: [(second_text, "supports")], off: [(second_text, "opposes")]})
    await assess(world, judge, [second])
    assert off in {item["element"] for item in judge.batches[0]["targets"] if not item["changed"]}
    assert reading(world, off).strength < 0.75
    assert reading(world, running).strength > 0.5


async def test_citing_a_field_and_the_whole_observation_is_one_source():
    """Live finding: integration cited an observation both whole and by field; count it once."""
    world = semantic_world()
    _, metadata = recorded_experience(world)
    [sensor] = recorded_messages(world, "N-1 current 12 A at 09:04", kind="observation")
    field = {**sensor, "output_path": ["reading"]}
    element = claim(world, metadata, [field], name="Pump running", description="Pump N-1 runs.")
    sensor_text = json.dumps({"reading": "N-1 current 12 A at 09:04"}, ensure_ascii=False)
    judge = Judge({element: [(sensor_text, "supports")]})
    await assess(world, judge, [sensor, field])
    assert len(judge.batches[0]["sources"]) == 1
    assert judge.batches[0]["targets"][0]["grounds"] == ["S1"]
    [component] = world.beliefs.active_sources(f"graph:{element}")
    assert component.source_ref["event_ref"] == sensor["event_ref"]
    assert not component.source_ref["output_path"]


def recorded_sources(world, *items):
    """Record (origin, text, source_type) observations; source_type "document" or None."""
    refs = []
    for origin, text, source_type in items:
        run = world.memory.start_run("Observation", "revision", {"task_id": "task"})
        arguments = {"source_id": origin}
        if source_type:
            arguments["source_type"] = source_type
        event = world.memory.record(run, "observation", arguments=arguments, output=text)
        world.memory.finish_run(run)
        refs.append(json_value(world.memory.output_ref(event)))
    return refs


async def test_discredited_origin_revises_every_fact_resting_on_it_and_recovers():
    """B3, B4: a faulty-sensor report weakens all its readings; withdrawing it restores them."""
    index = FixedIndex()
    world = semantic_world(index=index)
    _, metadata = recorded_experience(world)
    readings = [f"T-7: pump N-2{number} at {95 + number} C" for number in range(3)]
    elements = []
    for text in readings:
        [source] = recorded_sources(world, ("sensor:T-7", text, None))
        element = claim(world, metadata, [source], name=f"Overheat {text[-8:]}", description=text)
        await assess(
            world,
            Judge({element: [(text, "supports")]}, origin_priors={"sensor:T-7": 0.9}),
            [source],
        )
        elements.append(element)
    trusted = [reading(world, element).strength for element in elements]
    assert all(value > 0.7 for value in trusted)

    faulty = "The metrologist says sensor T-7 was faulty all week and overstated by 30 C."
    [report] = recorded_messages(world, faulty)
    result = await assess(world, Judge(origins={"sensor:T-7": [(faulty, "opposes")]}), [report])
    assert world.beliefs.read("origin:sensor:T-7").strength <= 0.5
    assert {item["element"] for item in result["reassessed"]} == set(elements)
    for element in elements:
        belief = reading(world, element)
        assert belief.strength < 0.55 and belief.stats.evidence_count == 1

    cleared = "Correction: it was T-8 that was faulty; T-7 passed calibration."
    [correction] = recorded_messages(world, cleared)
    rules = {"sensor:T-7": [(cleared, "supports", {"withdraws": faulty})]}
    await assess(world, Judge(origins=rules), [correction])
    assert world.beliefs.read("origin:sensor:T-7").strength > 0.7
    assert [reading(world, element).strength for element in elements] == pytest.approx(trusted)


async def test_reliable_document_outweighs_an_unreliable_one_and_origins_cannot_vouch_for_themselves():
    """B1, B2: a rumour from a low-reliability origin loses to a peer-reviewed trial."""
    index = FixedIndex()
    world = semantic_world(index=index)
    _, metadata = recorded_experience(world)
    rumour = "Forum post: additive PA-7 fully prevents cavitation."
    [post] = recorded_sources(world, ("forum:user123", rumour, "document"))
    element = claim(world, metadata, [post], name="PA-7 prevents cavitation", description=rumour)
    priors = {"forum:user123": 0.35, "doi:10.1038/x": 0.9}
    self_praise = {"forum:user123": [(rumour, "supports")]}
    await assess(
        world,
        Judge({element: [(rumour, "supports")]}, origin_priors=priors, origins=self_praise),
        [post],
    )
    assert world.beliefs.read("origin:forum:user123").stats.evidence_count == 0
    rumoured = reading(world, element).strength
    assert 0.5 < rumoured < 0.7

    index.ids = [element]
    trial = "Nature 2026, randomised trial on 120 pumps: PA-7 did not reduce cavitation."
    [paper] = recorded_sources(world, ("doi:10.1038/x", trial, "document"))
    await assess(world, Judge({element: [(trial, "opposes")]}, origin_priors=priors), [paper])
    belief = reading(world, element)
    assert belief.strength < 0.4 and belief.stats.evidence_count == 2


def scope_answer(scope, alternatives, other, evidence, prior=()):
    """A judged competition scope; evidence is [(source text, {element|"other": stance})]."""
    return {
        "scope": scope,
        "question": "What stopped pump N-40?",
        "alternatives": alternatives,
        "other": other,
        "prior": [{"alternative": key, "probability": value} for key, value in prior],
        "evidence": [
            {
                "source": text,
                "stances": [
                    {"alternative": str(alternative), "stance": stance}
                    for alternative, stance in stances.items()
                ],
                "repeats": None,
                "withdraws": None,
                "reason": "scripted",
            }
            for text, stances in evidence
        ],
    }


async def test_competing_hypotheses_share_one_profile_and_a_new_alternative_versions_the_scope():
    """C1, C3: exclusive causes compete in one scope; adding a cause rejudges every source."""
    index = FixedIndex()
    world = semantic_world(index=index)
    _, metadata = recorded_experience(world)
    stated = "N-40 stopped: bearing wear, cavitation or a motor fault, one of the three."
    [message] = recorded_messages(world, stated)
    bearing, cavitation, motor = (
        claim(world, metadata, [message], name=name, description=f"N-40 stopped due to {name}.")
        for name in ("bearing wear", "cavitation", "motor fault")
    )
    causes = [bearing, cavitation, motor]
    listed = {element: "weak_support" for element in causes}
    first = Judge(
        {bearing: [(stated, "supports")]},
        scopes=[scope_answer(None, causes, False, [(stated, listed)])],
    )
    await assess(world, first, [message])
    assert world.beliefs.scope_of(f"graph:{bearing}") == "scope:1"
    assert world.beliefs.active_sources(f"graph:{bearing}") == ()
    assert sum(reading(world, element).strength for element in causes) == pytest.approx(1)

    index.ids = causes
    vibration = "N-40 vibration 2.1 mm/s, normal; no cavitation noise."
    report = "Lab report: N-40 motor winding insulation 0.1 MOhm, breakdown."
    for text, stances in (
        (vibration, {bearing: "opposes", cavitation: "opposes"}),
        (report, {motor: "supports"}),
    ):
        [source] = recorded_sources(world, ("sensor:VIB-40", text, None))
        judge = Judge(scopes=[scope_answer("C1", causes, False, [(text, stances)])])
        await assess(world, judge, [source])
        assert judge.batches[-1]["scopes"][0]["alternatives"] == causes
    strengths = {element: reading(world, element).strength for element in causes}
    assert strengths[motor] > max(strengths[bearing], strengths[cavitation])
    assert sum(strengths.values()) == pytest.approx(1)
    assert reading(world, motor).stats.evidence_count == 3

    added = "Another possible cause of the N-40 stop is a clogged inlet filter."
    [fourth] = recorded_messages(world, added)
    clogged = claim(world, metadata, [fourth], name="clogged filter", description=added)
    extended = [*causes, clogged]
    rejudged = [
        (stated, listed),
        (vibration, {bearing: "opposes", cavitation: "opposes"}),
        (report, {motor: "supports", clogged: "opposes"}),
        (added, {clogged: "weak_support"}),
    ]
    prior = [(str(element), 0.2) for element in extended] + [("other", 0.2)]
    judge = Judge(scopes=[scope_answer("C1", extended, True, rejudged, prior)])
    result = await assess(world, judge, [fourth])
    [recorded] = result["scopes"]
    assert recorded["scope"] == "scope:2" and len(recorded["assignments"]) == 4
    assert world.beliefs.scope_of(f"graph:{motor}") == "scope:2"
    strengths = {element: reading(world, element).strength for element in extended}
    assert max(strengths, key=strengths.get) == motor
    assert sum(strengths.values()) < 1


async def test_deleted_alternative_leaves_the_scope_without_failing_the_assessment():
    """A correction deletes one competing value; a judgement still naming it versions the scope."""
    index = FixedIndex()
    world = semantic_world(index=index)
    _, metadata = recorded_experience(world)
    stated = "N-40 stopped: bearing wear, cavitation or a motor fault, one of the three."
    [message] = recorded_messages(world, stated)
    causes = [
        claim(world, metadata, [message], name=name, description=f"N-40 stopped due to {name}.")
        for name in ("bearing wear", "cavitation", "motor fault")
    ]
    bearing, cavitation, motor = causes
    listed = {element: "weak_support" for element in causes}
    await assess(world, Judge(scopes=[scope_answer(None, causes, False, [(stated, listed)])]))
    world.graph.apply(GraphDelta(deletes=(cavitation,)), provenance={"test": True})

    index.ids = [bearing, motor]
    report = "Lab report: N-40 motor winding insulation 0.1 MOhm, breakdown."
    [source] = recorded_sources(world, ("lab:N-40", report, "document"))
    stances = {bearing: "opposes", cavitation: "opposes", motor: "supports"}
    judge = Judge(scopes=[scope_answer("C1", causes, False, [(stated, listed), (report, stances)])])
    result = await assess(world, judge, [source])

    assert judge.batches[-1]["scopes"][0]["alternatives"] == [bearing, motor]
    [recorded] = result["scopes"]
    assert recorded["scope"] == "scope:2"
    assert world.beliefs.scope_of(f"graph:{motor}") == "scope:2"
    assert reading(world, motor).strength > reading(world, bearing).strength


async def test_scope_member_binary_evidence_is_released_and_rejected():
    """C2: competing values of one property join a scope; members take no binary evidence."""
    index = FixedIndex()
    world = semantic_world(index=index)
    _, metadata = recorded_experience(world)
    log, seen = "Movement log: N-41 is in shop 5.", "Right now N-41 stands in shop 3, I see it."
    [entry] = recorded_sources(world, ("doc:movement-log", log, "document"))
    shop5 = claim(world, metadata, [entry], name="N-41 in shop 5", description=log)
    await assess(world, Judge({shop5: [(log, "supports")]}), [entry])
    assert reading(world, shop5).strength > 0.7
    index.ids = [shop5]
    [message] = recorded_messages(world, seen)
    shop3 = claim(world, metadata, [message], name="N-41 in shop 3", description=seen)
    evidence = [
        (log, {shop5: "supports", shop3: "opposes"}),
        (seen, {shop3: "supports", shop5: "opposes"}),
    ]
    judge = Judge(scopes=[scope_answer(None, [shop5, shop3], True, evidence)])
    result = await assess(world, judge, [message])
    [recorded] = result["scopes"]
    assert [item["element"] for item in recorded["released"]] == [shop5]
    assert reading(world, shop5).strength + reading(world, shop3).strength < 1
    with pytest.raises(Exception, match="scope"):
        world.operations.execute(
            "evidence.record",
            {"element": shop3, "revision": world.graph.revision, "assign": []},
            metadata={**metadata, "run_id": "r"},
        )


async def test_withdrawn_statement_is_not_reused_against_the_correction():
    """B5 live finding: a withdrawn message must not oppose the element that replaces it."""
    index = FixedIndex()
    world = semantic_world(index=index)
    _, metadata = recorded_experience(world)
    said, withdrawal = (
        "Ivanov is responsible for N-3.",
        "Forget it: Ivanov is not responsible for N-3.",
    )
    [first] = recorded_messages(world, said)
    responsible = claim(world, metadata, [first], name="Ivanov responsible", description=said)
    await assess(world, Judge({responsible: [(said, "supports")]}), [first])
    index.ids = [responsible]
    [second] = recorded_messages(world, withdrawal)
    negation = claim(
        world, metadata, [second], name="Ivanov not responsible", description=withdrawal
    )
    rules = {
        responsible: [(withdrawal, "opposes", {"withdraws": said})],
        negation: [(withdrawal, "supports"), (said, "opposes")],
    }
    await assess(world, Judge(rules), [second])
    belief = reading(world, negation)
    assert belief.stats.evidence_count == 1 and belief.strength > 0.7
    assert world.beliefs.withdrawn_by(TraceOutputRef(first["event_ref"])) is not None

    reasserted = "No, I was right: Ivanov is responsible for N-3."
    index.ids = [responsible, negation]
    [third] = recorded_messages(world, reasserted)
    rules = {negation: [(reasserted, "opposes", {"withdraws": withdrawal})]}
    await assess(world, Judge(rules), [third])
    assert reading(world, negation).strength < 0.3
    # Withdrawing the withdrawal makes the first statement usable again.
    assert world.beliefs.withdrawn_by(TraceOutputRef(first["event_ref"])) is None


async def test_withdrawal_retracts_the_source_everywhere_except_where_it_is_kept():
    """B3 live finding: a correction must also reach facts outside the current batch."""
    index = FixedIndex()
    world = semantic_world(index=index)
    _, metadata = recorded_experience(world)
    report = "The metrologist says T-7 overstated N-20 and N-21 by 30 C, so neither overheated."
    [first] = recorded_messages(world, report)
    n20, n21, t7 = (
        claim(world, metadata, [first], name=name, description=f"{name} per the metrologist.")
        for name in ("N-20 not overheated", "N-21 not overheated", "T-7 exists")
    )
    rules = {element: [(report, "supports")] for element in (n20, n21, t7)}
    await assess(world, Judge(rules), [first])
    index.ids = [n20, t7]
    correction = "The metrologist was wrong: T-8 was faulty, T-7 is fine."
    [second] = recorded_messages(world, correction)
    rules = {
        n20: [(correction, "opposes", {"withdraws": report})],
        t7: [(report, "supports")],
    }
    await assess(world, Judge(rules), [second])
    assert world.beliefs.active_sources(f"graph:{n21}") == ()
    assert [c.source_ref["event_ref"] for c in world.beliefs.active_sources(f"graph:{t7}")] == [
        first["event_ref"]
    ]
    assert reading(world, n20).strength < 0.5
