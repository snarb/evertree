"""Submit explicit source-likelihood evidence; core retains dependency semantics."""


async def run(
    ctx,
    target: str,
    source_ref,
    likelihoods: dict,
    backed: bool = False,
    dependency_root: str | None = None,
):
    result = await ctx.step(
        "evidence.assess",
        {
            "target": target,
            "source_ref": source_ref,
            "likelihoods": likelihoods,
            "backed": backed,
            "dependency_root": dependency_root,
        },
    )
    return {"result": result, "feedback": None}
