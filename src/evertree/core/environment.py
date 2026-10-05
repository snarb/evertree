"""Runtime fingerprints for restoration; source files stay in Git."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from .backup import BackupError


class RuntimeEnvironmentError(BackupError):
    pass


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _installed_packages(roots=("evertree",)) -> dict[str, str]:
    """Follow installed runtime requirements, including requested dependency extras."""
    pending = [(name, frozenset()) for name in roots]
    visited: dict[str, set[str]] = {}
    versions = {}
    while pending:
        name, extras = pending.pop()
        name = canonicalize_name(name)
        contexts = {"", *extras} - visited.get(name, set())
        if not contexts:
            continue
        distribution = metadata.distribution(name)
        versions[name] = distribution.version
        visited.setdefault(name, set()).update(contexts)
        for value in distribution.requires or ():
            requirement = Requirement(value)
            if requirement.marker is None or any(
                requirement.marker.evaluate({"extra": extra}) for extra in contexts
            ):
                pending.append((requirement.name, frozenset(requirement.extras)))
    return dict(sorted(versions.items()))


def capture_runtime(source_root: Path) -> dict:
    source_root = Path(source_root).resolve()
    sources = {}
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(source_root):
            raise RuntimeEnvironmentError("Runtime source may not contain symbolic links")
        sources[(Path("src/evertree") / relative).as_posix()] = path.read_bytes()
    if "src/evertree/__init__.py" not in sources:
        raise RuntimeEnvironmentError("The installed EverTree Python sources are unavailable")
    source_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()}
    environment = {
        "format": 1,
        "revision": _git_source(source_root, "rev-parse", "HEAD"),
        "python": {
            "version": platform.python_version(),
            "implementation": sys.implementation.name,
            "build": sys.version,
            "platform": sys.platform,
            "machine": platform.machine(),
        },
        "packages": _installed_packages(),
        "source_files": source_hashes,
        "source_sha256": _digest(source_hashes),
    }
    environment["fingerprint"] = _digest(environment)
    return environment


def _git_source(source: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "-c", "core.hooksPath=", *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeEnvironmentError("Runtime Git check failed: " + str(error)) from error
    if result.returncode:
        raise RuntimeEnvironmentError("Runtime Git check failed: " + result.stderr.strip())
    return result.stdout.strip()


def require_committed_runtime(source: Path) -> None:
    repository = Path(_git_source(source, "rev-parse", "--show-toplevel"))
    if _git_source(
        source,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        str(source),
        str(repository / "pyproject.toml"),
        str(repository / "uv.lock"),
        str(repository / ".python-version"),
    ):
        raise RuntimeEnvironmentError(
            "Commit runtime source and dependency changes before starting EverTree"
        )
    _git_source(
        source,
        "fetch",
        "--prune",
        "--no-tags",
        "origin",
        "+refs/heads/*:refs/remotes/origin/*",
    )
    if not _git_source(
        source, "for-each-ref", "--contains=HEAD", "--format=%(refname)", "refs/remotes/origin/"
    ):
        raise RuntimeEnvironmentError("Push the runtime commit before starting EverTree")


def validate_runtime(saved: dict, source_root: Path) -> None:
    """Reject incompatible code or dependencies without saving their files."""
    if not isinstance(saved, dict) or saved.get("format") != 1:
        raise RuntimeEnvironmentError("Backup has no verifiable runtime fingerprint")
    current = capture_runtime(source_root)
    differences = [
        name
        for name in ("revision", "python", "packages", "source_sha256")
        if saved.get(name) != current[name]
    ]
    if differences:
        raise RuntimeEnvironmentError(
            "Runtime mismatch ("
            + ", ".join(differences)
            + "). Install the saved Git revision and dependency versions before restoring."
        )
    if saved.get("fingerprint") != current["fingerprint"]:
        raise RuntimeEnvironmentError("Runtime manifest fingerprint mismatch")
