"""Apply the configured provider mode within the current resource budget."""


def run(model: str, reasoning_effort: str = "high", remaining_active_minutes: float | None = None):
    if reasoning_effort != "high":
        raise ValueError("The configured v1 cognition profile uses high reasoning effort")
    return {
        "result": {
            "model": model,
            "reasoning_effort": reasoning_effort,
            "requires_resource_review": remaining_active_minutes is not None
            and remaining_active_minutes <= 0,
        },
        "feedback": None,
    }
