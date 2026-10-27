"""Forecast whether a newly framed task will pass independent completion verification."""

from evertree.core.learning.api import estimate, statistics

DESIGN = {
    "applicability": "Any task when it is framed. It assumes past tasks are exchangeable with "
    "the new one; when the request is unlike earlier work, the forecast is only a base rate.",
    "adaptation": "A persistent Brier loss or a forecast TaskFraming finds unhelpful is a reason "
    "to revise this model through the Program lifecycle, for example by conditioning on task kind.",
    "learning": "verified_rate counts verified and failed task outcomes Core observes when a task "
    "stops; cancelled tasks are not outcomes. Updates run through the standard learning pipeline; "
    "a revision is checked on the Brier score of held-out task outcomes.",
}

LEARNING = {
    "targets": {
        "TaskVerified": {
            "form": "probability",
            "result": "verified",
            "subject": "the task being framed",
            "horizon": "until the task stops",
            "check": "Core records succeeded as 1 and failed as 0 when the task stops; "
            "cancelled tasks have no outcome.",
            "metrics": ["brier", "log_loss"],
            "unexpectedness": {"kind": "bernoulli"},
        }
    },
    "estimators": {
        "verified_rate": {
            "kind": "beta_bernoulli",
            "target": "TaskVerified",
            "settings": {"alpha": 1, "beta": 1},
        }
    },
}


async def run(ctx, request: str, context: dict | None = None):
    """Return the probability of verification and how many task outcomes support it."""
    verified = await estimate(ctx, "verified_rate")
    observed = (await statistics(ctx, "verified_rate"))["observed_count"]
    return {"result": {"verified": verified, "observed": observed}, "feedback": None}
