"""Assess experience about run results as evidence for Program revisions and operators.

The target is (Program, revision): whether that revision reliably implements its
intended behaviour (exec) or accurately describes its process (model). Each anchored
operator use in the revision has its own target. Core pairs new user messages and
observations of a task with its recent completed runs, which they may concern; outcomes
recorded with outcome_of stay unseen for lifecycle evaluation. One model call judges the
batch.
Evidence goes first to the anchor whose output a source directly checks; the Program
gets its own stance only when the source bears on the revision as a whole.

Stances become likelihoods through the shared observation model, weakened by the
source origin's reliability, which graph evidence assessment keeps current before this
Program runs. Contributions keep their basis, so a later reliability change revises
them in code without another model call.
"""

from evertree.common.evidence_model import STANCES, evidence_item
from evertree.common.structured import ask
from evertree.core.learning.api import (
    pending_program_evidence,
    record_program_evidence,
    stale_program_evidence,
)

REASSESSMENT_ROUNDS = 3

INSTRUCTIONS = """You assess evidence for the agent's Programs: code that implements or
models a process. Each target is one revision of a Program, or one anchored operator in
it: a marked step whose use at that point in the code has its own belief.

Input fields:
- sources: experience keyed S1, S2, …. kind is "user" (a person's message),
  "observation" (a sensor reading, tool result or recorded outcome) or "document"; new
  marks experience not yet assessed; withdrawn_by marks a source its author later
  withdrew. Agent reasoning is never a source.
- runs: completed Program runs the sources may concern, keyed R1, R2, …. program names
  the Program, its process and roles; claim states what belief in this revision is
  about; arguments and result are what the run received and returned; called_by names
  the batch run that called it; operators are the anchored steps the run executed,
  with recorded uses (arguments, output). sources lists the source keys that may
  concern this run; active lists sources already counted for the run's Program target
  (or for an operator, in its own active) and their direction. new_target means the
  target has no belief yet.

Answer every run, with empty lists when no source bears on it. For each run, judge only
its listed sources. Active sources were already judged: do not judge them again; they
are listed so a new source can repeat or withdraw them.
- operators: for an anchored step whose output or use the source directly checks (a
  user saying a found value is wrong, an outcome contradicting the step's decision),
  give that op_id a stance. Use only op_ids listed for the run.
- program: a stance about the revision's claim as a whole. Give it only when the
  source bears on whether this revision implements its intended behaviour (or describes
  its process), not merely on one detail already judged for an operator. When one
  anchored step already explains the verdict (its output was wrong and the rest of the
  run followed from it), the revision as a whole gets at most weak_opposition or
  weak_support: one local failure says little about the whole implementation.
Stances:
- supports / opposes: the source clearly confirms or refutes the run's result or the
  step's output, and that result is what the claim is about (a confirmed correct answer
  supports, a reported wrong answer opposes);
- weak_support / weak_opposition: hedged, partial or indirect statements, hearsay, or a
  result that only partly matches;
- non_discriminating: the source is about the run but would be equally expected whether
  the revision or step is reliable or not (an outcome caused by wrong arguments its
  caller passed, an external failure after the run);
- not_addressed: the source does not bear on this target. An active source marked
  not_addressed stops counting.
Attribute an outcome to the most direct run: when a called run returned the wrong value
and its caller used it as intended, the evidence is about the called run, not the caller;
a caller that misused a correct result is the one opposed. A run or step is responsible
for the data it loads, looks up or returns: when that output is wrong or outdated for
its purpose, the source opposes that run or step, even if the data it read was itself
stale; only the arguments its caller passed are outside its responsibility. Judge what the source says
about the result, including its conditions; wording that attributes it ("the user says
the answer was wrong") does not change what is assessed. A request, instruction or
question in a source says nothing about a run: not_addressed. Agreement of wording is not
evidence, and a later run repeating a result does not confirm it. Never use a withdrawn
source where it is not already active. Set repeats to an earlier source key when this
source only restates that source. Set withdraws to an earlier active source key when this
source retracts or corrects that source's statement about the run ("sorry, the answer
was right after all"), and judge what this source itself says. Do not invent sources.
unresolved: a short reason when you cannot tell how the sources bear on a run; else null.
Write reasons in the sources' language.
"""

_EVIDENCE = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source": {"type": "string"},
            "stance": {"type": "string", "enum": list(STANCES)},
            "repeats": {"type": ["string", "null"]},
            "withdraws": {"type": ["string", "null"]},
            "reason": {"type": "string"},
        },
        "required": ["source", "stance", "repeats", "withdraws", "reason"],
    },
}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "runs": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "run": {"type": "string"},
                    "program": _EVIDENCE,
                    "operators": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "op_id": {"type": "string"},
                                "evidence": _EVIDENCE,
                            },
                            "required": ["op_id", "evidence"],
                        },
                    },
                    "unresolved": {"type": ["string", "null"]},
                },
                "required": ["run", "program", "operators", "unresolved"],
            },
        }
    },
    "required": ["runs"],
}


def _for_model(batch):
    """Keep only decision-relevant fields; identities, revisions and targets stay in code."""
    return {
        "sources": [
            {
                key: source[key]
                for key in ("key", "kind", "recorded_at", "new", "text", "withdrawn_by")
                if key in source
            }
            for source in batch["sources"]
        ],
        "runs": [
            {
                **{
                    key: run[key]
                    for key in (
                        "key",
                        "claim",
                        "new_target",
                        "arguments",
                        "result",
                        "called_by",
                        "sources",
                        "active",
                    )
                },
                "program": {
                    key: run["program"][key] for key in ("name", "description", "process", "roles")
                },
                "operators": [
                    {
                        key: operator[key]
                        for key in ("op_id", "new_target", "uses", "uses_total", "active")
                    }
                    for operator in run["operators"]
                ],
            }
            for run in batch["runs"]
        ],
    }


def _assess(entries, allowed, active, sources, reliability, withdrawn):
    """Turn judged entries for one target into assign items and retracted references.

    Only new sources linked to the run are judged; an active source changes only when a
    new one withdraws it, so a later batch cannot drift an earlier judgement.
    """
    assign, retract = {}, {}
    for entry in entries:
        key, stance = entry["source"], entry["stance"]
        if key not in allowed or key in withdrawn and key not in active:
            continue
        earlier = entry["withdraws"]
        if earlier in active and earlier != key:
            retract[earlier] = sources[earlier]["ref"]
        if stance == "not_addressed":
            if key in active:
                retract[key] = sources[key]["ref"]
            continue
        root = None
        if entry["repeats"] in sources and entry["repeats"] != key:
            root = sources[entry["repeats"]]["ref"]
        source = sources[key]
        assign[key] = evidence_item(source, stance, reliability.get(source["origin"]), root)
    for key in retract:
        assign.pop(key, None)
    return list(assign.values()), list(retract.values())


def _plan(batch, judgement):
    """Turn the model's judgement into per-target records, ignoring unknown keys."""
    sources = {source["key"]: source for source in batch["sources"]}
    withdrawn = {key for key, source in sources.items() if source.get("withdrawn_by")}
    reliability = batch["origins"]
    answers = {}
    for answer in judgement["runs"]:
        answers.setdefault(answer["run"], answer)
    records, unresolved = [], []
    for run in batch["runs"]:
        answer = answers.get(run["key"])
        if answer is None:
            continue
        if answer["unresolved"]:
            unresolved.append({"run": run["run"], "reason": answer["unresolved"]})
        linked = set(run["sources"])
        targets = [(run["target"], {entry["source"] for entry in run["active"]}, answer["program"])]
        operators = {operator["op_id"]: operator for operator in run["operators"]}
        seen = set()
        for judged in answer["operators"]:
            # Unanchored implementation details receive no evidence of their own.
            operator = operators.get(judged["op_id"])
            if operator is None or judged["op_id"] in seen:
                continue
            seen.add(judged["op_id"])
            active = {entry["source"] for entry in operator["active"]}
            targets.append((operator["target"], active, judged["evidence"]))
        for target, active, entries in targets:
            assign, retract = _assess(entries, linked, active, sources, reliability, withdrawn)
            if assign or retract:
                records.append({"target": target, "assign": assign, "retract": retract})
    return records, unresolved


async def _reassess(ctx):
    """Revise contributions whose origin reliability changed since they were judged."""
    revised = []
    for _ in range(REASSESSMENT_ROUNDS):
        stale = await stale_program_evidence(ctx)
        if not stale:
            break
        grouped = {}
        for item in stale:
            basis = item["basis"]
            source = {"kind": basis["kind"], "origin": basis["origin"], "ref": item["source_ref"]}
            evidence = evidence_item(
                source, basis["stance"], item["reliability"], basis.get("dependency_root")
            )
            grouped.setdefault(item["target"], []).append(evidence)
        records = [{"target": target, "assign": assign} for target, assign in grouped.items()]
        revised.append(await record_program_evidence(ctx, None, records))
    return revised


async def run(ctx):
    """Assess one batch of runs that new experience may concern and record their evidence."""
    batch = await pending_program_evidence(ctx)
    records, unresolved = [], []
    if batch["runs"] and any(source["new"] for source in batch["sources"]):
        judgement = await ask(ctx, instructions=INSTRUCTIONS, data=_for_model(batch), schema=SCHEMA)
        records, unresolved = _plan(batch, judgement["result"])
    recorded = await record_program_evidence(ctx, batch["through"], records)
    reassessed = await _reassess(ctx)
    return {
        "result": {
            "assessed": recorded["recorded"],
            "reassessed": reassessed,
            "unresolved": unresolved,
            "remaining": batch["remaining"],
        },
        "feedback": None,
    }
