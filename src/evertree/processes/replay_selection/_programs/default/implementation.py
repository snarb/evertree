"""Choose existing experience for replay without repeating external effects."""

from evertree.common.structured import ask

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "event_ids": {"type": "array", "items": {"type": "integer"}},
        "objective": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["event_ids", "objective", "reason"],
}


async def run(ctx, candidates: list[dict], objective: str, remaining_budget: dict):
    result = await ask(
        ctx,
        instructions=(
            "Choose retained experiences for a bounded replay relevant to the objective. Include informative "
            "successes, failures or contrasts when useful. Replay preserves original source identities and cannot "
            "create independent evidence or automatically repeat external actions. Return only available event IDs."
        ),
        data={
            "candidates": candidates,
            "objective": objective,
            "remaining_budget": remaining_budget,
        },
        schema=SCHEMA,
    )
    available = {event["id"] for event in candidates}
    chosen = result["result"]["event_ids"]
    if len(chosen) != len(set(chosen)) or not set(chosen) <= available:
        raise ValueError("Replay must select distinct existing experience")
    return result
