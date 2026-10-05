"""Fixed candidate test convention: committed tests/test_*.py using unittest."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from .backup import _extended, _restore_io, safe_remove_tree
from .runtime import extract_revision
from .sandbox import SandboxedProcess

_RUNNER = """
import json, pathlib, sys, unittest
checkout = pathlib.Path(sys.argv[1])
sys.path[:0] = [str(checkout / 'src'), str(checkout)]
import evertree
import evertree.core
evertree.__path__[:] = [str(checkout / 'src' / 'evertree')]
suite = unittest.defaultTestLoader.discover(str(checkout / 'tests'), pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
report = {'tests_run': result.testsRun, 'failures': len(result.failures),
          'errors': len(result.errors), 'skipped': len(result.skipped)}
passed = result.wasSuccessful() and result.testsRun > len(result.skipped)
print(sys.argv[2] + json.dumps(report), flush=True)
sys.exit(0 if passed else 1)
"""


async def _tail(stream) -> str:
    tail = b""
    while block := await asyncio.to_thread(stream.read, 8192):
        tail = (tail + block)[-65536:]
    return tail.decode("utf-8", errors="replace")


async def run_candidate_tests(
    repository: Path,
    revision: str,
    root: Path,
    *,
    process_factory=None,
    timeout: float = 300,
) -> dict:
    """Observe a real test process against an immutable exact commit.

    Candidate tests are development checks, not an independent quality oracle.
    Their outcome never replaces the separate protected holdout evaluation.
    """
    root = Path(root).resolve()
    try:
        source, scratch = _extended(root / "source"), root / "scratch"
        await _restore_io(extract_revision, repository, revision, source)
        scratch.mkdir(parents=True)
        files = sorted(
            path.relative_to(source).as_posix() for path in (source / "tests").glob("test_*.py")
        )
        report = {
            "kind": "candidate_tests",
            "revision": revision,
            "files": files,
            "passed": False,
            "exit_code": None,
            "tests_run": 0,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "stdout": "",
            "stderr": "",
        }
        if not files:
            report["reason"] = "No committed tests/test_*.py unittest suite"
            return report
        runner = root / "runner.py"
        runner.write_text(_RUNNER, encoding="utf-8")
        marker = "EVERTREE_TEST_RESULT_" + uuid4().hex + ":"
        process = None
        readers = []
        try:
            async with asyncio.timeout(timeout):
                executable = None if process_factory is None else Path(sys.executable)
                startup = asyncio.create_task(
                    asyncio.to_thread(
                        process_factory or SandboxedProcess,
                        executable,
                        ["-I", "-B", str(runner), str(source), marker],
                        workdir=source,
                        readable=(root,),
                        include_core=False,
                        writable=(scratch,),
                        profile_dir=scratch,
                    )
                )
                try:
                    process = await asyncio.shield(startup)
                except asyncio.CancelledError:
                    process = await startup
                    raise
                readers = [
                    asyncio.create_task(_tail(process.stdout)),
                    asyncio.create_task(_tail(process.stderr)),
                ]
                while (code := process.poll()) is None:
                    await asyncio.sleep(0.02)
                report["exit_code"] = code
                report["stdout"], report["stderr"] = await asyncio.gather(*readers)
                result_lines = [
                    line[len(marker) :]
                    for line in report["stdout"].splitlines()
                    if line.startswith(marker)
                ]
                if len(result_lines) == 1:
                    counts = json.loads(result_lines[0])
                    if set(counts) != {"tests_run", "failures", "errors", "skipped"} or any(
                        type(value) is not int or value < 0 for value in counts.values()
                    ):
                        raise ValueError("Invalid unittest outcome")
                    report.update(counts)
                    report["passed"] = (
                        code == 0
                        and counts["tests_run"] > counts["skipped"]
                        and not (counts["failures"] or counts["errors"])
                    )
                else:
                    report["reason"] = "Test process did not return one complete unittest outcome"
        except TimeoutError:
            report["reason"] = "Candidate tests timed out"
        except Exception as error:  # noqa: BLE001 -- test launch/import failures fail the fixed gate
            report["reason"] = f"{type(error).__name__}: {error}"
        finally:
            if process is not None:
                await asyncio.to_thread(process.close)
            if readers:
                outputs = await asyncio.gather(*readers, return_exceptions=True)
                for key, output in zip(("stdout", "stderr"), outputs, strict=True):
                    if isinstance(output, str):
                        report[key] = output
        return report
    finally:
        await _restore_io(safe_remove_tree, root, root.parent)
