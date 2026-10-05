"""Protected Git access and extraction of committed Program code."""

from __future__ import annotations

import io
import os
import re
import stat
import subprocess
import zipfile
from pathlib import Path

from .backup import _extended


class ProgramExecutionError(RuntimeError):
    pass


def _validate_git_metadata(repository: Path, *, initializing: bool = False) -> Path:
    """Keep Git's authority inside this repository before Git reads any config."""
    metadata = repository / ".git"
    if not metadata.exists() and not metadata.is_symlink():
        if initializing:
            return metadata
        raise ProgramExecutionError("Managed repository is missing its .git directory")

    def reject_link(path: Path) -> None:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ProgramExecutionError(
                "Git metadata must not contain symbolic links or reparse points"
            )

    reject_link(metadata)
    if not metadata.is_dir():
        raise ProgramExecutionError("Managed repository requires a private .git directory")
    # Check each directory before os.walk can descend into it. This includes
    # object packs, refs, config files and nested metadata, not only .git itself.
    for directory, folders, files in os.walk(metadata, followlinks=False):
        for name in (*folders, *files):
            reject_link(Path(directory) / name)
    for relative in (
        "commondir",
        "gitdir",
        "objects/info/alternates",
        "objects/info/http-alternates",
        "info/grafts",
    ):
        if (metadata / relative).exists():
            raise ProgramExecutionError(
                "Git metadata must not redirect objects or repository state"
            )
    for name in ("config", "config.worktree"):
        config = metadata / name
        if config.exists():
            contents = config.read_text(encoding="utf-8-sig", errors="replace")
            if re.search(r"(?im)^\s*\[\s*include(?:if)?(?:\s|\.|\])", contents):
                raise ProgramExecutionError("Git configuration includes are not allowed")
    return metadata


def _git(repository: Path, *arguments: str) -> bytes:
    # Candidate repositories contain untrusted .git/config and hooks. Git is
    # used as an object reader here, never as a way to execute their commands.
    if arguments and arguments[0] == "diff":
        arguments = ("diff", "--no-ext-diff", "--no-textconv", *arguments[1:])
    repository = Path(repository).absolute()
    metadata = _validate_git_metadata(
        repository, initializing=bool(arguments and arguments[0] == "init")
    )
    if arguments and arguments[0] == "init":
        arguments = ("init", "--template=", *arguments[1:])
    command = [
        "git",
        "-C",
        str(repository),
        "--git-dir=" + str(metadata),
        "--work-tree=" + str(repository),
        "-c",
        "core.hooksPath=",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.longpaths=true",
        "-c",
        "core.pager=",
        "-c",
        "commit.gpgSign=false",
        "-c",
        "tag.gpgSign=false",
        "-c",
        "core.attributesFile=" + os.devnull,
        "-c",
        "core.excludesFile=" + os.devnull,
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.file.allow=always",
        "-c",
        "transfer.fsckObjects=true",
        "-c",
        "fetch.fsckObjects=true",
        "-c",
        "fsck.skipList=" + os.devnull,
        "-c",
        "fetch.fsck.skipList=" + os.devnull,
    ]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
    )
    if arguments and arguments[0] in {
        "add",
        "status",
        "diff",
        "checkout",
        "switch",
        "merge",
        "reset",
        "commit",
    }:
        filters = subprocess.run(
            [
                *command,
                "config",
                "--name-only",
                "--get-regexp",
                r"^filter\..*\.(clean|smudge|process|required)$",
            ],
            capture_output=True,
            check=False,
            env=environment,
        )
        if filters.returncode not in (0, 1):
            raise ProgramExecutionError(filters.stderr.decode("utf-8", errors="replace").strip())
        for prefix in {
            name.rsplit(".", 1)[0] for name in filters.stdout.decode("utf-8").splitlines()
        }:
            for operation in ("clean", "smudge", "process"):
                command.extend(("-c", prefix + "." + operation + "="))
            command.extend(("-c", prefix + ".required=false"))
    result = subprocess.run(
        [*command, *arguments], capture_output=True, check=False, env=environment
    )
    if result.returncode:
        raise ProgramExecutionError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def extract_revision(repository: Path, revision: str, destination: Path) -> None:
    destination = _extended(destination)
    resolved = _git(repository, "rev-parse", "--verify", revision + "^{commit}").decode().strip()
    if resolved != revision:
        raise ValueError("An exact commit is required")
    archive = _git(repository, "archive", "--format=zip", revision)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        root = destination.resolve()
        for info in source.infolist():
            target = (root / info.filename).resolve()
            if (
                not target.is_relative_to(root)
                or ((info.external_attr >> 16) & 0o170000) == 0o120000
            ):
                raise ValueError("Program checkout contains an unsafe path or symbolic link")
        source.extractall(root)


# Keep existing trace type names and pickled references valid through the public module.
for _export in (
    ProgramExecutionError,
    _validate_git_metadata,
    _git,
    extract_revision,
):
    _export.__module__ = "evertree.core.runtime"
