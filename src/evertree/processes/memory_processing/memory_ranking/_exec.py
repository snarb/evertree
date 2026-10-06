"""Rerank actual retrieved candidates for a specific objective."""

from evertree.common.structured import ask

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "relevance": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                },
                "required": ["id", "relevance", "reason"],
            },
        }
    },
    "required": ["ranked"],
}


async def run(ctx, objective: str, candidates: list[dict]):
    result = await ask(
        ctx,
        instructions=(
            "Rank only the supplied memory candidate groups by usefulness for the objective. "
            "Preserve group IDs; do not split related evidence into independent confirmations. "
            "Omit irrelevant candidates and explain relevance. A retrieval score does not establish truth."
        ),
        data={"objective": objective, "candidates": candidates},
        schema=SCHEMA,
    )
    available = {str(candidate["id"]) for candidate in candidates}
    chosen = [item["id"] for item in result["result"]["ranked"]]
    if len(chosen) != len(set(chosen)) or not set(chosen) <= available:
        raise ValueError("Ranking must refer to distinct supplied candidate groups")
    result["result"]["ranked"].sort(key=lambda item: item["relevance"], reverse=True)
    return result
