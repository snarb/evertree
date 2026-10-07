from __future__ import annotations

import pytest

from evertree.core.programs.lifecycle import (
    LifecycleError,
    validate_program_imports,
)


def test_cross_program_imports_require_runtime_but_own_helpers_are_allowed():
    path = "src/evertree/processes/task/_exec/implementation.py"
    validate_program_imports("from evertree.processes.task._exec.helper import useful", path)
    validate_program_imports("from .helper import useful", path)
    validate_program_imports("from . import helper", path)
    for source in (
        "from evertree.processes.other._exec import run",
        "from .._model import run",
        "from ...other._exec import run",
        "importlib.import_module('evertree.processes.other._exec')",
        "from evertree.processes import other",
    ):
        with pytest.raises(LifecycleError, match="cross-Program"):
            validate_program_imports(source, path)
