from __future__ import annotations

from functools import partial

from evertree.core.evaluation.acceptance import AcceptanceCriteria
from evertree.core.graph.store import GraphStore
from evertree.core.graph.types import GraphDelta, Node
from evertree.core.learning.state import LearningStore
from evertree.core.memory.store import TraceStore
from evertree.core.programs.experiments import evaluate_pair as core_evaluate_pair
from evertree.core.programs.lifecycle import ProgramLifecycleRuntime
from evertree.core.runtime.controller import ProgramSpec, Runtime
from tests.support.runtime import TestProcess, commit_programs

PATH = "src/evertree/processes/example.py"


TEST_RUNTIME = partial(Runtime, process_factory=TestProcess)


async def evaluate_pair(*args, **kwargs):
    kwargs.setdefault(
        "test_process_factory", None if kwargs.get("runtime_factory") is Runtime else TestProcess
    )
    return await core_evaluate_pair(*args, **kwargs)


def prepare(tmp_path, source="def run(value): return {'result': value}\n", helpers=None):
    repo = tmp_path / "repo"
    local_tests = """
import importlib.util
from pathlib import Path
import unittest

class EntrypointTest(unittest.TestCase):
    def test_declared_entrypoint_imports(self):
        path = Path(__file__).parents[1] / 'src/evertree/processes/example.py'
        spec = importlib.util.spec_from_file_location('example_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.run))
"""
    revision = commit_programs(
        repo, {PATH: source, "tests/test_entrypoint.py": local_tests, **(helpers or {})}
    )
    lifecycle = ProgramLifecycleRuntime(
        repo,
        tmp_path / "lifecycle",
        AcceptanceCriteria(
            ("contracts", "tests", "holdout"), target_metric="accuracy", threshold=1
        ),
    )
    branch = lifecycle.create_candidate("program", "Correct the calculation")
    graph, memory, learning = GraphStore(), TraceStore(), LearningStore()
    run = memory.start_run("seed", revision, {})
    event = memory.record(run, "seed", output={})
    graph.apply(GraphDelta(creates=(Node(1, "original"),)), provenance=memory.output_ref(event))
    memory.finish_run(run)
    learning.create_state("beta_bernoulli", state_id="known")
    return repo, lifecycle, branch, ProgramSpec("program", PATH, revision), graph, memory, learning
