import asyncio

import pytest

from evertree.core.programs.tests import run_candidate_tests
from tests.support.runtime import TestProcess, commit_programs

SUITE = """
import unittest
from evertree.common.calculation import double

class CalculationTest(unittest.TestCase):
    def test_behavior(self):
        self.assertEqual(double(3), 6)
"""


async def run_suite(tmp_path, source, test=SUITE, *, timeout=30, process_factory=TestProcess):
    files = {"src/evertree/common/calculation.py": source}
    if test is not None:
        files["tests/test_calculation.py"] = test
    repo = tmp_path / "repo"
    revision = commit_programs(repo, files)
    # The mutable candidate tree is not what the fixed gate executes.
    (repo / "src/evertree/common/calculation.py").write_text("raise RuntimeError('dirty tree')\n")
    report = await run_candidate_tests(
        repo,
        revision,
        tmp_path / "run",
        process_factory=process_factory,
        timeout=timeout,
    )
    assert not (tmp_path / "run").exists()
    assert report["revision"] == revision
    return report


async def test_committed_candidate_tests_run_against_exact_code(tmp_path):
    """Execute committed candidate tests in a real interpreter to observe exit, output, and cleanup."""
    report = await run_suite(tmp_path, "def double(value): return value * 2\n")
    assert report["passed"] and report["exit_code"] == 0, report
    assert report["tests_run"] == 1
    assert report["files"] == ["tests/test_calculation.py"]
    assert "Ran 1 test" in report["stderr"]


async def test_syntax_valid_candidate_with_failing_test_is_rejected(tmp_path):
    """Execute committed candidate tests in a real interpreter to observe exit, output, and cleanup."""
    report = await run_suite(tmp_path, "def double(value): return value + 2\n")
    assert not report["passed"] and report["exit_code"] != 0
    assert report["failures"] == 1


@pytest.mark.parametrize(
    "suite",
    [
        None,
        "# no cases\n",
        "import unittest\n@unittest.skip('not ready')\nclass T(unittest.TestCase):\n    def test_skipped(self): pass\n",
    ],
)
async def test_absent_empty_or_entirely_skipped_suite_cannot_pass(tmp_path, suite):
    """Execute committed candidate tests in a real interpreter to observe exit, output, and cleanup."""
    report = await run_suite(tmp_path, "def double(value): return value * 2\n", suite)
    assert not report["passed"]


async def test_zero_exit_without_unittest_outcome_does_not_pass(tmp_path):
    """Execute committed candidate tests in a real interpreter to observe exit, output, and cleanup."""
    report = await run_suite(
        tmp_path, "def double(value): return value * 2\n", "import os\nos._exit(0)\n"
    )
    assert report["exit_code"] == 0 and not report["passed"]


async def test_test_timeout_stops_owned_process(tmp_path):
    """Execute committed candidate tests in a real interpreter to observe exit, output, and cleanup."""
    instances = []

    class RecordingProcess(TestProcess):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    report = await run_suite(
        tmp_path,
        "def double(value): return value * 2\n",
        "import time\ntime.sleep(120)\n",
        timeout=0.2,
        process_factory=RecordingProcess,
    )
    assert not report["passed"] and "timed out" in report["reason"]
    assert instances and instances[0].poll() is not None


async def test_cancelling_candidate_tests_stops_owned_process(tmp_path):
    """Execute committed candidate tests in a real interpreter to observe exit, output, and cleanup."""
    ready = asyncio.Event()
    instances = []
    loop = asyncio.get_running_loop()

    class RecordingProcess(TestProcess):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)
            loop.call_soon_threadsafe(ready.set)

    invocation = asyncio.create_task(
        run_suite(
            tmp_path,
            "def double(value): return value * 2\n",
            "import time\ntime.sleep(120)\n",
            process_factory=RecordingProcess,
        )
    )
    await asyncio.wait_for(ready.wait(), 10)
    invocation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await invocation
    assert instances[0].poll() is not None
