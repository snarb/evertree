"""The evidence assessment debug harness wires integration and assessment without external services."""

import json

from evertree import debug_evidence_assessment
from evertree.debug_evidence_assessment import EvidenceSession
from tests.support.application import completed, is_evidence_request, tool_events
from tests.support.semantics import EmptyIndex


class Provider:
    """Integrate the step's user message as a Claim, then judge it supported."""

    def __init__(self):
        self.requests = []

    async def run(self, request_id, request, *, tool_handler=None):
        self.requests.append(request)
        if is_evidence_request(request):
            batch = json.loads(request.prompt)
            [target] = batch["targets"]
            [source] = [item for item in batch["sources"] if "09:00" in item["text"]]
            answer = {
                "element": target["element"],
                "prior": 0.5,
                "evidence": [
                    {
                        "source": source["key"],
                        "stance": "supports",
                        "repeats": None,
                        "withdraws": None,
                        "reason": "states it",
                    }
                ],
                "unresolved": None,
            }
            for event in completed({"targets": [answer], "origins": [], "scopes": []}):
                yield event
            return
        material = json.loads(request.prompt)["material"]
        [source] = [
            item["reference"]
            for item in material["experience"]
            if item["source_kind"] == "user_input" and "09:00" in item["content"]
        ]
        calls = [
            ("search", {"query": "Pump off"}),
            (
                "create_claim",
                {
                    "name": "Pump off",
                    "description": "Pump N-1 was off 09:00–09:10 UTC.",
                    "sources": [source],
                },
            ),
        ]
        async for event in tool_events(request_id, request, tool_handler, calls):
            yield event

    async def close(self):
        pass


async def test_debug_steps_integrate_then_assess_and_save_beliefs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(debug_evidence_assessment, "STEPS", debug_evidence_assessment.STEPS[:1])
    session = EvidenceSession(tmp_path)
    session.index = session.service.index = EmptyIndex()
    session.provider = Provider()
    beliefs = await session.run()
    [(element, belief)] = beliefs.items()
    assert belief["kind"] == "claim" and belief["evidence_count"] == 1
    assert 0.5 < belief["strength"] <= 0.75
    assert session.evidence[0]["programs"]["status"] == "not_implemented"
    assert [call["method"] for call in session.calls if "evidence" in call["method"]] == [
        "evidence.pending",
        "evidence.record",
        "evidence.stale",
        "evidence.pending_properties",
    ]
    saved = json.loads((tmp_path / "beliefs.json").read_text())
    assert saved["assessed"] == {f"graph:{element}": session.graph.revision}
    assert "Убеждения после шага 1" in capsys.readouterr().out
