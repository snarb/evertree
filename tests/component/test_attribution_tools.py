"""Source-backed property declarations and their shared public reading boundary."""

from datetime import UTC, datetime

import pytest

from evertree._application.prompts import semantic_tools, tool_sets
from evertree.common.integration_actions import SemanticTools
from evertree.core.graph.types import GraphDelta, Node, Prototype
from evertree.core.memory.types import TraceOutputRef
from evertree.core.semantics.api import summarize_property
from evertree.core.semantics.reading import describe
from evertree.core.values import ContractError
from evertree.processes.semantic_processing.knowledge_integration._exec import _describe_for_model
from tests.support.semantics import context, recorded_experience, semantic_world, write_action


def declaration_world():
    world = semantic_world()
    graph = world.graph
    domain = Prototype(graph.reserve_id(), "Dog")
    classes = tuple(Node(graph.reserve_id(), name) for name in ("Small", "Medium", "Large"))
    graph.apply(GraphDelta(creates=(domain, *classes)), provenance="fixture")
    refs, metadata = recorded_experience(world, "Dog mass uses kg; this guide uses 10 and 25 kg.")
    action = {
        "action": "create_property",
        "name": "Body mass",
        "description": "Mass of an individual animal",
        "unit": "kg",
        "applies_to": [domain.id],
        "sources": refs,
    }
    result = write_action(world, refs, metadata, action, key="property")
    assert "error" not in result, result
    return world, domain, classes, refs, metadata, result["object"]


@pytest.mark.parametrize("action_name", ["create_property", "create_property_reference"])
def test_numeric_declaration_rejected_name_can_be_corrected_and_retried(action_name):
    world, domain, classes, refs, metadata, property_id = declaration_world()
    action = {
        "action": action_name,
        "name": "Published adult dog mass",
        "description": "A source-qualified mass definition",
        "unit": "kg",
        "sources": refs,
    }
    if action_name == "create_property":
        action["applies_to"] = [domain.id]
    else:
        action.update(
            property=property_id,
            domain=domain.id,
            reference_kind="bands",
            boundaries=[10, 25],
            classes=[node.id for node in classes],
            samples=[],
            conditions={},
        )
    before = world.graph.snapshot()
    rejected = write_action(world, refs, metadata, action, key="name-repair")
    assert "contain 1–3 words" in rejected["error"]
    assert world.graph.snapshot() == before
    action["name"] = "Adult mass guide" if action_name.endswith("reference") else "Adult mass"
    written = write_action(world, refs, metadata, action, key="name-repair")
    assert "error" not in written, written
    node = world.graph.get(written["object"])
    assert node.name == action["name"]
    change = world.graph.changes_of(node.id)[-1]
    event = world.memory.get_event(change.provenance["event_ref"])
    assert event.dependencies == tuple(TraceOutputRef(**ref) for ref in refs)


@pytest.mark.parametrize(
    ("reference_kind", "boundary_inclusive"),
    [("bands", None), ("bands", [False, True]), ("distribution", None)],
)
@pytest.mark.parametrize("conditions", [{}, {"exercise_state": "resting"}])
def test_property_reference_write_preserves_contract_sources_and_retry(
    reference_kind, boundary_inclusive, conditions
):
    world, domain, classes, refs, metadata, property_id = declaration_world()
    action = {
        "action": "create_property_reference",
        "name": "Dog mass reference",
        "description": "Published club reference for dogs; reported by the guide, not measured by us",
        "property": property_id,
        "domain": domain.id,
        "unit": "kg",
        "reference_kind": reference_kind,
        "boundaries": [10, 25] if reference_kind == "bands" else [],
        "classes": [node.id for node in classes] if reference_kind == "bands" else [],
        "samples": [{"lower": 5, "upper": 10, "count": 3}]
        if reference_kind == "distribution"
        else [],
        "conditions": conditions,
        "sources": refs,
    }
    if boundary_inclusive is not None:
        action["boundary_inclusive"] = boundary_inclusive
    result = write_action(world, refs, metadata, action, key="reference")
    assert "error" not in result, result
    reference_id = result["object"]
    graph = world.graph
    assert graph.get(property_id).kind == "property"
    assert world.attribution.definitions()[property_id].unit == "kg"
    view = _describe_for_model(describe(graph, world.attribution, reference_id))
    definition = view["subject"]["properties"]["numeric_reference"]
    for field in ("property", "domain", "unit", "reference_kind", "conditions"):
        assert definition[field] == action[field]
    assert definition["samples"] == action["samples"]
    assert definition["boundary_inclusive"] == (
        boundary_inclusive if boundary_inclusive is not None else [True] * len(action["boundaries"])
    )
    summary = world.attribution.summarize_property(domain.id, property_id, **conditions)
    assert [item["id"] for item in summary["references"]] == [reference_id]
    if reference_kind == "bands":
        summary = world.attribution.summarize_property(
            domain.id, property_id, value=10, unit="kg", **conditions
        )
        assert (
            summary["references"][0]["interpretation"]["class"]["id"]
            == classes[1 if boundary_inclusive == [False, True] else 0].id
        )
    change = graph.changes_of(reference_id)[-1]
    event = world.memory.get_event(change.provenance["event_ref"])
    assert event.dependencies == tuple(TraceOutputRef(**ref) for ref in refs)
    before = graph.snapshot()
    assert write_action(world, refs, metadata, action, key="reference") == result
    assert graph.snapshot() == before
    foreign, _ = recorded_experience(world, "Not supplied to this write")
    rejected = write_action(
        world, refs, metadata, {**action, "sources": foreign}, key="unauthorized"
    )
    assert "outside supplied experience" in rejected["error"]
    assert graph.snapshot() == before


async def test_semantic_property_creation_reads_domain_before_writing():
    world = semantic_world()
    refs, _ = recorded_experience(world, "Dog mass is measured in kg")
    ctx = context(world, None, role="exec")

    async def search(query):
        return (await ctx.call("semantic_search", {"query": query})).result

    async def describe_subject(subject):
        return await ctx.step("graph.describe", {"subject": subject})

    async def write(action, operation_key):
        return await ctx.step(
            "semantic.write",
            {"action": action, "operation_key": operation_key, "experience_refs": refs},
        )

    handler = SemanticTools(search=search, describe=describe_subject, write=write)
    result = await handler.handle(
        "create_property",
        {
            "name": "Body mass",
            "description": None,
            "unit": "kg",
            "applies_to": [999999],
            "sources": refs,
        },
    )
    assert "could not be resolved" in result["error"]
    assert world.graph.find("Body mass") is None
    assert any(read["tool"] == "describe" for read in result["reads"])


def test_reference_retries_after_repairing_existing_property_population():
    """A mistaken Concept scope can be corrected without replacing the saved property."""
    world, domain, classes, refs, metadata, property_id = declaration_world()
    concept = Node(world.graph.reserve_id(), "Guide population")
    world.graph.apply(GraphDelta(creates=(concept,)), provenance="fixture")
    properties = {"attribution": {"unit": "kg", "applies_to": [concept.id]}}
    update = {
        "action": "update",
        "object": property_id,
        "changes": {"properties": properties},
        "sources": refs,
    }
    assert "error" not in write_action(world, refs, metadata, update, key="mistaken-scope")
    reference = {
        "action": "create_property_reference",
        "name": "Club guide",
        "description": "Club size categories for all dogs",
        "property": property_id,
        "domain": concept.id,
        "unit": "kg",
        "reference_kind": "bands",
        "boundaries": [10, 25],
        "classes": [node.id for node in classes],
        "samples": [],
        "conditions": {},
        "sources": refs,
    }
    before = world.graph.snapshot()
    rejected = write_action(world, refs, metadata, reference, key="retry-reference")
    assert "population type" in rejected["error"]
    assert world.graph.snapshot() == before
    properties["attribution"]["applies_to"] = [domain.id]
    assert "error" not in write_action(world, refs, metadata, update, key="repaired-scope")
    reference["domain"] = domain.id
    result = write_action(world, refs, metadata, reference, key="retry-reference")
    assert "error" not in result, result
    assert [node.id for node in world.graph.nodes(kind="property")] == [property_id]
    report = world.attribution.summarize_property(domain.id, property_id, value=7, unit="kg")
    assert report["references"][0]["id"] == result["object"]
    assert report["references"][0]["interpretation"]["class"]["id"] == classes[0].id


async def test_summary_public_wrapper_resolves_names_preserves_report_and_time(monkeypatch):
    """Only the runtime boundary is substituted; this checks shared tool routing, not statistics."""
    world, domain, _classes, _refs, _metadata, property_id = declaration_world()
    report = {"belief_data": None, "qualification": "unassessed", "sources": []}
    calls = []

    def summarize(*args, **kwargs):
        calls.append((args, kwargs))
        return report

    monkeypatch.setattr(world.attribution, "summarize_property", summarize, raising=False)
    ctx = context(world, None, role="model")
    assert await summarize_property(ctx, "Dog", "Body mass", value=12, unit="kg") == report
    assert calls[-1][0] == (domain.id, property_id)
    assert calls[-1][1]["valid_at"] is None
    await summarize_property(
        ctx, "Dog", "Body mass", at="2026-01-01T00:00:00Z", parameters={"age": "adult"}
    )
    assert calls[-1][1]["valid_at"] == datetime(2026, 1, 1, tzinfo=UTC)
    assert calls[-1][1]["age"] == "adult"
    with pytest.raises(ContractError, match="non-reserved"):
        await summarize_property(ctx, "Dog", "Body mass", parameters={"domain": "Cat"})
    assert len(calls) == 2
    assert "graph.summarize_property" in {tool.name for tool in semantic_tools()}
    writes = next(group for group in tool_sets() if group.name == "graph_write_tools")
    assert {"graph.create_property", "graph.create_property_reference"} <= {
        tool.name for tool in writes.tools
    }


@pytest.mark.parametrize("reference_kind", ["distribution", "bands"])
def test_large_reference_describe_bounds_model_preview_without_changing_source(reference_kind):
    world, domain, _classes, refs, metadata, property_id = declaration_world()
    classes = tuple(Node(world.graph.reserve_id(), f"Band {i}") for i in range(26))
    world.graph.apply(GraphDelta(creates=classes), provenance="fixture")
    action = {
        "action": "create_property_reference",
        "name": "Large mass reference",
        "description": "A published table",
        "property": property_id,
        "domain": domain.id,
        "unit": "kg",
        "reference_kind": reference_kind,
        "boundaries": list(range(25)) if reference_kind == "bands" else [],
        "classes": [node.id for node in classes] if reference_kind == "bands" else [],
        "samples": [{"lower": i, "upper": i, "count": 1} for i in range(25)]
        if reference_kind == "distribution"
        else [],
        "conditions": {},
        "sources": refs,
    }
    written = write_action(world, refs, metadata, action, key="large-reference")
    assert "error" not in written, written
    reference_id = written["object"]
    stored = world.graph.get(reference_id).properties["numeric_reference"]
    output = world.operations.execute(
        "graph.describe", {"subject": reference_id}, metadata=metadata
    )
    preview = _describe_for_model(output)["subject"]["properties"]["numeric_reference"]
    assert preview["truncated"] is True
    assert "query" in preview["details"]
    if reference_kind == "distribution":
        assert len(preview["samples"]) == 20
        assert preview["samples_total"] == len(stored["samples"]) == 25
    else:
        assert len(preview["boundaries"]) == len(preview["boundary_inclusive"]) == 20
        assert len(preview["classes"]) == 21
        assert preview["boundaries_total"] == len(stored["boundaries"]) == 25
        assert preview["boundary_inclusive_total"] == len(stored["boundary_inclusive"]) == 25
        assert preview["classes_total"] == len(stored["classes"]) == 26
    assert "truncated" not in stored
