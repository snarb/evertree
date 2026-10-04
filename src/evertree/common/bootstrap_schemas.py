"""Shared structural response contracts, independent of any Program implementation."""

TASK_FRAMING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "objective": {"type": "string", "minLength": 1},
        "success_criteria": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "preferences": {"type": "array", "items": {"type": "string"}},
        "execution_budget": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"active_time_minutes": {"type": "number", "exclusiveMinimum": 0}},
            "required": ["active_time_minutes"],
        },
        "self_improvement_budget": {"type": "number", "minimum": 0, "maximum": 100},
        "budget_reason": {"type": "string", "minLength": 1},
    },
    "required": [
        "objective",
        "success_criteria",
        "constraints",
        "preferences",
        "execution_budget",
        "self_improvement_budget",
        "budget_reason",
    ],
}
