import asyncio
import functools
import inspect

import pytest

from evertree.core.anchors import (
    AnchorResolver,
    anchor_at,
    instrument,
    operator_changes,
    parse_anchors,
)
from evertree.core.graph.store import GraphStore
from evertree.core.values import ContractError

SOURCE = """\
def run(items):
    # et:op=subtotal
    # Sums price times quantity over the order lines.
    subtotal = sum(
        line["price"] * line["quantity"] for line in items
    )
    note = "# et:op=not_an_anchor"
    # et:op=free_shipping
    # Decides whether the order ships free.
    if subtotal >= 50:
        subtotal -= 0
    return {"result": subtotal, "feedback": None}
"""


def parse(source, commit="1" * 40):
    return parse_anchors(source, code_node_id=4, git_path="a.py", commit_sha=commit)


def test_anchor_binds_described_statement_and_ignores_string_comments():
    subtotal, guard = parse(SOURCE)
    assert (subtotal.op_id, subtotal.description) == (
        "subtotal",
        "Sums price times quantity over the order lines.",
    )
    assert (subtotal.line, subtotal.statement_line, subtotal.end_line) == (2, 4, 6)
    assert (guard.op_id, guard.kind, guard.statement_line, guard.end_line) == (
        "free_shipping",
        "If",
        10,
        11,
    )
    # A Core call made from any line of a multi-line statement belongs to its anchor.
    assert anchor_at((subtotal, guard), 5) is subtotal
    assert anchor_at((subtotal, guard), 11) is guard
    assert anchor_at((subtotal, guard), 12) is None


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("x = 1  # et:op=a\n", "own line"),
        ("# et:op=a\nx = 1\n", "description"),
        ("# et:op=a\n#\nx = 1\n", "description"),
        ("# et:op=a\n# " + "d" * 121 + "\nx = 1\n", "exceeds"),
        ("# et:op=a\n# Counts.\n\nx = 1\n", "follow the description"),
        ("# et:op=a-b\n# Counts.\nx = 1\n", "identifier"),
        ("for i in []:\n    # et:op=a\n    # Skips.\n    continue\n", "no result"),
        ("# et:op=a\n# One.\nx = 1\n# et:op=a\n# Two.\ny = 2\n", "twice"),
    ],
)
def test_malformed_anchor_is_refused(source, reason):
    with pytest.raises(ContractError, match=reason):
        parse(source)


def test_operator_identity_follows_op_id_across_revisions():
    graph = GraphStore()
    resolver = AnchorResolver(graph)
    resolver.sync(4, parse(SOURCE), "1" * 40, provenance="revision one")
    first = resolver.resolve_operator(4, "subtotal")
    guard = resolver.resolve_operator(4, "free_shipping")
    # Moved and redescribed subtotal, guard removed, a new discount step.
    revised = "\n" + SOURCE.replace("over the order lines", "over the lines").replace(
        "    # et:op=free_shipping\n    # Decides whether the order ships free.\n", ""
    ).replace(
        "    return",
        "    # et:op=discount\n    # Applies the discount.\n    subtotal *= 0.9\n    return",
    )
    delta = resolver.sync(4, parse(revised, "2" * 40), "2" * 40, provenance="revision two")
    kept = resolver.resolve_operator(4, "subtotal")
    assert kept.id == first.id and kept.description == "Sums price times quantity over the lines."
    assert kept.properties["line"] == 3
    assert list(kept.properties["revisions"]) == ["1" * 40, "2" * 40]
    assert delta.deletes == (guard.id,) and graph.find(guard.name) is None
    added = resolver.resolve_operator(4, "discount")
    assert list(added.properties["revisions"]) == ["2" * 40]
    # The same revision again changes nothing structural.
    again = resolver.sync(4, parse(revised, "2" * 40), "2" * 40, provenance="again")
    assert not again.creates and not again.deletes


def test_renamed_anchor_is_a_deletion_and_a_creation():
    old = parse("# et:op=a\n# Counts.\nx = 1\n")
    new = parse("# et:op=b\n# Counts.\nx = 1\n")
    graph = GraphStore()
    AnchorResolver(graph).sync(4, old, "1" * 40, provenance="one")
    creates, updates, deletes = operator_changes(AnchorResolver(graph).operators(4), new, "2" * 40)
    assert [anchor.op_id for anchor, _ in creates] == ["b"]
    assert not updates and [node.properties["local_id"] for node in deletes] == ["a"]


def run_instrumented(source, *arguments, uses=None):
    uses = [] if uses is None else uses

    def use(op_id, value):
        uses.append((op_id, "completed", value))
        return value

    def failed(op_id, error):
        uses.append((op_id, "failed", str(error)))

    def function(op_id):
        def decorate(target):
            @functools.wraps(target)
            def wrapper(*args, **kwargs):
                return use(op_id, target(*args, **kwargs))

            return wrapper

        return decorate

    namespace = {"__et_op__": use, "__et_op_failed__": failed, "__et_op_function__": function}
    exec(instrument(source, parse(source), "a.py"), namespace)  # noqa: S102 -- test source
    entry = namespace["run"]
    result = entry(*arguments)
    if inspect.iscoroutine(result):
        result = asyncio.run(result)
    return result, uses


def test_instrumented_statements_record_each_execution_without_changing_results():
    result, uses = run_instrumented(SOURCE, [{"price": 30, "quantity": 2}])
    assert result == {"result": 60, "feedback": None}
    assert uses == [("subtotal", "completed", 60), ("free_shipping", "completed", True)]


def test_instrumented_function_loop_and_failure():
    source = """\
# et:op=run
# Computes the order total.
def run(values):
    total = 0
    for value in values:
        # et:op=add
        # Adds one value.
        total += value
    # et:op=check
    # Requires a positive total.
    assert total > 0, "empty"
    return {"result": total, "feedback": None}
"""
    result, uses = run_instrumented(source, [1, 2])
    assert result["result"] == 3
    assert uses == [
        ("add", "completed", 1),
        ("add", "completed", 3),
        ("check", "completed", None),
        ("run", "completed", {"result": 3, "feedback": None}),
    ]
    uses = []
    with pytest.raises(AssertionError, match="empty"):
        run_instrumented(source, [], uses=uses)
    assert uses == [("check", "failed", "empty")]


def test_instrumented_async_program_keeps_awaits_and_coroutine_entrypoint():
    source = """\
import asyncio

async def run():
    # et:op=wait
    # Waits for the value.
    value = await asyncio.sleep(0, result=7)
    # et:op=answer
    # Returns the value.
    return {"result": value, "feedback": None}
"""
    result, uses = run_instrumented(source)
    assert result == {"result": 7, "feedback": None}
    assert uses == [("wait", "completed", 7), ("answer", "completed", result)]
