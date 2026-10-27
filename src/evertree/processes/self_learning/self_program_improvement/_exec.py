"""Improve a target Program through candidates, protected evaluation and an EvaluationChoice."""

from evertree.common.structured import ask
from evertree.core.programs.api import (
    choose_candidate,
    compare_candidates,
    create_candidate,
    develop_candidate,
    evaluate_candidate,
    list_programs,
)

DESIGN = {
    "applicability": "A named Program has an improvement objective and its slot has a protected "
    "holdout; without a holdout every candidate stays undecided and is kept for later evidence.",
    "adaptation": "Evaluation outcomes decide: verified candidates compete on the slot's target "
    "metric, failed ones are rejected, unresolved ones are kept. Changes to this Program itself "
    "go through consciousness and the stricter meta acceptance.",
    "learning": "Nothing is learned inside a run; the planner model proposes claims from the "
    "objective and retained failures, and Core's protected Evaluation checks each candidate.",
    "exploration": "Up to max_candidates distinct implementations of the objective are tried per "
    "run within the task budget; a failed attempt only archives its own branch.",
}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidates": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "claim": {"type": "string"},
                    "candidate_name": {"type": "string"},
                    "instruction": {"type": "string"},
                },
                "required": ["claim", "candidate_name", "instruction"],
            },
        }
    },
    "required": ["candidates"],
}
INSTRUCTIONS = (
    "Plan candidate changes that could achieve the objective for the target Program. Return at "
    "most max_candidates genuinely different implementations; one is enough when the fix is clear. "
    "Each claim states what changes and which observable behavior should improve. "
    "candidate_name has one to three words. instruction tells a coding agent what to implement "
    "at the Program's git_path, without assuming hidden evaluation cases."
)

# Decision words by whether the target holds its slot: a branch of the active Program
# merges, a new or alternative Program activates.
DECISIONS = {
    True: {
        "activate": "merge_branch",
        "keep": "continue_branch",
        "reject": "reject_branch",
        "archive": "archive_branch",
    },
    False: {
        "activate": "activate_program",
        "keep": "keep_alternatives",
        "reject": "reject_program",
        "archive": "archive_program",
    },
}


async def run(ctx, program: int, objective: str, max_candidates: int = 2):
    """Develop, evaluate and decide candidates for one Program; return every decision made."""
    target = next((item for item in await list_programs(ctx) if item["id"] == program), None)
    if target is None:
        raise ValueError(f"Unknown Program {program}")
    plan = await ask(
        ctx,
        instructions=INSTRUCTIONS,
        data={"objective": objective, "program": target, "max_candidates": max_candidates},
        schema=SCHEMA,
    )
    words = DECISIONS[target["lifecycle_status"] in (None, "active")]
    evaluated, outcomes = [], []
    proposals = plan["result"]["candidates"][:max_candidates]
    # Open every branch before any evaluation: a holdout an evaluation has shown
    # is spent for candidates the slot opens afterwards.
    candidates = [
        await create_candidate(
            ctx, program, claim=proposal["claim"], candidate_name=proposal["candidate_name"]
        )
        for proposal in proposals
    ]
    for proposal, candidate in zip(proposals, candidates, strict=True):
        record = {"candidate": candidate["id"], "claim": proposal["claim"]}
        try:
            await develop_candidate(ctx, candidate["id"], proposal["instruction"])
            evaluation = await evaluate_candidate(ctx, candidate["id"])
        except (ValueError, PermissionError, RuntimeError) as error:
            record["error"] = str(error)
            evaluation = None
        record["verification"] = (evaluation or {}).get("verification", {"status": "unresolved"})
        outcomes.append(record)
        if evaluation and evaluation.get("status") == "evaluated":
            evaluated.append(candidate["id"])
    ranking = (await compare_candidates(ctx, evaluated))["ranking"] if evaluated else []
    winner = next(
        (row["candidate"] for row in ranking if row["verification"]["status"] == "verified"), None
    )
    decisions = []
    # Decide the winner first: siblings stay open until then, and Core refuses to
    # activate a candidate while a better verified sibling is undecided.
    for record in sorted(outcomes, key=lambda item: item["candidate"] != winner):
        status = record["verification"]["status"]
        if record["candidate"] == winner:
            decision, reason = words["activate"], "Best verified candidate on the protected holdout"
        elif winner is not None:
            decision = words["archive"]
            reason = f"Candidate {winner} was verified and chosen instead"
        elif status == "failed":
            decision = words["reject"]
            reason = "Protected acceptance failed: " + "; ".join(record["verification"]["reasons"])
        else:
            decision, reason = words["keep"], "Evidence is insufficient for a decision"
        await choose_candidate(ctx, record["candidate"], decision, reason=reason)
        decisions.append({**record, "decision": decision, "reason": reason})
        if decision == "activate_program":
            # The target now holds its slot, so its remaining candidates are branches.
            words = DECISIONS[True]
    return {
        "result": {"program": program, "winner": winner, "decisions": decisions},
        "feedback": None,
    }
