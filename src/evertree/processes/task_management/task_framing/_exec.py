"""Frame the supplied request and choose a finite task-specific budget."""

from evertree.common.bootstrap_schemas import TASK_FRAMING_SCHEMA as SCHEMA
from evertree.common.structured import ask
from evertree.core.cognition.steps import ConsciousStepSpec
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
            "Choose initial_step with a task-specific local_goal, expected_result and finite active_time_minutes "
            "within the task budget. The first step should produce one meaningful increment: it may plan, inspect, "
            "test a hypothesis, or complete a simple task. Do not require a separate planning iteration for simple tasks. "
            "A step may include related tool calls, but should return control when its local result is achieved or "
            "new evidence requires a substantial decision. "
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
    initial_step = ConsciousStepSpec.model_validate(result["initial_step"])
    if initial_step.active_time_minutes > result["execution_budget"]["active_time_minutes"]:
        raise ValueError("Initial step budget cannot exceed the task execution budget")
    result["initial_step"] = initial_step.model_dump(mode="json")
    return output
