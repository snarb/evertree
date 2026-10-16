"""Match retained forecasts, evaluate outcomes and route unmatched experience."""

from evertree.core.evaluation.api import match, review
from evertree.core.learning.api import call_credit_assignment


async def run(
    ctx,
    observations: list[int],
    context: dict,
    metrics: list[str],
    selected_targets: list[str | int] | None = None,
):
    """Evaluate retained observations and route unmatched prediction cases to credit assignment and review."""
    batch = await match(
        ctx, observations, context=context, metrics=metrics, selected_targets=selected_targets
    )
    credits = []
    for case in batch["unmatched"]:
        if case["reason"] == "missing_prediction":
            credit = await call_credit_assignment(
                ctx,
                target=case["target"],
                observation_ids=case["observation_ids"],
                context={**case["context"], "unmatched_parts": case["parts"]},
            )
            credits.append(credit)
    if batch["unmatched"]:
        await review(ctx, cases=batch["unmatched"], credits=credits)
    return {"result": batch["results"], "feedback": None}
