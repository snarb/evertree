"""Git candidate lifecycle and fixed, core-owned activation gates."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from .backup import safe_remove_tree
from .evaluation import AcceptanceCriteria, assess_candidate
from .runtime import ProgramExecutionError, _git


class LifecycleError(RuntimeError):
    pass


def validate_program_imports(source: str, path: str) -> None:
    """Reject direct cross-Program imports while allowing a Program's helpers.

    This is an architectural source check, not an OS security boundary. Arbitrary
    Python reflection is confined by the worker sandbox and gateway separately.
    """
    parts = path.removeprefix("src/").removesuffix(".py").replace("/", ".").split(".")
    own = ".".join(parts[: parts.index("_programs") + 2]) if "_programs" in parts else None
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return  # The fixed compile gate reports syntax errors as failed checks.
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            prefix = ".".join(parts[: -node.level]) + "." if node.level else ""
            targets = [prefix + (node.module or "") + "." + alias.name for alias in node.names]
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            function = node.func
            is_import = (isinstance(function, ast.Name) and function.id == "__import__") or (
                isinstance(function, ast.Attribute) and function.attr == "import_module"
            )
            if is_import and isinstance(node.args[0].value, str):
                targets = [node.args[0].value]
        for target in targets:
            if "_programs" in target.split(".") and not (
                own and (target == own or target.startswith(own + "."))
            ):
                raise LifecycleError(
                    f"Direct cross-Program import at {path}:{node.lineno}; use ctx.call"
                )


def git(repository: Path, *arguments: str) -> str:
    try:
        return _git(repository, *arguments).decode("utf-8", errors="replace").strip()
    except ProgramExecutionError as error:
        raise LifecycleError(str(error)) from error


def remote_git(repository: Path, *arguments: str) -> str:
    """Network Git only for the trusted repository, never candidate-controlled config."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "core.hooksPath=",
            "-c",
            "core.longpaths=true",
            *arguments,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode:
        raise LifecycleError(result.stderr.strip())
    return result.stdout.strip()


def resolve_program_remote(source: Path, remote: str | None = None) -> str:
    if remote is None:
        remote = os.environ.get("EVERTREE_PROGRAM_REMOTE")
    if remote is None:
        remote = remote_git(source, "remote", "get-url", "origin")
    return remote


def publish_programs(repository: Path, remote: str) -> None:
    """Keep saved revisions reachable through one append-only Git branch."""
    branch = "refs/heads/evertree/programs"
    if remote_git(repository, "ls-remote", "--heads", remote, branch):
        remote_git(repository, "fetch", "--no-tags", remote, f"{branch}:{branch}")
    revisions = sorted(
        set(git(repository, "for-each-ref", "--format=%(objectname)", "refs/heads").splitlines())
    )
    parents = git(repository, "merge-base", "--independent", *revisions).splitlines()
    revision = parents[0]
    tree = git(repository, "rev-parse", "main^{tree}")
    if len(parents) > 1 or git(repository, "rev-parse", revision + "^{tree}") != tree:
        # Link divergent candidates and history after a restore without merging
        # unapproved code into main or rewriting already published history.
        revision = git(
            repository,
            "commit-tree",
            tree,
            *(argument for parent in parents for argument in ("-p", parent)),
            "-m",
            "Preserve program revisions",
        )
    remote_git(repository, "push", remote, f"{revision}:{branch}")
    git(repository, "update-ref", branch, revision)


def fetch_programs(repository: Path, remote: str, revision: str) -> None:
    remote_git(
        repository,
        "fetch",
        "--no-tags",
        remote,
        "refs/heads/evertree/programs:refs/heads/evertree/programs",
    )
    git(repository, "cat-file", "-e", revision + "^{commit}")


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".pending")
    pending.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    pending.replace(path)


def initialize_seed_repository(source: Path, destination: Path) -> str:
    """Create the managed Program repository without touching the developer repo.

    Copy only Program code and common helpers. Trusted core is supplied by the
    installed runtime, never copied into the autonomously editable repository.
    """
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if (destination / ".git").exists():
        return git(destination, "rev-parse", "main")
    if destination.exists() and any(destination.iterdir()):
        raise LifecycleError("Seed destination is not empty")
    destination.mkdir(parents=True, exist_ok=True)
    package = source / "src" / "evertree"
    if not package.exists():
        package = source
    for name in ("processes", "common"):
        if (package / name).is_dir():
            shutil.copytree(
                package / name,
                destination / "src" / "evertree" / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
    (destination / "README.md").write_text(
        "# EverTree managed Program repository\n\nActive programs are committed on main.\n",
        encoding="utf-8",
    )
    git(destination, "init", "-b", "main")
    git(destination, "config", "user.name", "EverTree")
    git(destination, "config", "user.email", "evertree@localhost")
    git(destination, "add", ".")
    git(destination, "commit", "-m", "Initialize verified bootstrap programs")
    return git(destination, "rev-parse", "HEAD")


@dataclass(frozen=True)
class ProgramBranch:
    id: str
    program_id: str | int
    git_ref: str
    workspace: str
    base_revision: str
    change_claim: str
    status: str = "active"


@dataclass(frozen=True)
class EvaluationReport:
    subject_revision: str
    dataset_revision: str
    checks: Mapping[str, bool | None]
    metrics: Mapping[str, float]
    independent: bool
    source_ids: tuple[str, ...]
    trace_ids: tuple[str, ...]
    baseline_metrics: Mapping[str, float] | None = None
    uncertainty: Mapping[str, tuple[float, float]] | None = None


class ProgramLifecycleRuntime:
    """A fixed acceptance procedure; candidate code never supplies its policy.

    The evaluator callback belongs to trusted core. A report cannot activate code
    until this runtime records a verified receipt for its exact committed tree.
    """

    def __init__(
        self,
        repository: Path,
        state_dir: Path,
        criteria: AcceptanceCriteria | Callable[[ProgramBranch], AcceptanceCriteria],
        *,
        on_activate: Callable[[ProgramBranch, str], None] | None = None,
    ):
        self.repository = Path(repository).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.criteria = criteria
        self.on_activate = on_activate
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._record_path = self.state_dir / "lifecycle.json"
        self._data = (
            json.loads(self._record_path.read_text(encoding="utf-8"))
            if self._record_path.exists()
            else {"branches": {}, "evaluations": {}, "choices": []}
        )
        self._lock = asyncio.Lock()
        self._recover_interrupted_activation()

    def _persist(self):
        _save(self._record_path, self._data)

    def _recover_interrupted_activation(self):
        pending = self._data.get("activation_pending")
        if pending:
            current = git(self.repository, "rev-parse", "main")
            if current == pending["new_revision"]:
                if git(self.repository, "status", "--porcelain"):
                    raise LifecycleError(
                        "Interrupted activation needs manual recovery: repository is dirty"
                    )
                git(self.repository, "reset", "--hard", pending["old_revision"])
            elif current != pending["old_revision"]:
                raise LifecycleError("Interrupted activation conflicts with current main")
            self._data.pop("activation_pending")
            self._persist()

    def create_candidate(self, program_id: str | int, change_claim: str) -> ProgramBranch:
        if not change_claim.strip():
            raise ValueError("A candidate requires a testable change claim")
        identifier = uuid.uuid4().hex
        workspace = self.state_dir / "candidates" / identifier
        workspace.parent.mkdir(parents=True, exist_ok=True)
        base = git(self.repository, "rev-parse", "main")
        # Fetch into a private initialized repository: no hardlinks, alternates,
        # shared metadata or host Git configuration enter a coding workspace.
        workspace.mkdir()
        git(workspace, "init", "-b", "main")
        git(workspace, "fetch", "--no-tags", str(self.repository), base)
        branch = "codex/" + identifier
        git(workspace, "switch", "-c", branch, base)
        git(workspace, "config", "user.name", "EverTree")
        git(workspace, "config", "user.email", "evertree@localhost")
        candidate = ProgramBranch(
            identifier, program_id, branch, str(workspace), base, change_claim
        )
        self._data["branches"][identifier] = asdict(candidate)
        self._persist()
        return candidate

    def candidate(self, candidate_id: str) -> ProgramBranch:
        try:
            return ProgramBranch(**self._data["branches"][candidate_id])
        except KeyError as exc:
            raise LifecycleError("Unknown candidate") from exc

    def retain_candidate(self, candidate_id: str) -> str:
        self.candidate(candidate_id)
        workspace = self.state_dir / "candidates" / candidate_id
        revision = git(workspace, "rev-parse", "HEAD")
        git(
            self.repository,
            "fetch",
            "--no-tags",
            str(workspace),
            f"{revision}:refs/heads/candidates/{revision}",
        )
        return revision

    def discard_candidates(self, identities=None) -> None:
        """Keep decisions and committed history; discard candidate working directories."""
        for identity in identities if identities is not None else self._data["branches"]:
            candidate = self._data["branches"][identity]
            workspace = self.state_dir / "candidates" / identity
            if workspace.exists():
                self.retain_candidate(identity)
                safe_remove_tree(workspace, self.state_dir / "candidates")
            if candidate["status"] == "active":
                candidate["status"] = "abandoned"
        if identities is None:
            safe_remove_tree(self.state_dir / "candidates", self.state_dir)
        self._persist()

    def _validate_candidate(self, candidate: ProgramBranch) -> str:
        if candidate.status != "active":
            raise LifecycleError("Candidate is no longer active")
        workspace = Path(candidate.workspace)
        if git(workspace, "status", "--porcelain"):
            raise LifecycleError("Commit all candidate changes before evaluation")
        revision = git(workspace, "rev-parse", "HEAD")
        git(workspace, "fsck", "--strict", "--no-reflogs", revision)
        if revision == candidate.base_revision:
            raise LifecycleError("Candidate has no committed change")
        base = git(workspace, "merge-base", candidate.base_revision, revision)
        if base != candidate.base_revision:
            raise LifecycleError("Candidate does not descend from its recorded baseline")
        changes = git(
            workspace, "diff", "--name-only", candidate.base_revision, revision
        ).splitlines()
        allowed = ("src/evertree/processes/", "src/evertree/common/", "tests/", "artifacts/")
        for changed in changes:
            if not changed.startswith(allowed):
                raise LifecycleError(f"Candidate touches protected or unapproved code: {changed}")
            if changed.startswith("src/") and changed.endswith(".py"):
                try:
                    source = git(workspace, "show", f"{revision}:{changed}")
                except LifecycleError:
                    continue  # Deleted files have no imports to inspect.
                validate_program_imports(source, changed)
        # Acceptance imports only installed core. Shared Program helpers are
        # permitted, but candidate tests cannot replace this gate or its policy.
        return revision

    async def evaluate(
        self,
        candidate_id: str,
        evaluator: Callable[[ProgramBranch, str], Awaitable[EvaluationReport]],
    ) -> EvaluationReport:
        async with self._lock:
            candidate = self.candidate(candidate_id)
            criteria = self.criteria(candidate) if callable(self.criteria) else self.criteria
            revision = self._validate_candidate(candidate)
            self.retain_candidate(candidate_id)
            report = await evaluator(candidate, revision)
            if (
                report.subject_revision != revision
                or self._validate_candidate(candidate) != revision
            ):
                raise LifecycleError("Evaluation does not match the unchanged committed candidate")
            if not report.dataset_revision or not report.source_ids or not report.trace_ids:
                raise LifecycleError("Evaluation must retain dataset, source and trace provenance")
            verification = assess_candidate(
                criteria=criteria,
                checks=report.checks,
                candidate_metrics=report.metrics,
                baseline_metrics=report.baseline_metrics,
                independent=report.independent,
                uncertainty=report.uncertainty,
            )
            self._data["evaluations"][candidate_id] = {
                "report": asdict(report),
                "verification": verification.to_dict(),
                "criteria": asdict(criteria),
            }
            self._persist()
            return report

    async def choose(
        self,
        candidate_id: str,
        decision: str,
        *,
        reason: str,
        expected_dataset_revision: str | None = None,
    ) -> str | None:
        """Explicit EvaluationChoice; only merge_branch performs activation."""
        if decision not in ("merge_branch", "continue_branch", "reject_branch", "archive_branch"):
            raise ValueError("Unsupported EvaluationChoice")
        if not reason.strip():
            raise ValueError("EvaluationChoice requires a reason")
        async with self._lock:
            candidate = self.candidate(candidate_id)
            if candidate.status != "active":
                raise LifecycleError("Candidate is no longer active")
            self.retain_candidate(candidate_id)
            if decision != "merge_branch":
                if decision != "continue_branch":
                    self._data["branches"][candidate_id]["status"] = (
                        "rejected" if decision == "reject_branch" else "archived"
                    )
                self._data["choices"].append(
                    {"candidate_id": candidate_id, "decision": decision, "reason": reason}
                )
                self._persist()
                if decision != "continue_branch":
                    self.discard_candidates([candidate_id])
                return None
            revision = self._validate_candidate(candidate)
            receipt = self._data["evaluations"].get(candidate_id)
            if not receipt or receipt["report"]["subject_revision"] != revision:
                raise LifecycleError("No evaluation exists for this exact revision")
            # Recheck the current fixed policy rather than trusting a saved boolean.
            report = EvaluationReport(**receipt["report"])
            criteria = self.criteria(candidate) if callable(self.criteria) else self.criteria
            if json.dumps(receipt["criteria"], sort_keys=True) != json.dumps(
                asdict(criteria), sort_keys=True
            ):
                raise LifecycleError(
                    "Acceptance criteria changed; independently reevaluate candidate"
                )
            if (
                expected_dataset_revision is not None
                and report.dataset_revision != expected_dataset_revision
            ):
                raise LifecycleError(
                    "Evaluation dataset changed; independently reevaluate candidate"
                )
            verification = assess_candidate(
                criteria=criteria,
                checks=report.checks,
                candidate_metrics=report.metrics,
                baseline_metrics=report.baseline_metrics,
                independent=report.independent,
                uncertainty=report.uncertainty,
            )
            if not verification.verified:
                raise LifecycleError("Acceptance checks failed: " + "; ".join(verification.reasons))
            previous = git(self.repository, "rev-parse", "main")
            if previous != candidate.base_revision:
                raise LifecycleError(
                    "Active code changed; rebase and independently reevaluate candidate"
                )
            if git(self.repository, "status", "--porcelain"):
                raise LifecycleError("Active Program repository is dirty")
            self._data["activation_pending"] = {"old_revision": previous, "new_revision": revision}
            self._persist()
            try:
                git(
                    self.repository,
                    "fetch",
                    "--no-tags",
                    "--no-write-fetch-head",
                    candidate.workspace,
                    revision,
                )
                git(self.repository, "merge", "--ff-only", revision)
                if self.on_activate:
                    self.on_activate(candidate, revision)
            except BaseException:
                git(self.repository, "reset", "--hard", previous)
                self._data.pop("activation_pending", None)
                self._persist()
                raise
            self._data.pop("activation_pending")
            self._data["branches"][candidate_id]["status"] = "merged"
            self._data["choices"].append(
                {
                    "candidate_id": candidate_id,
                    "decision": decision,
                    "reason": reason,
                    "revision": revision,
                }
            )
            self._persist()
            self.discard_candidates([candidate_id])
            return revision

    def snapshot(self):
        return json.loads(json.dumps(self._data))

    def restore(self, snapshot):
        if self._lock.locked():
            raise LifecycleError("Cannot restore lifecycle during an operation")
        self._data = json.loads(json.dumps(snapshot))
        self._persist()
