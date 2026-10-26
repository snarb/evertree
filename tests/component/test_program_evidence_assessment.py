"""Program evidence assessment scenarios over real graph, trace and belief stores.

Runs are recorded the way the application records them (ProgramRun with the Program's
own revision and task, anchors installed from a code_anchors event, anchored trace
events, run_finished). Only the model judgement is scripted. The PEA scenarios cover
the common paths of a Program's life after activation; the catalog is in
tests/evidence/README.md.
"""

import json

import pytest

from evertree.core.anchors import AnchorResolver, CodeAnchor
from evertree.core.beliefs import BeliefStore, operator_target, program_target
from evertree.core.evidence import GraphEvidence
from evertree.core.graph.types import GraphDelta, Node, NodeUpdate, Prototype
from evertree.core.program_evidence import ProgramEvidence
from evertree.core.semantics.reading import belief_summary, describe
from evertree.core.values import ContractError, json_value
from evertree.processes.self_learning.self_evidence_assessment.self_program_evidence_assessment._exec import (
    run,
)
from tests.support.application import IntegrationScriptedProvider as ScriptedProvider
from tests.support.application import completed, framing, is_program_evidence_request
from tests.support.component import component_app
from tests.support.semantics import context, semantic_world

REVISION_A, REVISION_B, HEAD = "a" * 40, "b" * 40, "c" * 40


class Judge:
    """Answer the Program judgement from rules keyed by Program name or (name, op_id).

    A rule is (source text, stance, options); options may name repeats or withdraws by
    source text. Calls are kept, so a test can tell that no model call happened.
    """

    def __init__(self, rules=None, *, fail=False):
        self.rules = rules or {}
        self.fail = fail
        self.batches = []

    def _evidence(self, keys, rules):
        evidence = []
        for text, stance, *options in rules:
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
        return evidence

    async def __call__(self, payload, call_tool=None):
        batch = json.loads(payload["prompt"])
        self.batches.append(batch)
        if self.fail:
            raise RuntimeError("model unavailable")
        keys = {source["text"]: source["key"] for source in batch["sources"]}
        answers = []
        for item in batch["runs"]:
            name = item["program"]["name"]
            operators = [
                {"op_id": op_id, "evidence": self._evidence(keys, rules)}
                for (program, op_id), rules in (
                    (key, value) for key, value in self.rules.items() if isinstance(key, tuple)
                )
                if program == name
            ]
            answers.append(
                {
                    "run": item["key"],
                    "program": self._evidence(keys, self.rules.get(name, ())),
                    "operators": operators,
                    "unresolved": None,
                }
            )
        return {"runs": answers}


def program(world, name, *, slug=None, roles=("exec",), revision=REVISION_A):
    """Register an active Program of its own process, as lifecycle activation leaves it."""
    process = Prototype(
        world.graph.reserve_id(),
        name + "Process",
        description="Plan pump maintenance windows.",
        properties={"process": True},
    )
    node = Node(
        world.graph.reserve_id(),
        name,
        kind="program",
        description="Choose a maintenance window for a pump from its duty schedule.",
        properties={
            "process": process.id,
            "role": roles[0],
            "roles": list(roles),
            "slug": slug or name.lower(),
            "revision": revision,
            "lifecycle_status": "active",
        },
    )
    world.graph.apply(GraphDelta(creates=(process, node)), provenance="lifecycle")
    return node.id


def activate(world, identity, revision):
    """Move a Program to a new accepted revision, as an activation does."""
    node = world.graph.get(identity)
    world.graph.apply(
        GraphDelta(
            updates=(
                NodeUpdate(identity, {"properties": {**node.properties, "revision": revision}}),
            )
        ),
        provenance="lifecycle",
    )


class Run:
    """Record one live ProgramRun the way the application's trace handler records it."""

    def __init__(self, world, identity, arguments, *, task="task", caller=None):
        self.world, self.identity = world, identity
        node = world.graph.get(identity)
        caller_event = None
        if caller is not None:
            caller_event = world.memory.record(
                caller.run, "call_program", output={"program": identity}
            ).id
        self.run = world.memory.start_run(
            identity,
            HEAD,
            arguments,
            caller_event=caller_event,
            program_revision=node.properties["revision"],
            task_id=task,
        )

    def anchored(self, *uses):
        """Install the run's anchors and record each (op_id, arguments, output) use."""
        anchors = tuple(
            CodeAnchor(self.identity, op_id, "src/evertree/processes/x/_exec.py", HEAD, line)
            for line, op_id in enumerate(dict.fromkeys(op for op, _, _ in uses), start=1)
        )
        event = self.world.memory.record(self.run, "code_anchors", output=json_value(anchors))
        AnchorResolver(self.world.graph).install(
            anchors, provenance=self.world.memory.output_ref(event)
        )
        for op_id, arguments, output in uses:
            operator = self.world.graph.find(f"op:{self.identity}:{op_id}")
            self.world.memory.record(self.run, operator.id, arguments=arguments, output=output)
        return self

    def finish(self, result):
        self.world.memory.record(
            self.run,
            "run_finished",
            output={"type": "run_finished", "result": {"result": result, "feedback": None}},
        )
        self.world.memory.finish_run(self.run)
        return self


def message(world, *texts, task="task", source_id=None):
    """Record user messages, or observations of source_id, in a task as the host does."""
    refs = []
    for index, text in enumerate(texts):
        run = world.memory.start_run("Observation", HEAD, {"task_id": task})
        if source_id is None:
            arguments, value = (
                {"source_id": f"input:{task}:{text}"},
                {"role": "user", "content": text},
            )
        else:
            arguments, value = {"source_id": source_id}, {"text": text}
        event = world.memory.record(run, "observation", arguments=arguments, output=value)
        world.memory.finish_run(run)
        refs.append(json_value(world.memory.output_ref(event)))
    return refs


def finished(world, identity, arguments, result, **kwargs):
    return Run(world, identity, arguments, **kwargs).finish(result)


async def assess(world, judge):
    return (await run(context(world, judge, role="exec")))["result"]


def strength(world, target):
    return world.beliefs.read(target).strength


def scheduler_world():
    world = semantic_world()
    return world, program(world, "PumpScheduler")


async def test_pea_01_disputed_result_lowers_the_revision_belief():
    """PEA-01: the user says a run's answer is wrong; that revision loses belief."""
    world, scheduler = scheduler_world()
    finished(world, scheduler, {"pump": "N-1"}, {"window": "Monday 02:00"})
    message(world, "Monday 02:00 is wrong, N-1 runs at night on Mondays.")
    judge = Judge(
        {"PumpScheduler": [("Monday 02:00 is wrong, N-1 runs at night on Mondays.", "opposes")]}
    )

    result = await assess(world, judge)

    [batch] = judge.batches
    [card] = batch["runs"]
    assert card["claim"].startswith("This revision reliably implements")
    assert card["result"] == json.dumps({"window": "Monday 02:00"})
    assert "revision" not in card and "target" not in card
    target = program_target(scheduler, REVISION_A)
    reading = world.beliefs.read(target)
    assert 0.25 <= reading.strength < 0.5 and reading.stats.evidence_count == 1
    assert [item["target"] for item in result["assessed"]] == [target]


async def test_pea_02_confirmed_result_raises_belief_and_repeats_add_nothing():
    """PEA-02: confirmation supports the revision; a repetition shares its dependency root."""
    world, scheduler = scheduler_world()
    finished(world, scheduler, {"pump": "N-1"}, {"window": "Sunday 14:00"})
    first, again = (
        "Sunday 14:00 worked, maintenance went fine.",
        "As I said, Sunday 14:00 worked.",
    )
    message(world, first, again)
    judge = Judge({"PumpScheduler": [(first, "supports"), (again, "supports", {"repeats": first})]})

    await assess(world, judge)

    target = program_target(scheduler, REVISION_A)
    reading = world.beliefs.read(target)
    single = BeliefStore()
    single.register_binary("one")
    single.assess_likelihoods("one", {"event_ref": 1}, {"true": 0.75, "false": 0.25}, backed=False)
    assert reading.strength == pytest.approx(single.read("one").strength)
    assert reading.stats.evidence_count == 1


async def test_pea_03_anchored_step_gets_the_evidence_and_unanchored_ids_are_ignored():
    """PEA-03: the wrong output of one anchored step lowers that step, not the revision."""
    world, scheduler = scheduler_world()
    Run(world, scheduler, {"pump": "N-1"}).anchored(
        ("load_schedule", {"pump": "N-1"}, {"idle": ["Mon 02:00"]}),
        ("choose_window", {"idle": ["Mon 02:00"]}, {"window": "Mon 02:00"}),
    ).finish({"window": "Mon 02:00"})
    text = "The duty schedule you loaded for N-1 is outdated: it runs on Mondays now."
    message(world, text)
    judge = Judge(
        {
            ("PumpScheduler", "load_schedule"): [(text, "opposes")],
            ("PumpScheduler", "helper_loop"): [(text, "opposes")],
        }
    )

    await assess(world, judge)

    [card] = judge.batches[0]["runs"]
    assert [item["op_id"] for item in card["operators"]] == ["load_schedule", "choose_window"]
    assert card["operators"][0]["uses"][0]["output"] == json.dumps({"idle": ["Mon 02:00"]})
    assert strength(world, operator_target(scheduler, "load_schedule", REVISION_A)) < 0.5
    assert not world.beliefs.known(program_target(scheduler, REVISION_A))
    assert not world.beliefs.known(operator_target(scheduler, "choose_window", REVISION_A))
    assert not world.beliefs.known(operator_target(scheduler, "helper_loop", REVISION_A))
    operator = world.graph.find(f"op:{scheduler}:load_schedule")
    assert belief_summary(world.graph, operator)["strength"] < 0.5


async def test_pea_04_called_run_is_blamed_for_its_own_wrong_value():
    """PEA-04: a child returned the wrong value and the parent used it as intended."""
    world, scheduler = scheduler_world()
    lookup = program(world, "DutyLookup")
    parent = Run(world, scheduler, {"pump": "N-1"})
    finished(world, lookup, {"pump": "N-1"}, {"idle": ["Mon 02:00"]}, caller=parent)
    parent.finish({"window": "Mon 02:00"})
    text = "N-1 is never idle on Monday nights, the duty data was wrong."
    message(world, text)
    judge = Judge({"DutyLookup": [(text, "opposes")], "PumpScheduler": [(text, "not_addressed")]})

    await assess(world, judge)

    cards = {card["program"]["name"]: card for card in judge.batches[0]["runs"]}
    assert cards["DutyLookup"]["called_by"] == cards["PumpScheduler"]["key"]
    assert strength(world, program_target(lookup, REVISION_A)) < 0.5
    assert not world.beliefs.known(program_target(scheduler, REVISION_A))


async def test_pea_05_new_revision_starts_without_the_old_revisions_evidence():
    """PEA-05: an improved Program is a new target; the old revision keeps its record."""
    world, scheduler = scheduler_world()
    finished(world, scheduler, {"pump": "N-1"}, {"window": "Mon 02:00"})
    complaint = "Mon 02:00 is wrong, it collides with the night shift."
    message(world, complaint)
    await assess(world, Judge({"PumpScheduler": [(complaint, "opposes")]}))
    old = strength(world, program_target(scheduler, REVISION_A))

    activate(world, scheduler, REVISION_B)
    assert belief_summary(world.graph, world.graph.get(scheduler)) is None
    finished(world, scheduler, {"pump": "N-1"}, {"window": "Sun 14:00"}, task="next")
    praise = "Sun 14:00 is right, thanks."
    message(world, praise, task="next")
    judge = Judge({"PumpScheduler": [(praise, "supports"), (complaint, "opposes")]})
    await assess(world, judge)

    # Only the new message is linked to the new run; the old complaint is not shown again.
    [card] = judge.batches[0]["runs"]
    assert card["new_target"] is True
    assert [source["text"] for source in judge.batches[0]["sources"]] == [praise]
    assert strength(world, program_target(scheduler, REVISION_A)) == old
    assert strength(world, program_target(scheduler, REVISION_B)) > 0.5
    current = describe(world.graph, world.attribution, scheduler)
    assert current["subject"]["belief"]["strength"] > 0.5


async def test_pea_06_user_withdraws_a_complaint():
    """PEA-06: "I was wrong" retracts the complaint, and its own confirmation counts."""
    world, scheduler = scheduler_world()
    finished(world, scheduler, {"pump": "N-1"}, {"window": "Sun 14:00"})
    complaint = "Sun 14:00 is wrong."
    message(world, complaint)
    await assess(world, Judge({"PumpScheduler": [(complaint, "opposes")]}))
    assert strength(world, program_target(scheduler, REVISION_A)) < 0.5

    correction = "Sorry, I was wrong: Sun 14:00 is fine."
    message(world, correction)
    judge = Judge({"PumpScheduler": [(correction, "supports", {"withdraws": complaint})]})
    await assess(world, judge)

    [card] = judge.batches[0]["runs"]
    assert [entry["direction"] for entry in card["active"]] == ["opposes"]
    reading = world.beliefs.read(program_target(scheduler, REVISION_A))
    assert reading.strength > 0.5 and reading.stats.evidence_count == 1


async def test_pea_06b_a_later_batch_cannot_rejudge_an_earlier_source():
    """PEA-06: only new sources are judged; an earlier verdict changes only by withdrawal."""
    world, scheduler = scheduler_world()
    finished(world, scheduler, {"pump": "N-1"}, {"window": "Sun 14:00"})
    complaint = "Sun 14:00 is wrong."
    message(world, complaint)
    await assess(world, Judge({"PumpScheduler": [(complaint, "opposes")]}))
    before = strength(world, program_target(scheduler, REVISION_A))

    message(world, "Please also plan N-2.")
    await assess(world, Judge({"PumpScheduler": [(complaint, "supports")]}))

    assert strength(world, program_target(scheduler, REVISION_A)) == before


async def test_pea_07_discredited_origin_revises_contributions_without_a_model_call():
    """PEA-07: an origin found unreliable weakens what it said about a run, in code."""
    world, scheduler = scheduler_world()
    finished(world, scheduler, {"pump": "N-1"}, {"window": "Sun 14:00"})
    message(world, "N-1 was running at 14:10 on Sunday.", source_id="sensor:T-7")
    await assess(
        world, Judge({"PumpScheduler": [("N-1 was running at 14:10 on Sunday.", "opposes")]})
    )
    target = program_target(scheduler, REVISION_A)
    before = strength(world, target)
    [calibration] = message(world, "Sensor T-7 is miscalibrated.", task="metrology")
    GraphEvidence(world.graph, world.memory, world.beliefs).record_origin(
        "sensor:T-7",
        assign=[{"source_ref": calibration, "likelihoods": {"true": 0.15, "false": 0.85}}],
    )
    judge = Judge()

    result = await assess(world, judge)

    assert judge.batches == []
    assert result["reassessed"]
    assert before < strength(world, target) <= 0.5


async def test_pea_08_nothing_to_judge_makes_no_model_call():
    """PEA-08: no run in the task, a hidden outcome, service runs, or nothing new: no call."""
    world, scheduler = scheduler_world()
    integration = program(world, "KnowledgeIntegration", slug="knowledge_integration")
    message(world, "Plan maintenance for N-1.")
    judge = Judge()
    await assess(world, judge)
    service = Run(world, integration, {"packet": 1})
    finished(world, scheduler, {"pump": "N-1"}, {"window": "Sun"}, caller=service)
    service.finish({"written": 1})
    message(world, "Thanks.")
    await assess(world, judge)
    run = finished(world, scheduler, {"pump": "N-1"}, {"window": "Sun"}, task=None).run
    observation = world.memory.start_run("Observation", HEAD, {"task_id": None})
    world.memory.record(
        observation,
        "observation",
        arguments={"source_id": "host:outcome", "outcome_of": run.id},
        output={"window": "Mon"},
    )
    world.memory.finish_run(observation)
    await assess(world, judge)

    assert judge.batches == []
    assert world.beliefs.cursor("programs") == max(event.id for event in world.memory.events)
    retained = world.memory.retention_reasons(max(event.id for event in world.memory.events))
    assert not any(reason.startswith("evidence:") for reason in retained)


async def test_pea_09_failed_judgement_leaves_the_batch_pending():
    """PEA-09: a failed model call records nothing; the next run judges the same sources."""
    world, scheduler = scheduler_world()
    finished(world, scheduler, {"pump": "N-1"}, {"window": "Sun"})
    text = "Sunday is wrong."
    message(world, text)

    with pytest.raises(RuntimeError):
        await assess(world, Judge(fail=True))
    assert world.beliefs.cursor("programs") == 0

    judge = Judge({"PumpScheduler": [(text, "opposes")]})
    await assess(world, judge)
    assert [source["text"] for source in judge.batches[0]["sources"]] == [text]
    assert strength(world, program_target(scheduler, REVISION_A)) < 0.5


async def test_pea_10_irrelevant_sources_and_model_roles():
    """PEA-10: an instruction is not evidence; a model Program is judged on its description."""
    world = semantic_world()
    forecaster = program(world, "LoadForecast", roles=("model", "simulation"))
    finished(world, forecaster, {"pump": "N-1"}, {"load": 0.7})
    text = "Remember to forecast N-2 too."
    message(world, text)
    judge = Judge({"LoadForecast": [(text, "not_addressed")]})

    result = await assess(world, judge)

    [card] = judge.batches[0]["runs"]
    assert card["claim"].startswith("This revision accurately describes its process")
    assert "simulated" in card["claim"]
    assert result["assessed"] == []
    assert not world.beliefs.known(program_target(forecaster, REVISION_A))


async def test_program_cursor_survives_a_snapshot():
    store = BeliefStore()
    store.advance_cursor("programs", 9)
    store.advance_cursor("programs", 4)
    assert BeliefStore.from_snapshot(store.snapshot()).cursor("programs") == 9


async def test_record_rejects_unknown_targets_before_any_change():
    world, scheduler = scheduler_world()
    with pytest.raises(ContractError, match="anchored operator"):
        ProgramEvidence(world.graph, world.memory, world.beliefs).record(
            1,
            [
                {"target": program_target(scheduler, REVISION_A), "assign": []},
                {"target": "op:999:missing@" + REVISION_A, "assign": []},
            ],
        )
    assert not world.beliefs.known(program_target(scheduler, REVISION_A))
    assert world.beliefs.cursor("programs") == 0


async def test_pea_11_application_records_runs_and_assesses_them_end_to_end(tmp_path):
    """PEA-11: a real Program run, a user's dispute and the full EvidenceAssessment chain."""

    class Provider(ScriptedProvider):
        async def run(self, request_id, request, **kwargs):
            if is_program_evidence_request(request):
                self.requests.append(request)
                batch = json.loads(request.prompt)
                [source] = [item for item in batch["sources"] if "wrong" in item["text"]]
                answers = [
                    {
                        "run": card["key"],
                        "program": [
                            {
                                "source": source["key"],
                                "stance": "opposes"
                                if card["program"]["name"] == "SelfTaskFraming.exec"
                                else "not_addressed",
                                "repeats": None,
                                "withdraws": None,
                                "reason": "the user rejects the framed objective",
                            }
                        ],
                        "operators": [],
                        "unresolved": None,
                    }
                    for card in batch["runs"]
                ]
                for event in completed({"runs": answers}):
                    yield event
                return
            async for event in super().run(request_id, request, **kwargs):
                yield event

    provider = Provider([framing()])
    async with component_app(tmp_path / "agent", provider=provider) as agent:
        task = agent.tasks.create_task("Count r in strawberry")
        agent.tasks.assign_budget(task.id, {"active_time_minutes": 3}, 0, reason="test")
        await agent._run_program(task.id, "SelfTaskFraming", {"request": "Count r"})
        node = next(
            item
            for item in agent.graph.nodes(kind="program")
            if item.properties.get("slug") == "task_framing"
        )
        [framed] = [item for item in agent.memory.runs if item.program == node.id]
        assert framed.task_id == task.id
        assert framed.program_revision == node.properties["revision"]
        agent.observe(
            {"role": "user", "content": "You framed it wrong: I asked about the letter R."},
            source_id="input:dispute",
            task_id=task.id,
        )

        result = await agent._run_program(task.id, "evidence_assessment", {"experience_refs": []})

        [request] = [item for item in provider.requests if is_program_evidence_request(item)]
        names = [card["program"]["name"] for card in json.loads(request.prompt)["runs"]]
        assert node.name == "SelfTaskFraming.exec" and node.name in names
        [recorded] = result["result"]["programs"]["assessed"]
        assert recorded["target"] == program_target(node.id, node.properties["revision"])
        listed = next(item for item in agent.programs() if item["id"] == node.id)
        assert listed["belief"]["strength"] < 0.5 and listed["belief"]["evidence_count"] == 1
