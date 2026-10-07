"""Assemble exact task state and caller-selected source material."""

from evertree.core.cognition.attention import prepare_context
from evertree.core.cognition.tasks import TaskState


def run(
    task_state: dict,
    incoming,
    episode_id: str | None = None,
    messages: list[dict] | None = None,
    source_ids: list[str] | None = None,
):
    context = prepare_context(
        TaskState.from_dict(task_state),
        episode_id,
        incoming,
        messages=messages or (),
        source_ids=source_ids or (),
    )
    return {"result": context.to_dict(), "feedback": None}
