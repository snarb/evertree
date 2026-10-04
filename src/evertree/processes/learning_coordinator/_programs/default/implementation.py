"""Forward selected evaluated experience to the protected standard learning pipeline."""


async def run(
    ctx,
    signal: dict,
    target: str,
    context: dict | None = None,
    attribution_weight: float = 1.0,
    ambiguous: bool = False,
):
    result = await ctx.step(
        "learning.learn",
        {
            "signal": signal,
            "target": target,
            "context": context or {},
            "attribution_weight": attribution_weight,
            "ambiguous": ambiguous,
        },
    )
    return {"result": result, "feedback": None}
