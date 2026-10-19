"""Real model invocations over in-process semantic stores for opt-in evaluations."""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from evertree.core.codex.configuration import EFFORT, MODEL
from evertree.core.provider import LLMRequest, ToolDefinition
from evertree.core.runtime.llm import ProgramLLMInvocations, run_llm_dialogue
from tests.support.semantics import context


class RecordedProvider:
    """Capture real requests and events with the application's model settings."""

    def __init__(self, provider, transcript):
        self.provider, self.transcript = provider, transcript

    async def run(self, request_id, request, **kwargs):
        request = replace(request, model=request.model or MODEL, effort=request.effort or EFFORT)
        record = {"request": {**asdict(request), "workspace": str(request.workspace)}, "events": []}
        self.transcript.append(record)
        async for event in self.provider.run(request_id, request, **kwargs):
            record["events"].append({"kind": event.kind, "data": event.data})
            yield event

    async def cancel(self, request_id):
        await self.provider.cancel(request_id)

    async def close(self):
        await self.provider.close()


async def conscious_question(app, question, reference):
    """Run a production conscious work step, then its normal integration and assessment.

    The caller substitutes only worker transport and backups through component_app. The
    task framing and scheduler are outside this boundary; the step and tools remain real.
    """
    from evertree._application.prompts import CONSCIOUSNESS_INSTRUCTIONS, tool_sets
    from evertree.core.cognition.steps import ConsciousStepResult, ConsciousStepSpec
    from evertree.core.values import json_value

    state = app.tasks.create_task(question)
    app.tasks.assign_budget(
        state.id, {"active_time_minutes": 8}, 0, reason="Bounded live acceptance scenario"
    )
    step = ConsciousStepSpec(
        local_goal=question,
        expected_result="A grounded comparison with its scope and uncertainty, or a concrete remaining gap.",
        active_time_minutes=3,
    )
    state.current_step = step.model_dump(mode="json")
    app._inputs[state.id] = [{"role": "user", "content": question, "source_ref": reference}]
    result = await app._invoke(
        state.id,
        LLMRequest(
            json.dumps(app._conscious_context(state, state.current_step), ensure_ascii=False),
            app._workspace(state.id),
            instructions=CONSCIOUSNESS_INSTRUCTIONS,
            mode="exec",
            output_schema=ConsciousStepResult.response_schema(),
            tools=app._tools(),
            tool_sets=tool_sets(),
            timeout_seconds=180,
        ),
        conversation=True,
    )
    decision = ConsciousStepResult.model_validate(result["parsed"])
    refs = [
        app._record_analysis(state.id, note.model_dump(mode="json"))
        for note in [decision.analysis, *decision.findings]
    ]
    run = app.memory.start_run("ConsciousStep", app._program_revision(), {"task_id": state.id})
    event = app.memory.record(run, "conscious_step_result", output=decision)
    app.memory.finish_run(run)
    state.last_step_ref = json_value(app.memory.output_ref(event))
    app.memory.retain(app.memory.output_ref(event), "task:" + state.id)
    state.step_state.update(
        status="result_ready",
        pending_result=decision.model_dump(mode="json"),
        analysis_ref=refs[0],
        finding_refs=refs[1:],
    )
    state.progress, state.plan = decision.progress, [item.model_dump() for item in decision.plan]
    state.unresolved_questions = decision.unresolved_questions
    await app._integrate_step(state)
    return {"result": decision.model_dump(mode="json"), "task": state.to_dict()}


def production_revision():
    """Fingerprint production files so an opt-in evaluation cannot hide concurrent changes."""
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for path in sorted((root / "src/evertree").rglob("*")):
        if path.suffix not in {".py", ".md"}:
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


@asynccontextmanager
async def real_search_index(directory):
    """Create a private live Redis Search namespace and remove only its derived index data."""
    import os

    from redis.asyncio import Redis
    from redis.exceptions import ResponseError

    from evertree.core.semantics.config import SemanticConfig
    from evertree.core.semantics.index import RedisSearchIndex
    from evertree.debug_integration import load_debug_environment

    repository = Path(__file__).resolve().parents[2]
    config = SemanticConfig.load(repository)
    load_debug_environment(repository, config)
    missing = [
        name for name in (config.redis_url_env, config.openai_key_env) if not os.environ.get(name)
    ]
    assert not missing, "Missing live search configuration: " + ", ".join(missing)
    index = RedisSearchIndex(config, directory)
    try:
        yield index, config
    finally:
        await index.close()
        client = Redis.from_url(os.environ[config.redis_url_env])
        try:
            for raw in await client.execute_command("FT._LIST"):
                name = raw.decode() if isinstance(raw, bytes) else raw
                if name.startswith(index.namespace + ":"):
                    try:
                        await client.execute_command("FT.DROPINDEX", name, "DD")
                    except ResponseError:
                        pass
            keys = [key async for key in client.scan_iter(index.namespace + ":*")]
            if keys:
                await client.delete(*keys)
        finally:
            await client.aclose()


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
                model=MODEL,
                effort=EFFORT,
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
            provider, directory, request, transcript, tool_handler=payload.get("_tool_handler")
        )

    invocations = ProgramLLMInvocations(gateway)
    business_step = ctx.step

    async def step(method, payload, *, journal=True):
        if method == "llm.run":
            return await gateway(method, payload)
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
