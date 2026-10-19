"""Evaluate text-based evidence case expectations against per-step belief snapshots.

A snapshot is {"elements": {id: {kind, text, strength, support, evidence_count, scope?}},
"origins": {origin: {reliability, support, evidence_count}}}, taken after each step.
Elements are selected by kind and keywords because their ids and wording come from a real
integration run; expectations are ordinal, not exact numbers.
"""

TOLERANCE = 0.01
OPERATORS = {
    "<": lambda value, bound: value < bound,
    "<=": lambda value, bound: value <= bound,
    ">": lambda value, bound: value > bound,
    ">=": lambda value, bound: value >= bound,
    "==": lambda value, bound: value == bound,
}


def select(snapshot, selector):
    """Return ids of assessed elements whose kind and text match the selector."""
    kinds = selector.get("kinds") or ([selector["kind"]] if "kind" in selector else None)
    result = []
    for identity, element in snapshot["elements"].items():
        text = element["text"].lower()
        if kinds and element["kind"] not in kinds:
            continue
        if selector.get("in_scope") and not element.get("scope"):
            continue
        if not all(
            any(option.lower() in text for option in (term if isinstance(term, list) else [term]))
            for term in selector.get("all", ())
        ):
            continue
        if any(term.lower() in text for term in selector.get("none", ())):
            continue
        result.append(identity)
    return result


def _bounded(value, condition):
    operator, *bounds = condition
    if operator == "between":
        return bounds[0] <= value <= bounds[1]
    return OPERATORS[operator](value, bounds[0])


def _direction(before, after, expected):
    delta = after - before
    return {
        "up": delta > TOLERANCE,
        "down": delta < -TOLERANCE,
        "same": abs(delta) <= TOLERANCE,
    }[expected]


FIELDS = ("strength", "support", "evidence_count")


def check(history, expectation):
    """Return None when an expectation holds, else a description of the failure."""
    if "origin" in expectation:
        origin = history[expectation["at"] - 1]["origins"].get(expectation["origin"])
        if origin is None:
            return f"origin {expectation['origin']} has no reliability belief"
        if not _bounded(origin["reliability"], expectation["reliability"]):
            return f"origin reliability {origin['reliability']} fails {expectation['reliability']}"
        return None
    if "scope" in expectation:
        snapshot = history[expectation["at"] - 1]
        groups = [select(snapshot, selector) for selector in expectation["scope"]]
        if not all(groups):
            if expectation.get("optional"):
                return None
            return f"scope members not all found: {groups}"
        scopes = [
            {snapshot["elements"][identity].get("scope") for identity in group} - {None}
            for group in groups
        ]
        shared = set.intersection(*scopes)
        if not shared:
            return f"selected elements share no scope: {list(zip(groups, scopes, strict=True))}"
        for scope in shared:
            members = [
                next(i for i in group if snapshot["elements"][i].get("scope") == scope)
                for group in groups
            ]
            total = sum(snapshot["elements"][identity]["strength"] for identity in members)
            if total <= 1 + TOLERANCE:
                return None
        return "scope alternatives sum above one"
    if "compare" in expectation:
        snapshot = history[expectation["at"] - 1]
        left, operator, right = expectation["compare"]
        values = []
        for selector in (left, right):
            found = select(snapshot, selector)
            if not found:
                return f"no element for {selector}"
            values.append(max(snapshot["elements"][identity]["strength"] for identity in found))
        if not OPERATORS[operator](*values):
            return f"compare {values[0]} {operator} {values[1]} fails"
        return None
    mode = expectation.get("mode", "any")
    if "change" in expectation:
        first, last = expectation["change"]
        before, after = history[first - 1], history[last - 1]
        found = [
            identity
            for identity in select(after, expectation["select"])
            if identity in before["elements"]
        ]
        verdicts = []
        for identity in found:
            for field in FIELDS:
                if field in expectation:
                    verdicts.append(
                        (
                            identity,
                            field,
                            before["elements"][identity][field],
                            after["elements"][identity][field],
                            _direction(
                                before["elements"][identity][field],
                                after["elements"][identity][field],
                                expectation[field],
                            ),
                        )
                    )
    else:
        snapshot = history[expectation["at"] - 1]
        found = select(snapshot, expectation["select"])
        verdicts = [
            (
                identity,
                field,
                None,
                snapshot["elements"][identity][field],
                _bounded(snapshot["elements"][identity][field], expectation[field]),
            )
            for identity in found
            for field in FIELDS
            if field in expectation
        ]
    if not found:
        return None if expectation.get("optional") else f"no element for {expectation['select']}"
    passed = [verdict[-1] for verdict in verdicts]
    if all(passed) if mode == "all" else any(passed):
        return None
    return f"{mode} of {verdicts} fails"
