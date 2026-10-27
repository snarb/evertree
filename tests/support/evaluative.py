"""Seeding evaluative experience through Core boundaries, and reading what it produced."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from evertree.core.memory.types import TraceOutputRef
from evertree.core.predictions import comparison_key
from evertree.core.provider import LLMEvent
from evertree.debug_evaluative_control import seed_omission, seed_task, seed_unexpectedness

FOREVER = ("2000-01-01T00:00:00+00:00", "2100-01-01T00:00:00+00:00")
TARGET = "TaskVerified"


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.isoformat()


def window(start: datetime, end: datetime) -> tuple[str, str]:
    return (iso(start), iso(end))


def around(moment: datetime, *, days: float) -> tuple[str, str]:
    return window(moment - timedelta(days=days), moment)


def process_id(agent, name: str) -> str:
    return str(agent.graph.find(name).id)


def checked_forecast(
    agent,
    process: str,
    prediction,
    outcome,
    *,
    calibration: dict | None,
    metrics: tuple[str, ...] = ("squared_error",),
    target: str = TARGET,
    subject: str | None = None,
) -> dict:
    """Save a forecast before its outcome, observe the outcome and score it through Core."""
    subject = subject or uuid4().hex
    run = agent.memory.start_run("EvaluativeForecaster", "0" * 40, {})
    event = agent.memory.record(run, "forecast", output={"value": prediction})
    agent.memory.finish_run(run)
    context = {"process_id": process, "subject": subject, "episode": subject}
    agent.save_prediction(
        target,
        TraceOutputRef(event.id, ("value",)),
        context,
        calibration=calibration,
        comparison_key=comparison_key(target, calibration),
    )
    observation = agent.observe(
        {"value": outcome},
        source_id="outcome:" + subject,
        context=context,
        projections={target: {"value": ["value"]}},
    )
    (result,) = agent.prediction_evaluator().evaluate([observation.event_ref], context, metrics)[
        "results"
    ]
    return result


# Past experience is seeded exactly as the live scenarios seed it.
seeded_unexpectedness = seed_unexpectedness
seeded_omission = seed_omission
finished_task = seed_task


def tool_calls(*calls) -> list[LLMEvent]:
    """Scripted conscious tool calls, in order, as provider events."""
    return [
        LLMEvent("tool_call", {"name": name, "arguments": arguments}) for name, arguments in calls
    ]


def tool_results(agent, name: str) -> list:
    """Results the conscious agent received from a tool, read back from the retained trace."""
    found = []
    for event in agent.memory.events:
        output = event.output
        if event.operator != "provider_event" or not hasattr(output, "get"):
            continue
        data = output.get("data") or {}
        if output.get("kind") == "tool_result" and data.get("name") == name:
            found.append(data)
    return found


def _path(value, path: str):
    for key in path.split("."):
        value = value[key] if isinstance(value, dict) else None
    return value


def _compare(actual, check: dict) -> str | None:
    if "equals" in check and actual != check["equals"]:
        return f"expected {check['equals']!r}, found {actual!r}"
    if "between" in check:
        low, high = check["between"]
        if not isinstance(actual, (int, float)) or not low <= actual <= high:
            return f"expected a value in [{low}, {high}], found {actual!r}"
    if "present" in check and (actual is not None) != check["present"]:
        return f"expected presence {check['present']}, found {actual!r}"
    return None


def _selects(call: dict, process: str | None) -> bool:
    if process is None:
        return True
    selected = (call.get("arguments") or {}).get("processes") or []
    return any(str(item).lower() == process.lower() for item in selected)


def failures(state: dict, expect: list[dict]) -> list[dict]:
    """Return every structural expectation of a live evaluative scenario that failed."""
    problems = []
    answer = (state["task"] or {}).get("answer", "") or ""
    for check in expect:
        kind, problem = check["check"], None
        if kind == "status":
            problem = _compare((state["task"] or {}).get("status"), check)
        elif kind == "answer_contains_any":
            if not any(value.lower() in answer.lower() for value in check["values"]):
                problem = f"answer mentions none of {check['values']}"
        elif kind == "answer_contains_count":
            found = [value for value in check["values"] if value.lower() in answer.lower()]
            if len(found) < check["min"]:
                problem = f"answer mentions only {found}"
        elif kind == "tool_called":
            calls = [
                call
                for call in state["tool_calls"]
                if call["name"] in check.get("names", [check.get("name")])
                and call.get("status") == "completed"
                and _selects(call, check.get("processes_include"))
            ]
            if not calls:
                problem = f"no completed {check.get('names', check.get('name'))} call for {check.get('processes_include')}"
            elif "result_path" in check:
                outcomes = [
                    _compare(_path(call["result"], check["result_path"]), check) for call in calls
                ]
                if all(outcomes):
                    problem = outcomes[-1]
        elif kind == "outcome_unexpectedness":
            results = [
                result
                for result in state["outcome_evaluations"]
                if any(
                    s["channel"] == "prediction_unexpectedness" for s in result["metric_samples"]
                )
            ]
            # A resumed Task is reframed and forecast again; each forecast is checked.
            if not check.get("min", 0) <= len(results) <= check.get("max", len(results)):
                problem = f"{len(results)} calibrated outcome checks outside {check}"
            for result in results:
                for key in ("method", "kind"):
                    if key in check and result["basis"].get(key) != check[key]:
                        problem = f"basis {key} is {result['basis'].get(key)!r}"
        elif kind == "feedback_on_task":
            task = state["task_state"]
            matching = [
                result
                for result in state["feedback"]
                if result["evaluated_subject"] == task["id"]
                and result["process_id"] == task["process_id"]
                and result["metric_samples"][0]["value"] == check["value"]
            ]
            if not matching:
                problem = "no supervisor_feedback_signal result on the task's process"
        elif kind == "task_field":
            problem = _compare(_path(state["task_state"], check["path"]), check)
        elif kind == "stats":
            key = json.dumps(check, sort_keys=True)
            problem = _compare(_path(state["stats"][key], check["path"]), check)
        elif kind == "program_run":
            runs = [run for run in state["program_runs"] if run["program"] == check["program"]]
            fitting = [
                run
                for run in runs
                if check["context_has"] in json.dumps(run["arguments"])
                and check["result_has"] in json.dumps(run["result"])
            ]
            if not fitting:
                problem = f"{len(runs)} {check['program']} runs, none with {check['context_has']}"
        else:
            problem = "unknown check"
        if problem:
            problems.append({"check": check, "problem": problem})
    return problems
