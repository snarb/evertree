"""Propose a compact semantic trace; protected memory decides retention."""

from evertree.common.structured import ask

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "keep_event_ids": {"type": "array", "items": {"type": "integer"}},
        "lost_details": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "keep_event_ids", "lost_details"],
}


async def run(ctx, events: list[dict], observation_counts: dict | None = None):
    result = await ask(
        ctx,
        instructions=(
            "Propose a faithful summary and important event IDs to retain. Preserve requirements, decisions, "
            "outcomes, errors, provenance and dependencies. Identify lost detail. Never delete material required for "
            "workflow recovery, source verification or learning; the protected memory store makes retention decisions. "
            "Do not invent observations or change their counts."
        ),
        data={"events": events, "observation_counts": observation_counts or {}},
        schema=SCHEMA,
    )
    available = {event["id"] for event in events}
    if not set(result["result"]["keep_event_ids"]) <= available:
        raise ValueError("Compaction refers to an event outside the supplied trace")
    result["result"]["observation_counts"] = dict(observation_counts or {})
    result["result"]["source_event_ids"] = [event["id"] for event in events]
    return result
