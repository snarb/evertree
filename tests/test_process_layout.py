"""Source/graph drift must block publication and Program activation."""

from pathlib import Path

import pytest

from evertree.core.graph import GraphDelta, GraphStore, Node, NodeUpdate, Prototype
from evertree.core.programs.bootstrap import seed_process_delta
from evertree.core.programs.layout import PREFIX, process_directory, validate_process_layout


@pytest.fixture
def seed_tree():
    graph = GraphStore()
    graph.bootstrap(provenance={"test": True})
    self_node = Node(graph.reserve_id(), "Self")
    graph.apply(GraphDelta(creates=(self_node,)), provenance={"test": True})
    graph.apply(
        seed_process_delta(graph, self_id=self_node.id, revision="0" * 40),
        provenance={"test": True},
    )
    repository = Path(__file__).resolve().parents[1]
    sources = {
        path.relative_to(repository).as_posix(): path.read_text(encoding="utf-8")
        for path in (repository / PREFIX).rglob("*.py")
    }
    return graph, sources


def update(graph, node, **properties):
    graph.apply(
        GraphDelta(
            updates=(NodeUpdate(node.id, {"properties": {**node.properties, **properties}}),)
        ),
        provenance={"test": True},
    )


def test_own_process_tree_preserves_general_process_and_role_semantics(seed_tree):
    graph, sources = seed_tree
    validate_process_layout(graph, sources, sources.__getitem__)
    assert [node.name for node in graph.ancestors(graph.find("Planning").id)] == [
        "TaskManagement",
        "SelfProcess",
        "Process",
    ]
    assert (
        process_directory(graph, graph.find("Planning").id) == PREFIX + "task_management/planning"
    )
    assert graph.find("Self").id not in {
        node.id for node in graph.ancestors(graph.find("Process").id)
    }
    assert all(node.properties["role"] == "exec" for node in graph.nodes(kind="program"))


@pytest.mark.parametrize(
    "damage",
    ["missing", "unregistered", "entrypoint", "binding", "role", "taxonomy_init", "membership"],
)
def test_source_graph_drift_is_rejected(seed_tree, damage):
    graph, sources = seed_tree
    program = graph.find("Planning.exec")
    path = program.properties["git_path"]
    if damage == "missing":
        sources.pop(path)
    elif damage == "unregistered":
        sources[PREFIX + "other/_exec.py"] = "def run(): return 1"
    elif damage == "entrypoint":
        sources[path] = "def wrong(): return 1"
    elif damage == "binding":
        update(graph, graph.find("Planning"), active_exec=None)
    elif damage == "role":
        update(graph, program, role="model", roles=("model",))
        update(graph, graph.find("Planning"), active_exec=None, active_model=program.id)
    elif damage == "taxonomy_init":
        sources[PREFIX + "task_management/__init__.py"] = "from .planning._exec import run"
    else:
        root = graph.find("SelfProcess")
        fact = next(fact for fact in graph.facts("PART_WHOLE") if fact.args["part"] == root.id)
        graph.apply(GraphDelta(deletes=(fact.id,)), provenance={"test": True})
    with pytest.raises(ValueError):
        validate_process_layout(graph, sources, sources.__getitem__)


def test_model_and_exec_are_distinct_programs_with_one_version_per_role(seed_tree):
    graph, sources = seed_tree
    process = graph.find("Planning")
    path = process_directory(graph, process.id) + "/_model.py"
    model = Node(
        graph.reserve_id(),
        "Planning.model",
        kind="program",
        properties={
            "process": process.id,
            "role": "model",
            "roles": ("model",),
            "git_path": path,
            "active": True,
        },
    )
    graph.apply(
        GraphDelta(
            creates=(
                model,
                graph.new_fact("PROGRAM_FOR_PROCESS", {"program": model.id, "process": process.id}),
            )
        ),
        provenance={"test": True},
    )
    update(graph, process, active_model=model.id)
    sources[path] = "def run(plan): return {'predicted_cost': len(plan)}"
    validate_process_layout(graph, sources, sources.__getitem__)


def test_role_package_allows_helpers_and_inactive_proposal_does_not_require_main_code(seed_tree):
    graph, sources = seed_tree
    program = graph.find("Planning.exec")
    old = program.properties["git_path"]
    new = old.removesuffix(".py") + "/implementation.py"
    sources[new] = sources.pop(old)
    sources[old.removesuffix(".py") + "/helper.py"] = "def helper(): return 1"
    update(graph, program, git_path=new)
    validate_process_layout(graph, sources, sources.__getitem__)
    update(graph, program, active=False)
    for path in list(sources):
        if (
            path.startswith(old.removesuffix(".py") + "/")
            or path == old.removesuffix("_exec.py") + "__init__.py"
        ):
            sources.pop(path)
    validate_process_layout(graph, sources, sources.__getitem__)
    with pytest.raises(ValueError, match="Missing committed"):
        validate_process_layout(
            graph, sources, sources.__getitem__, candidate_program_id=program.id
        )


@pytest.mark.parametrize("registered_package", [False, True])
def test_role_cannot_have_both_file_and_package(seed_tree, registered_package):
    graph, sources = seed_tree
    program = graph.find("Planning.exec")
    path = program.properties["git_path"]
    package_entrypoint = path.removesuffix(".py") + "/implementation.py"
    sources[package_entrypoint] = sources[path]
    if registered_package:
        update(graph, program, git_path=package_entrypoint)
    with pytest.raises(ValueError, match="both a file and a package"):
        validate_process_layout(graph, sources, sources.__getitem__)


def test_candidate_subtype_keeps_parent_directory_with_inactive_parent_program(seed_tree):
    graph, sources = seed_tree
    parent = graph.find("Planning")
    parent_program = graph.find("Planning.exec")
    update(graph, parent_program, active=False)
    sources.pop(parent_program.properties["git_path"])
    child = Prototype(graph.reserve_id(), "BudgetPlanning", properties={"process": True})
    path = process_directory(graph, parent.id) + "/budget_planning/_exec.py"
    program = Node(
        graph.reserve_id(),
        "BudgetPlanning.exec",
        kind="program",
        properties={"process": child.id, "role": "exec", "git_path": path, "active": False},
    )
    graph.apply(
        GraphDelta(
            creates=(
                child,
                program,
                graph.new_fact("SUBTYPE_OF", {"type": child.id, "supertype": parent.id}),
                graph.new_fact("PROGRAM_FOR_PROCESS", {"program": program.id, "process": child.id}),
            )
        ),
        provenance={"test": True},
    )
    sources[path] = "def run(): return 1"
    validate_process_layout(graph, sources, sources.__getitem__, candidate_program_id=program.id)


def test_independent_layout_gate_runs_before_candidate_evaluator(tmp_path):
    from test_runtime import commit_programs

    from evertree.core.evaluation import AcceptanceCriteria
    from evertree.core.programs.lifecycle import ProgramLifecycleRuntime, git

    repository = tmp_path / "programs"
    path = PREFIX + "example/_exec.py"
    commit_programs(repository, {path: "def run(): return 1"})
    calls = []

    def reject(branch, revision):
        calls.append((branch.id, revision))
        raise ValueError("layout drift")

    runtime = ProgramLifecycleRuntime(
        repository, tmp_path / "lifecycle", AcceptanceCriteria(("tests",)), validate_layout=reject
    )
    branch = runtime.create_candidate(
        "program/with space", "Improve result", candidate_name="preserve inputs"
    )
    assert branch.git_ref == "codex/program/program/with%20space/preserve-inputs"
    workspace = Path(branch.workspace)
    (workspace / path).write_text("def run(): return 2")
    git(workspace, "add", ".")
    git(workspace, "commit", "-m", "Candidate")
    with pytest.raises(ValueError, match="layout drift"):
        runtime._validate_candidate(branch)
    assert calls == [(branch.id, git(workspace, "rev-parse", "HEAD"))]
    assert git(repository, "show", "main:" + path) == "def run(): return 1"
