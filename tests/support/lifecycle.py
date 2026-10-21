"""Lifecycle scenario support: structural checks and the native mirror's scripted provider.

Checks read only the session state (graph Programs, branches, receipts, choices,
bindings, probes). Live model work varies, so checks bound counts and compare
metrics with baselines instead of fixing exact identities or values.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from evertree.core.provider import LLMEvent, ProviderError


def programs(state, reference):
    """Program ids named by a scenario key, or alternative:<key> for its alternatives."""
    if reference.startswith("alternative:"):
        target = state["names"][reference.removeprefix("alternative:")]
        return [
            int(identity)
            for identity, program in state["programs"].items()
            if program.get("alternative_to") == target
        ]
    return [state["names"][reference]]


def branches(state, reference):
    """Scenario candidates of the referenced Programs; seed installations are not part of it."""
    ids = set(programs(state, reference))
    return [
        branch
        for branch in state["branches"].values()
        if branch["program_id"] in ids and branch["id"] not in state["seed_candidates"]
    ]


def _within(value, bounds):
    low, high = bounds
    return low <= value and (high is None or value <= high)


def _merged_receipts(state, reference):
    merged = {
        choice["candidate_id"]
        for choice in state["choices"]
        if choice["decision"] in {"merge_branch", "activate_program"}
    }
    return [
        state["evaluations"][branch["id"]]
        for branch in branches(state, reference)
        if branch["id"] in merged and branch["id"] in state["evaluations"]
    ]


def check(state, expectation) -> str | None:
    """Return a failure description, or None when the state satisfies the expectation."""
    kind = expectation["kind"]
    if kind == "slot":
        holder = programs(state, expectation["program"])
        program = state["programs"][str(holder[0])] if holder else None
        if program is None:
            return f"No Program for {expectation['program']}"
        process = state["processes"][str(program["process"])]
        active = process.get("active_" + program["role"])
        if active not in holder:
            return f"Slot holds {active}, expected one of {holder}"
    elif kind == "status":
        statuses = [
            state["programs"][str(identity)].get("lifecycle_status", "active")
            for identity in programs(state, expectation["program"])
        ]
        if expectation["lifecycle_status"] not in statuses:
            return f"Lifecycle statuses are {statuses}"
    elif kind == "revision":
        key = expectation["program"]
        current = state["programs"][str(state["names"][key])].get("revision")
        changed = current != state["setup_revisions"][key]
        if changed != expectation["changed"]:
            return f"Revision changed={changed}, expected {expectation['changed']}"
    elif kind == "choices":
        ids = {branch["id"] for branch in branches(state, expectation["program"])}
        count = sum(
            choice["candidate_id"] in ids and choice["decision"] in expectation["decisions"]
            for choice in state["choices"]
        )
        if not _within(count, expectation["count"]):
            return f"{count} choices among {expectation['decisions']}"
    elif kind == "branches":
        count = sum(
            branch["status"] in expectation["statuses"]
            for branch in branches(state, expectation["program"])
        )
        if not _within(count, expectation["count"]):
            return f"{count} branches with status in {expectation['statuses']}"
    elif kind == "evaluations":
        receipts = [
            state["evaluations"][branch["id"]]
            for branch in branches(state, expectation["program"])
            if branch["id"] in state["evaluations"]
        ]
        if not _within(len(receipts), expectation["count"]):
            return f"{len(receipts)} evaluated candidates"
        datasets = {receipt["report"]["dataset_revision"] for receipt in receipts}
        if expectation.get("same_dataset") and len(datasets) > 1:
            return f"Candidates met different holdouts: {sorted(datasets)}"
    elif kind == "refreshed":
        count = sum(
            branch.get("refreshed_from") is not None
            for branch in branches(state, expectation["program"])
        )
        if not _within(count, expectation["count"]):
            return f"{count} refreshed candidates"
    elif kind == "improved":
        receipts = _merged_receipts(state, expectation["program"])
        if not receipts:
            return "No activated candidate has an evaluation receipt"
        report = receipts[-1]["report"]
        metric, sign = expectation["metric"], 1 if expectation["direction"] == "maximize" else -1
        candidate = report["metrics"].get(metric)
        baseline = (report["baseline_metrics"] or {}).get(metric)
        if candidate is None or baseline is None or sign * (candidate - baseline) <= 0:
            return f"{metric}: candidate {candidate} does not improve baseline {baseline}"
    elif kind == "probe":
        probe = next(
            (item for item in state["probes"] if item["arguments"] == expectation["arguments"]),
            None,
        )
        if probe is None or "error" in probe:
            return f"Probe failed: {probe}"
        result, expected = probe["result"], expectation.get("result")
        if "range" in expectation:
            low, high = expectation["range"]
            if not isinstance(result, (int, float)) or not low <= result <= high:
                return f"Probe returned {result}, expected within {expectation['range']}"
        elif isinstance(expected, float) and isinstance(result, (int, float)):
            if not math.isclose(result, expected, abs_tol=expectation.get("tolerance", 1e-9)):
                return f"Probe returned {result}, expected {expected}"
        elif expectation.get("best_choice") is not None:
            choices = result["choices"]
            best = max(choices, key=lambda item: item[1])[0]
            if best != expectation["best_choice"]:
                return f"Most probable choice is {best}"
        elif result != expected:
            return f"Probe returned {result}, expected {expected}"
    elif kind == "derived":
        key = expectation["program"]
        program = state["programs"][str(state["names"][key])]
        binding = state["bindings"][f"slot:{program['process']}:{program['role']}"]
        derived = sum(
            case.startswith("experience:")
            for case in state["datasets"][binding["dataset_revision"]]
        )
        if not _within(derived, expectation["count"]):
            return f"{derived} experience cases in the bound holdout"
    elif kind == "sealed":
        if not _within(len(state["sealed"]), expectation["count"]):
            return f"{len(state['sealed'])} sealed outcomes"
    elif kind == "runs":
        ids = set(programs(state, expectation["program"]))
        count = sum(
            run["program"] in ids and run["status"] == expectation["status"]
            for run in state["runs"]
        )
        if not _within(count, expectation["count"]):
            return f"{count} runs with status {expectation['status']}"
    elif kind == "verification":
        count = sum(
            any(
                expectation["match"] in reason
                for reason in state["evaluations"][branch["id"]]["verification"]["reasons"]
            )
            for branch in branches(state, expectation["program"])
            if branch["id"] in state["evaluations"]
        )
        if not _within(count, expectation["count"]):
            return f"{count} receipts give the reason {expectation['match']!r}"
    elif kind == "hidden":
        sealed = set(state["sealed"])
        shown = {
            event["id"]
            for step in state["steps"]
            if step["op"] == "recall"
            for group in step.get("result") or ()
            for event in group["events"]
        }
        if shown & sealed:
            return f"Recall returned sealed outcomes {sorted(shown & sealed)}"
        if not any(step["op"] == "recall" for step in state["steps"]) and state["task"] is None:
            return "No recall step ran"
    elif kind == "step_error":
        errors = [
            step.get("error", "")
            for step in state["steps"]
            if step["op"] == expectation["op"] and expectation["match"] in step.get("error", "")
        ]
        if not errors:
            return f"No {expectation['op']} step failed with {expectation['match']!r}"
    elif kind == "task":
        if state["task"] is None or state["task"]["status"] not in expectation["statuses"]:
            return f"Task ended as {state['task']}"
    else:
        raise ValueError(f"Unknown lifecycle check: {kind}")
    return None


def failures(state, expectations, mode: str) -> list[str]:
    """Evaluate the expectations that apply to this mode (live or mirror)."""
    return [
        f"{expectation}: {failure}"
        for expectation in expectations
        if expectation.get("mode", mode) == mode
        and (failure := check(state, expectation)) is not None
    ]


class MirrorProvider:
    """Play the coding agent with each scenario's fixed files and the planner with fixed answers.

    files maps a candidate id, files_by_name a candidate name, to {path: text};
    "$program" stands for the Program's git_path. Model requests with a schema
    pop answers in order. No conscious agent runs in the mirror.
    """

    name = "lifecycle-mirror"

    def __init__(self):
        self.files: dict[str, dict] = {}
        self.files_by_name: dict[str, dict] = {}
        self.answers: list = []
        self.requests = []

    async def run(self, request_id, request, *, tool_handler=None, approval_handler=None):
        self.requests.append(request)
        yield LLMEvent("session", {"provider": self.name, "id": request_id})
        if request.native_coding:
            payload = json.loads(request.prompt)
            candidate = payload["candidate"]
            name = candidate["git_ref"].rsplit("/", 1)[-1]
            files = self.files.get(candidate["id"]) or self.files_by_name.get(name)
            if files is None:
                raise ProviderError(f"No scripted files for candidate {name}")
            for path, text in files.items():
                path = payload["program"]["properties"]["git_path"] if path == "$program" else path
                target = Path(request.workspace) / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            yield LLMEvent(
                "completed", {"text": "Implemented the scripted candidate", "parsed": None}
            )
            return
        if not self.answers:
            raise ProviderError("No scripted model answer remains")
        answer = self.answers.pop(0)
        yield LLMEvent("completed", {"text": json.dumps(answer), "parsed": answer})

    async def cancel(self, request_id):
        pass

    async def doctor(self):
        return {"provider": self.name, "available": True, "offline": True}

    async def close(self):
        pass
