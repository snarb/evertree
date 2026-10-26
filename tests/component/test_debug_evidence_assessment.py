"""The evidence assessment debug harness wires integration and assessment without external services."""

import json

from evertree import debug_evidence_assessment
from evertree.debug_evidence_assessment import CASES, EvidenceSession
from tests.evidence.checks import check
from tests.support.application import (
    completed,
    is_evidence_request,
    is_program_evidence_request,
    tool_events,
)
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
            ("search", {"queries": ["Pump off"]}),
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
    # No Program ran in the debug task, so Program assessment has nothing to judge.
    assert session.evidence[0]["programs"]["assessed"] == []
    assert [call["method"] for call in session.calls if "evidence" in call["method"]] == [
        "evidence.pending",
        "evidence.record",
        "evidence.stale",
        "evidence.pending_properties",
        "evidence.pending_programs",
        "evidence.record_programs",
        "evidence.stale_programs",
    ]
    saved = json.loads((tmp_path / "beliefs.json").read_text())
    assert saved["assessed"] == {f"graph:{element}": session.graph.revision}
    assert "Убеждения после шага 1" in capsys.readouterr().out


class ProgramCaseProvider(Provider):
    """Integrate nothing, find no graph evidence, and oppose the anchored loading step."""

    async def run(self, request_id, request, *, tool_handler=None):
        self.requests.append(request)
        if is_program_evidence_request(request):
            batch = json.loads(request.prompt)
            [card] = batch["runs"]
            [source] = [item for item in batch["sources"] if "устарел" in item["text"]]
            entry = {
                "source": source["key"],
                "stance": "opposes",
                "repeats": None,
                "withdraws": None,
                "reason": "stale schedule",
            }
            answer = {
                "run": card["key"],
                "program": [],
                "operators": [{"op_id": "load_schedule", "evidence": [entry]}],
                "unresolved": None,
            }
            for event in completed({"runs": [answer]}):
                yield event
            return
        if is_evidence_request(request):
            for event in completed({"targets": [], "origins": [], "scopes": []}):
                yield event
            return
        async for event in tool_events(request_id, request, tool_handler, []):
            yield event


async def test_program_case_checks_run_on_recorded_runs(tmp_path):
    """A live Program case's steps and checks work offline with a scripted model."""
    [case] = [
        item
        for item in json.loads(CASES.read_text(encoding="utf-8"))
        if item["id"] == "program-anchored-step-wrong"
    ]
    session = EvidenceSession(tmp_path, task=case["task"], steps=case["steps"])
    session.index = session.service.index = EmptyIndex()
    session.provider = ProgramCaseProvider()
    await session.run()
    [first, second] = session.history
    assert first["programs"] == {}
    assert second["programs"][f"PumpScheduler:load_schedule@{'a' * 40}"]["strength"] < 0.5
    assert [check(session.history, expectation) for expectation in case["expect"]] == [
        None,
        None,
        None,
    ]
