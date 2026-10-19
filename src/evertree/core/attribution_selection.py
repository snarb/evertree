"""Scale-aware selection over property readings, retaining unknowns and their grounds."""

from __future__ import annotations

from collections.abc import Mapping

from .attribution_population import finite_number
from .graph.matching import values_equal
from .values import UNKNOWN, ContractError, json_value, timestamp, utcnow

_COMPARISONS = {"==", "!=", "<", "<=", ">", ">="}


def selection_contract(runtime, subjects, filters, order_by, limit):
    """Validate a selection before reading any source, returning its property identities."""
    if not isinstance(subjects, (list, tuple)) or any(type(v) is not int for v in subjects):
        raise ContractError("Selection subjects must be graph identities")
    if type(limit) is not int or not 1 <= limit <= 600:
        raise ContractError("Selection limit must be between 1 and 600")
    definitions = runtime.definitions()
    properties = []
    for condition in filters:
        if (
            not isinstance(condition, Mapping)
            or set(condition) - {"property", "op", "value", "tolerance", "alternative"}
            or not {"property", "op", "value"} <= condition.keys()
        ):
            raise ContractError("A property filter requires property, op and value")
        definition = definitions.get(condition["property"])
        if definition is None:
            raise ContractError("Selection requires declared properties")
        op = condition["op"]
        if op not in _COMPARISONS | {"in", "approx"}:
            raise ContractError("Unknown property predicate")
        alternative = condition.get("alternative")
        if alternative is not None:
            if (
                definition.scale not in {"nominal", "ordinal"}
                or str(alternative) not in set(map(str, definition.classes))
                or op not in _COMPARISONS
            ):
                raise ContractError(
                    "Profile filters require an allowed alternative and strength comparison"
                )
            if not 0 <= finite_number(condition["value"]) <= 1:
                raise ContractError("Profile strength must be between zero and one")
        elif op in {"<", "<=", ">", ">="} and definition.scale in {"nominal", "circular"}:
            raise ContractError("This scale has no linear ordering")
        if op == "in" and not isinstance(condition["value"], (list, tuple)):
            raise ContractError("Membership requires a list of allowed values")
        if alternative is None and definition.scale in {"numeric", "circular"}:
            operands = condition["value"] if op == "in" else (condition["value"],)
            for value in operands:
                finite_number(value)
        elif alternative is None and definition.scale == "ordinal" and op in {"<", "<=", ">", ">="}:
            if condition["value"] not in definition.classes:
                raise ContractError("Value is outside the property's ordered scale")
        if op == "approx" or "tolerance" in condition:
            if definition.scale not in {"numeric", "circular"} or alternative is not None:
                raise ContractError("Tolerance requires a numeric or circular property")
            if finite_number(condition.get("tolerance", 0)) < 0:
                raise ContractError("Tolerance cannot be negative")
        properties.append(definition.id)
    if order_by is not None:
        if (
            not isinstance(order_by, Mapping)
            or set(order_by) - {"property", "direction", "value", "alternative"}
            or not {"property", "direction"} <= order_by.keys()
        ):
            raise ContractError("Ordering requires property and direction")
        definition = definitions.get(order_by["property"])
        if definition is None:
            raise ContractError("Ordering requires a declared property")
        direction = order_by["direction"]
        if direction not in {"asc", "desc", "nearest"}:
            raise ContractError("Unknown ordering direction")
        if order_by.get("alternative") is not None:
            if (
                definition.scale not in {"nominal", "ordinal"}
                or str(order_by["alternative"]) not in set(map(str, definition.classes))
                or direction == "nearest"
            ):
                raise ContractError("Profile ordering requires an allowed alternative's strength")
        elif direction == "nearest":
            if definition.scale not in {"numeric", "circular"}:
                raise ContractError("Nearest requires a scale with a distance")
            finite_number(order_by.get("value"))
        elif definition.scale in {"nominal", "circular"}:
            raise ContractError("This scale has no linear ordering")
        properties.append(definition.id)
    return tuple(dict.fromkeys(properties))


def _value(reading, alternative=None):
    if reading is UNKNOWN:
        return UNKNOWN
    if alternative is not None:
        profile = getattr(reading.belief_data, "profile", None)
        return profile.get(str(alternative), UNKNOWN) if profile is not None else UNKNOWN
    return reading.value_U if reading.value_U is not None else UNKNOWN


def _matches(runtime, condition, reading):
    value = _value(reading, condition.get("alternative"))
    if value is UNKNOWN or isinstance(value, Mapping):
        return UNKNOWN
    expected, op, property_id = condition["value"], condition["op"], condition["property"]
    definition = runtime.definitions()[property_id]
    if op == "in":
        return any(values_equal(value, allowed) for allowed in expected)
    if condition.get("alternative") is not None:
        compared = (value > expected) - (value < expected)
    elif op in {"==", "!=", "approx"}:
        equal = (
            runtime.distance(property_id, value, finite_number(expected))
            <= condition.get("tolerance", 0)
            if definition.scale in {"numeric", "circular"}
            else values_equal(value, expected)
        )
        return not equal if op == "!=" else equal
    else:
        compared = runtime.compare(property_id, value, expected)
    return {
        "==": compared == 0,
        "!=": compared != 0,
        "<": compared < 0,
        "<=": compared <= 0,
        ">": compared > 0,
        ">=": compared >= 0,
    }[op]


def select_properties(
    runtime,
    subjects,
    *,
    filters=(),
    order_by=None,
    limit=20,
    valid_at=None,
    parameters=None,
    readings=None,
):
    """Filter with AND and rank explicit candidates using one fixed set of property readings.

    A Profile requires an explicit alternative-strength predicate or order. Intervals and
    missing readings remain unknown rather than acquiring an invented point estimate.
    Async callers may supply the readings obtained from the same production read contract.
    """
    properties = selection_contract(runtime, subjects, filters, order_by, limit)
    valid_at = timestamp(valid_at) if valid_at is not None else utcnow()
    parameters = parameters or {}
    selected, unknown = [], []
    for subject in dict.fromkeys(subjects):
        values = {
            prop: readings[(subject, prop)]
            if readings is not None
            else runtime.read_property(subject, prop, valid_at=valid_at, **parameters)
            for prop in properties
        }
        predicates = [
            _matches(runtime, condition, values[condition["property"]]) for condition in filters
        ]
        if any(result is False for result in predicates):
            continue
        if any(result is UNKNOWN for result in predicates):
            unknown.append(subject)
            continue
        score = None
        if order_by is not None:
            prop = order_by["property"]
            value = _value(values[prop], order_by.get("alternative"))
            if value is UNKNOWN or isinstance(value, Mapping):
                unknown.append(subject)
                continue
            if order_by["direction"] == "nearest":
                score = runtime.distance(prop, value, order_by["value"])
            elif (
                runtime.definitions()[prop].scale == "ordinal"
                and order_by.get("alternative") is None
            ):
                score = runtime.definitions()[prop].classes.index(value)
            else:
                score = value
        selected.append(
            {
                "subject": subject,
                "name": runtime.graph.get(subject).name,
                "readings": {str(prop): json_value(reading) for prop, reading in values.items()},
                **({"score": score} if order_by is not None else {}),
            }
        )
    if order_by is not None:
        selected.sort(key=lambda row: row["score"], reverse=order_by["direction"] == "desc")
    return {
        "items": selected[:limit],
        "total": len(selected),
        "unknown": unknown[:limit],
        "unknown_total": len(unknown),
        "truncated": len(selected) > limit or len(unknown) > limit,
    }
