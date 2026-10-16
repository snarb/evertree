"""Retrieve existing semantic objects without modifying beliefs or facts."""

from evertree.common.semantic_search import search


async def run(ctx, query, kind=None, limit=20):
    """Find semantic objects by exact lookup, then fused lexical and vector retrieval when needed."""
    return await search(ctx, query, kind, limit)
