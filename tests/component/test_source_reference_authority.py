"""Resolving a pointer for reading does not automatically grant integration write authority."""

import pytest

from evertree.core.memory.types import TraceOutputRef
from evertree.core.values import json_value
from tests.support.semantics import recorded_experience, semantic_world, write_action


def note(reference):
    return {
        "action": "save_note",
        "name": "Authorized material",
        "source": reference,
        "sources": [],
    }


def test_explicit_forwarded_input_authorizes_its_resolved_source():
    world = semantic_world()
    original, metadata = recorded_experience(world, "Explicitly supplied source material")
    run = world.memory.start_run("ForwardedOutput", "revision", {})
    event = world.memory.record(
        run,
        "forwarded",
        output=original[0],
        dependencies=(TraceOutputRef(**original[0]),),
    )
    world.memory.finish_run(run)
    reference = json_value(TraceOutputRef(event.id))
    assert (
        world.memory.resolve(TraceOutputRef(**reference)) == "Explicitly supplied source material"
    )
    result = write_action(world, [reference], metadata, note(reference))
    assert "error" not in result, result
    assert world.graph.get(result["object"]).description == "Explicitly supplied source material"


def test_actual_nested_data_within_supplied_source_can_ground_a_write():
    world = semantic_world()
    refs, metadata = recorded_experience(world, {"body": {"text": "A supplied nested assertion"}})
    selected = world.service.prepare_sources(
        refs, [{"source": 0, "path": ["body", "text"]}], metadata=metadata
    )["experience"][0]
    assert world.memory.resolve(TraceOutputRef(**selected["reference"])) == selected["content"]
    result = write_action(world, refs, metadata, note(selected["reference"]))
    assert "error" not in result, result
    assert world.graph.get(result["object"]).description == "A supplied nested assertion"


@pytest.mark.parametrize("prepared", [False, True])
def test_pointer_target_can_ground_a_write_when_also_explicitly_supplied(prepared):
    world = semantic_world()
    target, _ = recorded_experience(world, "Separately supplied target material")
    wrapper, metadata = recorded_experience(world, {"citation": target[0]})
    base = wrapper[0]
    if prepared:
        base = world.service.prepare_sources(
            [*wrapper, *target],
            [{"source": 0, "path": [], "keys": ["citation"]}],
            metadata=metadata,
        )["experience"][0]["reference"]
    pointer = {**base, "output_path": [*base.get("output_path", []), "citation"]}
    result = write_action(world, [*wrapper, *target], metadata, note(pointer))
    assert "error" not in result, result
    assert world.graph.get(result["object"]).description == "Separately supplied target material"


@pytest.mark.parametrize("prepared", [False, True])
def test_embedded_pointer_remains_readable_but_cannot_expand_supplied_write_sources(prepared):
    world = semantic_world()
    outside, _ = recorded_experience(world, "Earlier material outside these integration inputs")
    refs, metadata = recorded_experience(
        world, {"citation": outside[0], "observation": "Only this observation was supplied"}
    )
    base = refs[0]
    if prepared:
        base = world.service.prepare_sources(
            refs,
            [{"source": 0, "path": [], "keys": ["citation", "observation"]}],
            metadata=metadata,
        )["experience"][0]["reference"]
    pointer = {
        "event_ref": base["event_ref"],
        "output_path": [*base.get("output_path", []), "citation"],
    }
    assert (
        world.memory.resolve(TraceOutputRef(**pointer))
        == "Earlier material outside these integration inputs"
    )
    before = world.graph.snapshot()
    result = write_action(world, refs, metadata, note(pointer))
    assert "error" in result, "An embedded historical pointer must not authorize its target"
    assert world.graph.snapshot() == before


@pytest.mark.parametrize("explicit_target", [False, True])
def test_preparing_pointer_field_requires_explicit_target_and_returns_its_actual_content(
    explicit_target,
):
    world = semantic_world()
    target, _ = recorded_experience(world, "The target's source text")
    wrapper, metadata = recorded_experience(world, {"citation": target[0]})
    refs = [*wrapper, *target] if explicit_target else wrapper
    before = world.memory.snapshot()
    if not explicit_target:
        with pytest.raises(ValueError, match="outside supplied experience"):
            world.service.prepare_sources(
                refs, [{"source": 0, "path": ["citation"]}], metadata=metadata
            )
        assert world.memory.snapshot() == before
        return
    item = world.service.prepare_sources(
        refs, [{"source": 0, "path": ["citation"]}], metadata=metadata
    )["experience"][0]
    assert item["content"] == "The target's source text"
    assert world.memory.resolve(TraceOutputRef(**item["reference"])) == item["content"]
    assert "error" not in write_action(world, refs, metadata, note(item["reference"]))
