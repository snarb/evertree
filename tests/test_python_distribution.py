"""Source changes must not duplicate dependencies or broaden sandbox access."""

import json
import os
from pathlib import Path

import pytest

from evertree.core import cache, sandbox


@pytest.mark.skipif(os.name != "nt", reason="Private Windows Python distribution")
def test_python_shares_dependencies_and_collects_old_source_environments(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "cache_root", lambda: tmp_path / "cache")
    source = tmp_path / "evertree"
    (source / "core").mkdir(parents=True)
    (source / "__init__.py").write_text("")
    (source / "core/__init__.py").write_text("")
    (source / "core/contracts.py").write_text("VERSION = 1")
    (source / "core/private.py").write_text("PROTECTED = True")
    monkeypatch.setattr(sandbox, "__file__", str(source / "core/sandbox.py"))

    with sandbox.prepare_python(include_core=False) as (coding, (base, public)):
        packages = base / "Lib/site-packages"
        assert (packages / "dbos").is_dir()
        assert (packages / "pydantic").is_dir()
        assert not (packages / "codex_cli_bin").exists()
        assert not (packages / "pytest").exists()
        assert not list(packages.glob("*.pth"))
        assert {
            p.relative_to(public / "Lib/site-packages/evertree").as_posix()
            for p in (public / "Lib/site-packages/evertree").rglob("*.py")
        } == {"__init__.py", "core/__init__.py", "core/contracts.py"}
        with sandbox.prepare_python() as (worker, (worker_base, worker_source)):
            assert worker_base == base and worker != coding
            assert (worker_source / "Lib/site-packages/evertree/core/private.py").is_file()
            assert not (worker_source / "DLLs").exists()
            with sandbox.prepare_python(include_core=False) as (again, _):
                assert again == coding

        (source / "core/contracts.py").write_text("VERSION = 2")
        with sandbox.prepare_python(include_core=False) as (updated, (same_base, new_source)):
            assert same_base == base and updated != coding
            assert public.exists()  # Still leased by this process.
            scratch = tmp_path / "scratch"
            scratch.mkdir()
            code = """
import json, dbos, pydantic
from pathlib import Path
from evertree.core.contracts import VERSION
try:
    Path(dbos.__file__).write_text('must not change a shared library')
except PermissionError:
    pass
else:
    raise AssertionError('shared libraries are writable')
print(json.dumps([VERSION, str(Path.home())]))
"""
            with sandbox.SandboxedProcess(
                None,
                ["-I", "-c", code],
                workdir=scratch,
                readable=(),
                writable=(scratch,),
                include_core=False,
            ) as process:
                profile = Path(process.command_environment["USERPROFILE"])
                assert process.wait(timeout=30) == 0, process.stderr.read().decode()
                assert json.loads(process.stdout.read())[0] == 2
            assert not profile.exists()
        assert public.exists()
    assert not public.exists()
    assert new_source.exists() and base.exists()
    assert len(list((tmp_path / "cache/python").glob("*/python.exe"))) == 1


@pytest.mark.skipif(os.name != "nt", reason="Shared Windows AppContainer ACLs")
def test_parallel_sandboxes_keep_access_to_shared_python(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(cache, "cache_root", lambda: tmp_path / "cache")

    def run(index):
        scratch = tmp_path / str(index)
        scratch.mkdir()
        with sandbox.SandboxedProcess(
            None,
            ["-I", "-c", "import dbos, pydantic, time; time.sleep(0.1); print('ready')"],
            workdir=scratch,
            readable=(),
            writable=(scratch,),
        ) as process:
            assert process.wait(timeout=30) == 0, process.stderr.read().decode()
            assert process.stdout.read().strip() == b"ready"

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run, range(8)))
    assert not list((tmp_path / "cache/.leases").iterdir())
    assert not list((tmp_path / "cache/temporary").iterdir())
