"""Search authoritative graph cards through two batched derived indexes."""

import asyncio

from evertree.core.semantics import api as semantics
from evertree.core.semantics.searching import search_kinds, search_limit, search_queries


async def search(ctx, queries, kinds=None, limit=10):
    """Resolve exact identities, then fuse each query's lexical and vector candidates."""
    queries = search_queries(queries)
    search_limit(limit)
    kinds = search_kinds(kinds)
    exact = await semantics.lookup(ctx, queries, kinds=kinds, limit=limit)
    if exact is not None:
        return {"result": exact, "feedback": None}

    async def channel(name, rank):
        try:
            rows = await rank(ctx, queries, kinds=kinds)
            if len(rows) != len(queries):
                raise ValueError("Search channel response count mismatch")
            return rows
        except Exception as exc:  # noqa: BLE001 -- preserve candidates from the other index
            return [{"ids": [], "error": str(exc)} for _ in queries]

    lexical, vector = await asyncio.gather(
        channel("bm25", semantics.bm25), channel("vector", semantics.vector)
    )
    rankings = []
    for left, right in zip(lexical, vector, strict=True):
        scores, channels, errors = {}, {}, []
        for name, row in (("bm25", left), ("vector", right)):
            if row.get("error"):
                errors.append({"channel": name, "error": row["error"]})
            for rank, identity in enumerate(dict.fromkeys(row["ids"]), 1):
                # Index scores are incomparable; agreement between ranks is useful.
                scores[identity] = scores.get(identity, 0) + 1 / (60 + rank)
                channels.setdefault(identity, []).append(name)
        ranked = sorted(scores, key=lambda identity: (-scores[identity], identity))
        rankings.append(
            {
                "items": [
                    {"id": identity, "channels": channels[identity], "score": scores[identity]}
                    for identity in ranked
                ],
                "errors": errors,
            }
        )
    result = await semantics.results(ctx, queries, kinds=kinds, rankings=rankings, limit=limit)
    return {"result": result, "feedback": None}
