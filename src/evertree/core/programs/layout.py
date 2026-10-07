"""Validate committed process code against Self's semantic process taxonomy."""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath

from evertree.core.graph.store import GraphStore

PREFIX = "src/evertree/processes/"
ROLES = {"_exec": "exec", "_model": "model"}


def process_slug(name: str) -> str:
    """Use one deterministic Python spelling for a semantic process name."""
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def process_directory(graph: GraphStore, identity: int) -> str:
    root = graph.find("SelfProcess")
    node = graph.get(identity)
    lineage = (node, *graph.ancestors(identity))
    if root is None or root.id not in {item.id for item in lineage}:
        raise ValueError("Program process must belong to Self/Process")
    slugs = []
    for item in lineage:
        if item.id == root.id:
            break
        slug = process_slug(item.name)
        if not slug.isidentifier() or slug.startswith("_"):
            raise ValueError(f"Invalid process directory name: {item.name}")
        slugs.append(slug)
    return PREFIX + "/".join(reversed(slugs))


def validate_process_layout(
    graph: GraphStore,
    paths: Iterable[str],
    read_source: Callable[[str], str],
    *,
    candidate_program_id: int | None = None,
) -> None:
    """Check a source tree without importing or executing candidate-controlled code.

    Inactive proposals may lack code in main. Only the selected candidate joins
    the active bindings when validating its proposed commit.
    """
    root, self_node = graph.find("SelfProcess"), graph.find("Self")
    if (
        root is None
        or self_node is None
        or not any(
            fact.args["part"] == root.id and fact.args["whole"] == self_node.id
            for fact in graph.facts("PART_WHOLE")
        )
    ):
        raise ValueError("Self/Process must belong to Self")
    general = graph.find("Process")
    if general is None or general.id not in {item.id for item in graph.ancestors(root.id)}:
        raise ValueError("Self/Process must be a subtype of the general Process")

    files = {path for path in paths if path.startswith(PREFIX) and path.endswith(".py")}
    own_processes = {root.id, *(node.id for node in graph.descendants(root.id))}
    programs = [
        node
        for node in graph.nodes(kind="program")
        if node.properties.get("process") in own_processes
    ]
    selected = [
        node
        for node in programs
        if node.properties.get("active", True) or node.id == candidate_program_id
    ]
    if candidate_program_id is not None and candidate_program_id not in {
        node.id for node in selected
    }:
        raise ValueError("Candidate Program must belong to Self/Process")
    inactive_processes = {node.properties["process"] for node in programs} - {
        node.properties["process"] for node in selected
    }
    required_processes = own_processes - inactive_processes
    # A parent's own Program may be inactive while its subtype needs the directory.
    required_processes |= {
        ancestor.id
        for identity in tuple(required_processes)
        for ancestor in graph.ancestors(identity)
        if ancestor.id in own_processes
    }
    directories = {
        process_directory(graph, identity).rstrip("/") for identity in required_processes
    }
    if len(directories) != len(required_processes):
        raise ValueError("Process taxonomy has colliding directory names")

    entrypoints = {}
    bindings = set()
    links = {
        (fact.args["program"], fact.args["process"]) for fact in graph.facts("PROGRAM_FOR_PROCESS")
    }
    for program in selected:
        props = program.properties
        process = graph.get(props["process"])
        role = props.get("role")
        if role not in ROLES.values() or (process.id, role) in bindings:
            raise ValueError(f"Process must have at most one Program per role: {process.name}")
        bindings.add((process.id, role))
        if (program.id, process.id) not in links:
            raise ValueError(f"Missing PROGRAM_FOR_PROCESS: {program.name}")
        if (
            program.id != candidate_program_id
            and process.properties.get("active_" + role) != program.id
        ):
            raise ValueError(f"Active Program binding is inconsistent: {program.name}")
        roles = props.get("roles", (role,))
        if {item for item in roles if item in {"exec", "model"}} != {role} or (
            "meta" in roles and role != "exec"
        ):
            raise ValueError(f"Program roles are inconsistent: {program.name}")
        directory = process_directory(graph, process.id).rstrip("/")
        path = props["git_path"]
        marker = directory + "/_" + role
        if path != marker + ".py" and not (path.startswith(marker + "/") and path.endswith(".py")):
            raise ValueError(f"Program path disagrees with taxonomy or role: {path}")
        if ".." in PurePosixPath(path).parts or path not in files:
            raise ValueError(f"Missing committed Program file: {path}")
        tree = ast.parse(read_source(path), filename=path)
        entrypoint = props.get("entrypoint", "run")
        if not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entrypoint
            for node in tree.body
        ):
            raise ValueError(f"Missing Program entrypoint {entrypoint}: {path}")
        entrypoints[marker] = path

    actual_directories = {PREFIX.rstrip("/")}
    for path in files:
        relative = PurePosixPath(path.removeprefix(PREFIX))
        parts = relative.parts
        role_index = next(
            (
                i
                for i, part in enumerate(parts)
                if part in ROLES or part.removesuffix(".py") in ROLES
            ),
            None,
        )
        if role_index is not None:
            marker = PREFIX + "/".join((*parts[:role_index], parts[role_index].removesuffix(".py")))
            if marker not in entrypoints:
                raise ValueError(f"Unregistered Program code: {path}")
            if (entrypoints[marker] == marker + ".py") != (path == marker + ".py"):
                raise ValueError(f"Program role cannot be both a file and a package: {marker}")
            process_parts = parts[:role_index]
        elif relative.name == "__init__.py":
            process_parts = parts[:-1]
            tree = ast.parse(read_source(path), filename=path)
            if any(
                not (
                    isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                )
                for node in tree.body
            ):
                raise ValueError(f"Taxonomy __init__.py must contain only a docstring: {path}")
        else:
            raise ValueError(f"Process helpers must belong to _exec/ or _model/: {path}")
        for length in range(1, len(process_parts) + 1):
            actual_directories.add(PREFIX + "/".join(process_parts[:length]))
    if actual_directories != directories:
        missing, extra = (
            sorted(directories - actual_directories),
            sorted(actual_directories - directories),
        )
        raise ValueError(
            f"Process directories disagree with graph: missing={missing}, extra={extra}"
        )


def main() -> None:
    """CI check of installed seed sources and their freshly constructed graph."""
    from pathlib import Path

    from evertree.core.graph.types import GraphDelta, Node

    from .bootstrap import seed_process_delta

    package = Path(__file__).resolve().parents[2]
    graph = GraphStore()
    graph.bootstrap(provenance={"check": "process-layout"})
    self_node = Node(graph.reserve_id(), "Self")
    graph.apply(GraphDelta(creates=(self_node,)), provenance={"check": "process-layout"})
    graph.apply(
        seed_process_delta(graph, self_id=self_node.id, revision="0" * 40),
        provenance={"check": "process-layout"},
    )
    paths = [
        "src/evertree/" + path.relative_to(package).as_posix()
        for path in (package / "processes").rglob("*.py")
    ]
    validate_process_layout(
        graph,
        paths,
        lambda path: (package / path.removeprefix("src/evertree/")).read_text(encoding="utf-8"),
    )
    print("Self/Process taxonomy, Program roles and source paths are synchronized.")


if __name__ == "__main__":
    main()
