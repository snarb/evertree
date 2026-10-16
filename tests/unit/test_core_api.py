from __future__ import annotations

from evertree.common import semantic_search, structured
from evertree.core.contracts import CALLED_PROGRAMS, ProgramResult
from evertree.core.evaluation import api as evaluation
from evertree.core.graph import api as graph
from evertree.core.learning import api as learning
from evertree.core.memory import api as memory
from evertree.core.semantics import api as semantics


class RecordingContext:
    def __init__(self, results=None):
        self.results = results or {}
        self.steps, self.calls = [], []

    async def step(self, method, payload=None):
        self.steps.append((method, payload))
        return self.results.get(method)

    async def call(self, program, arguments=None):
        self.calls.append((program, arguments))
        return ProgramResult({"called": program})


async def test_wrappers_send_core_methods_and_payload_keys():
    ctx = RecordingContext()
    await semantics.load_sources(ctx, ["ref"], focus="f")
    await semantics.write(ctx, {"action": "x"}, operation_key="k", experience_refs=["ref"])
    await graph.describe(ctx, 7)
    await graph.read(ctx, "walk", {"start": 7})
    await memory.retrieve(ctx, "q", limit=3)
    await learning.credit(ctx, "target")
    await learning.prepare(ctx, {"id": 1})
    await learning.learn(ctx, {"s": 1}, "target")
    await learning.assess_evidence(ctx, "target", {"ref": 1}, {"true": 0.9})
    await evaluation.match(ctx, [1], context={}, metrics=["m"])
    await evaluation.review(ctx, cases=[], credits=[])
    assert ctx.steps == [
        ("semantic.sources", {"experience_refs": ["ref"], "focus": "f"}),
        (
            "semantic.write",
            {"action": {"action": "x"}, "operation_key": "k", "experience_refs": ["ref"]},
        ),
        ("graph.describe", {"subject": 7}),
        ("graph.walk", {"start": 7}),
        ("memory.retrieve", {"query": "q", "limit": 3}),
        (
            "learning.credit",
            {
                "target": "target",
                "signal": None,
                "ambiguous": False,
                "observation_ids": [],
                "context": {},
            },
        ),
        ("learning.prepare", {"credit": {"id": 1}}),
        (
            "learning.learn",
            {
                "signal": {"s": 1},
                "target": "target",
                "context": {},
                "attribution_weight": 1.0,
                "ambiguous": False,
            },
        ),
        (
            "evidence.assess",
            {
                "target": "target",
                "source_ref": {"ref": 1},
                "likelihoods": {"true": 0.9},
                "dependency_root": None,
            },
        ),
        (
            "evaluation.match",
            {"observations": [1], "context": {}, "metrics": ["m"], "selected_targets": []},
        ),
        ("evaluation.review", {"cases": [], "credits": []}),
    ]


async def test_program_calls_follow_declared_contracts():
    ctx = RecordingContext()
    assert await semantics.call_semantic_search(ctx, "q") == {"called": "semantic_search"}
    assert await learning.call_credit_assignment(
        ctx, target="t", observation_ids=["o"], context={}
    ) == {"called": "credit_assignment"}
    assert {program: tuple(arguments) for program, arguments in ctx.calls} == CALLED_PROGRAMS


async def test_shared_helpers_use_typed_semantic_and_llm_steps():
    ctx = RecordingContext(
        {"semantic.bm25": [2, 1], "semantic.vector": [1], "llm.run": {"parsed": {"ok": True}}}
    )
    await semantic_search.search(ctx, "Query", kind="Note")
    methods = [method for method, _ in ctx.steps]
    assert methods[:2] == ["semantic.lookup", "semantic.revision"]
    assert sorted(methods[2:4]) == ["semantic.bm25", "semantic.vector"]
    assert ctx.steps[-1] == (
        "semantic.results",
        {
            "query": "Query",
            "kind": "note",
            "revision": None,
            "items": [{"id": 1, "channels": ["bm25", "vector"]}, {"id": 2, "channels": ["bm25"]}],
            "errors": [],
            "limit": 20,
        },
    )
    schema = {"type": "object"}
    result = await structured.ask(ctx, instructions="i", data={"a": 1}, schema=schema)
    assert result == {"result": {"ok": True}, "feedback": None}
    assert ctx.steps[-1][0] == "llm.run"
    assert ctx.steps[-1][1]["output_schema"] == schema and ctx.steps[-1][1]["mode"] == "model"
