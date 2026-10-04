"""Retrieve grouped experience by source/semantic context through protected memory."""


async def run(ctx, query: str, limit: int = 10):
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Retrieval limit must be between 1 and 100")
    result = await ctx.step("memory.retrieve", {"query": query, "limit": limit})
    return {"result": result, "feedback": None}
