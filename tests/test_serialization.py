"""Compressed snapshots preserve persistent values and reject invalid data."""

import math
from datetime import UTC, datetime

import msgpack
import pytest
import zstandard

from evertree.core.graph import UNKNOWN, GraphDelta, GraphStore, Node
from evertree.core.memory import TraceStore
from evertree.core.serialization import decode_snapshot, encode_snapshot


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
