"""Actual backup files and worker calls close property source persistence boundaries."""

import json
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import timedelta
from types import SimpleNamespace

import pytest

from evertree._application.persistence import PersistenceMixin
from evertree._application.programs import ProgramsMixin
from evertree.core.attribution_sources import prepare_program_read
from evertree.core.backup import BackupManager
from evertree.core.graph.types import GraphDelta, Node, NodeUpdate
from evertree.core.runtime.controller import ProgramSpec, Runtime
from evertree.core.values import UNKNOWN, timestamp
from tests.support.runtime import TestProcess, commit_programs
from tests.support.semantics import semantic_world


class IdleRuntime:
    def __init__(self, directory):
        self.state_dir = directory

    def snapshot(self):
        return {}

    @asynccontextmanager
    async def quiesce(self, **kwargs):
        yield


async def test_exact_backup_restores_typed_read_without_live_state_or_workflows(tmp_path):
    """Real compressed files and integrity verification prove historical isolation, without startup."""
    world = semantic_world()
    subject = Node(world.graph.reserve_id(), "Parcel")
    prop = Node(
        world.graph.reserve_id(),
        "Mass",
        kind="property",
        properties={
            "attribution": {
                "source": "result",
                "scale": "numeric",
                "unit": "kg",
                "applies_to": [subject.id],
            }
        },
    )
    result = Node(
        world.graph.reserve_id(),
        "Mass estimate",
        kind="result",
        properties={
            "attribution_result": {
                "subject": subject.id,
                "property": prop.id,
                "conditions": {},
                "value_U": {"kind": "interval", "lower": 1000, "upper": 3000},
                "unit": "g",
            }
        },
    )
    world.graph.apply(GraphDelta(creates=(subject, prop, result)), provenance="measurement")
    world.beliefs.register_binary(f"graph:{result.id}", prior=0.3)
    owner = PersistenceMixin()
    owner.backups = BackupManager(tmp_path / "backups")
    saved = await owner.backups.create(
        IdleRuntime(tmp_path / "runtime"),
        lambda: {
            "graph": world.graph.snapshot(),
            "beliefs": world.beliefs.snapshot(),
            "attribution": world.attribution.snapshot(),
            "memory": world.memory.snapshot(),
        },
    )
    at = timestamp(json.loads((saved / "manifest.json").read_text())["created_at"])
    world.attribution.historical_loader = owner._historical_attribution
    world.beliefs.assign(f"graph:{result.id}", "new evidence", 4, backed=True)
    direct = world.attribution.read_property(subject.id, prop.id, valid_at=at, known_at=at)
    assert direct.belief_data.strength == 0.3
    assert world.attribution.read_property(subject.id, prop.id).belief_data.strength > 0.3
    assert (
        world.attribution.read_property(subject.id, prop.id, known_at=at + timedelta(days=1))
        is UNKNOWN
    )
    updated = {
        **result.properties["attribution_result"],
        "value_U": {"kind": "interval", "lower": 4000, "upper": 6000},
    }
    world.graph.apply(
        GraphDelta(
            updates=(NodeUpdate(result.id, {"properties": {"attribution_result": updated}}),)
        ),
        provenance="new measurement",
    )
    before = world.graph.snapshot()
    old = world.attribution.reconstruct_property(subject.id, prop.id, valid_at=at, known_at=at)
    assert dict(old.value_U) == {"kind": "interval", "lower": 1, "upper": 3}
    assert world.attribution.read_property(subject.id, prop.id).value_U["lower"] == 4
    assert world.graph.snapshot() == before
    assert owner._historical_attribution(at + timedelta(microseconds=1)) is None
    historical = owner._historical_attribution(at)
    assert historical.memory is not world.memory
    with pytest.raises(PermissionError, match="read-only"):
        historical.graph.apply(GraphDelta(), provenance="forbidden")
    world.graph.apply(GraphDelta(deletes=(result.id, prop.id)), provenance="remove current result")
    before = world.graph.snapshot()
    assert world.attribution.read_property(subject.id, prop.id) is UNKNOWN
    assert (
        world.attribution.read_property(subject.id, prop.id, valid_at=at, known_at=at).value_U
        == old.value_U
    )
    (saved / "state.msgpack.zst").write_bytes(b"corrupted")
    assert (
        world.attribution.reconstruct_property(subject.id, prop.id, valid_at=at, known_at=at)
        is UNKNOWN
    )
    assert world.graph.snapshot() == before


async def test_property_model_child_executes_and_replays_over_worker_ipc(tmp_path):
    """DBOS and worker IPC prove the model child is outside a step and completed reads replay."""
    parent_path, child_path = (
        "src/evertree/processes/reader.py",
        "src/evertree/processes/estimate.py",
    )
    revision = commit_programs(
        tmp_path / "repository",
        {
            parent_path: """from evertree.core.graph.api import read
from evertree.core.contracts import ProgramResult
async def run(ctx, subject, property):
    return ProgramResult(await read(ctx, 'read_property', {'subject': subject, 'property': property, 'parameters': {'loaded': True}}))
""",
            child_path: """from evertree.core.contracts import ProgramResult
async def run(ctx, subject, property, valid_at, known_at, parameters):
    return ProgramResult({'subject': subject, 'property': property, 'valid_at': valid_at,
        'known_at': known_at, 'conditions': parameters,
        'value_U': {'kind': 'interval', 'lower': 1000, 'upper': 3000}, 'unit': 'g'})
""",
        },
    )
    world = semantic_world()
    subject = Node(world.graph.reserve_id(), "Parcel")
    child = Node(
        world.graph.reserve_id(),
        "Mass.model",
        kind="program",
        properties={"role": "model", "lifecycle_status": "active"},
    )
    parent = Node(
        world.graph.reserve_id(), "Property reader", kind="program", properties={"role": "model"}
    )
    prop = Node(
        world.graph.reserve_id(),
        "Mass",
        kind="property",
        properties={
            "attribution": {
                "source": "program",
                "program": child.id,
                "unit": "kg",
                "required_parameters": ["loaded"],
                "applies_to": [subject.id],
            }
        },
    )
    world.graph.apply(GraphDelta(creates=(subject, child, parent, prop)), provenance="binding")
    parent_spec, child_spec = (
        ProgramSpec(parent.id, parent_path, revision, role="model"),
        ProgramSpec(child.id, child_path, revision, role="model"),
    )
    calls, traces = [], []
    task = SimpleNamespace(program_run_ids=[])
    trace_owner = SimpleNamespace(
        memory=world.memory,
        graph=world.graph,
        _run_map={},
        _operator_seq={},
        tasks=SimpleNamespace(get=lambda _: task),
        _program_source=lambda spec: (tmp_path / "repository" / spec["git_path"]).read_text(),
    )

    async def gateway(method, payload):
        arguments = dict(payload)
        metadata = arguments.pop("_runtime")
        calls.append(method)
        if method == "resolve_program":
            assert arguments["program_id"] == child.id
            return asdict(child_spec)
        return world.operations.execute(method, arguments, metadata=metadata)

    async def trace(event):
        traces.append(event)
        await ProgramsMixin._runtime_trace(trace_owner, event)

    runtime = Runtime(
        tmp_path / "runtime", tmp_path / "repository", gateway, trace, process_factory=TestProcess
    )
    try:
        before = world.graph.snapshot()
        arguments = {"subject": subject.id, "property": prop.id}
        result = await runtime.execute("task", parent_spec, arguments, run_id="read")
        assert result.result["value_U"] == {"kind": "interval", "lower": 1, "upper": 3}
        assert result.result["belief_data"] is None
        assert world.graph.snapshot() == before
        assert sum(event["type"] == "run_started" for event in traces) == 2
        assert calls.count("attribution.finish_read") == 1
        owner = PersistenceMixin()
        owner.backups = BackupManager(tmp_path / "backups")
        saved = await owner.backups.create(
            runtime,
            lambda: {
                "graph": world.graph.snapshot(),
                "beliefs": world.beliefs.snapshot(),
                "attribution": world.attribution.snapshot(),
                "memory": world.memory.snapshot(),
            },
        )
        known_at = timestamp(json.loads((saved / "manifest.json").read_text())["created_at"])
        historical = owner._historical_attribution(known_at)
        child_run = next(run for run in world.memory.runs if run.program == child.id)
        computed_at = timestamp(child_run.arguments["valid_at"])
        retained = prepare_program_read(
            historical,
            subject.id,
            prop.id,
            valid_at=computed_at,
            known_at=known_at,
            parameters={"loaded": True},
        )
        assert dict(retained.value_U) == result.result["value_U"]
        assert retained.known_at == known_at and retained.belief_data is None
        assert retained.provenance["revision"] == revision
        reference = retained.provenance["result"]
        assert reference["event_ref"] in {event.id for event in world.memory.events}
        assert (
            historical.reconstruct_property(
                subject.id, prop.id, valid_at=computed_at, known_at=known_at, loaded=True
            )
            == retained
        )
        assert (
            prepare_program_read(
                historical,
                subject.id,
                prop.id,
                valid_at=computed_at + timedelta(microseconds=1),
                known_at=known_at,
                parameters={"loaded": True},
            )
            is UNKNOWN
        )
        assert sum(event["type"] == "run_started" for event in traces) == 2
        again = await runtime.execute("task", parent_spec, arguments, run_id="read")
        assert again.result == result.result
        assert calls.count("attribution.finish_read") == 1
    finally:
        await runtime.close()


def test_historical_bound_program_cannot_borrow_current_executable():
    world = semantic_world()
    subject = Node(world.graph.reserve_id(), "Parcel")
    child = Node(
        world.graph.reserve_id(),
        "Mass.model",
        kind="program",
        properties={"role": "model", "lifecycle_status": "active"},
    )
    prop = Node(
        world.graph.reserve_id(),
        "Mass",
        kind="property",
        properties={"attribution": {"source": "program", "program": child.id}},
    )
    world.graph.apply(GraphDelta(creates=(subject, child, prop)), provenance="binding")
    world.graph.known_at = timestamp("2026-01-01T00:00:00+00:00")
    assert (
        prepare_program_read(world.attribution, subject.id, prop.id, known_at=world.graph.known_at)
        is UNKNOWN
    )
