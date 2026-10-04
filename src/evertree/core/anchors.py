"""Resolve explicit semantic operators at immutable source-code coordinates."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass

from .graph import ContractError, GraphDelta, GraphStore, Node


@dataclass(frozen=True)
class CodeAnchor:
    code_node_id: int
    op_id: str
    git_path: str
    commit_sha: str
    line: int

    @property
    def concept_name(self) -> str:
        return f"op:{self.code_node_id}:{self.op_id}"


def parse_anchors(
    source: str, *, code_node_id: int, git_path: str, commit_sha: str
) -> tuple[CodeAnchor, ...]:
    """Only comment tokens bind operators; text inside strings is not an anchor."""
    ast.parse(source, filename=git_path)
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit_sha):
        raise ContractError("Anchors require an exact Git commit")
    anchors = []
    seen = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        match = re.fullmatch(r"#\s*et:op=([A-Za-z_][A-Za-z_0-9]*)\s*", token.string)
        if not match:
            if "et:op=" in token.string:
                raise ContractError("Invalid Code Anchor")
            continue
        operator = match[1]
        if operator in seen:
            raise ContractError("Operator anchor identity occurs twice in one CodeNode")
        seen.add(operator)
        anchors.append(CodeAnchor(code_node_id, operator, git_path, commit_sha, token.start[0]))
    return tuple(anchors)


class AnchorResolver:
    """The semantic graph owns operator identities; source coordinates are revision-specific."""

    def __init__(self, graph: GraphStore):
        self.graph = graph

    def install(self, anchors: tuple[CodeAnchor, ...], *, provenance) -> None:
        creates = []
        for anchor in anchors:
            if self.graph.find(anchor.concept_name) is None:
                creates.append(
                    Node(
                        self.graph.reserve_id(),
                        anchor.concept_name,
                        kind="operator",
                        properties={"code_node": anchor.code_node_id, "local_id": anchor.op_id},
                    )
                )
        if creates:
            self.graph.apply(GraphDelta(creates=tuple(creates)), provenance=provenance)

    def resolve_operator(self, code_node_id: int, op_id: str) -> Node:
        node = self.graph.find(f"op:{code_node_id}:{op_id}")
        if node is None or node.kind != "operator":
            raise KeyError(f"Unknown Code Anchor: {code_node_id}:{op_id}")
        return node
