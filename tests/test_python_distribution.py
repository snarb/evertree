"""Worker and coding interpreters expose different core authority surfaces."""

import importlib.metadata
import os
import sysconfig
from types import SimpleNamespace

import pytest

from evertree.core import sandbox


@pytest.mark.skipif(os.name != "nt", reason="Private Windows Python distribution")
def test_native_python_contains_only_public_contracts_and_keeps_third_party(tmp_path, monkeypatch):
    base = tmp_path / "base"
    (base / "Lib").mkdir(parents=True)
    (base / "python.exe").write_bytes(b"fixture interpreter; never executed")
    (base / "Lib" / "stdlib.py").write_text("stdlib = True\n", encoding="utf-8")
    site = tmp_path / "site"
    (site / "third_party").mkdir(parents=True)
    (site / "third_party" / "__init__.py").write_text("value = 1\n", encoding="utf-8")
    (site / "evertree").mkdir()
    (site / "evertree" / "private.py").write_text("protected = True\n", encoding="utf-8")
    (site / "evertree.pth").write_text("outside path\n", encoding="utf-8")
    monkeypatch.setattr(sandbox.sys, "base_prefix", str(base))
    monkeypatch.setattr(sysconfig, "get_paths", lambda: {"purelib": str(site)})
    monkeypatch.setattr(
        importlib.metadata,
        "distributions",
        lambda: [SimpleNamespace(metadata={"Name": "third-party"}, version="1")],
    )
    coding = sandbox.prepare_python(tmp_path / "cache", include_core=False)
    packages = coding.parent / "Lib" / "site-packages"
    assert (packages / "third_party" / "__init__.py").is_file()
    assert not (packages / "evertree.pth").exists()
    assert {
        path.relative_to(packages / "evertree").as_posix()
        for path in (packages / "evertree").rglob("*")
        if path.is_file()
    } == {"__init__.py", "core/__init__.py", "core/contracts.py"}
    assert (packages / "evertree" / "__init__.py").read_text() == ""
    worker = sandbox.prepare_python(tmp_path / "cache")
    assert worker != coding
    assert (worker.parent / "Lib" / "site-packages" / "evertree" / "core" / "runtime.py").is_file()
    assert sandbox.prepare_python(tmp_path / "cache", include_core=False) == coding
