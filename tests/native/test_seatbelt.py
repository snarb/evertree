"""macOS contracts that require real Seatbelt enforcement."""

import os
import socket
import sys
from pathlib import Path

import pytest

from evertree.core.sandbox.diagnostics import check_sandbox
from evertree.core.sandbox.process import start_process
from evertree.core.sandbox.python import prepare_python

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt")


def test_seatbelt_protects_files_links_tools_and_environment(tmp_path, monkeypatch):
    """A native child must retain boundaries across symlinks and subprocesses."""
    secret = tmp_path / "secret.txt"
    secret.write_text("protected")
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("readable")
    scratch = tmp_path / 'робота " & spaces'
    scratch.mkdir()
    (scratch / "escape").symlink_to(secret)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-inherit")
    code = f"""
import importlib.util, os, subprocess, sys
from pathlib import Path
import dbos, pydantic
from evertree.core.contracts import ProgramResult
assert ProgramResult('ok').result == 'ok'
for name in ('application', 'core.runtime', 'core.sandbox'):
    assert importlib.util.find_spec('evertree.' + name) is None
assert importlib.util.find_spec('pytest') is None
assert 'OPENAI_API_KEY' not in os.environ
assert Path({str(source / "input.txt")!r}).read_text() == 'readable'
for path in ({str(secret)!r}, 'escape', pydantic.__file__, {str(source / "input.txt")!r}):
    try:
        Path(path).write_text('changed')
    except PermissionError:
        pass
    else:
        raise AssertionError('write escaped: ' + path)
for path in ({str(secret)!r}, 'escape'):
    try:
        Path(path).read_text()
    except PermissionError:
        pass
    else:
        raise AssertionError('read escaped: ' + path)
Path('данные & spaces.txt').write_text('Привіт')
assert subprocess.run([sys.executable, '-I', '-c', 'print(42)'], capture_output=True, check=True).stdout.strip() == b'42'
print('ok', flush=True)
"""
    with start_process(
        None,
        ["-I", "-c", code],
        workdir=scratch,
        readable=(source,),
        writable=(scratch,),
        include_core=False,
    ) as process:
        home = process.command_environment["HOME"]
        assert process.wait(timeout=30) == 0, process.stderr.read().decode()
        assert process.stdout.read().strip() == b"ok"
    assert not os.path.exists(home)
    assert secret.read_text() == "protected"
    assert (scratch / "данные & spaces.txt").read_text() == "Привіт"
    process.close()


def test_seatbelt_allows_connections_to_local_services(tmp_path):
    """A live host listener proves networking remains usable in the sandbox."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(10)
        code = f"import socket; socket.create_connection({listener.getsockname()!r}, timeout=5).close()"
        with start_process(
            None,
            ["-I", "-c", code],
            workdir=tmp_path,
            readable=(),
            writable=(tmp_path,),
        ) as process:
            connection, _ = listener.accept()
            connection.close()
            assert process.wait(timeout=10) == 0, process.stderr.read().decode()


def test_seatbelt_doctor_reports_actual_boundaries():
    """Doctor must prove isolation with a real process, rather than platform detection."""
    assert check_sandbox() == {
        "backend": "seatbelt",
        "isolated": True,
        "read_denied": True,
        "write_denied": True,
        "scratch_writable": True,
    }


def test_mac_python_environment_uses_installed_runtime_and_only_declared_packages():
    """Prepared Python must expose public contracts without exposing installed core."""
    with prepare_python(include_core=False) as (python, roots):
        assert python.resolve() == Path(sys.executable).resolve()
        assert Path(sys.base_prefix).resolve() not in roots
        site = (
            python.parent.parent
            / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
        )
        assert (site / "pydantic").is_symlink()
        assert not (site / "pytest").exists()
        assert not list(site.glob("*.pth"))
        assert not (site / "evertree/core/runtime").exists()


def test_seatbelt_failure_never_starts_user_code(tmp_path, monkeypatch):
    """An invalid kernel profile must prevent execution rather than use a bare process."""
    from evertree.core.sandbox import seatbelt

    monkeypatch.setattr(seatbelt, "_profile", lambda *_: "(invalid-profile)")
    with start_process(
        Path(sys.executable),
        ["-c", "from pathlib import Path; Path('unsafe').touch()"],
        workdir=tmp_path,
        readable=(),
        writable=(tmp_path,),
    ) as process:
        assert process.wait(timeout=10) != 0
        assert process.stderr.read()
    assert not (tmp_path / "unsafe").exists()


def test_seatbelt_denies_host_terminal_and_pty_creation(tmp_path):
    """A separate host PTY must be inaccessible even to a sandbox with the same UID."""
    master, slave = os.openpty()
    try:
        terminal = os.ttyname(slave)
        code = f"""
import os
for flags in (os.O_RDONLY, os.O_WRONLY, os.O_RDWR):
    try:
        fd = os.open({terminal!r}, flags | os.O_NOCTTY | os.O_NONBLOCK)
    except PermissionError:
        pass
    else:
        os.close(fd)
        raise AssertionError('host terminal accessible')
try:
    master, slave = os.openpty()
except OSError:
    pass
else:
    os.close(master)
    os.close(slave)
    raise AssertionError('sandbox allocated a PTY')
"""
        with start_process(
            None,
            ["-I", "-c", code],
            workdir=tmp_path,
            readable=(),
            writable=(tmp_path,),
        ) as process:
            assert process.wait(timeout=10) == 0, process.stderr.read().decode()
    finally:
        os.close(master)
        os.close(slave)


def test_seatbelt_denies_base_site_packages(tmp_path):
    """Python import isolation alone cannot protect packages readable by absolute path."""
    import sysconfig

    site = Path(sysconfig.get_path("stdlib")) / "site-packages"
    assert site.is_dir()
    code = f"""
import os
try:
    os.listdir({str(site)!r})
except PermissionError:
    pass
else:
    raise AssertionError('host site-packages exposed')
"""
    candidates = list(site.glob("*/__init__.py"))
    if candidates:
        code += f"""
try:
    open({str(candidates[0])!r}, 'rb').read()
except PermissionError:
    pass
else:
    raise AssertionError('host package readable by absolute path')
"""
    with start_process(
        None,
        ["-I", "-c", code],
        workdir=tmp_path,
        readable=(),
        writable=(tmp_path,),
        include_core=False,
    ) as process:
        assert process.wait(timeout=10) == 0, process.stderr.read().decode()
