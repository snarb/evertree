"""Placeholder for evidence about Program revisions.

The intended target is (Program, revision): whether that revision correctly and
applicably implements its documented process. Evidence will come from evaluation
results, candidate test suites and documentation checks, assessed only for revisions
changed since their last assessment. Until then no Program belief is touched.
"""


async def run(ctx):
    """Assess nothing yet and report that Program assessment is not implemented."""
    return {"result": {"assessed": [], "status": "not_implemented"}, "feedback": None}
