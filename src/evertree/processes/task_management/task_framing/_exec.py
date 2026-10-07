"""Frame the supplied request and choose a finite task-specific budget."""

from evertree.common.bootstrap_schemas import TASK_FRAMING_SCHEMA as SCHEMA
from evertree.common.structured import ask
from evertree.core.cognition.tasks import ExecutionBudget, TaskSpecification


async def run(ctx, request: str, context: dict | None = None):
    output = await ask(
        ctx,
        instructions=(
            "You are EverTree TaskFraming. Preserve every explicit requirement, constraint, and preference. "
            "Distinguish user requirements from assumptions. Choose a finite execution budget and an optional "
            "self-improvement share for THIS task according to complexity, urgency, expected value and supplied hard limits. "
            "There is no universal 30-minute budget or fixed self-improvement percentage. The budget includes all task work "
            "and is reassessed before continuation; user waiting time is excluded. A zero self-improvement share is valid. "
            "Choose conservative explicit success criteria that can be checked. Return the requested JSON object."
        ),
        data={"request": request, "context": context or {}},
        schema=SCHEMA,
    )
    result = output["result"]
    TaskSpecification(
        result["objective"],
        result["success_criteria"],
        result["constraints"],
        result["preferences"],
    )
    ExecutionBudget(result["execution_budget"], result["budget_reason"])
    return output
