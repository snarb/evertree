"""Forward selected evaluated experience to the protected standard learning pipeline."""

from evertree.core.learning.api import learn


async def run(
    ctx,
    signal: dict,
    target: str,
    context: dict | None = None,
    attribution_weight: float = 1.0,
    ambiguous: bool = False,
):
    """Submit a learning signal through Core credit assignment, planning and transactional update."""
    result = await learn(
        ctx,
        signal,
        target,
        context=context,
        attribution_weight=attribution_weight,
        ambiguous=ambiguous,
    )
    return {"result": result, "feedback": None}
