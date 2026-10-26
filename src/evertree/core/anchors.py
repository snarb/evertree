"""Resolve explicit semantic operators at immutable source-code coordinates.

A Code Anchor is two comment lines directly above the statement it marks:

    # et:op=apply_discount
    # Applies the percentage discount to the subtotal.
    total = subtotal * (1 - discount_percent / 100)

The graph keeps one operator node per anchor of a Program's active revision.
Activation creates, updates and deletes those nodes; the worker instruments each
anchored statement so every execution records one operator use.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass

from evertree.core.graph.store import GraphStore
from evertree.core.graph.types import GraphDelta, Node, NodeUpdate

from .values import ContractError

DESCRIPTION_LIMIT = 120
# Statements without a value or effect of their own carry no semantic result.
_UNANCHORABLE = (
    ast.Pass,
    ast.Break,
    ast.Continue,
    ast.Global,
    ast.Nonlocal,
    ast.Import,
    ast.ImportFrom,
)
# Hook names the worker binds in an instrumented module.
USE_HOOK, FAILURE_HOOK, FUNCTION_HOOK = "__et_op__", "__et_op_failed__", "__et_op_function__"


@dataclass(frozen=True)
class CodeAnchor:
    code_node_id: int
    op_id: str
    git_path: str
    commit_sha: str
    line: int
    description: str = ""
    statement_line: int = 0
    end_line: int = 0
    kind: str = ""

    @property
    def concept_name(self) -> str:
        """Return the graph operator name scoped to this code node and local anchor."""
        return f"op:{self.code_node_id}:{self.op_id}"


def _statements(tree: ast.Module) -> dict[int, ast.stmt]:
    """Map each starting line to its outermost statement; a decorated def starts at its decorator."""
    starts: dict[int, ast.stmt] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            decorators = getattr(node, "decorator_list", ())
            line = min([node.lineno, *(item.lineno for item in decorators)])
            starts.setdefault(line, node)
    return starts


def _comments(source: str) -> dict[int, tuple[str, bool]]:
    """Return comment text by line and whether the comment is alone on its line."""
    comments = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            alone = not token.line[: token.start[1]].strip()
            comments[token.start[0]] = (token.string, alone)
    return comments


def parse_anchors(
    source: str, *, code_node_id: int, git_path: str, commit_sha: str
) -> tuple[CodeAnchor, ...]:
    """Parse operator anchors for one committed source file.

    Only comment tokens bind operators; matching text inside strings is ignored.
    """
    tree = ast.parse(source, filename=git_path)
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit_sha):
        raise ContractError("Anchors require an exact Git commit")
    statements = _statements(tree)
    comments = _comments(source)
    anchors = []
    seen = set()
    for line, (text, alone) in sorted(comments.items()):
        if "et:op=" not in text:
            continue

        def invalid(reason, line=line):
            return ContractError(f"Invalid Code Anchor at {git_path}:{line}: {reason}")

        match = re.fullmatch(r"#\s*et:op=([A-Za-z_][A-Za-z_0-9]*)\s*", text)
        if not match:
            raise invalid("write it as # et:op=<identifier>")
        if not alone:
            raise invalid("the anchor comment must be on its own line")
        operator = match[1]
        if operator in seen:
            raise ContractError("Operator anchor identity occurs twice in one CodeNode")
        seen.add(operator)
        description, description_alone = comments.get(line + 1, ("", False))
        description = description.lstrip("#").strip()
        if not description_alone or not description or "et:op=" in description:
            raise invalid("the next line must be a short # description of the operator")
        if len(description) > DESCRIPTION_LIMIT:
            raise invalid(f"the description exceeds {DESCRIPTION_LIMIT} characters")
        statement = statements.get(line + 2)
        if statement is None:
            raise invalid("the anchored statement must follow the description line")
        if isinstance(statement, _UNANCHORABLE):
            raise invalid(f"{type(statement).__name__} has no result to anchor")
        anchors.append(
            CodeAnchor(
                code_node_id,
                operator,
                git_path,
                commit_sha,
                line,
                description,
                line + 2,
                statement.end_lineno or line + 2,
                type(statement).__name__,
            )
        )
    return tuple(anchors)


def anchor_at(anchors, source_line: int) -> CodeAnchor | None:
    """Return the innermost anchored statement whose lines contain a source line."""
    containing = [item for item in anchors if item.statement_line <= source_line <= item.end_line]
    return max(containing, key=lambda item: item.statement_line, default=None)


def operator_changes(installed, anchors, revision: str):
    """Compare a Program's operator nodes with the anchors of its next active revision.

    Identity is the local op id: a moved or redescribed anchor keeps its node and
    gains the revision; an id no longer present is deleted; a renamed id is a
    deletion and a creation.
    """
    by_id = {node.properties["local_id"]: node for node in installed}
    creates, updates = [], []
    for anchor in anchors:
        node = by_id.pop(anchor.op_id, None)
        properties = {
            "code_node": anchor.code_node_id,
            "local_id": anchor.op_id,
            "git_path": anchor.git_path,
            "line": anchor.line,
            "revision": revision,
        }
        if node is None:
            creates.append((anchor, {**properties, "revisions": [revision]}))
            continue
        revisions = list(node.properties.get("revisions", ()))
        if revision not in revisions:
            revisions.append(revision)
        updates.append((node, anchor, {**properties, "revisions": revisions}))
    return creates, updates, list(by_id.values())


class AnchorResolver:
    """The semantic graph owns operator identities; source coordinates are revision-specific."""

    def __init__(self, graph: GraphStore):
        self.graph = graph

    def operators(self, code_node_id: int) -> list[Node]:
        """List the installed operator nodes of one Program."""
        return [
            node
            for node in self.graph.nodes(kind="operator")
            if node.properties.get("code_node") == code_node_id
        ]

    def sync(self, code_node_id: int, anchors, revision: str, *, provenance) -> GraphDelta:
        """Make the Program's operator nodes match the anchors of its active revision."""
        creates, updates, deletes = operator_changes(
            self.operators(code_node_id), anchors, revision
        )
        delta = GraphDelta(
            creates=tuple(
                Node(
                    self.graph.reserve_id(),
                    anchor.concept_name,
                    kind="operator",
                    description=anchor.description,
                    properties=properties,
                )
                for anchor, properties in creates
            ),
            updates=tuple(
                NodeUpdate(node.id, {"description": anchor.description, "properties": properties})
                for node, anchor, properties in updates
            ),
            deletes=tuple(node.id for node in deletes),
        )
        if delta.creates or delta.updates or delta.deletes:
            self.graph.apply(delta, provenance=provenance)
        return delta

    def resolve_operator(self, code_node_id: int, op_id: str) -> Node:
        """Resolve a code-local anchor to its installed semantic operator node."""
        node = self.graph.find(f"op:{code_node_id}:{op_id}")
        if node is None or node.kind != "operator":
            raise KeyError(f"Unknown Code Anchor: {code_node_id}:{op_id}")
        return node


class _Instrument(ast.NodeTransformer):
    def __init__(self, anchored: dict[int, str]):
        self.anchored = anchored

    def _call(self, hook, *arguments):
        return ast.Call(ast.Name(hook, ast.Load()), list(arguments), [])

    def _use(self, op_id, value=None):
        return self._call(USE_HOOK, ast.Constant(op_id), value or ast.Constant(None))

    def _guarded(self, op_id, body):
        """Record a failure of the anchored statement and re-raise it unchanged."""
        error = "__et_error__"
        handler = ast.ExceptHandler(
            ast.Name("BaseException", ast.Load()),
            error,
            [
                ast.Expr(
                    self._call(FAILURE_HOOK, ast.Constant(op_id), ast.Name(error, ast.Load()))
                ),
                ast.Raise(),
            ],
        )
        return ast.Try(body, [handler], [], [])

    def visit(self, node):
        node = super().visit(node)
        if not isinstance(node, ast.stmt):
            return node
        decorators = getattr(node, "decorator_list", ())
        op_id = self.anchored.get(min([node.lineno, *(item.lineno for item in decorators)]))
        if op_id is None:
            return node
        replaced = self._replace(node, op_id)
        for item in replaced if isinstance(replaced, list) else [replaced]:
            ast.copy_location(item, node)
        return replaced

    def _replace(self, node, op_id):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            node.value = self._use(op_id, node.value)
            return self._guarded(op_id, [node])
        if isinstance(node, ast.Return):
            node.value = self._use(op_id, node.value)
            return self._guarded(op_id, [node])
        if isinstance(node, ast.Expr):
            node.value = self._use(op_id, node.value)
            return self._guarded(op_id, [node])
        if isinstance(node, ast.AugAssign):
            target = ast.parse(ast.unparse(node.target), mode="eval").body
            return self._guarded(op_id, [node, ast.Expr(self._use(op_id, target))])
        if isinstance(node, (ast.If, ast.While)):
            node.test = self._use(op_id, node.test)
            return node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.decorator_list.append(self._call(FUNCTION_HOOK, ast.Constant(op_id)))
            return node
        if isinstance(node, (ast.For, ast.AsyncFor, ast.With, ast.AsyncWith, ast.Try)):
            return [node, ast.Expr(self._use(op_id))]
        return self._guarded(op_id, [node, ast.Expr(self._use(op_id))])


def instrument(source: str, anchors, filename: str):
    """Compile a Program module so each anchored statement reports its result through hooks.

    Line numbers are preserved, so tracebacks and gateway source lines still
    point at the committed file.
    """
    tree = ast.parse(source, filename=filename)
    anchored = {anchor.statement_line: anchor.op_id for anchor in anchors}
    tree = _Instrument(anchored).visit(tree)
    ast.fix_missing_locations(tree)
    return compile(tree, filename, "exec")
