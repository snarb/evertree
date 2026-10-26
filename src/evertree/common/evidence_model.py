"""Initial observation model shared by evidence assessment of every target family.

A judged stance becomes likelihoods through OBSERVATION_MODEL, an initial heuristic
table to be trained on independently resolved cases. The table presumes a cooperative
origin; likelihoods are weakened toward non-discrimination as the origin's reliability
falls. Every assign item keeps the basis it was judged under, so a later reliability
change can revise it in code without another model call.
"""

# (P(stance | target true), P(stance | target false)) by source kind and stance, for an
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

# Reliability of an origin nothing is known against. The table above presumes the
# cooperative-source correctness of the belief model and applies unchanged at or above it;
# an origin's reliability belief starts here unless its kind is doubtful. Under the
# shared cap one unsupported prior and one contrary report only cancel, so a higher
# starting point would make an origin impossible to discredit by a single report.
PRESUMED_RELIABILITY = 0.5
# Reliability at which an origin discriminates nothing, such as a sensor reported faulty.
DISCREDITED_RELIABILITY = 0.25


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


def evidence_item(source, stance, reliability, dependency_root=None):
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
