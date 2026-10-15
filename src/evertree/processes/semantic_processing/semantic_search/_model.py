"""Retrieve existing semantic objects without modifying beliefs or facts."""

from evertree.common.semantic_search import search


async def run(ctx, query, kind=None, limit=20):
    return await search(ctx, query, kind, limit)
