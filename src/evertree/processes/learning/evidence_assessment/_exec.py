"""Submit source likelihoods keyed by scope alternatives or binary false/true.

The keys identify the target state; dictionary insertion order has no meaning.
Core retains dependency semantics.
"""

from evertree.core.learning.api import assess_evidence


async def run(
    ctx,
    target: str,
    source_ref,
    likelihoods: dict,
    dependency_root: str | None = None,
):
    """Submit source-backed likelihoods for a declared belief target through Core validation."""
    result = await assess_evidence(
        ctx, target, source_ref, likelihoods, dependency_root=dependency_root
    )
    return {"result": result, "feedback": None}
