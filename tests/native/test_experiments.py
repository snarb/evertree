from __future__ import annotations

import os
from pathlib import Path

import pytest

from evertree.core.runtime import Runtime
from tests.support.evaluation import dataset
from tests.support.experiments import evaluate_pair, prepare
from tests.support.lifecycle_backup import change


@pytest.mark.parametrize("factory", [Runtime], ids=["native"])
async def test_isolated_pair_pins_helpers_and_keeps_outcomes_hidden(tmp_path, factory):
    """Real Windows isolation/tools are required; a test process cannot prove this OS contract."""
    source = """
async def run(value, ctx):
    from evertree.common.calculation import calculate
    node = await ctx.step('graph.get', {'id': 1})
    assert node['name'] == 'original'
    await ctx.step('graph.apply', {'updates': [{'id': 1, 'changes': {'name': 'changed'}}]})
    assert await ctx.step('learning.predict', {'state_id': 'known'}) == 0.5
    answer = await ctx.step('agent.run', {'prompt': str(value), 'mode': 'exec'})
    return {'result': calculate(value) + answer['parsed']}
"""
    repo, _, branch, spec, graph, memory, learning = prepare(
        tmp_path,
        source,
        {
            "src/evertree/common/calculation.py": "def calculate(value): return value\n",
            "src/evertree/common/__init__.py": "",
        },
    )
    # Baseline helper is committed before branching so both sides can run.
    initial_helper = Path(branch.workspace) / "src/evertree/common/calculation.py"
    revision = change(
        branch, "src/evertree/common/calculation.py", "def calculate(value): return value * 2\n"
    )
    assert initial_helper.is_file()
    snapshots = graph.snapshot(), memory.snapshot(), learning.snapshot()
    prepared = []

    async def model_call(payload, context):
        assert payload == {"prompt": "3", "mode": "model"}
        assert context.graph.get(1).name == "changed"
        assert context.workspace.exists()
        prepared.append(context)
        return {"parsed": 0}

    experiment = await evaluate_pair(
        branch,
        revision,
        spec,
        dataset(({"value": 3}, 6)),
        tmp_path / "evaluations",
        repo,
        graph,
        memory,
        learning,
        lambda _: spec,
        runtime_factory=factory,
        model_call=model_call,
    )
    assert experiment.report.baseline_metrics == {"accuracy": 0}
    assert experiment.report.metrics == {"accuracy": 1}
    assert all(experiment.report.checks.values())
    assert (graph.snapshot(), memory.snapshot(), learning.snapshot()) == snapshots
    assert len(prepared) == 2
    assert experiment.report.trace_ids


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native isolation")
