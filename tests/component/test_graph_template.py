"""Starter ontology contracts, real traversal and separation from live Self state."""

import copy
import json
from itertools import pairwise

import pytest

from evertree.application import EverTree
from evertree.core.attribution import AttributionRuntime
from evertree.core.beliefs import BeliefStore
from evertree.core.graph.store import GraphStore
from evertree.core.graph.template import (
    TEMPLATE_DIRECTORY,
    install_template,
    read_template,
)
from evertree.core.graph.types import (
    GraphDelta,
    NodeUpdate,
    Prototype,
    RelationInstance,
    RelationType,
)
from evertree.core.operations import CoreOperations
from evertree.core.semantics.index import RedisSearchIndex
from evertree.core.semantics.reading import describe, search_card
from evertree.core.values import ContractError
from evertree.processes.self_semantic_processing.self_knowledge_integration._exec import _node


@pytest.fixture(scope="module")
def package():
    return read_template()


@pytest.fixture
def seeded(package):
    graph = GraphStore()
    ids = install_template(graph, provenance={"test": "template"}, package=package)
    return graph, ids


def test_minimal_bootstrap_and_template_are_distinct_and_restore_exactly(seeded, package):
    graph, ids = seeded
    minimal = GraphStore()
    minimal.bootstrap(provenance="test")
    assert len(minimal.nodes()) == 9
    assert minimal.find("Entity") is None
    assert len(ids) == len(package["nodes"])
    assert all(
        node.id in ids.values() for node in graph.nodes() if not isinstance(node, RelationInstance)
    )
    restored = GraphStore.from_snapshot(json.loads(json.dumps(graph.snapshot())))
    assert restored.snapshot() == graph.snapshot()
    assert restored.find("Entity").properties["template"]["key"] == "sumo.entity"
    assert restored.find("Self") is None
    assert not restored.nodes(kind="program")


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate_key",
        "duplicate_name",
        "cycle",
        "missing_parent",
        "abstract_signature",
        "dangling_subject",
        "dangling_role",
        "dangling_value_type",
        "bad_view",
        "dangling_view_constraint",
        "missing_projection",
        "bad_projection",
        "widen_projection",
        "unknown_source",
        "unpinned_source",
        "small_gain",
        "bad_core_contract",
        "semantic_link",
    ],
)
def test_invalid_package_is_rejected_without_partial_state(package, damage):
    broken = copy.deepcopy(package)
    nodes = {node["key"]: node for node in broken["nodes"]}
    node = nodes["rel.training_uses_data"]
    if damage == "duplicate_key":
        broken["nodes"].append(copy.deepcopy(node))
    elif damage == "duplicate_name":
        nodes["rel.about"]["name"] = " subtype_of "
    elif damage == "cycle":
        nodes["sumo.physical"]["parent"] = "sumo.process"
    elif damage == "missing_parent":
        node["parent"] = "missing"
    elif damage == "abstract_signature":
        nodes["relation.epistemic"]["signature"] = []
    elif damage == "dangling_subject":
        node["subjects"] = ["missing"]
    elif damage == "dangling_role":
        node["signature"][0]["role_concept"] = "missing"
    elif damage == "dangling_value_type":
        node["signature"][0]["value_concept"] = "missing"
    elif damage == "bad_view":
        node["views"][0]["outputs"] = ["missing"]
    elif damage == "dangling_view_constraint":
        node["views"][0]["constraints"] = {
            "all": [{"field": "training", "op": "==", "value": "missing"}]
        }
    elif damage == "missing_projection":
        del node["specialization"]
    elif damage == "bad_projection":
        node["specialization"]["roles"] = {"process": "training"}
    elif damage == "widen_projection":
        node["signature"][0]["value_concept"] = "sumo.entity"
    elif damage == "unknown_source":
        node["source"]["source"] = "missing"
    elif damage == "unpinned_source":
        node["source"]["revision"] = "latest"
    elif damage == "small_gain":
        node["adaptation"] = {
            "kind": "navigation",
            "reason": "Test policy only",
            "evidence": {
                "independent_intents": 100,
                "baseline_failures": 10,
                "candidate_failures": 9,
                "paired_ci95_lower": 0.001,
                "matched_conditions": True,
                "semantic_regressions": 0,
                "priority_regressions": 0,
                "evaluation_ref": "test-fixture",
            },
        }
    elif damage == "semantic_link":
        nodes["local.compiler"]["links"].append(
            {"relation": "rel.relation_subject", "target": "local.source_code"}
        )
    else:
        nodes["rel.subtype_of"]["views"][0]["output_arity"] = "one"
    graph = GraphStore()
    graph.bootstrap(provenance="minimal")
    before = graph.snapshot()
    with pytest.raises(ContractError):
        install_template(graph, provenance="failed", package=broken)
    assert graph.snapshot() == before


def test_late_contract_failure_rolls_back_initial_bootstrap_and_reserved_ids(package):
    broken = copy.deepcopy(package)
    next(node for node in broken["nodes"] if node["key"] == "rel.subtype_of")["views"][0][
        "output_arity"
    ] = "one"
    graph = GraphStore()
    before = graph.snapshot()
    with pytest.raises(ContractError, match="core relation contract"):
        install_template(graph, provenance="failed", package=broken)
    assert graph.snapshot() == before


def test_manifest_cannot_read_external_modules(tmp_path, package):
    manifest = copy.deepcopy(package["manifest"])
    manifest["modules"] = ["../outside.json"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ContractError, match="local JSON"):
        read_template(tmp_path)


def test_relations_have_complete_taxonomy_and_semantic_roles(seeded):
    graph, ids = seeded
    runtime = AttributionRuntime(graph, BeliefStore())
    relation = graph.get(ids["rel.training_uses_data"])
    projection = describe(graph, runtime, relation.id)
    assert projection["parent"]["id"] == ids["rel.uses_input"]
    assert relation.properties["specialization"]["roles"] == {
        "process": "training",
        "input": "data",
    }
    assert relation.properties["specialization"]["inference"] == "declaration_only"
    assert isinstance(graph.get(ids["relation.participation"]), Prototype)
    assert not isinstance(graph.get(ids["relation.participation"]), RelationType)
    indexed = search_card(graph, relation)
    assert indexed["properties"]["aliases"]["ru"]
    assert indexed["semantic_signature"][0]["role_concept"]["name"] == "ProcessRole"
    assert indexed["semantic_signature"][0]["value_concept"]["id"] == ids["local.learning_process"]
    assert indexed["semantic_links"]
    searchable = json.loads(RedisSearchIndex._text(indexed).split("\n", 1)[1])
    assert searchable["semantic_signature"][0]["role_concept"]["name"] == "ProcessRole"
    assert "id" not in searchable["semantic_signature"][0]["role_concept"]
    assert searchable["semantic_links"][0]["target"]["name"]
    assert _node(indexed)["semantic_links"] == indexed["semantic_links"]
    assert _node(indexed)["semantic_signature"] == indexed["semantic_signature"]
    assert not graph.facts("USES_INPUT")  # A declaration does not synthesize parent assertions.
    complete = describe(graph, runtime, ids["sumo.process"], focus="children")
    expected = graph.query_view("SUBTYPE_OF", "get_subtypes", supertype=ids["sumo.process"])
    assert set(complete["children"]) == {graph.get(match.value).name for match in expected}
    assert "children_total" not in complete


def test_constrained_views_resolve_symbols_and_preserve_filtering_after_restore(package):
    constrained = copy.deepcopy(package)
    relation = next(node for node in constrained["nodes"] if node["key"] == "rel.about")
    relation["views"].append(
        {
            "name": "selected_targets",
            "inputs": [],
            "outputs": ["target"],
            "constraints": {
                "all": [
                    {"field": "source", "op": "in", "value": ["sumo.entity"]},
                    {"field": "name", "op": "==", "value": "selected"},
                ]
            },
        }
    )
    graph = GraphStore()
    ids = install_template(graph, provenance="test", package=constrained)
    facts = tuple(
        RelationInstance(
            graph.reserve_id(),
            name,
            relation_type=ids["rel.about"],
            args={"source": ids[source], "target": ids[target]},
        )
        for name, source, target in (
            ("selected", "sumo.entity", "sumo.process"),
            ("excluded", "sumo.entity", "sumo.physical"),
            ("selected", "sumo.physical", "sumo.entity"),
        )
    )
    graph.apply(GraphDelta(creates=facts), provenance="test")
    restored = GraphStore.from_snapshot(json.loads(json.dumps(graph.snapshot())))
    for store in (graph, restored):
        matches = store.query_view("ABOUT", "selected_targets")
        assert [match.value for match in matches] == [ids["sumo.process"]]
        assert matches[0].source_fact.id == facts[0].id


def test_semantic_references_cannot_become_dangling(seeded):
    graph, ids = seeded
    role = ids["role.process"]
    incident = [fact.id for fact in graph.facts("SUBTYPE_OF") if fact.args["type"] == role]
    before = graph.snapshot()
    with pytest.raises(ContractError, match="semantic reference"):
        graph.apply(GraphDelta(deletes=(role, *incident)), provenance="test")
    assert graph.snapshot() == before


def test_no_reinstallation_or_silent_upgrade_of_a_live_graph(seeded, package):
    graph, _ = seeded
    before = graph.snapshot()
    with pytest.raises(ContractError, match="minimal graph"):
        install_template(graph, provenance="test", package=package)
    assert graph.snapshot() == before


def test_specialization_declaration_cannot_outlive_its_parent_link(seeded):
    graph, ids = seeded
    child = ids["rel.training_uses_data"]
    edge = next(fact for fact in graph.facts("SUBTYPE_OF") if fact.args["type"] == child)
    before = graph.snapshot()
    with pytest.raises(ContractError, match="specialization"):
        graph.apply(
            GraphDelta(
                updates=(
                    NodeUpdate(
                        edge.id,
                        {"args": {"type": child, "supertype": ids["relation.participation"]}},
                    ),
                )
            ),
            provenance="test",
        )
    assert graph.snapshot() == before


def test_new_application_has_world_self_and_programs_without_name_collisions(tmp_path):
    app = EverTree(tmp_path)
    app._bootstrap_state("0" * 40)
    graph = app.graph
    self_node = graph.find("Self")
    assert self_node.kind == "instance"
    assert (
        graph.query_view("IDENTITY_TYPE", "get_type", instance=self_node.id).value
        == graph.find("SoftwareAgent").id
    )
    own = graph.find("SelfReflection")
    assert graph.find("SelfProcess").id in {node.id for node in graph.ancestors(own.id)}
    assert graph.find("Entity").id in {node.id for node in graph.ancestors(own.id)}
    assert graph.find("SelfReflection.exec").properties["slug"] == "reflection"
    assert graph.find("ReflectionProcess").id != own.id
    assert graph.find("PlanningProcess").id != graph.find("SelfPlanning").id
    assert any(fact.args["source"] == own.id for fact in graph.facts("ABOUT"))
    operations = CoreOperations(
        graph,
        app.memory,
        app.beliefs,
        app.attribution,
        app.evaluations,
        app.learning,
        set(),
        app._protected_nodes,
    )
    edge = next(fact for fact in graph.facts("SUBTYPE_OF") if fact.args["type"] == own.id)
    for delta in (
        GraphDelta(deletes=(edge.id,)),
        GraphDelta(
            updates=(
                NodeUpdate(
                    edge.id, {"args": {"type": own.id, "supertype": graph.find("Process").id}}
                ),
            )
        ),
        GraphDelta(
            creates=(
                graph.new_fact(
                    "PART_WHOLE", {"part": self_node.id, "whole": graph.find("Entity").id}
                ),
            )
        ),
    ):
        with pytest.raises(PermissionError, match="structure"):
            operations.apply_delta(delta, task_id="test", revision="0" * 40)


def test_curated_intents_have_real_complete_top_down_routes(seeded):
    """Check declared destinations and full child reads, not an LLM's ability to select them."""
    graph, ids = seeded
    scenarios = [
        scenario
        for filename in ("scenarios.json", "world_scenarios.json")
        for scenario in json.loads((TEMPLATE_DIRECTORY / filename).read_text())["scenarios"]
    ]
    assert scenarios
    runtime = AttributionRuntime(graph, BeliefStore())
    for scenario in scenarios:
        target = ids[scenario["target"]]
        route = list(reversed(graph.ancestors(target))) + [graph.get(target)]
        assert route[0].id == ids["sumo.entity"], scenario["id"]
        for parent, child in pairwise(route):
            children = describe(graph, runtime, parent.id, focus="children")["children"]
            assert child.name in children, scenario["id"]
        assert target not in {ids[key] for key in scenario["not_targets"]}, scenario["id"]
        assert graph.get(target).description, scenario["id"]
        assert {ids[key] for key in scenario.get("expected_ancestors", [])} <= {
            node.id for node in route
        }, scenario["id"]
