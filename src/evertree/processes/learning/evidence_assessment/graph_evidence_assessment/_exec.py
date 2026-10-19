"""Assess experience as evidence for changed and related graph elements.

One batch per run: Core selects elements changed since their last assessment, their
primary sources and nearby elements; search adds elements the new experience may bear
on without having changed them. One model call judges how each source bears on each
element. Code converts that judgement into likelihoods through OBSERVATION_MODEL, an
initial heuristic table to be trained on independently resolved cases, and Core keeps
its influence under the shared cap for unsupported estimates.

Each source has an origin (the user, a sensor, a journal) whose reliability is itself a
binary belief: "reports from this origin are correct". Its neutral 0.5 means nothing is
known against the origin, and the table applies as presumed; a doubtful kind of origin
starts lower, and experience about the origin (a calibration failure, a retraction)
moves it. The table's likelihoods are weakened toward non-discrimination as reliability
falls, and every contribution keeps the reliability it was judged under, so when an
origin's reliability changes, code revises all contributions resting on it without
another model call.

Elements that answer one question with mutually exclusive alternatives (competing causes,
values of one property at one time) are judged together as a competition scope: each
source gets one assignment over all alternatives, and each member reads as its
alternative's probability in the scope's Profile.
"""

from evertree.common.structured import ask
from evertree.core.learning.api import (
    pending_evidence,
    pending_property_evidence,
    record_evidence,
    record_origin_evidence,
    record_property_evidence,
    record_scope_evidence,
    stale_evidence,
    withdraw_evidence,
)
from evertree.core.semantics.api import call_semantic_search

# (P(stance | element true), P(stance | element false)) by source kind and stance, for an
# origin of presumed reliability; documents report what their authors state.
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
OBSERVATION_MODEL["document"] = OBSERVATION_MODEL["observation"]
STANCES = (*OBSERVATION_MODEL["user"], "not_addressed")

PROPERTY_INSTRUCTIONS = """Assess the declared qualitative properties of recorded subjects.
Each question has mutually exclusive, exhaustive class alternatives. The numeric reading,
fitted population norm and conditional interpretation are supplied by deterministic code.
They are context for judging the subject's actual class, not calibrated confidence.
Count describes the norm's sample size; it is never epistemic support. A norm fitted to a
few reported subjects does not establish a reliable norm for the whole population.
The training-evidence preview preserves assessed beliefs of individual inputs and the
reference, prioritizing assessed inputs with lower Strength; its total may exceed the
preview. This ordering does not reweight training data. Missing assessments are not refutations.

For every question, judge the primary sources with role measurement against every class:
supports/opposes for clear applicable evidence, weak_support/weak_opposition for hedged,
indirect or uncertain evidence, non_discriminating when it does not distinguish the
alternatives, not_addressed when it does not bear on the claim. Account for numeric and
criterion uncertainty, its declared domain and conditions, and the supplied norm belief.
Do not multiply confidence numbers. Source origin reliability is applied by code.
Norm-context sources explain the rule and its population; do not assign them independent
votes about this individual. Never assign withdrawn sources. A criterion or a computed
bin alone does not prove an object's actual class. Keep all alternatives even without a
winning class; an empty evidence list preserves the prior.

Set repeats to another source key only when the measurement source restates that source.
Return one answer per question; class values are the supplied integer class ids. Reasons
explain a semantic judgment in the source's language. No graph facts are requested.
"""

PROPERTY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scopes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "scope": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "source": {"type": "string"},
                                "stances": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "class": {"type": "integer"},
                                            "stance": {"type": "string", "enum": list(STANCES)},
                                        },
                                        "required": ["class", "stance"],
                                    },
                                },
                                "repeats": {"type": ["string", "null"]},
                                "reason": {"type": "string"},
                            },
                            "required": ["source", "stances", "repeats", "reason"],
                        },
                    },
                },
                "required": ["scope", "evidence"],
            },
        }
    },
    "required": ["scopes"],
}
# Reliability of an origin nothing is known against. The table above presumes the
# cooperative-source correctness of the belief model and applies unchanged at or above it;
# an origin's reliability belief starts here unless its kind is doubtful. Under the
# shared cap one unsupported prior and one contrary report only cancel, so a higher
# starting point would make an origin impossible to discredit by a single report.
PRESUMED_RELIABILITY = 0.5
# Reliability at which an origin discriminates nothing, such as a sensor reported faulty.
DISCREDITED_RELIABILITY = 0.25
REASSESSMENT_ROUNDS = 3
SEARCH_LIMIT = 6
QUERY_CHARACTERS = 400

INSTRUCTIONS = """You assess evidence for elements of an agent's knowledge graph.

Input fields:
- sources: primary experience, keyed S1, S2, …. kind is "user" (a person's message),
  "observation" (a sensor reading, tool result or other recorded observation) or
  "document" (an article, report, post or other text whose author states something);
  origin_key names its origin; recorded_at is when it was recorded; new marks experience
  not yet assessed; withdrawn_by marks a source its author later withdrew (the
  withdrawing source's key, or "earlier"). Agent reasoning is never a source: it was already replaced by the
  experience it cites.
- origins: where sources come from, keyed O1, O2, …: origin is its name (a sensor id, a
  journal DOI, a forum account, "user"); reliability is the current belief that its
  reports are correct, or null for a new origin; active lists sources already counted
  about its reliability and their direction.
- targets: elements to judge. changed is true for an element that was created or changed,
  false for an existing element near the changes or found by searching new experience,
  which the new sources may confirm, contradict or leave unaffected. card is the element
  (relation facts show relation, args and conditions; facets show their validity
  interval). grounds are the sources cited when a changed element was written. active
  lists sources already counted for it and their direction. new_target means the element
  has no belief yet.
- scopes: competition scopes that batch elements already belong to (an element's scope
  field names it). alternatives are element ids or "other" (none of the listed is
  true); active lists sources already counted for the scope and the alternative each
  favoured.

Answer every target, with an empty evidence list when no source bears on it. For a
changed target, assess each of its grounds and active sources, and any other new source
that bears on it; for a changed new_target, also sources already active for unchanged
targets when they bear on it (earlier records supporting a pattern stated only now). For
an unchanged target, assess only new sources, and only when they bear on it. Judge what the source actually says about the element's assertion as a whole,
including its time interval, conditions and qualifications. Wording that attributes the
assertion to someone ("the user reports that X", "according to the log, X", "not
independently verified") does not change what is assessed: judge X, not whether the
report was made: "Petrov said N-18 is broken; I did not check" is about whether N-18 is
broken, so Petrov's word is weak_support and a measurement showing N-18 running opposes
it. An unchanged target is often contradicted or confirmed only indirectly, for example a
stated pattern by counts in a log:
- supports / opposes: the source clearly asserts or denies the element;
- weak_support / weak_opposition: hedged, partial, indirect or approximate statements,
  and hearsay the speaker has not checked ("Petrov says it is broken; I did not check");
- non_discriminating: the source is about the element but would be equally expected
  whether the element is true or false;
- not_addressed: the source does not bear on this element (for example a classification
  added from general knowledge, or a ground that no longer fits a changed element).
  An active source marked not_addressed stops counting.
Set repeats to an earlier source key when this source only restates that source (the
same person repeating or paraphrasing themselves, a copy of the same report). Set
withdraws to an earlier source key when this source retracts or corrects that source's
statement, for example "I was wrong earlier".
A withdrawn source is no longer evidence for anything: never use it for an element it
is not already active for. Where it is active, set withdraws on the correcting source if
the correction concerns that element. A source that withdraws a withdrawal (for example
"I was right after all") makes the original statement usable again.
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
Write reasons in the sources' language.

origins (output): for each origin that a new source says something about, or that is new:
- prior: for a new origin other than "user", null unless its kind is clearly less
  trustworthy than an ordinary source; null means nothing is known against it, the
  normal case for a sensor, log, report, journal or named person. A doubtful kind gets a
  number from 0.3 to 0.45: an anonymous comment or review, a rumour, a repost or
  second-hand retelling, a self-reported home test.
- evidence: new sources that bear on whether this origin's reports are correct, with
  stance as above: a source reporting that a sensor was faulty or miscalibrated, or that
  an author fabricated data, opposes; a source confirming calibration or accuracy
  supports. When a new source corrects an earlier statement about the origin (one listed
  in the origin's active, for example "the metrologist was wrong: T-7 is fine"), set
  withdraws to that earlier source's key, and judge what the new source itself says.
  A source never judges its own origin. Agreement with other sources is not evidence of
  reliability here: it is already counted for the elements themselves.
Do not judge an element's evidence by its origin's reliability: code applies it.

scopes (output): group elements that answer one question with mutually exclusive
alternatives, exactly one of which is true at a time: competing hypotheses about a single
cause, different values of one property of one object at the same time. Values stated
as current or without a time (a location now, a log entry for today) overlap unless a
source says the value changed in between. Never group
assertions that can be true together: states at different times, an object and its
classification, independent facts. For an existing scope repeat its key and list all its
alternatives; adding or removing an alternative creates a new version, and then judge
every source again. other is true unless the alternatives are exhaustive (for example the
source itself says "one of these three").
- prior: for a new or changed scope, a probability for each alternative (element id as a
  string, or "other") from background knowledge alone, summing to 1; [] otherwise.
- evidence: every source that bears on the question (the members' grounds and active
  sources, the scope's active sources, and new sources), with a stance for every
  alternative: supports for the one it asserts, opposes for ones it rules out,
  not_addressed for ones it says nothing about. repeats and withdraws are as above.
Elements in a scope get evidence only there: give them an empty evidence list in targets.
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
        },
        "origins": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "origin": {"type": "string"},
                    "prior": {"type": ["number", "null"]},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "source": {"type": "string"},
                                "stance": {"type": "string", "enum": list(STANCES)},
                                "withdraws": {"type": ["string", "null"]},
                                "reason": {"type": "string"},
                            },
                            "required": ["source", "stance", "withdraws", "reason"],
                        },
                    },
                },
                "required": ["origin", "prior", "evidence"],
            },
        },
        "scopes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "scope": {"type": ["string", "null"]},
                    "question": {"type": "string"},
                    "alternatives": {"type": "array", "items": {"type": "integer"}},
                    "other": {"type": "boolean"},
                    "prior": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "alternative": {"type": "string"},
                                "probability": {"type": "number"},
                            },
                            "required": ["alternative", "probability"],
                        },
                    },
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "source": {"type": "string"},
                                "stances": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "alternative": {"type": "string"},
                                            "stance": {"type": "string", "enum": list(STANCES)},
                                        },
                                        "required": ["alternative", "stance"],
                                    },
                                },
                                "repeats": {"type": ["string", "null"]},
                                "withdraws": {"type": ["string", "null"]},
                                "reason": {"type": "string"},
                            },
                            "required": ["source", "stances", "repeats", "withdraws", "reason"],
                        },
                    },
                },
                "required": ["scope", "question", "alternatives", "other", "prior", "evidence"],
            },
        },
    },
    "required": ["targets", "origins", "scopes"],
}


def likelihoods(kind, stance, reliability):
    """Table likelihoods of a stance, moved toward 0.5 for an origin of lower reliability.

    At or above the presumed reliability the table applies unchanged; a discredited
    origin discriminates nothing.
    """
    true, false = OBSERVATION_MODEL.get(kind, OBSERVATION_MODEL["user"])[stance]
    if reliability is None:
        reliability = PRESUMED_RELIABILITY
    span = PRESUMED_RELIABILITY - DISCREDITED_RELIABILITY
    weight = min(max((reliability - DISCREDITED_RELIABILITY) / span, 0.0), 1.0)
    return {"true": 0.5 + (true - 0.5) * weight, "false": 0.5 + (false - 0.5) * weight}


def _evidence(source, stance, reliability, dependency_root=None):
    """One assign item with the basis that lets a reliability change revise it.

    stance is one stance, or for a scope a mapping from alternative to stance; a scope
    alternative's likelihood is P(source says this | that alternative is true).
    """
    basis = {
        "kind": source["kind"],
        "origin": source["origin"],
        "reliability": reliability if reliability is not None else PRESUMED_RELIABILITY,
    }
    if isinstance(stance, dict):
        basis["stances"] = stance
        values = {
            alternative: 0.5
            if value == "not_addressed"
            else likelihoods(source["kind"], value, reliability)["true"]
            for alternative, value in stance.items()
        }
    else:
        basis["stance"] = stance
        values = likelihoods(source["kind"], stance, reliability)
    item = {"source_ref": source["ref"], "likelihoods": values, "basis": basis}
    if dependency_root is not None:
        item["dependency_root"] = dependency_root
        basis["dependency_root"] = dependency_root
    return item


def _for_model(batch):
    """Keep only decision-relevant fields; references stay in code."""
    return {
        "sources": [
            {
                key: source[key]
                for key in (
                    "key",
                    "kind",
                    "origin_key",
                    "recorded_at",
                    "new",
                    "text",
                    "withdrawn_by",
                )
                if key in source
            }
            for source in batch["sources"]
        ],
        "origins": [
            {key: item.get(key, []) for key in ("key", "origin", "reliability", "active")}
            for item in batch["origins"]
        ],
        # Changed and related elements form one list: the model reliably answers every
        # listed target but tends to skip a separate list of related elements.
        "targets": [
            {
                "element": item["element"],
                "changed": changed,
                **{
                    key: item[key]
                    for key in ("card", "new_target", "grounds", "active", "scope")
                    if key in item
                },
            }
            for changed, items in ((True, batch["targets"]), (False, batch["related"]))
            for item in items
        ],
        "scopes": [
            {key: item[key] for key in ("key", "question", "alternatives", "active")}
            for item in batch["scopes"]
        ],
    }


def _withdrawals(batch, judgement):
    """(withdrawn, withdrawing) source key pairs a judgement states for new sources."""
    sources = {source["key"]: source for source in batch["sources"]}
    entries = [
        entry
        for group in ("targets", "origins", "scopes")
        for answer in judgement.get(group, ())
        for entry in answer["evidence"]
    ]
    return {
        (entry["withdraws"], entry["source"])
        for entry in entries
        if entry["withdraws"] in sources
        and entry["source"] in sources
        and entry["withdraws"] != entry["source"]
        and sources[entry["source"]]["new"]
    }


def _kept(batch, judgement, key):
    """Targets for which the judgement still gives a withdrawn source a stance."""
    scopes = {item["key"]: item["scope"] for item in batch["scopes"]}
    origins = {item["key"]: item["origin"] for item in batch["origins"]}
    origins.update({item["origin"]: item["origin"] for item in batch["origins"]})
    kept = []
    for answer in judgement.get("targets", ()):
        if any(e["source"] == key and e["stance"] != "not_addressed" for e in answer["evidence"]):
            kept.append(f"graph:{answer['element']}")
    for answer in judgement.get("origins", ()):
        if answer["origin"] in origins and any(
            e["source"] == key and e["stance"] != "not_addressed" for e in answer["evidence"]
        ):
            kept.append(f"origin:{origins[answer['origin']]}")
    for answer in judgement.get("scopes", ()):
        if answer["scope"] in scopes and any(
            e["source"] == key and any(s["stance"] != "not_addressed" for s in e["stances"])
            for e in answer["evidence"]
        ):
            kept.append(scopes[answer["scope"]])
    return kept


def _plan(batch, judgement, reliability, members=frozenset(), withdrawn=frozenset()):
    """Turn the model's judgement into per-element records, ignoring unknown keys.

    reliability maps origin names to their current reliability; members are elements
    judged in a competition scope, which get no binary record; withdrawn sources give
    no evidence to an element they are not already active for.
    """
    sources = {source["key"]: source for source in batch["sources"]}
    new = {key for key, source in sources.items() if source["new"]}
    elements = {item["element"]: (item, True) for item in batch["targets"]}
    elements.update({item["element"]: (item, False) for item in batch["related"]})
    answers = {}
    for answer in judgement["targets"]:
        if answer["element"] in elements and answer["element"] not in answers:
            answers[answer["element"]] = answer
    # Experience already counted for nearby elements may bear on a new element too, such
    # as earlier failure records on a pattern claimed only now.
    context = {entry["source"] for item in batch["related"] for entry in item["active"]}
    records, unresolved = [], []
    for element, (item, pending) in elements.items():
        if element in members or "scope" in item:
            continue
        answer = answers.get(element)
        if answer is None and not pending:
            continue
        answer = answer or {"prior": None, "evidence": [], "unresolved": None}
        active = {entry["source"] for entry in item["active"]}
        # Changed elements may be judged against any of their sources; related ones
        # only against new experience, so old sources are not reassessed through them.
        allowed = set(item.get("grounds", ())) | active | new if pending else new
        if pending and item["new_target"]:
            allowed |= context
        assign, retract = {}, {}
        for entry in answer["evidence"]:
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
            assign[key] = _evidence(source, stance, reliability.get(source["origin"]), root)
        for key in retract:
            assign.pop(key, None)
        if answer["unresolved"]:
            unresolved.append({"element": element, "reason": answer["unresolved"]})
        if not pending and not assign and not retract:
            continue
        prior = answer["prior"] if item["new_target"] else None
        records.append((element, prior, list(assign.values()), list(retract.values())))
    return records, unresolved


def _plan_scopes(batch, judgement, reliability, withdrawn=frozenset()):
    """Turn judged competition scopes into scope records; return them and their members.

    Existing scopes the batch touches but the judgement omits are recorded unchanged,
    so their changed members still count as assessed.
    """
    sources = {source["key"]: source for source in batch["sources"]}
    new = {key for key, source in sources.items() if source["new"]}
    items = {item["element"]: item for item in batch["targets"] + batch["related"]}
    existing = {scope["key"]: scope for scope in batch["scopes"]}
    records, members, answered = [], set(), set()
    for answer in judgement.get("scopes", ()):
        # A listed element already in a scope brings that scope along, whatever scope key the
        # judgement names (or none for a new version).
        declared = existing.get(answer["scope"]) or next(
            (
                existing[items[element]["scope"]]
                for element in answer["alternatives"]
                if element in items and items[element].get("scope") in existing
            ),
            None,
        )
        # A scope keeps its alternatives unless the judgement adds to them: a model that
        # lists only some of them would otherwise silently split the scope.
        kept = [label for label in declared["alternatives"] if label != "other"] if declared else []
        alternatives = [
            element
            for element in dict.fromkeys([*kept, *answer["alternatives"]])
            if (element in items or element in kept) and element not in members
        ]
        other = answer["other"] or bool(declared and "other" in declared["alternatives"])
        labels = [str(element) for element in alternatives] + (["other"] if other else [])
        if len(alternatives) < 1 or len(labels) < 2:
            continue
        scope_active = {entry["source"] for entry in declared["active"]} if declared else set()
        allowed = set(new) | scope_active
        for element in alternatives:
            if element in items:
                allowed.update(items[element].get("grounds", ()))
                allowed.update(entry["source"] for entry in items[element]["active"])
        assign, retract = {}, {}
        for entry in answer["evidence"]:
            key = entry["source"]
            if key not in allowed or key in withdrawn and key not in scope_active:
                continue
            earlier = entry["withdraws"]
            if earlier in scope_active and earlier != key:
                retract[earlier] = sources[earlier]["ref"]
            given = {str(item["alternative"]): item["stance"] for item in entry["stances"]}
            stances = {label: given.get(label, "not_addressed") for label in labels}
            if all(value == "not_addressed" for value in stances.values()):
                if key in scope_active:
                    retract[key] = sources[key]["ref"]
                continue
            root = None
            if entry["repeats"] in sources and entry["repeats"] != key:
                root = sources[entry["repeats"]]["ref"]
            source = sources[key]
            assign[key] = _evidence(source, stances, reliability.get(source["origin"]), root)
        for key in retract:
            assign.pop(key, None)
        prior = {str(item["alternative"]): item["probability"] for item in answer["prior"]}
        records.append(
            {
                "scope": declared["scope"] if declared else None,
                "alternatives": alternatives,
                "other": other,
                "question": answer["question"],
                "prior": prior if set(prior) == set(labels) else None,
                "assign": list(assign.values()),
                "retract": list(retract.values()),
            }
        )
        members.update(alternatives)
        if declared:
            answered.add(declared["key"])
    for key, declared in existing.items():
        if key in answered:
            continue
        labels = declared["alternatives"]
        records.append(
            {
                "scope": declared["scope"],
                "alternatives": [label for label in labels if label != "other"],
                "other": "other" in labels,
                "question": declared["question"],
                "prior": None,
                "assign": [],
                "retract": [],
            }
        )
    return records, members


async def _assess_origins(ctx, batch, judgement):
    """Register new origins and record new evidence about origins; return reliabilities."""
    sources = {source["key"]: source for source in batch["sources"]}
    by_key = {item["key"]: item for item in batch["origins"]}
    by_name = {item["origin"]: item for item in batch["origins"]}
    reliability = {item["origin"]: item["reliability"] for item in batch["origins"]}
    answers = {}
    for answer in judgement.get("origins", ()):
        item = by_key.get(answer["origin"]) or by_name.get(answer["origin"])
        if item is not None and item["origin"] not in answers:
            answers[item["origin"]] = answer
    recorded = []
    for name, item in by_name.items():
        answer = answers.get(name, {"prior": None, "evidence": []})
        assign, retract = [], []
        for entry in answer["evidence"]:
            source = sources.get(entry["source"])
            if source is None or not source["new"] or source["origin"] == name:
                continue
            withdrawn = sources.get(entry["withdraws"])
            if withdrawn is not None and withdrawn is not source:
                retract.append(withdrawn["ref"])
            if entry["stance"] in {"not_addressed", "non_discriminating"}:
                continue
            assign.append(_evidence(source, entry["stance"], reliability.get(source["origin"])))
        # A new origin is registered when first seen, so later experience about it finds
        # it; the user origin only once something is said about it. A prior never starts
        # above the presumption.
        prior = None
        if item["new_target"]:
            if name == "user" and not assign and not retract:
                continue
            prior = PRESUMED_RELIABILITY
            if name != "user" and answer["prior"] is not None:
                prior = min(answer["prior"], PRESUMED_RELIABILITY)
        elif not assign and not retract:
            continue
        result = await record_origin_evidence(
            ctx, name, prior=prior, assign=assign, retract=retract
        )
        reliability[name] = result["belief"]["data"]["strength"]
        recorded.append(result)
    return reliability, recorded


async def _reassess(ctx, revision):
    """Revise contributions whose origin reliability changed since they were judged."""
    revised = []
    for _ in range(REASSESSMENT_ROUNDS):
        stale = await stale_evidence(ctx)
        if not stale:
            break
        grouped = {}
        for item in stale:
            basis = dict(item["basis"])
            basis["reliability"] = item["reliability"]
            source = {"kind": basis["kind"], "origin": basis["origin"], "ref": item["source_ref"]}
            stance = basis.get("stances", basis.get("stance"))
            evidence = _evidence(source, stance, item["reliability"], basis.get("dependency_root"))
            key = (item.get("element"), item.get("origin"), item.get("scope"))
            grouped.setdefault(key, (item, []))[1].append(evidence)
        for (element, origin, scope), (item, assign) in grouped.items():
            if element is not None:
                result = await record_evidence(ctx, element, revision, assign=assign)
            elif origin is not None:
                result = await record_origin_evidence(ctx, origin, assign=assign)
            else:
                alternatives = item["alternatives"]
                result = await record_scope_evidence(
                    ctx,
                    revision,
                    scope=scope,
                    alternatives=[label for label in alternatives if label != "other"],
                    other="other" in alternatives,
                    question=item["question"],
                    assign=assign,
                )
            revised.append(result)
    return revised


def _training_priority(item):
    """Keep assessed weak inputs visible even when the full sample exceeds the preview."""
    belief = item["belief"]
    if belief and belief["stats"]["evidence_count"] > 0:
        return 0, belief["data"]["strength"]
    return 1, 0


def _property_sources(item, training):
    """Retain all measurement sources and a bounded preview of the norm's source texts."""
    sources = {source["key"]: source for source in item["sources"]}
    preferred = list(dict.fromkeys(key for record in training for key in record["source_keys"]))
    ordered = preferred + [key for key in sources if key not in preferred]
    context = [sources[key] for key in ordered if sources[key]["role"] == "norm_context"][:20]
    return [source for source in item["sources"] if source["role"] == "measurement"] + context


async def _assess_properties(ctx):
    """Use the same source observation model for declared qualitative scopes."""
    pending = await pending_property_evidence(ctx)
    scopes = {f"P{index + 1}": item for index, item in enumerate(pending["scopes"])}
    if not scopes:
        return []
    questions = []
    for key, item in scopes.items():
        training = sorted(item["norm"]["training_evidence"], key=_training_priority)[:20]
        questions.append(
            {
                "scope": key,
                "subject": item["subject_name"],
                "property": item["property_name"],
                "classes": item["class_meanings"],
                "conditions": item["parameters"],
                "reading": item["reading"],
                "norm": {
                    "definition": item["norm"]["definition"],
                    "state": {
                        field: value
                        for field, value in item["norm"]["state"].items()
                        if field not in {"semantic_revision", "revision"}
                    },
                    "belief_data": item["norm"]["belief_data"],
                    "belief_status": item["norm"]["belief_status"],
                    "training_evidence": training,
                    "training_evidence_total": len(item["norm"]["training_evidence"]),
                },
                "conditional_interpretation": item["conditional_interpretation"],
                "sources": [
                    {
                        field: source[field]
                        for field in ("key", "kind", "origin", "role", "text", "withdrawn_by")
                    }
                    for source in _property_sources(item, training)
                ],
                "sources_total": len(item["sources"]),
            }
        )
    judged = await ask(
        ctx,
        instructions=PROPERTY_INSTRUCTIONS,
        data={"questions": questions},
        schema=PROPERTY_SCHEMA,
    )
    recorded, answered = [], set()
    for answer in judged["result"]["scopes"]:
        key = answer["scope"]
        if key not in scopes or key in answered:
            continue
        answered.add(key)
        item = scopes[key]
        sources = {source["key"]: source for source in item["sources"]}
        assign = []
        for evidence in answer["evidence"]:
            source = sources.get(evidence["source"])
            if source is None or source["role"] != "measurement" or source["withdrawn_by"]:
                continue
            given = {str(entry["class"]): entry["stance"] for entry in evidence["stances"]}
            stances = {
                str(identity): given.get(str(identity), "not_addressed")
                for identity in item["classes"]
            }
            if all(stance == "not_addressed" for stance in stances.values()):
                continue
            prior = source["origin_belief"]
            reliability = prior["data"]["strength"] if prior is not None else None
            repeat = sources.get(evidence["repeats"])
            root = repeat["ref"] if repeat is not None else source["dependency_root"]
            assign.append(_evidence(source, stances, reliability, root))
        recorded.append(
            await record_property_evidence(
                ctx,
                item["subject"],
                item["property"],
                item["input_revision"],
                parameters=item["parameters"],
                at=item["at"],
                assign=assign,
            )
        )
    return recorded


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
    assessed, unresolved, origins, scopes = [], [], [], []
    has_new = any(source["new"] for source in batch["sources"])
    if batch["targets"] or batch["related"] or has_new:
        judgement = await ask(
            ctx,
            instructions=INSTRUCTIONS,
            data=_for_model(batch),
            schema=SCHEMA,
        )
        sources = {source["key"]: source for source in batch["sources"]}
        withdrawn = {key for key, source in sources.items() if source.get("withdrawn_by")}
        for earlier, later in sorted(_withdrawals(batch, judgement["result"])):
            keep = _kept(batch, judgement["result"], earlier)
            await withdraw_evidence(ctx, sources[earlier]["ref"], sources[later]["ref"], keep=keep)
            withdrawn.add(earlier)
            # Withdrawing a withdrawal makes the original statements usable again.
            withdrawn -= {
                key for key, source in sources.items() if source.get("withdrawn_by") == earlier
            }
        reliability, origins = await _assess_origins(ctx, batch, judgement["result"])
        scope_records, members = _plan_scopes(batch, judgement["result"], reliability, withdrawn)
        records, unresolved = _plan(batch, judgement["result"], reliability, members, withdrawn)
        for element, prior, assign, retract in records:
            recorded = await record_evidence(
                ctx, element, batch["revision"], prior=prior, assign=assign, retract=retract
            )
            assessed.append(recorded)
        for record in scope_records:
            scopes.append(await record_scope_evidence(ctx, batch["revision"], **record))
    reassessed = await _reassess(ctx, batch["revision"])
    properties = await _assess_properties(ctx)
    return {
        "result": {
            "assessed": assessed,
            "origins": origins,
            "scopes": scopes,
            "reassessed": reassessed,
            "properties": properties,
            "unresolved": unresolved,
            "remaining": batch["remaining"],
            "search_errors": search_errors,
        },
        "feedback": None,
    }
