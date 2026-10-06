"""Match retained forecasts, evaluate outcomes and route unmatched experience."""


async def run(
    ctx,
    observations: list[int],
    context: dict,
    metrics: list[str],
    selected_targets: list[str | int] | None = None,
):
    batch = await ctx.step(
        "evaluation.match",
        {
            "observations": observations,
            "context": context,
            "metrics": metrics,
            "selected_targets": selected_targets or [],
        },
    )
    credits = []
    for case in batch["unmatched"]:
        if case["reason"] == "missing_prediction":
            credit = await ctx.call(
                "CreditAssignment",
                {
                    "target": case["target"],
                    "observation_ids": case["observation_ids"],
                    "context": {**case["context"], "unmatched_parts": case["parts"]},
                },
            )
            credits.append(credit.result)
    if batch["unmatched"]:
        await ctx.step("evaluation.review", {"cases": batch["unmatched"], "credits": credits})
    return {"result": batch["results"], "feedback": None}
