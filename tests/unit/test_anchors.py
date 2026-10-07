import pytest

from evertree.core.anchors import AnchorResolver, parse_anchors
from evertree.core.graph.store import GraphStore
from evertree.core.values import ContractError


def test_anchor_identity_survives_line_movement_and_ignores_string_comments():
    source = 'def run():  # et:op=start\n    return "# et:op=not_an_anchor"\n'
    anchors = parse_anchors(source, code_node_id=4, git_path="a.py", commit_sha="1" * 40)
    assert len(anchors) == 1
    moved = parse_anchors("\n" + source, code_node_id=4, git_path="a.py", commit_sha="2" * 40)
    graph = GraphStore()
    resolver = AnchorResolver(graph)
    resolver.install(anchors, provenance="source revision one")
    first = resolver.resolve_operator(4, "start")
    resolver.install(moved, provenance="source revision two")
    assert resolver.resolve_operator(4, "start").id == first.id
    assert moved[0].line == 2
    assert moved[0].commit_sha != anchors[0].commit_sha


def test_duplicate_anchor_is_not_an_ambiguous_trace_location():
    with pytest.raises(ContractError, match="twice"):
        parse_anchors(
            "x = 1 # et:op=a\ny = 2 # et:op=a\n",
            code_node_id=1,
            git_path="p.py",
            commit_sha="a" * 40,
        )
