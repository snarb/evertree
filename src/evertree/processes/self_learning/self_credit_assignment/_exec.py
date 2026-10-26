"""Assign a known semantic target without selecting or updating parameter storage."""

from evertree.core.learning.api import credit


async def run(
    ctx,
    target: str,
    signal: dict | None = None,
    ambiguous: bool = False,
    observation_ids: list[str] | None = None,
    context: dict | None = None,
):
    """Request Core credit assignment, retaining unresolved observations when no signal is available."""
    result = await credit(
        ctx,
        target,
        signal=signal,
        ambiguous=ambiguous,
        observation_ids=observation_ids,
        context=context,
    )
    return {"result": result, "feedback": None}
