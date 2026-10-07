"""Minimal evaluation fixtures without repository or candidate creation."""

from evertree.core.datasets import DatasetRevision, EvaluationCase
from evertree.core.graph.store import GraphStore
from evertree.core.learning.state import LearningStore
from evertree.core.memory.store import TraceStore
from evertree.core.programs.lifecycle import ProgramBranch
from evertree.core.runtime.controller import ProgramSpec


def evaluation_state(tmp_path):
    revision = "0" * 40
    repo = tmp_path / "unused-repository"
    branch = ProgramBranch("candidate", "program", "candidate", str(repo), revision, "Fixture")
    spec = ProgramSpec("program", "src/evertree/processes/example.py", revision)
    return repo, branch, spec, GraphStore(), TraceStore(), LearningStore()


def fixed_outcomes(monkeypatch, baseline, candidate):
    """Supply execution results while testing real scoring/aggregation/acceptance.

    Git presence, syntax and candidate-test results are boundary inputs here;
    their enforcement is covered by integration tests, not these arithmetic cases.
    """
    from unittest.mock import AsyncMock

    from evertree.core.programs import experiments
    from evertree.core.runtime.controller import RunResult

    def baseline_exists(repository, *arguments):
        assert arguments[:2] == ("cat-file", "-e")
        return b""

    monkeypatch.setattr(experiments, "_git", baseline_exists)
    monkeypatch.setattr(experiments, "_compile_changed", lambda *args: [])
    monkeypatch.setattr(
        experiments, "run_candidate_tests", AsyncMock(return_value={"passed": True})
    )

    class ResultRuntime:
        def __init__(self, state_dir, repository, gateway, trace):
            self.result = baseline if state_dir.parent.name == "baseline" else candidate

        async def execute(self, *args, **kwargs):
            return RunResult("fixture", self.result)

        async def close(self):
            pass

    return ResultRuntime


def dataset(*cases):
    return DatasetRevision(
        "holdout",
        "Fixed independent examples",
        "evaluation",
        tuple(
            EvaluationCase(str(index), inputs, outcome, "exact", ("source-" + str(index),))
            for index, (inputs, outcome) in enumerate(cases)
        ),
        ("accuracy",),
    )
