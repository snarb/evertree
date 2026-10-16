"""Search authoritative graph cards through the two derived indexes."""

import asyncio

from evertree.core.semantics import api as semantics


async def search(ctx, query, kind=None, limit=20):
    """Try exact graph lookup, then fuse lexical and vector ranks while reporting failed channels."""
    if kind is not None:
        kind = kind.strip().casefold()
    exact = await semantics.lookup(ctx, query, kind=kind, limit=limit)
    if exact is not None:
        return {"result": exact, "feedback": None}

    revision = await semantics.revision(ctx)

    async def channel(name, rank):
        try:
            ids = await rank(ctx, query, kind=kind, revision=revision)
            return list(dict.fromkeys(ids)), None
        except Exception as exc:  # noqa: BLE001 -- preserve the other index and report partial search
            return [], {"channel": name, "error": str(exc)}

    (lexical, lexical_error), (vector, vector_error) = await asyncio.gather(
        channel("bm25", semantics.bm25), channel("vector", semantics.vector)
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
    result = await semantics.results(
        ctx,
        query,
        kind=kind,
        revision=revision,
        items=[{"id": identity, "channels": channels[identity]} for identity in ranked],
        errors=errors,
        limit=limit,
    )
    return {"result": result, "feedback": None}
