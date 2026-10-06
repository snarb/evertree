"""Assign a known semantic target without selecting or updating parameter storage."""


async def run(
    ctx,
    target: str,
    signal: dict | None = None,
    ambiguous: bool = False,
    observation_ids: list[str] | None = None,
    context: dict | None = None,
):
    result = await ctx.step(
        "learning.credit",
        {
            "target": target,
            "signal": signal,
            "ambiguous": ambiguous,
            "observation_ids": observation_ids or [],
            "context": context or {},
        },
    )
    return {"result": result, "feedback": None}
