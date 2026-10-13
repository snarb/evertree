from __future__ import annotations

from copy import deepcopy

import pytest

from evertree.processes.learning.reflection._exec import run as reflect
from evertree.processes.memory_processing.experience_consolidation._exec import run as consolidate


class AnalyticalContext:
    def __init__(self, output):
        self.output = output
        self.calls = []

    async def step(self, method, payload):
        self.calls.append(method)
        assert method == "agent.run"
        return {"parsed": deepcopy(self.output)}


@pytest.mark.parametrize(
    ("program", "proposal"),
    [
        (reflect, {"incidents": [], "hypotheses": [], "proposed_changes": []}),
        (consolidate, {"claims": [], "reusable_principles": []}),
    ],
)
async def test_analytical_programs_keep_partial_insights_and_original_trace_sources(
    program, proposal
):
    reference = {"event_ref": 5, "output_path": ["samples", 1]}
    context = AnalyticalContext(
        {
            **proposal,
            "analysis": {
                "text": "A and B support the hypothesis, but C is still unexplained.",
                "source_refs": [reference],
            },
            "findings": [
                {
                    "text": "The explanation may require a locale condition. Keep this; it changes the next test.",
                    "kind": "claim",
                    "source_refs": [reference],
                }
            ],
        }
    )
    result = await program(context, {"experience_refs": [{"event_ref": 5, "output_path": []}]})
    assert result["result"]["analysis"]["source_refs"] == [reference]
    assert "Keep this" in result["result"]["findings"][0]["text"]
    assert context.calls == ["agent.run"]


async def test_reflection_rejects_invented_source_instead_of_making_it_memory_evidence():
    context = AnalyticalContext(
        {
            "analysis": {
                "text": "The parser is wrong.",
                "source_refs": [{"event_ref": 999, "output_path": []}],
            },
            "incidents": [],
            "hypotheses": [],
            "proposed_changes": [],
        }
    )
    with pytest.raises(ValueError, match="supplied experience"):
        await reflect(context, {"experience_refs": [{"event_ref": 5}]})
