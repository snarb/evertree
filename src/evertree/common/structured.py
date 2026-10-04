"""Validation for the small, explicit JSON schemas of bootstrap Programs."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any


def validate(value: Any, schema: Mapping[str, Any], path: str = "$") -> None:
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
        None: True,
    }
    if not any(matches.get(candidate, False) for candidate in kinds):
        raise ValueError(f"{path}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: unsupported value")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", ())) - value.keys()
        if missing:
            raise ValueError(f"{path}: missing {sorted(missing)}")
        if schema.get("additionalProperties") is False and value.keys() - properties.keys():
            raise ValueError(f"{path}: unexpected fields")
        for key, child in value.items():
            child_schema = properties.get(key, schema.get("additionalProperties", {}))
            if isinstance(child_schema, dict):
                validate(child, child_schema, path + "." + key)
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{path}: too few items")
        for index, child in enumerate(value):
            validate(child, schema.get("items", {}), f"{path}[{index}]")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path}: above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise ValueError(f"{path}: must exceed minimum")
    elif isinstance(value, str) and len(value) < schema.get("minLength", 0):
        raise ValueError(f"{path}: string is too short")


async def ask(ctx, *, instructions: str, data: dict, schema: dict):
    response = await ctx.step(
        "agent.run",
        {
            "prompt": json.dumps(data, ensure_ascii=False, allow_nan=False),
            "instructions": instructions,
            "mode": "model",
            "output_schema": schema,
        },
    )
    result = response.get("parsed")
    if result is None:
        result = json.loads(response["text"])
    validate(result, schema)
    return {"result": result, "feedback": None}
