"""Derived structural signals and explicit concept reification.

No associative-plane pattern store is introduced: that subsystem is future
work in the architecture.  These queries inspect the current semantic graph.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict

from .graph import ContractError, GraphDelta, GraphStore, Node


@dataclasses.dataclass(frozen=True)
class TopologySignals:
    cycles: tuple[tuple[int, ...], ...]
    hubs: tuple[tuple[int, int], ...]
    bridges: tuple[tuple[int, int], ...]


def adjacency(graph: GraphStore) -> dict[int, set[int]]:
    edges: dict[int, set[int]] = defaultdict(set)
    for fact in graph.facts():
        relation = graph.get(fact.relation_type)
        ids = []
        for slot in relation.signature:
            if slot.value_type not in {"node", "concept", "prototype", "instance", "facet"}:
                continue
            values = fact.args.get(slot.label)
            if values is None:
                continue
            ids.extend(values if slot.arity.startswith("list") else (values,))
        if ids:
            for identity in ids[1:]:
                edges[ids[0]].add(identity)
                edges.setdefault(identity, set())
    return dict(edges)


def inspect_topology(
    graph: GraphStore, *, hub_degree: int = 4, max_cycles: int = 100
) -> TopologySignals:
    if hub_degree < 1 or max_cycles < 0:
        raise ContractError("topology limits must be nonnegative")
    directed = adjacency(graph)
    cycles = set()
    # A DFS cycle basis gives bounded signals in linear traversal time instead
    # of enumerating exponentially many simple paths in an acyclic graph.
    visited, active = set(), set()
    for start in sorted(directed):
        if start in visited:
            continue
        path, positions = [start], {start: 0}
        active.add(start)
        visited.add(start)
        stack = [(start, iter(sorted(directed.get(start, ()))))]
        while stack:
            current, successors = stack[-1]
            successor = next(successors, None)
            if successor is None:
                stack.pop()
                active.remove(current)
                positions.pop(current)
                path.pop()
            elif successor in active:
                cycle = tuple(path[positions[successor] :])
                smallest = cycle.index(min(cycle))
                if len(cycles) < max_cycles:
                    cycles.add(cycle[smallest:] + cycle[:smallest])
            elif successor not in visited:
                visited.add(successor)
                active.add(successor)
                positions[successor] = len(path)
                path.append(successor)
                stack.append((successor, iter(sorted(directed.get(successor, ())))))
    undirected: dict[int, set[int]] = defaultdict(set)
    for source, targets in directed.items():
        for target in targets:
            undirected[source].add(target)
            undirected[target].add(source)
    hubs = tuple(
        sorted(
            (
                (identity, len(neighbors))
                for identity, neighbors in undirected.items()
                if len(neighbors) >= hub_degree
            ),
            key=lambda item: (-item[1], item[0]),
        )
    )
    # Removing each undirected edge is simple and exact for the small active
    # graphs expected in v1; topology is not persistent duplicate state.
    bridges = []
    for source in sorted(undirected):
        for target in sorted(undirected[source]):
            if source >= target:
                continue
            seen = {source}
            pending = [source]
            while pending:
                current = pending.pop()
                for neighbor in undirected[current]:
                    if {current, neighbor} == {source, target} or neighbor in seen:
                        continue
                    seen.add(neighbor)
                    pending.append(neighbor)
            if target not in seen:
                bridges.append((source, target))
    return TopologySignals(tuple(sorted(cycles)), hubs, tuple(bridges))


def propose_reification(
    graph: GraphStore,
    *,
    name: str,
    members: tuple[int, ...],
    benefit: str,
    description: str | None = None,
) -> GraphDelta:
    """Build an integrated concept proposal; caller must evaluate and apply it."""
    if benefit not in {"compression", "prediction", "control", "generalization"}:
        raise ContractError("reification needs a declared operational benefit")
    if len(set(members)) < 2:
        raise ContractError("reification requires a related multi-node pattern")
    for identity in members:
        graph.get(identity)
    edges = adjacency(graph)
    member_set = set(members)
    connected = {members[0]}
    while True:
        previous = set(connected)
        for source, targets in edges.items():
            if source in connected:
                connected.update(targets & member_set)
            if source in member_set and targets & connected:
                connected.add(source)
        if connected == previous:
            break
    if connected != member_set:
        raise ContractError("reified members must describe a connected pattern")
    pattern = Node(
        graph.reserve_id(),
        name,
        description=description,
        properties={"reification_benefit": benefit},
    )
    links = tuple(
        graph.new_fact("PART_WHOLE", {"part": identity, "whole": pattern.id})
        for identity in members
    )
    # Incoming/outgoing structural integration follows from ordinary semantic
    # links; this creates neither a hidden execution shortcut nor shared weights.
    return GraphDelta(creates=(pattern, *links))
