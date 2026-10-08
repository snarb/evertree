"""macOS Seatbelt filesystem isolation with unrestricted outgoing networking."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
import threading
from contextlib import ExitStack
from pathlib import Path

from .. import cache
from .job import MacProcessGroup
from .process import SandboxLimits, SandboxUnavailable
from .python import prepare_python

_SANDBOX = Path("/usr/bin/sandbox-exec")


def _profile(readable: tuple[Path, ...], writable: tuple[Path, ...]) -> str:
    def paths(operation, values):
        rules = []
        for path in dict.fromkeys(Path(value).resolve() for value in values):
            kind = "subpath" if path.is_dir() else "literal"
            rules.append(
                f"(allow {operation} ({kind} {json.dumps(str(path), ensure_ascii=False)}))"
            )
        return rules

    return "\n".join(
        [
            "(version 1)",
            "(deny default)",
            "(allow process-exec process-fork)",
            "(allow process-info* (target self))",
            "(allow signal (target self) (target children))",
            "(allow sysctl-read)",
            "(allow network-outbound)",
            "(allow file-read-metadata)",
            # dyld opens the root directory while resolving its shared libraries.
            '(allow file-read* (literal "/"))',
            # Python lists the stdlib directory before importing individual packages.
            f"(allow file-read* (literal {json.dumps(str(Path(sysconfig.get_path('stdlib')).resolve()))}))",
            (
                '(allow mach-lookup (global-name "com.apple.system.logger") '
                '(global-name "com.apple.system.notification_center") '
                '(global-name "com.apple.system.opendirectoryd.libinfo") '
                '(global-name "com.apple.networkd") '
                '(global-name "com.apple.trustd.agent"))'
            ),
            *paths(
                "file-read*",
                (
                    Path("/System/Library"),
                    Path("/usr/lib"),
                    Path("/usr/share"),
                    Path("/usr/bin"),
                    Path("/bin"),
                    Path("/private/etc/hosts"),
                    Path("/private/etc/resolv.conf"),
                    Path("/private/etc/localtime"),
                    Path("/private/etc/ssl"),
                    Path("/dev/null"),
                    Path("/dev/urandom"),
                    Path("/dev/random"),
                    *readable,
                    *writable,
                ),
            ),
            *paths("file-write*", (Path("/dev/null"), *writable)),
        ]
    )


class SandboxedProcess:
    """Popen-like owner of a Seatbelt process and its private process group."""

    def __init__(
        self,
        executable: Path | None,
        arguments: list[str],
        *,
        workdir: Path,
        readable: tuple[Path, ...],
        writable: tuple[Path, ...],
        limits: SandboxLimits | None = None,
        path_entries: tuple[Path, ...] = (),
        profile_dir: Path | None = None,
        include_core: bool = True,
    ) -> None:
        if sys.platform != "darwin" or not _SANDBOX.is_file():
            raise SandboxUnavailable("macOS execution requires /usr/bin/sandbox-exec")
        self._resources = ExitStack()
        self._lock = threading.RLock()
        self._closed = False
        self._process = self._tree = None
        try:
            if executable is None:
                executable, roots = self._resources.enter_context(
                    prepare_python(include_core=include_core)
                )
                readable = (*readable, *roots)
            if profile_dir is None:
                profile_dir = self._resources.enter_context(cache.temporary_directory())
            profile_dir = Path(profile_dir).resolve()
            writable = (*writable, profile_dir)
            self.command_environment = {
                "HOME": str(profile_dir),
                "TMPDIR": str(profile_dir) + "/",
                "TMP": str(profile_dir),
                "TEMP": str(profile_dir),
                "SHELL": "/bin/zsh",
                "ZDOTDIR": str(profile_dir),
                "PATH": os.pathsep.join(
                    map(str, (executable.parent, *path_entries, Path("/usr/bin"), Path("/bin")))
                ),
                "LANG": "en_US.UTF-8",
                "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
            }
            profile = _profile((*readable, executable.resolve()), writable)
            self._process = subprocess.Popen(
                [str(_SANDBOX), "-p", profile, str(executable), *arguments],
                cwd=workdir,
                env=self.command_environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            self.pid = self._process.pid
            self._tree = MacProcessGroup(self.pid)
            self.stdin, self.stdout, self.stderr = (
                self._process.stdin,
                self._process.stdout,
                self._process.stderr,
            )
        except BaseException:
            self.close()
            raise

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self._process.wait(timeout=timeout)

    def terminate(self) -> None:
        with self._lock:
            if self._process:
                self._process.poll()
            if self._tree:
                self._tree.close()
            if self._process:
                self._process.wait(timeout=10)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            commands = getattr(self, "command_groups", None)
            if commands:
                commands.close()
            self.terminate()
            if self._process:
                for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
                    stream.close()
            self._resources.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
