"""Prepare a bound estimator update; this Program does not apply it."""

from evertree.core.learning.api import prepare


async def run(ctx, credit: dict):
    """Request a compatible estimator update plan for resolved learning credit without applying it."""
    result = await prepare(ctx, credit)
    return {"result": result, "feedback": None}
