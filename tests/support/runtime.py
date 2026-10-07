from __future__ import annotations

import subprocess
from pathlib import Path


class TestProcess:
    """Explicit test injection: exercise DBOS separately from native isolation."""

    __test__ = False

    def __init__(self, executable, arguments, *, workdir, **_):
        self.process = subprocess.Popen(
            [str(executable), *arguments],
            cwd=workdir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.stdin, self.stdout, self.stderr = (
            self.process.stdin,
            self.process.stdout,
            self.process.stderr,
        )

    def poll(self):
        return self.process.poll()

    def terminate(self):
        self.process.terminate()
        self.process.wait(timeout=10)

    def close(self):
        if self.poll() is None:
            self.terminate()
        self.stdin.close()


def commit_programs(root: Path, files: dict[str, str]) -> str:
    root.mkdir(parents=True)
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for arguments in (
        ("init", "-b", "main"),
        ("config", "user.name", "Test"),
        ("config", "user.email", "test@localhost"),
        ("add", "."),
        ("commit", "-m", "Fixture"),
    ):
        subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
