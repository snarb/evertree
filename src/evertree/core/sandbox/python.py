"""Cached Python distributions and EverTree source environments for isolated execution."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from contextlib import contextmanager
from pathlib import Path

from .. import cache
from ..backup import _extended
from .process import SandboxUnavailable


def _key(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def _sources(include_core):
    package_root = Path(__file__).resolve().parents[2]
    if include_core:
        return {
            path.relative_to(package_root): path.read_bytes()
            for path in package_root.rglob("*.py")
            if not set(path.relative_to(package_root).parts)
            & {"processes", "common", "__pycache__"}
        }
    return {
        Path("__init__.py"): b"",
        Path("core/__init__.py"): b"",
        Path("core/contracts.py"): (package_root / "core" / "contracts.py").read_bytes(),
    }


def _macos_runtime_paths() -> tuple[Path, ...]:
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    library = Path(sysconfig.get_config_var("LIBDIR"))
    # Grant stdlib entries individually: its site-packages belongs to the host.
    paths = [
        Path(sys._base_executable).resolve(),
        *(path for path in stdlib.iterdir() if path.name != "site-packages"),
        *library.glob("*.dylib"),
        *library.glob("python*.zip"),
    ]
    framework = Path(sys.base_prefix) / "Python"
    if framework.is_file():
        paths.append(framework)
    return tuple(paths)


@contextmanager
def _prepare_macos(include_core):
    from importlib import metadata

    from ..environment import _installed_packages

    packages = _installed_packages(("dbos", "pydantic"))
    dependencies = {}
    for name in packages:
        distribution = metadata.distribution(name)
        if distribution.files is None:
            raise SandboxUnavailable(f"Installed dependency has no file manifest: {name}")
        for relative in distribution.files:
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or relative.suffix
                in (
                    ".pth",
                    ".pyc",
                    ".egg-link",
                )
            ):
                continue
            root = relative.parts[0]
            if root != "__pycache__":
                dependencies[root] = Path(distribution.locate_file(root)).resolve()
    sources = _sources(include_core)
    key = _key(
        [
            1,
            sys.platform,
            platform.machine(),
            sys.version,
            sys.base_prefix,
            packages,
            {name: str(path) for name, path in dependencies.items()},
            {str(path): hashlib.sha256(data).hexdigest() for path, data in sources.items()},
        ]
    )
    site_relative = Path(
        f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )

    def build(destination):
        subprocess.run(
            [sys.executable, "-I", "-m", "venv", "--without-pip", str(destination)],
            check=True,
            capture_output=True,
        )
        site = destination / site_relative
        # Link only declared packages, rather than exposing the host's entire site-packages.
        for name, path in dependencies.items():
            (site / name).symlink_to(path, target_is_directory=path.is_dir())
        for relative, data in sources.items():
            target = site / "evertree" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    kind = "worker" if include_core else "public"
    with cache.acquire(kind, key, build) as environment:
        yield (
            environment / "bin/python",
            (
                *_macos_runtime_paths(),
                environment,
                *dependencies.values(),
            ),
        )


@contextmanager
def prepare_python(*, include_core: bool = True):
    """Private source environments with only declared worker dependencies."""
    from importlib import metadata

    from ..environment import _installed_packages

    if sys.platform == "darwin":
        with _prepare_macos(include_core) as prepared:
            yield prepared
        return
    if os.name != "nt":
        raise SandboxUnavailable("Generated programs require macOS or Windows")
    # These are the worker's declared dependencies, not the developer's entire environment.
    packages = _installed_packages(("dbos", "pydantic"))
    base_key = _key([1, sys.platform, platform.machine(), sys.version, packages])

    def build_base(destination):
        destination = _extended(destination)
        base = Path(sys.base_prefix)
        for name in ("python.exe", "pythonw.exe", "LICENSE.txt"):
            if (base / name).is_file():
                shutil.copy2(base / name, destination / name)
        for path in base.glob("*.dll"):
            shutil.copy2(path, destination / path.name)
        for name in ("Lib", "DLLs"):
            if (base / name).is_dir():
                shutil.copytree(
                    base / name,
                    destination / name,
                    ignore=shutil.ignore_patterns("__pycache__", "site-packages", "test", "tests"),
                )
        site = destination / "Lib" / "site-packages"
        for name in packages:
            distribution = metadata.distribution(name)
            if distribution.files is None:
                raise SandboxUnavailable(f"Installed dependency has no file manifest: {name}")
            for relative in distribution.files:
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or "__pycache__" in relative.parts
                    or relative.suffix in (".pth", ".pyc", ".egg-link")
                ):
                    continue
                target = site / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(distribution.locate_file(relative), target)

    sources = _sources(include_core)
    source_key = _key(
        [base_key, {str(path): hashlib.sha256(data).hexdigest() for path, data in sources.items()}]
    )
    with cache.acquire("python", base_key, build_base) as base:

        def build_sources(destination):
            subprocess.run(
                [
                    str(base / "python.exe"),
                    "-I",
                    "-m",
                    "venv",
                    "--without-pip",
                    "--system-site-packages",
                    str(destination),
                ],
                check=True,
                capture_output=True,
                creationflags=0x08000000,
            )
            for relative, data in sources.items():
                target = _extended(destination / "Lib/site-packages/evertree" / relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

        kind = "worker" if include_core else "public"
        with cache.acquire(kind, source_key, build_sources) as environment:
            yield environment / "Scripts/python.exe", (base, environment)
