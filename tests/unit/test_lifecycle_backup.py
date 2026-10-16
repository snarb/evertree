from __future__ import annotations

from pathlib import Path

import pytest

from evertree.core.programs.lifecycle import (
    LifecycleError,
    validate_program_source,
)


def test_cross_program_imports_require_runtime_but_own_helpers_are_allowed():
    path = "src/evertree/processes/task/_exec/implementation.py"
    validate_program_source("from evertree.processes.task._exec.helper import useful", path)
    validate_program_source("from .helper import useful", path)
    validate_program_source("from . import helper", path)
    for source in (
        "from evertree.processes.other._exec import run",
        "from .._model import run",
        "from ...other._exec import run",
        "importlib.import_module('evertree.processes.other._exec')",
        "from evertree.processes import other",
    ):
        with pytest.raises(LifecycleError, match="cross-Program"):
            validate_program_source(source, path)


@pytest.mark.parametrize("method", ["step", "call"])
def test_program_code_reaches_core_through_typed_api(method):
    path = "src/evertree/common/helper.py"
    validate_program_source("await memory.retrieve(ctx, 'query')", path)
    with pytest.raises(LifecycleError, match=f"Direct ctx.{method}"):
        validate_program_source(f"await ctx.{method}('memory.retrieve', {{}})", path)


def test_seed_program_sources_use_typed_core_api():
    root = Path(__file__).resolve().parents[2]
    for directory in ("src/evertree/processes", "src/evertree/common"):
        for path in (root / directory).rglob("*.py"):
            validate_program_source(
                path.read_text(encoding="utf-8"), path.relative_to(root).as_posix()
            )
