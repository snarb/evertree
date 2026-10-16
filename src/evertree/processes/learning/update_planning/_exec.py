"""Prepare a bound estimator update; this Program does not apply it."""


async def run(ctx, credit: dict):
    """Request a compatible estimator update plan for resolved learning credit without applying it."""
    result = await ctx.step("learning.prepare", {"credit": credit})
    return {"result": result, "feedback": None}
