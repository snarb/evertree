"""Exact source preparation crosses the native worker boundary only for admitted exec Programs."""

import os
import sys

import pytest

from evertree.core.memory.types import TraceOutputRef
from evertree.core.operations import authorize_operation
from evertree.core.runtime.controller import ProgramSpec, Runtime
from evertree.core.runtime.repository import ProgramExecutionError
from evertree.core.values import json_value
from tests.support.runtime import commit_programs
from tests.support.semantics import semantic_world

pytestmark = pytest.mark.skipif(
    os.name != "nt" and sys.platform != "darwin", reason="Native macOS/Windows isolation"
)


@pytest.mark.parametrize("role", ["exec", "model"])
async def test_native_source_preparation_preserves_exact_writes_and_rejects_model_role(
    tmp_path, role
):
    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "program.py": """
from evertree.core.semantics import api as semantics

async def run(ctx, experience_refs, section):
    prepared = await semantics.prepare_sources(ctx, experience_refs, [section])
    source = prepared["experience"][0]
    saved = await semantics.write(
        ctx,
        {"action": "save_note", "name": "Exact native source", "source": source["reference"],
         "sources": []},
        operation_key="native-section:1", experience_refs=experience_refs,
    )
    return {"result": {"source": source, "saved": saved}}
"""
        },
    )
    world = semantic_world()
    preceding = "Station Cedar owns this reading. " + "context " * 70
    body = "Earlier unrelated material. " * 80 + "\n\n" + preceding + "\n\n"
    body += "Точный факт: 17 kg. Final qualification."
    start, end = body.index("Точный"), body.index("Final")
    run = world.memory.start_run("Article", revision, {})
    event = world.memory.record(run, "observation", output={"title": "Source", "body": body})
    world.memory.finish_run(run)
    original = json_value(world.memory.output_ref(event))
    calls = []

    async def gateway(method, payload):
        payload = dict(payload)
        metadata = payload.pop("_runtime")
        calls.append(method)
        authorize_operation(method, metadata["program"]["role"])
        metadata.update(
            knowledge_integration_authorized=True,
            integration_operation_id="native-preparation",
            integration_context={},
        )
        return await world.service.execute(method, payload, metadata)

    runtime = Runtime(tmp_path / "runtime", repository, gateway)
    spec = ProgramSpec(1, "program.py", revision, role=role)
    arguments = {
        "experience_refs": [original],
        "section": {"source": 0, "path": ["body"], "start": start, "end": end},
    }
    try:
        if role == "model":
            before = world.memory.snapshot()
            with pytest.raises(ProgramExecutionError, match="model Program cannot perform effects"):
                await runtime.execute("task", spec, arguments, timeout=30)
            assert calls == ["semantic.prepare_sources"]
            assert world.memory.snapshot() == before
            assert world.graph.find("Exact native source") is None
            return

        result = await runtime.execute(
            "task", spec, arguments, run_id="source-preparation", timeout=30
        )
        source, saved = result.result["source"], result.result["saved"]
        assert "error" not in saved, saved
        assert source["content"] == body[start:end]
        assert source["reference"] != original
        assert source["reference"]["output_path"] == ["text"]
        assert source["source_reference"] == original
        assert source["source_context"][-1]["preceding_text"] == preceding + "\n\n"
        assert world.memory.resolve(TraceOutputRef(**source["reference"])) == body[start:end]
        node = world.graph.get(saved["object"])
        assert node.description == body[start:end]
        assert json_value(node.properties["source_ref"]) == source["reference"]
        assert calls == ["semantic.prepare_sources", "semantic.write"]
        before = world.memory.snapshot()
        replayed = await runtime.execute(
            "task", spec, arguments, run_id="source-preparation", timeout=30
        )
        assert replayed == result
        assert calls == ["semantic.prepare_sources", "semantic.write"]
        assert world.memory.snapshot() == before
        assert len(world.graph.changes_of(node.id)) == 1
    finally:
        await runtime.close()
