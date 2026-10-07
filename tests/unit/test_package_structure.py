"""Package markers must not execute code or hide dependencies behind re-exports."""

import ast
from pathlib import Path


def test_package_initializers_contain_only_a_docstring():
    package = Path(__file__).resolve().parents[2] / "src" / "evertree"
    initializers = sorted(package.rglob("__init__.py"))
    assert initializers
    for path in initializers:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert ast.get_docstring(tree), path
        assert len(tree.body) == 1, path
