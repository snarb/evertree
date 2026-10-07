"""Immutable semantic values, UNKNOWN, timestamps and snapshot value encoding."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any


class ContractError(ValueError):
    """A semantic interface or graph invariant was violated."""


class _Unknown:
    def __repr__(self) -> str:
        return "unknown"

    def __bool__(self) -> bool:
        raise TypeError("unknown is not a boolean; compare with UNKNOWN explicitly")


UNKNOWN = _Unknown()


def utcnow() -> datetime:
    return datetime.now(UTC)


def timestamp(value: datetime | str) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None:
        raise ContractError("timestamps must include a timezone")
    return result.astimezone(UTC)


def freeze(value: Any) -> Any:
    """Detach JSON-shaped values and prevent mutations through returned reads."""
    if value is UNKNOWN:
        return UNKNOWN
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return MappingProxyType(
            {field.name: freeze(getattr(value, field.name)) for field in dataclasses.fields(value)}
        )
    if hasattr(value, "model_dump"):
        return freeze(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze(item) for item in value)
    if isinstance(value, (str, int, bool, float, datetime, type(None))):
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError("non-finite values cannot be persisted")
        return value
    raise ContractError(f"unsupported persisted value: {type(value).__name__}")


def json_value(value: Any) -> Any:
    """Encode values without importing classes or executing code on restore."""
    if value is UNKNOWN:
        return {"$unknown": True}
    if isinstance(value, datetime):
        return {"$datetime": timestamp(value).isoformat()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if hasattr(value, "model_dump"):
        return json_value(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        if len(value) == 1 and next(iter(value)) in {"$unknown", "$datetime", "$set", "$mapping"}:
            return {"$mapping": [[str(key), json_value(item)] for key, item in value.items()]}
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return {"$set": [json_value(item) for item in sorted(value, key=repr)]}
    if isinstance(value, (str, int, float, bool, type(None))):
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError("non-finite values cannot be persisted")
        return value
    raise ContractError(f"unsupported snapshot value: {type(value).__name__}")


def restore_value(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$mapping"}:
            return {key: restore_value(item) for key, item in value["$mapping"]}
        if set(value) == {"$unknown"}:
            return UNKNOWN
        if set(value) == {"$datetime"}:
            return timestamp(value["$datetime"])
        if set(value) == {"$set"}:
            return frozenset(restore_value(item) for item in value["$set"])
        return {key: restore_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(restore_value(item) for item in value)
    return value
