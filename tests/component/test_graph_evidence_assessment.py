"""Graph evidence assessment over real graph, trace and belief stores; only the model is scripted."""

import json
import math

import pytest

from evertree.core.beliefs import BeliefStore
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

    def __init__(self, rules=None, *, prior=None):
        self.rules = rules or {}
        self.prior = prior
        self.batches = []

    async def __call__(self, payload, call_tool=None):
        batch = json.loads(payload["prompt"])
        self.batches.append(batch)
        texts = {source["key"]: source["text"] for source in batch["sources"]}
        keys = {text: key for key, text in texts.items()}
        answers = []
        for item in batch["targets"] + batch["related"]:
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
        return {"targets": answers}


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
    assert judge.batches[0]["related"][0]["element"] == element
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
    result = await assess(world, Judge(rules), [correction])
    [record] = result["assessed"]
    assert record["retracted"] == [said]
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
            ]
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
    assert off in {item["element"] for item in judge.batches[0]["related"]}
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
