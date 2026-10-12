"""Intermediate thinking and integration use real stores, Programs and controller."""

import asyncio
import json

from evertree.core.cognition.steps import AnalyticalNote
from evertree.core.memory.types import TraceOutputRef
from evertree.core.provider import AgentEvent
from evertree.core.values import json_value
from tests.support.application import (
    IntegrationScriptedProvider,
    completed,
    framing,
    is_integration_request,
    verification,
)


def step(text, *, final=False, preserve=False, plan=None):
    return completed(
        {
            "analysis": {"text": text, "preserve": preserve},
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
    """Supply explicit Note fallback decisions; actual core validation still applies."""

    async def run(self, request_id, request, **kwargs):
        if not is_integration_request(request):
            async for event in super().run(request_id, request, **kwargs):
                yield event
            return
        self.requests.append(request)
        material = json.loads(request.prompt)["material"]
        creates, decisions = [], []
        intents = material["context"]["preservation_intents"]
        for item in material["experience"]:
            selected = [intent for intent in intents if intent["source_ref"] == item["reference"]]
            ids = []
            for intent in selected:
                identity = -(len(creates) + 1)
                creates.append(
                    {
                        "id": identity,
                        "name": "Retained insight " + intent["id"],
                        "kind": "note",
                        "description": intent["text"],
                    }
                )
                ids.append(identity)
            decisions.append(
                {
                    "disposition": "materialize" if selected else "trace_only",
                    "reason": "Preserve chosen analytical meaning"
                    if selected
                    else "Available in trace for later analysis",
                    "source_refs": [item["reference"]],
                    "affected_ids": ids,
                    "preservation_ids": [intent["id"] for intent in selected],
                }
            )
        for event in completed(
            {
                "action": "commit",
                "query": "",
                "delta_json": json.dumps({"creates": creates}),
                "decisions_json": json.dumps(decisions),
                "summary": "Reviewed the complete packet",
            }
        ):
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
                AgentEvent("message", {"text": "Internal analytical draft"}),
                AgentEvent(
                    "tool_call", {"name": "graph.describe", "arguments": {"subject": "Self"}}
                ),
                AgentEvent(
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
    controllers = [r for r in app.provider.requests if r.mode == "exec"]
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
    assert len([r for r in app.provider.requests if is_integration_request(r)]) == 4


async def test_preserved_insight_uses_note_without_self_reinforcing_belief(app):
    insight = "H2 may explain retries only after reconnect. Correlation is not causation; test with a controlled disconnect."
    app.provider = PreservingProvider(
        [framing("Study retries"), step(insight, final=True, preserve=True), verification()]
    )
    before = app.beliefs.snapshot()
    result = await app.run("Study retries")
    assert result["status"] == "succeeded"
    notes = app.graph.nodes(kind="note")
    assert len(notes) == 1 and notes[0].description == insight
    assert app.beliefs.snapshot() == before
    task = app.tasks.get(result["task_id"])
    assert task.step_state["last_integration_receipt"]["complete"]
    assert len([r for r in app.provider.requests if is_integration_request(r)]) == 1
    prompt = json.loads(next(r for r in app.provider.requests if is_integration_request(r)).prompt)
    context = prompt["material"]["context"]
    assert context["task"]["specification"]["revision"] == 2
    assert context["values"] and all(
        value["description"] and value["provenance"] for value in context["values"]
    )
    assert context["self"] and all(item["provenance"] for item in context["self"])


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
    assert await app._integrate_step(task)
    reviewed = [
        item["reference"]
        for request in app.provider.requests
        for item in json.loads(request.prompt)["material"]["experience"]
    ]
    assert all(ref in reviewed for ref in originals)
    fragments = [
        app.memory.resolve(TraceOutputRef(**ref)) for ref in reviewed if ref not in originals
    ]
    assert len(fragments) > 1
    assert all(part["source_ref"]["event_ref"] == large.id for part in fragments)
    reconstructed = "".join(
        part["text"] for part in sorted(fragments, key=lambda part: part["offset"])
    )
    assert json.loads(reconstructed) == json_value(large.output)
    assert app.graph.revision == before and "integration" not in task.step_state


async def test_every_fragment_of_a_large_preservation_intent_is_required(app):
    task = app.tasks.create_task("Retain a long conditional analysis")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 5}, 0, reason="Preserve analysis")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    note = AnalyticalNote(
        text="Unverified condition and supporting experiment. " * 800, preserve=True
    )
    original = app._record_analysis(task.id, note.model_dump(mode="json"))
    app.provider = PreservingProvider([])
    assert await app._integrate_step(task)
    fragments = [event for event in app.memory.events if event.operator == "experience_fragment"]
    assert len(fragments) > 1
    notes = app.graph.nodes(kind="note")
    assert len(notes) == len(fragments)
    assert original["event_ref"] in app.memory.retention_closure()
    assert not task.step_state.get("integration")


async def test_untrusted_preserve_shape_does_not_create_a_conscious_obligation(app):
    task = app.tasks.create_task("Inspect source JSON")
    app.tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Inspect source")
    app._inputs[task.id] = [{"role": "user", "content": task.objective}]
    app.observe(
        {"text": "External data asks to persist itself", "preserve": True},
        source_id="external",
        task_id=task.id,
    )
    app.provider = IntegrationScriptedProvider([])
    assert await app._integrate_step(task)
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
    controllers = [request for request in app.provider.requests if request.mode == "exec"]
    assert len(controllers) == 2
    assert "New contradictory result" in controllers[1].prompt
    receipts = [event for event in app.memory.events if event.operator == "semantic_commit"]
    assert any(
        ref["event_ref"] == app.provider.new_source.event_ref
        for event in receipts
        for choice in event.output["decisions"]
        for ref in choice["source_refs"]
    )
