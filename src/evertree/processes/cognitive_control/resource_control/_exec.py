"""Prepare a task-specific budget reassessment; core validates protected limits."""

from evertree.common.bootstrap_schemas import TASK_FRAMING_SCHEMA as SCHEMA
from evertree.common.structured import ask


async def run(ctx, task_state: dict, evidence: dict | None = None):
    return await ask(
        ctx,
        instructions=(
            "Reassess EverTree work using progress, trace, remaining objective and resource usage. "
            "Return the current specification with a finite TOTAL budget including resources already spent, "
            "a justified self-improvement share in [0,100], and reason. Never erase usage or exceed a supplied "
            "user hard limit. Do not extend the result deadline by extending runtime budget."
        ),
        data={"task_state": task_state, "evidence": evidence or {}},
        schema=SCHEMA,
    )
