"""Run evidence assessment for graph elements, then for Programs, one after the other."""

from evertree.core.runtime.api import call_program


async def run(ctx, experience_refs: list | None = None):
    """Assess newly integrated experience; each child awaits the previous one."""
    graph = await call_program(
        ctx, "graph_evidence_assessment", {"experience_refs": experience_refs or []}
    )
    programs = await call_program(ctx, "program_evidence_assessment", {})
    return {"result": {"graph": graph.result, "programs": programs.result}, "feedback": None}
