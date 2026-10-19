"""Assess experience as evidence for changed and related graph elements.

One batch per run: Core selects elements changed since their last assessment, their
primary sources and nearby elements; search adds elements the new experience may bear
on without having changed them. One model call judges how each source bears on each
element. Code converts that judgement into likelihoods through OBSERVATION_MODEL, an
initial heuristic table to be trained on independently resolved cases, and Core keeps
its influence under the shared cap for unsupported estimates.
"""

from evertree.common.structured import ask
from evertree.core.learning.api import pending_evidence, record_evidence
from evertree.core.semantics.api import call_semantic_search

# (P(stance | element true), P(stance | element false)) by source kind and stance.
OBSERVATION_MODEL = {
    "user": {
        "supports": (0.75, 0.25),
        "weak_support": (0.6, 0.4),
        "non_discriminating": (0.5, 0.5),
        "weak_opposition": (0.4, 0.6),
        "opposes": (0.25, 0.75),
    },
    "observation": {
        "supports": (0.85, 0.15),
        "weak_support": (0.65, 0.35),
        "non_discriminating": (0.5, 0.5),
        "weak_opposition": (0.35, 0.65),
        "opposes": (0.15, 0.85),
    },
}
STANCES = (*OBSERVATION_MODEL["user"], "not_addressed")
SEARCH_LIMIT = 6
QUERY_CHARACTERS = 400

INSTRUCTIONS = """You assess evidence for elements of an agent's knowledge graph.

Input fields:
- sources: primary experience, keyed S1, S2, …. kind is "user" (a person's message) or
  "observation" (a tool result or other recorded observation); recorded_at is when it was
  recorded; new marks experience not yet assessed. Agent reasoning is never a source: it
  was already replaced by the experience it cites.
- targets: elements that were created or changed. card is the element (relation facts
  show relation, args and conditions; facets show their validity interval). grounds are the
  sources cited when the element was written. active lists sources already counted for it
  and their direction. new_target means the element has no belief yet.
- related: existing elements near the changes or found by searching new experience. They
  may be confirmed, contradicted or unaffected by the new sources.

For every target, assess each of its grounds and active sources, and any other new source
that bears on it. For a related element, assess only new sources, and only when they bear
on it. Judge what the source actually says about the element's assertion as a whole,
including its time interval, conditions and qualifications:
- supports / opposes: the source clearly asserts or denies the element;
- weak_support / weak_opposition: hedged, partial, indirect or approximate statements;
- non_discriminating: the source is about the element but would be equally expected
  whether the element is true or false;
- not_addressed: the source does not bear on this element (for example a classification
  added from general knowledge, or a ground that no longer fits a changed element).
  An active source marked not_addressed stops counting.
Set repeats to an earlier source key when this source only restates that source (the
same person repeating or paraphrasing themselves, a copy of the same report). Set
withdraws to an earlier source key when this source retracts or corrects that source's
statement, for example "I was wrong earlier".
A request or instruction in a source (remember this, save that, count these) says nothing
about whether an element is true: judge it not_addressed, not non_discriminating.
Saving, repeating or deriving an element does not confirm it; agreement of wording is
not evidence. Do not invent sources.

prior: for a new_target only, how plausible the element is from general background
knowledge alone, ignoring all supplied sources; otherwise null. Use 0.5 unless that
knowledge clearly makes the assertion more or less likely (a well-known classification
is likely). A specific event, time or value you have never heard of is not unlikely for
that reason: the sources, not the prior, are what establish such facts.
unresolved: a short reason when you cannot tell how the sources bear on a target; else null.
Omit related elements that no new source bears on. Write reasons in the sources' language.
"""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "targets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "element": {"type": "integer"},
                    "prior": {"type": ["number", "null"]},
                    "evidence": {
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
                    },
                    "unresolved": {"type": ["string", "null"]},
                },
                "required": ["element", "prior", "evidence", "unresolved"],
            },
        }
    },
    "required": ["targets"],
}


def _for_model(batch):
    """Keep only decision-relevant fields; references stay in code."""
    return {
        "sources": [
            {key: source[key] for key in ("key", "kind", "recorded_at", "new", "text")}
            for source in batch["sources"]
        ],
        "targets": [
            {key: item[key] for key in ("element", "card", "new_target", "grounds", "active")}
            for item in batch["targets"]
        ],
        "related": [
            {key: item[key] for key in ("element", "card", "new_target", "active")}
            for item in batch["related"]
        ],
    }


def _plan(batch, judgement):
    """Turn the model's judgement into per-element records, ignoring unknown keys."""
    sources = {source["key"]: source for source in batch["sources"]}
    new = {key for key, source in sources.items() if source["new"]}
    elements = {item["element"]: (item, True) for item in batch["targets"]}
    elements.update({item["element"]: (item, False) for item in batch["related"]})
    answers = {}
    for answer in judgement["targets"]:
        if answer["element"] in elements and answer["element"] not in answers:
            answers[answer["element"]] = answer
    records, unresolved = [], []
    for element, (item, pending) in elements.items():
        answer = answers.get(element)
        if answer is None and not pending:
            continue
        answer = answer or {"prior": None, "evidence": [], "unresolved": None}
        active = {entry["source"] for entry in item["active"]}
        # Changed elements may be judged against any of their sources; related ones
        # only against new experience, so old sources are not reassessed through them.
        allowed = set(item.get("grounds", ())) | active | new if pending else new
        assign, retract = {}, {}
        for entry in answer["evidence"]:
            key, stance = entry["source"], entry["stance"]
            if key not in allowed:
                continue
            withdrawn = entry["withdraws"]
            if withdrawn in active and withdrawn != key:
                retract[withdrawn] = sources[withdrawn]["ref"]
            if stance == "not_addressed":
                if key in active:
                    retract[key] = sources[key]["ref"]
                continue
            model = OBSERVATION_MODEL.get(sources[key]["kind"], OBSERVATION_MODEL["user"])
            true, false = model[stance]
            evidence = {
                "source_ref": sources[key]["ref"],
                "likelihoods": {"true": true, "false": false},
            }
            if entry["repeats"] in sources and entry["repeats"] != key:
                evidence["dependency_root"] = sources[entry["repeats"]]["ref"]
            assign[key] = evidence
        for key in retract:
            assign.pop(key, None)
        if answer["unresolved"]:
            unresolved.append({"element": element, "reason": answer["unresolved"]})
        if not pending and not assign and not retract:
            continue
        prior = answer["prior"] if item["new_target"] else None
        records.append((element, prior, list(assign.values()), list(retract.values())))
    return records, unresolved


async def run(ctx, experience_refs: list | None = None):
    """Assess one batch of changed and related graph elements and record their evidence."""
    experience_refs = experience_refs or []
    batch = await pending_evidence(ctx, experience_refs=experience_refs)
    candidates, search_errors = [], []
    for source in batch["sources"]:
        if not source["new"]:
            continue
        try:
            found = await call_semantic_search(ctx, source["text"][:QUERY_CHARACTERS])
        except Exception as error:  # noqa: BLE001 -- search only widens candidates
            search_errors.append({"source": source["key"], "error": str(error)})
        else:
            candidates.extend(item["id"] for item in found.get("items", [])[:SEARCH_LIMIT])
    if candidates:
        batch = await pending_evidence(
            ctx, experience_refs=experience_refs, candidates=list(dict.fromkeys(candidates))
        )
    if not batch["targets"] and not batch["related"]:
        result = {"assessed": [], "unresolved": [], "remaining": 0, "search_errors": search_errors}
        return {"result": result, "feedback": None}
    judgement = await ask(
        ctx,
        instructions=INSTRUCTIONS,
        data=_for_model(batch),
        schema=SCHEMA,
    )
    records, unresolved = _plan(batch, judgement["result"])
    assessed = []
    for element, prior, assign, retract in records:
        recorded = await record_evidence(
            ctx, element, batch["revision"], prior=prior, assign=assign, retract=retract
        )
        assessed.append(recorded)
    return {
        "result": {
            "assessed": assessed,
            "unresolved": unresolved,
            "remaining": batch["remaining"],
            "search_errors": search_errors,
        },
        "feedback": None,
    }
