"""Integration retries preserve source obligations and the identity of saved progress."""

import json
from copy import deepcopy

import pytest

from evertree.core.values import json_value
from tests.support.application import (
    IntegrationScriptedProvider,
    is_integration_request,
    tool_events,
)


def task_and_source(app, *, first="First assertion. " * 35):
    task = app.tasks.create_task("Retain all supplied assertions")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 5}, 0, reason="Review")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    run = app.memory.start_run("RetainedSource", app._program_revision(), {})
    event = app.memory.record(
        run,
        "source",
        output={"first": first, "second": "Second assertion. " * 35},
    )
    app.memory.finish_run(run)
    refs = [json_value(app.memory.output_ref(event, path=(key,))) for key in ("first", "second")]
    app.memory.retain(event.id, "integration_pending:" + task.id)
    return task, event.id, refs


@pytest.mark.parametrize("separate_attempts", [False, True])
async def test_completed_child_keeps_same_event_pinned_for_unfinished_sibling(
    app, separate_attempts
):
    class Provider(IntegrationScriptedProvider):
        fail_second = True

        async def run(self, request_id, request, **kwargs):
            assert is_integration_request(request)
            self.requests.append(request)
            refs = [
                item["reference"] for item in json.loads(request.prompt)["material"]["experience"]
            ]
            if self.fail_second and any(ref["output_path"] == ["second"] for ref in refs):
                raise RuntimeError("Second source unavailable")
            async for event in tool_events(request_id, request, kwargs["tool_handler"], []):
                yield event

    task, event_id, refs = task_and_source(app)
    app.provider = Provider([])
    if separate_attempts:
        await app._run_integration(task.id, {"experience_refs": [refs[1]]})
        result = await app._run_integration(task.id, {"experience_refs": [refs[0]]})
        assert result["result"]["processing"]["status"] == "processed"
        retry_refs = [refs[1]]
    else:
        result = await app._run_integration(task.id, {"experience_refs": refs})
        assert result["result"]["processing"]["failed"]
        retry_refs = refs
    assert refs[0] in task.step_state["integrated"][str(task.specification.revision)]
    assert event_id in app.memory.retention_closure()

    app.provider.fail_second = False
    result = await app._run_integration(task.id, {"experience_refs": retry_refs})
    assert result["result"]["processing"]["status"] == "processed"
    assert event_id not in app.memory.retention_closure()


async def test_pending_resume_and_plain_continuation_share_progress_identity(app, monkeypatch):
    """The coordinator reuses progress even when a resumed worker includes its checkpoint input."""
    task, _, refs = task_and_source(app)
    units = [{"parts": [{"source": index, "path": []}]} for index in range(2)]
    initial = {
        "completed": [],
        "pending": units,
        "failed": [],
        "attempts": {},
        "status": "incomplete",
    }
    advanced = {**initial, "completed": units[:1], "pending": units[1:]}
    completed = {**initial, "completed": units, "pending": [], "status": "processed"}
    supplied = []

    async def program_result(task_id, identity, arguments):
        assert task_id == task.id and identity == "knowledge_integration"
        supplied.append(deepcopy(arguments))
        app._pending_programs.pop(task.id, None)
        progress = [initial, advanced, completed][len(supplied) - 1]
        return {"result": {"writes": [], "processing": deepcopy(progress)}}

    monkeypatch.setattr(app, "_run_program", program_result)
    base = {"experience_refs": refs}
    await app._run_integration(task.id, base, retry=False)
    resumed = {**base, "processing": deepcopy(initial)}
    app._pending_programs[task.id] = {
        "identity": "knowledge_integration",
        "arguments": resumed,
        "run_id": "interrupted-worker",
    }
    await app._run_integration(task.id, resumed, retry=False)
    await app._run_integration(task.id, base, retry=False)
    assert supplied[-1]["processing"] == advanced
    assert len(task.step_state["integration_attempts"]) == 1
    assert len(task.step_state["integration_attempt_sources"]) == 1


async def test_prepared_fragments_keep_original_source_indexes_until_all_sections_complete(app):
    class Provider(IntegrationScriptedProvider):
        fail_later_fragment = True

        async def run(self, request_id, request, **kwargs):
            assert is_integration_request(request)
            self.requests.append(request)
            if self.fail_later_fragment and len(self.requests) == 2:
                raise RuntimeError("Later fragment failed")
            async for event in tool_events(request_id, request, kwargs["tool_handler"], []):
                yield event

    task, _, refs = task_and_source(app, first="First independently useful assertion.\n\n" * 240)
    app.provider = Provider([])
    args = {"experience_refs": refs}
    progress = (await app._run_integration(task.id, args))["result"]["processing"]
    assert progress["completed"] and progress["failed"] and progress["pending"]
    assert {part["source"] for part in progress["failed"][0]["unit"]["parts"]} == {0}
    assert {part["source"] for unit in progress["pending"] for part in unit["parts"]} == {0, 1}
    assert not task.step_state["integrated"][str(task.specification.revision)]
    for request in app.provider.requests:
        for item in json.loads(request.prompt)["material"]["experience"]:
            assert item["source_reference"] == refs[0]
            assert item["reference"]["event_ref"] != refs[0]["event_ref"]
            assert item["reference"]["output_path"] == ["text"]

    app.provider.fail_later_fragment = False
    progress = (await app._run_integration(task.id, args))["result"]["processing"]
    assert progress["status"] == "processed"
    assert not progress["pending"] and not progress["failed"]
    assert all(part["source"] in {0, 1} for unit in progress["completed"] for part in unit["parts"])
    assert task.step_state["integrated"][str(task.specification.revision)] == refs
