"""Expansion of selected ProcessConcepts into the process set an aggregate covers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..datasets import freeze_json, thaw_json
from .contracts import UNKNOWN_PROCESS


@dataclass(frozen=True)
class ProcessScope:
    """Process identities (graph ids as text) with their names, after SUBTYPE_OF expansion."""

    processes: Mapping[str, str]
    skipped: Mapping[str, str] = field(default_factory=dict)
    # The selected concepts themselves; their omissions are always reported individually.
    roots: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "processes", freeze_json(dict(self.processes)))
        object.__setattr__(self, "skipped", freeze_json(dict(self.skipped)))
        object.__setattr__(self, "roots", tuple(self.roots) or tuple(self.processes))

    def name(self, process: str) -> str:
        return self.processes.get(process, process)

    def to_dict(self) -> dict[str, Any]:
        return {"processes": thaw_json(self.processes), "skipped": thaw_json(self.skipped)}


def process_node(graph, reference: str | int):
    """Resolve a process name or identity to its ProcessConcept, or None when it is not one."""
    if isinstance(reference, str) and reference.isdecimal():
        reference = int(reference)
    matches = graph.lookup(reference)
    root = graph.find("Process")
    for node in matches:
        if root is not None and (
            node.id == root.id or any(item.id == root.id for item in graph.ancestors(node.id))
        ):
            return node
    return None


def canonical_process(graph, reference: str | int) -> str:
    """Return the graph identity used to attribute evaluations and Tasks to a process."""
    node = process_node(graph, reference)
    if node is None:
        raise ValueError(f"Not a ProcessConcept: {reference}")
    return str(node.id)


def process_scope(graph, processes: Iterable[str | int]) -> ProcessScope:
    """Include each selected concept and all its SUBTYPE_OF descendants once.

    [Process] selects the whole taxonomy; unresolved selections are reported, not dropped.
    """
    selected: dict[str, str] = {}
    skipped: dict[str, str] = {}
    roots: list[str] = []
    for reference in processes:
        node = process_node(graph, reference)
        if node is None:
            skipped[str(reference)] = UNKNOWN_PROCESS
            continue
        roots.append(str(node.id))
        for item in (node, *graph.descendants(node.id)):
            selected.setdefault(str(item.id), item.name)
    return ProcessScope(selected, skipped, tuple(roots))
