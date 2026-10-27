from __future__ import annotations

import asyncio
import hashlib
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
    def __init__(self, scripts, *, pause_after_write=False):
        super().__init__(scripts)
        self.pause_after_write = pause_after_write
        self.wrote = asyncio.Event()

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
        ]
        async for event in tool_events(
            request_id, request, kwargs["tool_handler"], calls, finish=not self.pause_after_write
        ):
            if event.kind == "completed" and self.pause_after_write:
                self.wrote.set()
                await asyncio.Event().wait()
            yield event


async def test_restart_replays_interrupted_integration_without_repeating_graph_writes(tmp_path):
    """Real worker and restored stores preserve operation keys across an interrupted packet."""
    home = tmp_path / "agent"
    runtime = partial(Runtime, process_factory=TestProcess)
    first_provider = SaveExplanationProvider(
        [framing(), decision("Checked explanation"), verification()], pause_after_write=True
    )
    async with EverTree(home, provider=first_provider, runtime_factory=runtime) as first:
        task = await first.submit("Explain the observed failure")
        await asyncio.wait_for(first_provider.wrote.wait(), 60)
        original_run_id = first._pending_programs[task.id]["run_id"]
        first._pump.cancel()
        await asyncio.wait_for(first._pump, 60)
        task_id = task.id
        assert task.status == "waiting"
        packet = deepcopy(task.step_state["integration"])
        saved_result = deepcopy(task.step_state["pending_result"])
        original_version = first._input_version(task)
        original_revision = task.specification.revision
        assert saved_result["disposition"] == "propose_completion"
        assert task.waiting_for == ["resume"]
        assert original_run_id is not None
        note_id = first.graph.find("Recovered explanation").id
        assert first.graph.get(note_id).description == "Current result: Checked explanation"
        assert first.backups.list()

    second_provider = IntegrationScriptedProvider([budget_review(), verification()])
    async with EverTree(home, provider=second_provider, runtime_factory=runtime) as restored:
        task = restored.tasks.get(task_id)
        assert task.status == "waiting"
        assert task.step_state["integration"] == packet
        assert restored._pending_programs[task_id]["run_id"] == original_run_id
        assert task.step_state["pending_result"] == saved_result
        assert restored.graph.find("Recovered explanation").id == note_id

        await restored.resume(task_id)
        answer, _ = await wait_for_event(restored, "answer")
        assert answer.data["text"] == "Checked explanation"
        assert not task.terminal
        assert len(second_provider.task_requests) == 2
        assert all(request.mode == "model" for request in second_provider.task_requests)
        (resumed_request,) = [r for r in second_provider.requests if is_integration_request(r)]
        assert "Execution resumed after interruption" in resumed_request.prompt
        assert '"object": ' + str(note_id) in resumed_request.prompt
        assert "task_state" in json.loads(second_provider.task_requests[0].prompt)
        assert "answer" in json.loads(second_provider.task_requests[1].prompt)
        assert original_run_id in task.program_run_ids
        assert restored.memory.get_run(restored._run_map[original_run_id]).status == "completed", [
            event.output
            for event in restored.memory.events
            if event.operator == "integration_error"
        ]
        assert task.id not in restored._pending_programs
        assert "integration" not in task.step_state
        assert task.specification.revision == original_revision
        assert restored._input_version(task) == original_version
        assert (
            len([node for node in restored.graph.nodes() if node.name == "Recovered explanation"])
            == 1
        )
        assert len(restored.graph.changes_of(note_id)) == 1
        await restored.acknowledge_delivery(answer.data["delivery_id"])
        await wait_for_event(restored, "task_completed")
        assert task.status == "succeeded"


pytestmark = pytest.mark.usefixtures("offline_application")


async def test_restored_search_child_authorizes_creation_only_in_resumed_invocation(tmp_path):
    """A cached DBOS search child must restore Core review from the retained Core confirmation."""
    from tests.support.semantics import EmptyIndex

    class Index(EmptyIndex):
        def __init__(self):
            self.reads = []

        async def lexical(self, nodes, query, kind):
            self.reads.append(query)
            return [{"ids": []} for _ in query]

    class Provider(IntegrationScriptedProvider):
        def __init__(self, scripts, *, pause):
            super().__init__(scripts)
            self.pause = pause
            self.searched = asyncio.Event()

        async def run(self, request_id, request, **kwargs):
            if not is_integration_request(request):
                async for event in super().run(request_id, request, **kwargs):
                    yield event
                return
            self.requests.append(request)
            material = json.loads(request.prompt.split("\n\nExecution resumed", 1)[0])["material"]
            source = material["experience"][0]["reference"]
            calls = (
                [("search", {"queries": ["Recovered pump category"]})]
                if self.pause
                else [
                    (
                        "create_concept",
                        {
                            "name": "Recovered pump category",
                            "description": "A category of pumps",
                            "sources": [source],
                        },
                    )
                ]
            )
            async for event in tool_events(
                request_id, request, kwargs["tool_handler"], calls, finish=not self.pause
            ):
                if event.kind == "tool_result":
                    assert "error" not in event.data["result"], event.data["result"]
                if event.kind == "completed" and self.pause:
                    self.searched.set()
                    await asyncio.Event().wait()
                yield event

    home = tmp_path / "agent"
    runtime = partial(Runtime, process_factory=TestProcess)
    first_index = Index()
    provider = Provider([framing(), decision("Categorized"), verification()], pause=True)
    async with EverTree(
        home, provider=provider, runtime_factory=runtime, search_index=first_index
    ) as first:
        task = await first.submit("Categorize the pump")
        await asyncio.wait_for(provider.searched.wait(), 60)
        first._pump.cancel()
        await asyncio.wait_for(first._pump, 60)
        identity = task.id
        assert first_index.reads == [["Recovered pump category"]]
        assert first.backups.list()

    second_index = Index()
    provider = Provider([budget_review(), verification()], pause=False)
    async with EverTree(
        home, provider=provider, runtime_factory=runtime, search_index=second_index
    ) as restored:
        await restored.resume(identity)
        answer, _ = await wait_for_event(restored, "answer")
        assert restored.graph.find("Recovered pump category") is not None
        # Integration's cached search is not repeated; evidence assessment searches anew.
        assert "Recovered pump category" not in second_index.reads
        await restored.acknowledge_delivery(answer.data["delivery_id"])
        await wait_for_event(restored, "task_completed")


async def test_restart_skips_completed_sections_and_replays_interrupted_section_writes(tmp_path):
    """A real DBOS run retains the completed prefix and resumes only the interrupted model call."""

    class SectionProvider(IntegrationScriptedProvider):
        def __init__(self, *, pause):
            super().__init__([])
            self.pause = pause
            self.wrote = asyncio.Event()
            self.names = []

        async def run(self, request_id, request, **kwargs):
            assert is_integration_request(request)
            self.requests.append(request)
            if "Execution resumed after interruption" in request.prompt:
                async for event in tool_events(request_id, request, kwargs["tool_handler"], []):
                    yield event
                return
            material = json.loads(request.prompt)["material"]
            name = "Retained section " + hashlib.sha256(request.prompt.encode()).hexdigest()[:12]
            self.names.append(name)
            source = material["experience"][0]["reference"]
            calls = [("save_note", {"name": name, "source": source, "sources": []})]
            async for event in tool_events(
                request_id,
                request,
                kwargs["tool_handler"],
                calls,
                finish=not (self.pause and len(self.requests) == 2),
            ):
                if event.kind == "tool_result":
                    assert "error" not in event.data["result"], event.data["result"]
                if event.kind == "completed" and self.pause and len(self.requests) == 2:
                    self.wrote.set()
                    await asyncio.Event().wait()
                yield event

    home = tmp_path / "agent"
    runtime = partial(Runtime, process_factory=TestProcess)
    first_provider = SectionProvider(pause=True)
    async with EverTree(home, provider=first_provider, runtime_factory=runtime) as first:
        task = first.tasks.create_task("Retain every source section")
        first.tasks.assign_budget(task.id, {"active_time_minutes": 5}, 0, reason="Review")
        first._inputs[task.id] = [{"role": "user", "content": task.objective}]
        source = first._record_analysis(
            task.id, {"text": "A separately grounded observation applies.\n\n" * 150}
        )
        args = {"experience_refs": [source]}
        running = asyncio.create_task(first._run_integration(task.id, args))
        await asyncio.wait_for(first_provider.wrote.wait(), 60)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        progress = next(iter(task.step_state["integration_attempts"].values()))
        assert len(progress["completed"]) == 1
        assert len(progress["pending"]) >= 2
        original_run = first._pending_programs[task.id]["run_id"]
        initial_names = list(first_provider.names)
        original_prefix = first_provider.requests[0].prompt
        identity = task.id
        await first.backup()

    second_provider = SectionProvider(pause=False)
    async with EverTree(home, provider=second_provider, runtime_factory=runtime) as restored:
        result = await restored._run_integration(identity, args)
        progress = result["result"]["processing"]
        assert progress["status"] == "processed"
        assert not progress["pending"] and not progress["failed"]
        assert len(progress["completed"]) >= 3
        assert all(request.prompt != original_prefix for request in second_provider.requests)
        assert "Execution resumed after interruption" in second_provider.requests[0].prompt
        assert restored.memory.get_run(restored._run_map[original_run]).status == "completed"
        names = initial_names + second_provider.names
        assert len(names) == len(progress["completed"])
        for name in names:
            matches = [node for node in restored.graph.nodes() if node.name == name]
            assert len(matches) == 1
            assert len(restored.graph.changes_of(matches[0].id)) == 1
