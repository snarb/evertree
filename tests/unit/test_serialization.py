import importlib
import math
import pickle
from datetime import UTC, datetime
from typing import get_type_hints

import msgpack
import pytest
import zstandard

from evertree._application.prompts import AnswerVerification, Decision
from evertree.core.cognition.tasks import TaskSpecification
from evertree.core.evaluation.contracts import SupervisorFeedback
from evertree.core.graph.store import GraphStore
from evertree.core.graph.types import GraphDelta, Node
from evertree.core.learning.contracts import LearningObjective
from evertree.core.memory.store import TraceStore
from evertree.core.serialization import decode_snapshot, encode_snapshot
from evertree.core.values import UNKNOWN


def test_snapshot_preserves_scalar_types_unicode_and_arbitrary_integers():
    values = [
        None,
        False,
        True,
        0,
        1,
        1.0,
        -0.0,
        "Память 🌳",
        [],
        {},
        -(2**63),
        2**64 - 1,
        -(2**63) - 1,
        2**64,
        -(2**20000),
        2**20000,
    ]
    restored = decode_snapshot(encode_snapshot(values))
    assert restored == values
    assert [type(value) for value in restored] == [type(value) for value in values]
    assert math.copysign(1, restored[6]) == -1


def test_graph_history_and_trace_references_survive_compressed_snapshot():
    memory = TraceStore()
    run = memory.start_run("program", "commit", {"text": "Опыт"})
    event = memory.record(run, "observation", output={"value": 2**100})
    reference = memory.output_ref(event)
    memory.record(run, "derived", output={"accepted": True}, dependencies=(reference,))
    memory.finish_run(run)
    graph = GraphStore()
    node = Node(
        graph.reserve_id(),
        "Knowledge",
        properties={
            "unknown": UNKNOWN,
            "at": datetime(2026, 10, 5, tzinfo=UTC),
            "set": frozenset({1, 2}),
            "reserved": {"$unknown": True},
            "integer": 2**100,
        },
    )
    graph.apply(GraphDelta(creates=(node,)), provenance=reference)
    graph.activate(node.id, "attention", 0.5)
    snapshot = {"graph": graph.snapshot(), "memory": memory.snapshot()}
    restored = decode_snapshot(encode_snapshot(snapshot))
    restored_graph = GraphStore.from_snapshot(restored["graph"])
    restored_memory = TraceStore.from_snapshot(restored["memory"])
    assert restored_graph.snapshot() == graph.snapshot()
    assert restored_memory.snapshot() == memory.snapshot()
    assert restored_graph.get(node.id).properties["unknown"] is UNKNOWN
    assert dict(restored_graph.get(node.id).properties["reserved"]) == {"$unknown": True}
    assert restored_memory.resolve(reference)["value"] == 2**100


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_values_are_rejected_on_write_and_read(value):
    with pytest.raises(ValueError, match="Non-finite"):
        encode_snapshot({"nested": [value]})
    packed = msgpack.packb({"nested": [value]})
    with pytest.raises(ValueError, match="Non-finite"):
        decode_snapshot(zstandard.ZstdCompressor().compress(packed))


@pytest.mark.parametrize("value", [b"unsupported", {1: "non-string key"}, {1, 2}])
def test_values_outside_the_snapshot_contract_are_rejected(value):
    with pytest.raises(TypeError):
        encode_snapshot(value)


def test_truncated_corrupt_and_trailing_data_are_rejected():
    encoded = encode_snapshot({"state": "memory" * 1000})
    damaged = bytearray(encoded)
    damaged[-1] ^= 1
    invalid = [b"not zstd", encoded[:-1], bytes(damaged), encoded + b"extra", encoded * 2]
    invalid.append(zstandard.ZstdCompressor().compress(b"\xc1"))
    invalid.append(zstandard.ZstdCompressor().compress(msgpack.packb(1) + msgpack.packb(2)))
    for payload in invalid:
        with pytest.raises(ValueError, match="Invalid compressed snapshot"):
            decode_snapshot(payload)


@pytest.mark.parametrize("extension", [msgpack.ExtType(2, b"unknown"), msgpack.ExtType(1, b"")])
def test_unknown_or_empty_extensions_are_rejected(extension):
    encoded = zstandard.ZstdCompressor().compress(msgpack.packb(extension))
    with pytest.raises(ValueError, match="snapshot extension"):
        decode_snapshot(encoded)


@pytest.mark.parametrize(
    ("module_name", "name"),
    [
        ("evertree.core.graph.types", "Node"),
        ("evertree.core.memory.types", "TraceEvent"),
        ("evertree.core.memory.types", "RetentionPolicy"),
        ("evertree.core.cognition.tasks", "TaskState"),
        ("evertree.core.learning.contracts", "LearningSignal"),
        ("evertree.core.evaluation.contracts", "EvaluationResult"),
        ("evertree.core.evaluation.acceptance", "AcceptanceCriteria"),
        ("evertree.core.sandbox.appcontainer", "SandboxLimits"),
        ("evertree.core.runtime.controller", "ProgramSpec"),
        ("evertree.core.runtime.controller", "RunResult"),
        ("evertree._application.prompts", "Decision"),
        ("evertree._application.prompts", "AnswerVerification"),
    ],
)
def test_defined_types_support_pickle_and_resolve_annotations(module_name, name):
    defined_type = getattr(importlib.import_module(module_name), name)
    assert defined_type.__module__ == module_name
    assert pickle.loads(pickle.dumps(defined_type)) is defined_type
    assert get_type_hints(defined_type)


@pytest.mark.parametrize(
    ("value", "type_name"),
    [
        (Node(1, "Knowledge"), "evertree.core.graph.types.Node"),
        (TaskSpecification("Read a source"), "evertree.core.cognition.tasks.TaskSpecification"),
        (SupervisorFeedback(1), "evertree.core.evaluation.contracts.SupervisorFeedback"),
        (
            LearningObjective(("brier",), "minimize"),
            "evertree.core.learning.contracts.LearningObjective",
        ),
        (
            Decision(status="completed", answer="Done", progress="Verified"),
            "evertree._application.prompts.Decision",
        ),
        (
            AnswerVerification(verified=True, reason="Checked"),
            "evertree._application.prompts.AnswerVerification",
        ),
    ],
)
def test_trace_records_defining_module_and_preserves_it_in_snapshot(value, type_name):
    memory = TraceStore()
    run = memory.start_run("program", "commit", {})
    event = memory.record(run, "result", output=value)
    assert event.output_type == type_name
    restored = TraceStore.from_snapshot(decode_snapshot(encode_snapshot(memory.snapshot())))
    assert restored.get_event(event.id).output_type == type_name
