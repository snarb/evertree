from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from functools import partial

import pytest

from evertree.application import EverTree
from evertree.core.runtime.controller import Runtime
from tests.support.application import (
    IntegrationScriptedProvider,
    budget_review,
    decision,
    framing,
    is_integration_request,
    tool_events,
    verification,
    wait_for_event,
)
from tests.support.runtime import TestProcess


class SaveExplanationProvider(IntegrationScriptedProvider):
    async def run(self, request_id, request, **kwargs):
        if not is_integration_request(request):
            async for event in super().run(request_id, request, **kwargs):
                yield event
            return
        self.requests.append(request)
        experience = json.loads(request.prompt)["material"]["experience"]
        explanation = next(
            item["reference"] for item in experience if item["source_kind"] == "analytical_note"
        )
        calls = [
            ("save_note", {"name": "Recovered explanation", "source": explanation, "sources": []}),
            (
                "trace_only",
                {
                    "sources": [
                        item["reference"] for item in experience if item["reference"] != explanation
                    ]
                },
            ),
            ("finish", {}),
        ]
        async for event in tool_events(request_id, request, kwargs["tool_handler"], calls):
            yield event


async def test_restart_replays_committed_integration_before_delivering_saved_completion(
    tmp_path, monkeypatch
):
    """Real worker, backup and reopen prove receipt/checkpoint recovery across process state."""
    home = tmp_path / "agent"
    runtime = partial(Runtime, process_factory=TestProcess)
    first_provider = SaveExplanationProvider([framing(), decision("Checked explanation")])
    async with EverTree(home, provider=first_provider, runtime_factory=runtime) as first:
        run_program = first._run_program
        original_run_id = None

        async def lose_committed_reply(task_id, identity, arguments, **kwargs):
            nonlocal original_run_id
            output = await run_program(task_id, identity, arguments, **kwargs)
            if identity == "knowledge_integration":
                original_run_id = output["run_id"]
                assert output["result"]["complete"]
                raise RuntimeError("Integration reply lost after committed mutation")
            return output

        monkeypatch.setattr(first, "_run_program", lose_committed_reply)
        waiting = await asyncio.wait_for(first.run("Explain the observed failure"), 60)
        assert waiting["status"] == "waiting", waiting
        await first._pump
        task_id = waiting["task_id"]
        task = first.tasks.get(task_id)
        packet = deepcopy(task.step_state["integration"])
        saved_result = deepcopy(task.step_state["pending_result"])
        original_version = first._input_version(task)
        original_revision = task.specification.revision
        assert saved_result["disposition"] == "propose_completion"
        assert task.waiting_for == ["knowledge_integration"]
        assert original_run_id is not None
        receipt_events = [
            event for event in first.memory.events if event.operator == "semantic_commit"
        ]
        assert len(receipt_events) == 1
        receipt_ref = first.memory.output_ref(receipt_events[0])
        note_id = first.graph.find("Recovered explanation").id
        assert first.graph.get(note_id).description == "Current result: Checked explanation"
        assert first.backups.list()

    second_provider = IntegrationScriptedProvider([budget_review(), verification()])
    async with EverTree(home, provider=second_provider, runtime_factory=runtime) as restored:
        task = restored.tasks.get(task_id)
        assert task.status == "waiting"
        assert task.step_state["integration"] == packet
        assert task.step_state["pending_result"] == saved_result
        assert restored.memory.resolve(receipt_ref)["complete"]
        assert restored.graph.find("Recovered explanation").id == note_id
        previous_runs = set(task.program_run_ids)

        await restored.resume(task_id)
        answer, _ = await wait_for_event(restored, "answer")
        assert answer.data["text"] == "Checked explanation"
        assert not task.terminal
        assert len(second_provider.requests) == 2
        assert all(request.mode == "model" for request in second_provider.requests)
        assert not any(is_integration_request(request) for request in second_provider.requests)
        assert "task_state" in json.loads(second_provider.requests[0].prompt)
        assert "answer" in json.loads(second_provider.requests[1].prompt)
        integration = restored._program("knowledge_integration")
        replay_runs = [
            run_id
            for run_id in set(task.program_run_ids) - previous_runs
            if restored.memory.get_run(restored._run_map[run_id]).program == integration.program_id
        ]
        assert len(replay_runs) == 1 and replay_runs[0] != original_run_id
        assert task.step_state["last_integration_receipt"]["operation_id"] == packet["operation_id"]
        assert task.specification.revision == original_revision
        assert restored._input_version(task) == original_version
        assert (
            len([node for node in restored.graph.nodes() if node.name == "Recovered explanation"])
            == 1
        )
        assert (
            len([event for event in restored.memory.events if event.operator == "semantic_commit"])
            == 1
        )
        await restored.acknowledge_delivery(answer.data["delivery_id"])
        await wait_for_event(restored, "task_completed")
        assert task.status == "succeeded"


pytestmark = pytest.mark.usefixtures("offline_application")
