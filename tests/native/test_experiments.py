from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from evertree.core.runtime.controller import Runtime
from tests.support.evaluation import dataset
from tests.support.experiments import (
    INTEGRATION_PATH,
    INTEGRATION_SOURCE,
    evaluate_pair,
    prepare,
    register_integration,
)
from tests.support.lifecycle_backup import change


@pytest.mark.parametrize("factory", [Runtime], ids=["native"])
async def test_isolated_pair_pins_helpers_and_keeps_outcomes_hidden(tmp_path, factory):
    """Real native isolation is required; a test transport cannot prove this OS contract."""
    source = """
async def run(value, ctx):
    from evertree.common.calculation import calculate
    node = await ctx.step('graph.get', {'id': 1})
    assert node['name'] == 'original'
    async def handle_tool(name, arguments):
        result = await ctx.call('knowledge_integration', arguments)
        assert result.result['writes'][0]['object'] == 1
        return result.result
    tools = [{'name': 'rename', 'description': 'Apply an isolated correction.',
        'input_schema': {'type': 'object', 'properties': {'name': {'type': 'string'}},
                         'required': ['name'], 'additionalProperties': False},
        'read_only': False}]
    assert await ctx.step('learning.predict', {'state_id': 'known'}) == 0.5
    answer = await ctx.llm({'prompt': str(value), 'mode': 'exec'},
                             tools=tools, tool_handler=handle_tool)
    return {'result': calculate(value) + answer['parsed']}
"""
    repo, _, branch, spec, graph, memory, learning = prepare(
        tmp_path,
        source,
        {
            "src/evertree/common/calculation.py": "def calculate(value): return value\n",
            "src/evertree/common/__init__.py": "",
            INTEGRATION_PATH: INTEGRATION_SOURCE,
        },
    )
    integration = register_integration(graph, spec.revision)
    # Baseline helper is committed before branching so both sides can run.
    initial_helper = Path(branch.workspace) / "src/evertree/common/calculation.py"
    revision = change(
        branch, "src/evertree/common/calculation.py", "def calculate(value): return value * 2\n"
    )
    assert initial_helper.is_file()
    snapshots = graph.snapshot(), memory.snapshot(), learning.snapshot()
    prepared = []

    async def model_call(payload, context):
        assert payload["prompt"] == "3" and payload["mode"] == "exec"
        assert [tool["name"] for tool in payload["tools"]] == ["rename"]
        assert context.graph.get(1).name == "original"
        result = await payload["_tool_handler"]("rename", {"name": "changed"})
        assert result["writes"][0]["object"] == 1
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
        lambda identity: integration if identity == 2 else spec,
        runtime_factory=factory,
        model_call=model_call,
    )
    assert experiment.report.baseline_metrics == {"accuracy": 0}
    assert experiment.report.metrics == {"accuracy": 1}, [
        trace["error"] for trace in experiment.traces if "error" in trace
    ]
    assert all(experiment.report.checks.values())
    assert (graph.snapshot(), memory.snapshot(), learning.snapshot()) == snapshots
    assert len(prepared) == 2
    assert experiment.report.trace_ids


pytestmark = pytest.mark.skipif(
    os.name != "nt" and sys.platform != "darwin", reason="Native macOS/Windows isolation"
)
