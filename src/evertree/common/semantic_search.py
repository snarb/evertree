"""Search authoritative graph cards through the two derived indexes."""

import asyncio


async def search(ctx, query, kind=None, limit=20):
    """Try exact graph lookup, then fuse lexical and vector ranks while reporting failed channels."""
    if kind is not None:
        kind = kind.strip().casefold()
    exact = await ctx.step("semantic.lookup", {"query": query, "kind": kind, "limit": limit})
    if exact is not None:
        return {"result": exact, "feedback": None}

    revision = await ctx.step("semantic.revision", {})

    async def channel(name):
        try:
            ids = await ctx.step(
                "semantic." + name, {"query": query, "kind": kind, "revision": revision}
            )
            return list(dict.fromkeys(ids)), None
        except Exception as exc:  # noqa: BLE001 -- preserve the other index and report partial search
            return [], {"channel": name, "error": str(exc)}

    (lexical, lexical_error), (vector, vector_error) = await asyncio.gather(
        channel("bm25"), channel("vector")
    )
    scores = {}
    channels = {}
    for name, ids in (("bm25", lexical), ("vector", vector)):
        for rank, identity in enumerate(ids, 1):
            # Rank fusion rewards agreement without comparing incompatible index scores.
            scores[identity] = scores.get(identity, 0) + 1 / (60 + rank)
            channels.setdefault(identity, []).append(name)
    ranked = sorted(scores, key=lambda identity: (-scores[identity], identity))
    errors = [error for error in (lexical_error, vector_error) if error is not None]
    result = await ctx.step(
        "semantic.results",
        {
            "query": query,
            "kind": kind,
            "revision": revision,
            "items": [{"id": identity, "channels": channels[identity]} for identity in ranked],
            "errors": errors,
            "limit": limit,
        },
    )
    return {"result": result, "feedback": None}
