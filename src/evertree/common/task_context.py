"""Task information used to choose objectives and budgets, without runtime bookkeeping."""


def task_context(state: dict) -> dict:
    """Select task meaning, progress and resource evidence for a Program's model input."""
    fields = (
        "progress",
        "plan",
        "unresolved_questions",
        "waiting_for",
        "hard_limits",
        "deadline",
        "spent",
        "self_improvement_budget",
        "self_improvement_spent",
        "current_step",
    )
    result = {key: state[key] for key in fields if key in state and state[key] is not None}
    if state.get("specification"):
        result["specification"] = {
            key: state["specification"][key]
            for key in ("objective", "success_criteria", "constraints", "preferences")
            if key in state["specification"]
        }
    if state.get("execution_budget"):
        budget = state["execution_budget"]
        result["execution_budget"] = budget.get("resources", budget)
    if state.get("inputs"):
        result["inputs"] = [
            {key: item[key] for key in ("role", "content") if key in item}
            for item in state["inputs"]
        ]
    return result


def fit_total_budget(proposed: dict, spent: dict | None) -> dict:
    """Read a total below what is already spent as the remaining allowance on top of it.

    Budgets are totals including spent time; a smaller total cannot be meant literally
    and would otherwise fail the Task instead of continuing it.
    """
    spent = spent or {}
    return {
        resource: value + spent[resource] if value < spent.get(resource, 0) else value
        for resource, value in proposed.items()
    }


def budget_evidence(evidence: dict) -> dict:
    """Retain budget-review evidence while projecting trace entries to operations and outputs."""
    result = dict(evidence)
    if "trace" in result:
        result["trace"] = [
            {key: event[key] for key in ("operator", "output") if key in event}
            for event in result["trace"]
        ]
    return result
