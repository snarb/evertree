"""Real model invocations over in-process semantic stores for opt-in evaluations."""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from evertree.core.provider import LLMRequest, ToolDefinition
from evertree.core.runtime.llm import ProgramLLMInvocations, run_llm_dialogue
from tests.support.semantics import context


def assert_no_individual_concept_assignments(graph):
    """Check rule-only learning without relying on a particular membership relation name."""
    instances = {node.id for node in graph.nodes(kind="instance")}
    concepts = {node.id for node in graph.nodes(kind="concept")}
    assignments = []
    for fact in graph.facts():
        relation = graph.get(fact.relation_type)
        identities = set()
        for slot in relation.signature:
            if slot.value_type not in {"node", "concept", "prototype", "instance", "facet"}:
                continue
            value = fact.args.get(slot.label)
            values = value if isinstance(value, (list, tuple)) else [value]
            identities.update(item for item in values if type(item) is int)
        if identities & instances and identities & concepts:
            assignments.append({"id": fact.id, "relation": relation.name, "args": dict(fact.args)})
    assert not assignments, (
        "A classification guide must not become unconditional individual assignments",
        assignments,
    )


def load_completed_acquisition(path, case, source_version):
    """Reuse only a completed acquisition from identical sources and production code."""
    path = Path(path).resolve()
    raw = path.read_bytes()
    saved = json.loads(raw)
    assert saved["case"] == json.loads(json.dumps(case)), "Acquisition case changed"
    assert saved["source_version_start"] == saved["source_version_end"] == source_version, (
        "Acquisition production source changed"
    )
    assert len(saved["packets"]) == len(case["packets"]), "Acquisition is missing source packets"
    for packet, content in zip(saved["packets"], case["packets"], strict=True):
        assert packet["content"] == content, "Acquisition source packet changed"
        assert "outcome" in packet and "snapshot" in packet, "Acquisition packet did not finish"
        invocations = [item for item in packet["transcript"] if "events" in item]
        assert invocations, "Acquisition has no recorded model invocation"
        for invocation in invocations:
            events = invocation["events"]
            assert not any(event["kind"] == "error" for event in events), "Acquisition model failed"
            assert sum(event["kind"] == "completed" for event in events) == 1, (
                "Acquisition model did not complete"
            )
    assert "learned" in saved, "Acquisition has no completed learned snapshot"
    origin = {
        "artifact": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_version": saved["source_version_start"],
    }
    return saved["learned"], saved["packets"], origin


async def provider_result(provider, directory, payload, transcript, *, tool_handler=None):
    """Record one isolated model invocation, including exchanges when it fails."""
    events, request_id = [], uuid4().hex
    try:
        async for event in provider.run(
            request_id,
            LLMRequest(
                payload["prompt"],
                directory,
                instructions=payload["instructions"],
                mode=payload.get("mode", "model"),
                output_schema=payload.get("output_schema"),
                tools=tuple(ToolDefinition(**tool) for tool in payload.get("tools", [])),
                model="gpt-6-luna",
                effort="medium",
                timeout_seconds=120,
            ),
            tool_handler=tool_handler,
        ):
            events.append(event)
    except asyncio.CancelledError:
        await provider.cancel(request_id)
        raise
    finally:
        transcript.append(
            {
                "request": payload,
                "events": [{"kind": event.kind, "data": event.data} for event in events],
            }
        )
    errors = [event.data for event in events if event.kind == "error"]
    assert not errors, errors
    completed = [event.data for event in events if event.kind == "completed"]
    assert len(completed) == 1, completed
    return completed[0]


@asynccontextmanager
async def native_semantic_context(
    world,
    provider,
    directory,
    transcript,
    *,
    role="exec",
    integration_context=None,
    operation_id="packet",
):
    """Use production native-tool dialogue and handlers without worker or scheduler fixtures."""

    async def unexpected_model(*args):
        raise AssertionError("The evaluated Program must use its declared native tools")

    ctx = context(
        world,
        unexpected_model,
        role=role,
        integration_context=integration_context,
        operation_id=operation_id,
    )
    ctx.run_id = uuid4().hex
    metadata = {"run_id": ctx.run_id, "program": {"role": role}}

    async def gateway(method, payload):
        assert method == "llm.run"
        request = {key: value for key, value in payload.items() if not key.startswith("_")}
        return await provider_result(
            provider, directory, request, transcript, tool_handler=payload["_tool_handler"]
        )

    invocations = ProgramLLMInvocations(gateway)
    business_step = ctx.step

    async def step(method, payload, *, journal=True):
        if method == "llm.next":
            return await invocations.next(payload, metadata)
        if method == "llm.close":
            transcript.append(
                {"invocation_id": payload["invocation_id"], "tool_history": payload["history"]}
            )
            return await invocations.close(
                payload["invocation_id"],
                metadata,
                history=payload["history"],
                drain=payload.get("drain", False),
            )
        return await business_step(method, payload, journal=journal)

    async def llm(payload, **options):
        return await run_llm_dialogue(ctx, payload, **options)

    ctx.step, ctx.llm = step, llm
    try:
        yield ctx
    finally:
        await invocations.close_all()
