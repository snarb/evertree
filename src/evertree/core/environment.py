"""Content-addressed source and dependency bundles for compatible restoration."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from importlib import metadata
from pathlib import Path
from uuid import uuid4

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from .backup import BackupError, _extended, rename_state


class RuntimeEnvironmentError(BackupError):
    pass


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _installed_packages() -> dict[str, str]:
    """Follow installed runtime requirements, including requested dependency extras."""
    pending = [("evertree", frozenset())]
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


def _capture(source_root: Path) -> tuple[dict, dict[str, bytes]]:
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
    return environment, sources


def _requirements(environment: dict) -> str:
    python = environment["python"]
    lines = [
        f"# Python {python['implementation']} {python['version']} ({python['platform']} {python['machine']})",
        f"# evertree=={environment['packages']['evertree']} is supplied in src/evertree.",
        "# Install the saved EverTree sources separately; restoration never replaces trusted code.",
    ]
    lines.extend(
        f"{name}=={version}"
        for name, version in environment["packages"].items()
        if name != "evertree"
    )
    return "\n".join(lines) + "\n"


def _check_bundle(path: Path, environment: dict) -> None:
    path = _extended(path)
    try:
        saved = json.loads((path / "environment.json").read_text(encoding="utf-8"))
        if saved != environment:
            raise RuntimeEnvironmentError(
                "Runtime bundle manifest differs from the backup snapshot"
            )
        expected = {
            *environment["source_files"],
            "environment.json",
            "requirements.txt",
            ".python-version",
        }
        actual = {
            entry.relative_to(path).as_posix() for entry in path.rglob("*") if entry.is_file()
        }
        if actual != expected:
            raise RuntimeEnvironmentError("Runtime bundle contains missing or unexpected files")
        for relative, digest in environment["source_files"].items():
            source = path / relative
            if source.is_symlink() or not source.resolve().is_relative_to(path.resolve()):
                raise RuntimeEnvironmentError("Runtime bundle contains an unsafe source path")
            if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                raise RuntimeEnvironmentError("Runtime bundle source hash mismatch: " + relative)
        if (path / "requirements.txt").read_text(encoding="utf-8") != _requirements(environment):
            raise RuntimeEnvironmentError("Runtime bundle frozen requirements changed")
        if (path / ".python-version").read_text(encoding="utf-8") != environment["python"][
            "version"
        ] + "\n":
            raise RuntimeEnvironmentError("Runtime bundle Python version changed")
    except (OSError, ValueError, KeyError) as error:
        raise RuntimeEnvironmentError("Invalid runtime bundle: " + str(error)) from error


def prepare_runtime_bundle(source_root: Path, cache_root: Path) -> tuple[dict, Path]:
    """Capture sources once at startup and reuse their verified fingerprint directory."""
    environment, sources = _capture(source_root)
    destination = Path(cache_root).resolve() / environment["fingerprint"]
    if destination.exists():
        _check_bundle(destination, environment)
        return environment, destination
    staging = destination.with_name(destination.name + ".pending-" + uuid4().hex)
    for relative, contents in sources.items():
        target = _extended(staging / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
    _extended(staging / "environment.json").write_text(
        json.dumps(environment, sort_keys=True, indent=2), encoding="utf-8"
    )
    _extended(staging / "requirements.txt").write_text(_requirements(environment), encoding="utf-8")
    _extended(staging / ".python-version").write_text(
        environment["python"]["version"] + "\n", encoding="utf-8"
    )
    rename_state(staging, destination)
    return environment, destination


def validate_runtime_bundle(bundle: Path, saved: dict, source_root: Path) -> None:
    """Reject a restore before state changes unless code, Python and packages match."""
    if not isinstance(saved, dict) or saved.get("format") != 1 or "fingerprint" not in saved:
        raise RuntimeEnvironmentError(
            "Backup has no verifiable runtime bundle; identical runtime installation is required"
        )
    _check_bundle(bundle, saved)
    current, _ = _capture(source_root)
    differences = [
        name for name in ("python", "packages", "source_sha256") if saved.get(name) != current[name]
    ]
    if differences:
        raise RuntimeEnvironmentError(
            "Runtime mismatch ("
            + ", ".join(differences)
            + "). Install the exact saved runtime before restoring; trusted code was not changed."
        )
    if saved["fingerprint"] != current["fingerprint"]:
        raise RuntimeEnvironmentError("Runtime manifest fingerprint mismatch")
