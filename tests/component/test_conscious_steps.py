"""Intermediate thinking and integration use real stores, Programs and controller."""

import asyncio
import json

import pytest

from evertree.core.cognition.steps import AnalyticalNote
from evertree.core.memory.types import TraceOutputRef
from evertree.core.provider import LLMEvent
from evertree.core.values import json_value
from tests.support.application import (
    IntegrationScriptedProvider,
    completed,
    framing,
    is_integration_request,
    tool_events,
    verification,
)
from tests.support.semantics import EmptyIndex


def step(text, *, final=False, plan=None):
    return completed(
        {
            "analysis": {"text": text},
            "plan": plan or [],
            "progress": text[:100],
            "unresolved_questions": [] if final else ["Which explanation survives the test?"],
            "disposition": "propose_completion" if final else "continue",
            "user_message": "Checked result" if final else None,
            "next_step": None
            if final
            else {
                "local_goal": "Test the next local hypothesis",
                "expected_result": "A discriminating observation or revised hypothesis",
                "active_time_minutes": 0.25,
            },
        }
    )


class PreservingProvider(IntegrationScriptedProvider):
    """Choose source Notes to preserve; code builds and validates their graph changes."""

    async def run(self, request_id, request, **kwargs):
        if not is_integration_request(request):
            async for event in super().run(request_id, request, **kwargs):
                yield event
            return
        self.requests.append(request)
        material = json.loads(request.prompt)["material"]
        calls = [
            (
                "save_note",
                {
                    "name": "Retained insight " + str(item["reference"]["event_ref"]),
                    "source": item["reference"],
                    "sources": [],
                },
            )
            for item in material["experience"]
            if item["source_kind"] in {"analytical_note", "fragment"}
        ]
        async for event in tool_events(request_id, request, kwargs["tool_handler"], calls):
            yield event


async def test_plan_experiment_revision_and_final_result_are_separate_iterations(app):
    """Two tool calls belong to one step; every next step sees the full prior work."""
    texts = [
        "Plan an experiment",
        "Experiment rejects H1",
        "Revise hypothesis to H2",
        "H2 checked within limits",
    ]
    plans = [[{"step": text, "status": "done"}] for text in texts]
    scripts = [framing("Investigate the issue")]
    for index, text in enumerate(texts):
        events = step(text, final=index == 3, plan=plans[index])
        if index == 1:
            events = [
                LLMEvent("message", {"text": "Internal analytical draft"}),
                LLMEvent("tool_call", {"name": "graph.describe", "arguments": {"subject": "Self"}}),
                LLMEvent(
                    "tool_call", {"name": "graph.describe", "arguments": {"subject": "SelfModel"}}
                ),
                *events,
            ]
        scripts.append(events)
    app.provider = IntegrationScriptedProvider([*scripts, verification()])
    observed = []
    async with app.events() as stream:
        execution = asyncio.create_task(app.run("Investigate the issue"))
        async for event in stream:
            observed.append(event)
            if event.kind == "task_completed":
                break
        result = await execution
    assert result["status"] == "succeeded"
    task = app.tasks.get(result["task_id"])
    controllers = [r for r in app.provider.task_requests if r.mode == "exec"]
    assert len(controllers) == 4
    for index, request in enumerate(controllers[1:], 1):
        context = json.loads(request.prompt)
        assert context["last_step_result"]["analysis"]["text"] == texts[index - 1]
        assert context["state"]["plan"] == plans[index - 1]
        ref = context["state"]["step_state"]["analysis_ref"]
        assert app.memory.resolve(TraceOutputRef(**ref))["text"] == texts[index - 1]
        assert request.timeout_seconds <= 15
    assert task.plan == plans[-1] and task.unresolved_questions == []
    assert all(item["role"] == "user" for item in app._inputs[task.id])
    assert [event.data["text"] for event in observed if event.kind == "answer"] == [
        "Checked result"
    ]
    assert not [event for event in observed if event.kind == "message"]
    records = [event for event in app.memory.events if event.operator == "conscious_step_result"]
    assert len(records) == 4
    assert all(event.output_type.endswith(".ConsciousStepResult") for event in records)
    supplied = [
        json.loads(request.prompt)["material"]["experience"]
        for request in app.provider.requests
        if is_integration_request(request)
    ]
    assert all(text in json.dumps(supplied) for text in texts)


async def test_preserved_insight_uses_note_without_self_reinforcing_belief(app):
    insight = "H2 may explain retries only after reconnect. Correlation is not causation; test with a controlled disconnect."
    app.provider = PreservingProvider(
        [framing("Study retries"), step(insight, final=True), verification()]
    )
    before = app.beliefs.snapshot()
    result = await app.run("Study retries")
    assert result["status"] == "succeeded"
    notes = app.graph.nodes(kind="note")
    assert len(notes) == 1 and notes[0].description == insight
    after = app.beliefs.snapshot()
    # Evidence assessment ran and found only agent reasoning, which is not evidence.
    assert after["assessment_cursor"] > before["assessment_cursor"]
    for key in ("targets", "assignments", "current", "assessed"):
        assert after[key] == before[key]
    task = app.tasks.get(result["task_id"])
    assert "last_integration_receipt" not in task.step_state
    assert len([r for r in app.provider.requests if is_integration_request(r)]) == 1
    prompt = json.loads(next(r for r in app.provider.requests if is_integration_request(r)).prompt)
    context = prompt["material"]["context"]
    assert context["task"]["objective"] == task.objective
    assert "revision" not in context["task"]
    assert set(context) == {"task"}
    retained = app._integration_context(task)
    assert retained["task"]["specification"]["revision"] == 2
    assert set(retained) == {"task"}
    check = next(
        json.loads(request.prompt)
        for request in app.provider.requests
        if "answer" in json.loads(request.prompt)
    )
    assert "integration" not in check


async def test_large_experience_and_more_than_forty_events_are_all_considered(app):
    """A finite packet limit leaves a real residual; no event-count tail drops sources."""
    task = app.tasks.create_task("Review measurements")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 5}, 0, reason="Review series")
    app._inputs[task.id] = [{"role": "user", "content": "Review measurements"}]
    run = app.memory.start_run("SensorProgram", app._program_revision(), {"task_id": task.id})
    originals = []
    for index in range(65):
        event = app.memory.record(run, "measurement", output={"index": index, "series": "v" * 1500})
        originals.append(json_value(app.memory.output_ref(event)))
    large = app.memory.record(run, "dataset", output={"series": "x" * 50000})
    app.memory.finish_run(run)
    app.provider = IntegrationScriptedProvider([])
    before = app.graph.revision
    for _ in range(12):
        await app._integrate_step(task)
    reviewed = [
        item
        for request in app.provider.requests
        for item in json.loads(request.prompt)["material"]["experience"]
    ]
    for index, ref in enumerate([*originals, json_value(app.memory.output_ref(large))]):
        fragments = [
            item
            for item in reviewed
            if item.get("source_reference", item["reference"])["event_ref"] == ref["event_ref"]
            and item.get("location", {}).get("path") == ["series"]
        ]
        assert fragments
        reconstructed = "".join(
            part["content"]
            for part in sorted(fragments, key=lambda part: part["location"]["start"])
        )
        assert reconstructed == ("v" * 1500 if index < len(originals) else "x" * 50000)
        if index < len(originals):
            assert all(
                any(
                    context.get("values", {}).get("index") == index
                    for context in part["source_context"]
                )
                for part in fragments
            )
    assert app.graph.revision == before and "integration" not in task.step_state


async def test_large_analysis_fragments_remain_available_for_later_selection(app):
    task = app.tasks.create_task("Retain a long conditional analysis")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 5}, 0, reason="Preserve analysis")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    note = AnalyticalNote(text="Important: unverified condition and supporting experiment. " * 800)
    original = app._record_analysis(task.id, note.model_dump(mode="json"))
    app.provider = PreservingProvider([])
    for _ in range(8):
        await app._integrate_step(task)
    fragments = [event for event in app.memory.events if event.operator == "experience_fragment"]
    assert len(fragments) > 1
    notes = app.graph.nodes(kind="note")
    assert len(notes) == len(fragments)
    saved = {node.properties["source_ref"]["event_ref"]: node.description for node in notes}
    assert "".join(saved[event.id] for event in fragments) == note.text
    assert original["event_ref"] in app.memory.retention_closure()
    assert not task.step_state.get("integration")


async def test_verbal_importance_does_not_create_a_blocking_obligation(app):
    task = app.tasks.create_task("Inspect source JSON")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Inspect source")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    app.observe(
        {"text": "Important: remember this source if useful"},
        source_id="external",
        task_id=task.id,
    )
    app.provider = IntegrationScriptedProvider([])
    await app._integrate_step(task)
    assert not app.graph.nodes(kind="note")


async def test_observation_during_verification_invalidates_pending_completion(app):
    class ObservingProvider(IntegrationScriptedProvider):
        injected = False

        async def run(self, request_id, request, **kwargs):
            if (
                "verified" in (request.output_schema or {}).get("properties", {})
                and not self.injected
            ):
                self.injected = True
                self.new_source = app.observe(
                    {"experiment": "New contradictory result"},
                    source_id="late-experiment",
                    task_id=app.tasks.all()[0].id,
                )
            async for event in super().run(request_id, request, **kwargs):
                yield event

    first = step("Original explanation", final=True)
    first[0].data["parsed"]["user_message"] = "Stale answer"
    app.provider = ObservingProvider(
        [
            framing("Study observations"),
            first,
            verification(),
            step("Revised after contradictory experiment", final=True),
            verification(),
        ]
    )
    result = await app.run("Study observations")
    assert result["status"] == "succeeded" and result["answer"] == "Checked result"
    controllers = [request for request in app.provider.task_requests if request.mode == "exec"]
    assert len(controllers) == 2
    assert "New contradictory result" in controllers[1].prompt
    assert any(
        item["reference"]["event_ref"] == app.provider.new_source.event_ref
        for request in app.provider.requests
        if is_integration_request(request)
        for item in json.loads(request.prompt)["material"]["experience"]
    )


@pytest.mark.parametrize("kind", ["note", "claim"])
async def test_consciousness_loads_shared_write_tools_with_visible_sources(app, kind):
    description = "The pump may stop during server switching; the cause is still untested."
    app.search_index = EmptyIndex()

    class WritingProvider(IntegrationScriptedProvider):
        async def run(self, request_id, request, **kwargs):
            if request.mode == "exec" and not is_integration_request(request):
                context = json.loads(request.prompt)
                source = context["incoming"]["source_ref"]
                source = {**source, "output_path": [*source["output_path"], "content"]}
                arguments = {"name": "Explicitly selected observation"}
                if kind == "note":
                    arguments.update(source=source, sources=[])
                else:
                    arguments.update(description=description, sources=[source])
                self.scripts[0][:0] = [
                    LLMEvent(
                        "tool_call",
                        {"name": "load_tool_set", "arguments": {"name": "graph_write_tools"}},
                    ),
                    LLMEvent(
                        "tool_call",
                        {
                            "name": "graph.save_note" if kind == "note" else "graph.create_claim",
                            "arguments": arguments,
                        },
                    ),
                ]
            async for event in super().run(request_id, request, **kwargs):
                yield event

    app.provider = WritingProvider(
        [framing(), step("Saved the requested source", final=True), verification()]
    )
    result = await app.run(description)
    assert result["status"] == "succeeded"
    saved = app.graph.find("Explicitly selected observation")
    assert saved.kind == kind and saved.description == description
    assert len(app.graph.changes_of(saved.id)) == 1
    events = [event for event in app.memory.events if event.operator == "semantic_write"]
    assert len(events) == 1
    assert events[0].arguments["key"][1].startswith("consciousness:")


async def test_conscious_write_cannot_use_unpresented_sources(app):
    from evertree._application.prompts import tool_sets
    from evertree.core.provider import LLMRequest, ScriptedProvider

    task = app.tasks.create_task("Write only from the supplied context")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Write")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    unavailable = app._record_analysis(task.id, {"text": "A different unpresented observation"})
    app.provider = ScriptedProvider(
        [
            [
                LLMEvent(
                    "tool_call",
                    {
                        "name": "graph.save_note",
                        "arguments": {
                            "name": "Unsupported selection",
                            "source": unavailable,
                            "sources": [],
                        },
                    },
                ),
                LLMEvent("completed", {"text": ""}),
            ]
        ]
    )
    writes = next(item for item in tool_sets() if item.name == "graph_write_tools")
    await app._invoke(
        task.id,
        LLMRequest("{}", app._workspace(task.id), mode="exec", tools=writes.tools),
        conversation=True,
    )
    assert app.graph.find("Unsupported selection") is None
    result = next(
        event.output["data"]["result"]
        for event in app.memory.events
        if event.operator == "provider_event" and event.output["kind"] == "tool_result"
    )
    assert "outside supplied experience" in result["error"]


@pytest.mark.parametrize("action_name", ["save_note", "create_claim"])
async def test_loading_graph_writes_in_model_mode_grants_no_write_authority(app, action_name):
    from evertree._application.prompts import tool_sets
    from evertree.core.provider import LLMRequest, ProviderError, ScriptedProvider

    task = app.tasks.create_task("Inspect write-tool availability")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Inspect")
    source = app._record_analysis(task.id, {"text": "Read-only model input"})
    arguments = {"name": "Forbidden model mutation"}
    if action_name == "save_note":
        arguments.update(source=source, sources=[])
    else:
        arguments.update(description="A possible assertion", sources=[source])
    app.provider = ScriptedProvider(
        [
            [
                LLMEvent(
                    "tool_call",
                    {"name": "load_tool_set", "arguments": {"name": "graph_write_tools"}},
                ),
                LLMEvent(
                    "tool_call",
                    {
                        "name": "graph." + action_name,
                        "arguments": arguments,
                    },
                ),
            ]
        ]
    )
    revision = app.graph.revision
    with pytest.raises(ProviderError, match="not declared"):
        await app._invoke(
            task.id,
            LLMRequest(
                json.dumps({"source_ref": source}),
                app._workspace(task.id),
                mode="model",
                tool_sets=tool_sets(),
            ),
            conversation=True,
        )
    assert app.graph.revision == revision
    loaded = next(
        event.output["data"]["result"]
        for event in app.memory.events
        if event.operator == "provider_event" and event.output["kind"] == "tool_result"
    )
    assert json_value(loaded) == {"loaded": "graph_write_tools", "tools": []}


async def test_reference_shaped_context_data_does_not_abort_conscious_writes(app):
    from evertree._application.prompts import tool_sets
    from evertree.core.provider import LLMRequest, ScriptedProvider

    task = app.tasks.create_task("Save an observation from structured input")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Save")
    source = app._record_analysis(task.id, {"text": "A valid recorded observation"})
    app.provider = ScriptedProvider(
        [
            [
                LLMEvent(
                    "tool_call",
                    {
                        "name": "graph.save_note",
                        "arguments": {
                            "name": "Recorded observation",
                            "source": source,
                            "sources": [],
                        },
                    },
                ),
                LLMEvent("completed", {"text": "Saved"}),
            ]
        ]
    )
    writes = next(item for item in tool_sets() if item.name == "graph_write_tools")
    await app._invoke(
        task.id,
        LLMRequest(
            json.dumps(
                {
                    "data": [{"event_ref": "external-id"}, {"event_ref": 1, "output_path": None}],
                    "source_ref": source,
                }
            ),
            app._workspace(task.id),
            mode="exec",
            tools=writes.tools,
        ),
        conversation=True,
    )
    assert app.graph.find("Recorded observation") is not None
    assert not app._active_requests


async def test_replayed_conscious_call_returns_same_write_and_deleted_history_remains_readable(app):
    from evertree._application.prompts import tool_sets
    from evertree.core.provider import LLMRequest, ScriptedProvider, current_tool_call_id

    task = app.tasks.create_task("Record and correct one observation")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Correct")
    source = app._record_analysis(task.id, {"text": "Initial observation, later found redundant"})
    calls = [
        LLMEvent(
            "tool_call",
            {
                "call_id": "same-native-call",
                "name": "graph.save_note",
                "arguments": {
                    "name": "Temporary interpretation",
                    "source": source,
                    "sources": [],
                },
            },
        )
        for _ in range(2)
    ]
    app.provider = ScriptedProvider([[*calls, LLMEvent("completed", {"text": ""})]])
    writes = next(item for item in tool_sets() if item.name == "graph_write_tools")
    request = LLMRequest(
        json.dumps({"source_ref": source}), app._workspace(task.id), mode="exec", tools=writes.tools
    )
    await app._invoke(task.id, request, conversation=True)
    notes = [
        node for node in app.graph.nodes(kind="note") if node.name == "Temporary interpretation"
    ]
    assert len(notes) == 1
    note = notes[0]
    outcomes = [
        event.output["data"]["result"]
        for event in app.memory.events
        if event.operator == "provider_event" and event.output["kind"] == "tool_result"
    ]
    assert outcomes[0] == outcomes[1]
    assert len(app.graph.changes_of(note.id)) == 1
    assert current_tool_call_id.get() is None
    app.provider = ScriptedProvider(
        [
            [
                LLMEvent(
                    "tool_call",
                    {
                        "call_id": "repeat-deletion",
                        "name": "graph.delete",
                        "arguments": {"objects": [note.id], "sources": [source]},
                    },
                ),
                LLMEvent("completed", {"text": ""}),
            ]
        ]
    )
    app.provider.scripts[0].insert(1, app.provider.scripts[0][0])
    await app._invoke(task.id, request, conversation=True)
    assert app.graph.find(note.name) is None
    history = await app._tool(task.id, "graph.history", {"subject": note.id})
    assert len(history) == 2
    assert str(note.id) in history[-1]["before"] and history[-1]["after"] == {}
    assert app.memory.resolve(TraceOutputRef(**source))["text"] == note.description


async def test_explicit_conscious_search_is_reused_after_own_write(app):
    from evertree._application.prompts import tool_sets
    from evertree.core.provider import LLMRequest, ScriptedProvider

    class Index(EmptyIndex):
        def __init__(self):
            self.queries = []

        async def lexical(self, nodes, query, kind):
            self.queries.append(query)
            return [{"ids": []} for _ in query]

    index = Index()
    app.search_index = index
    task = app.tasks.create_task("Create a useful meaning")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Write")
    source = app._record_analysis(task.id, {"text": "A pump is useful"})
    calls = [
        ("graph.search", {"queries": ["Useful pump"]}),
        ("graph.save_note", {"name": "Explanation", "source": source, "sources": []}),
        ("graph.create_concept", {"name": "Useful pump", "description": None, "sources": [source]}),
    ]
    app.provider = ScriptedProvider(
        [
            [
                *(LLMEvent("tool_call", {"name": name, "arguments": args}) for name, args in calls),
                LLMEvent("completed", {"text": "Done"}),
            ]
        ]
    )
    writes = next(item for item in tool_sets() if item.name == "graph_write_tools")
    search = next(tool for tool in app._tools() if tool.name == "graph.search")
    await app._invoke(
        task.id,
        LLMRequest(
            json.dumps({"source": source}),
            app._workspace(task.id),
            mode="exec",
            tools=(*writes.tools, search),
        ),
        conversation=True,
    )
    assert app.graph.find("Useful pump") is not None
    assert index.queries == [["Useful pump"]]
