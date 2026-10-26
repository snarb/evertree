"""Retrieve grouped experience by source/semantic context through protected memory."""

from evertree.core.memory.api import retrieve


async def run(ctx, query: str, limit: int = 10):
    """Retrieve a bounded set of retained experience groups through Core memory search."""
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Retrieval limit must be between 1 and 100")
    result = await retrieve(ctx, query, limit=limit)
    return {"result": result, "feedback": None}
