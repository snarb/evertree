"""Git candidate lifecycle and fixed, core-owned activation gates."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote

from evertree.core.evaluation.acceptance import AcceptanceCriteria, assess_candidate
from evertree.core.runtime.repository import ProgramExecutionError, _git

from ..backup import safe_remove_tree


class LifecycleError(RuntimeError):
    pass


def validate_program_source(source: str, path: str) -> None:
    """Reject direct cross-Program imports and raw ctx method calls in Program code.

    Program and shared helper code only passes ctx to the typed evertree.core API,
    which owns durability. A Program's own helpers stay importable. This is an
    architectural source check, not an OS security boundary. Arbitrary Python
    reflection is confined by the worker sandbox and gateway separately.
    """
    parts = path.removeprefix("src/").removesuffix(".py").replace("/", ".").split(".")
    if parts[-1] == "__init__":
        parts.pop()
        package = ".".join(parts)
    else:
        package = ".".join(parts[:-1])
    role_index = next((i for i, part in enumerate(parts) if part in {"_exec", "_model"}), None)
    own = ".".join(parts[: role_index + 1]) if role_index is not None else None
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return  # The fixed compile gate reports syntax errors as failed checks.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ctx"
        ):
            raise LifecycleError(
                f"Direct ctx.{node.func.attr} at {path}:{node.lineno}; use the evertree.core API"
            )
        targets = []
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            try:
                module = (
                    importlib.util.resolve_name("." * node.level + (node.module or ""), package)
                    if node.level
                    else (node.module or "")
                )
            except (ImportError, ValueError) as error:
                raise LifecycleError(f"Invalid relative import at {path}:{node.lineno}") from error
            targets = [module + "." + alias.name for alias in node.names]
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            function = node.func
            is_import = (isinstance(function, ast.Name) and function.id == "__import__") or (
                isinstance(function, ast.Attribute) and function.attr == "import_module"
            )
            if is_import and isinstance(node.args[0].value, str):
                targets = [node.args[0].value]
        for target in targets:
            if (
                target == "evertree.processes" or target.startswith("evertree.processes.")
            ) and not (own and (target == own or target.startswith(own + "."))):
                raise LifecycleError(
                    f"Direct cross-Program import at {path}:{node.lineno}; use call_program"
                )


def git(repository: Path, *arguments: str) -> str:
    """Run a managed repository Git command and return its output or a lifecycle error."""
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
    """Select the explicit Program remote, EVERTREE_PROGRAM_REMOTE or the source repository origin."""
    if remote is None:
        remote = os.environ.get("EVERTREE_PROGRAM_REMOTE")
    if remote is None:
        remote = remote_git(source, "remote", "get-url", "origin")
    return remote


def publish_programs(repository: Path, remote: str) -> None:
    """Publish the active Program tree, retaining verified and candidate history."""
    branch = "refs/heads/evertree/programs"
    if remote_git(repository, "ls-remote", "--heads", remote, branch):
        remote_git(repository, "fetch", "--no-tags", remote, f"{branch}:{branch}")
    revisions = sorted(
        set(
            git(
                repository, "for-each-ref", "--format=%(objectname)", "refs/heads", "refs/tags"
            ).splitlines()
        )
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
    """Fetch retained Program history and require the requested revision to be available."""
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
        "# EverTree managed Program repository\n\n"
        "main is the active/default branch. Each commit contains one version per Program role.\n"
        "Alternatives use codex/program/<process-graph-path>/<role>/<candidate-name> at the same source path.\n"
        "Graph paths start with Self/Process; candidate names contain one to three words joined by hyphens.\n"
        "Repeated names receive -2, -3, etc. UUIDs remain internal candidate identities.\n"
        "tags/<candidate-branch>/<commit> retain exact candidate revisions.\n"
        "The remote active Program branch is evertree/programs; execution and restore use exact commits.\n",
        encoding="utf-8",
    )
    git(destination, "init", "-b", "main")
    git(destination, "config", "user.name", "EverTree")
    git(destination, "config", "user.email", "evertree@localhost")
    git(destination, "add", ".")
    git(destination, "commit", "-m", "Initialize verified bootstrap programs")
    return git(destination, "rev-parse", "HEAD")


# Activation, pause, rejection and archival per candidate kind. A branch of the
# slot's active Program merges; a new or alternative Program activates.
BRANCH_DECISIONS = {
    "merge_branch": "merged",
    "continue_branch": "active",
    "reject_branch": "rejected",
    "archive_branch": "archived",
}
PROGRAM_DECISIONS = {
    "activate_program": "merged",
    "keep_alternatives": "active",
    "reject_program": "rejected",
    "archive_program": "archived",
}


@dataclass(frozen=True)
class ProgramBranch:
    """A candidate change; status is active (open workspace), paused, merged, rejected or archived."""

    id: str
    program_id: str | int
    git_ref: str
    workspace: str
    base_revision: str
    change_claim: str
    status: str = "active"
    # The revision this candidate was replayed from onto a newer main.
    refreshed_from: str | None = None


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
        validate_layout: Callable[[ProgramBranch, str], None] | None = None,
        program_path: Callable[[str | int], str] | None = None,
    ):
        self.repository = Path(repository).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.criteria = criteria
        self.on_activate = on_activate
        self.validate_layout = validate_layout
        self.program_path = program_path or str
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

    def create_candidate(
        self, program_id: str | int, change_claim: str, *, candidate_name: str | None = None
    ) -> ProgramBranch:
        """Create an isolated candidate workspace and branch for a testable Program change."""
        if not change_claim.strip():
            raise ValueError("A candidate requires a testable change claim")
        if not str(program_id):
            raise ValueError("A candidate requires a Program ID")
        words = re.findall(
            r"[^\W_]+", (candidate_name if candidate_name is not None else change_claim).casefold()
        )
        if not words or (candidate_name is not None and len(words) > 3):
            raise ValueError("Candidate name must contain one to three words")
        name = "-".join(words[:3])
        parts = self.program_path(program_id).split("/")
        if not all(parts):
            raise ValueError("Program graph path must have nonempty components")
        program_ref = "/".join(
            quote(part, safe="").replace(".", "%2E").replace("~", "%7E") for part in parts
        )
        prefix = f"codex/program/{program_ref}/"
        existing = {item["git_ref"] for item in self._data["branches"].values()}
        existing.update(
            git(
                self.repository, "for-each-ref", "--format=%(refname:short)", "refs/heads"
            ).splitlines()
        )
        branch = prefix + name
        suffix = 2
        while branch in existing:
            branch = prefix + name + "-" + str(suffix)
            suffix += 1
        identifier = uuid.uuid4().hex
        workspace = self.state_dir / "candidates" / identifier
        workspace.parent.mkdir(parents=True, exist_ok=True)
        base = git(self.repository, "rev-parse", "main")
        # Fetch into a private initialized repository: no hardlinks, alternates,
        # shared metadata or host Git configuration enter a coding workspace.
        workspace.mkdir()
        git(workspace, "init", "-b", "main")
        git(workspace, "fetch", "--no-tags", str(self.repository), base)
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
        """Read the lifecycle record for a known candidate."""
        try:
            return ProgramBranch(**self._data["branches"][candidate_id])
        except KeyError as exc:
            raise LifecycleError("Unknown candidate") from exc

    def retain_candidate(self, candidate_id: str) -> str:
        """Copy a candidate's committed revision into the managed repository before workspace disposal."""
        candidate = self.candidate(candidate_id)
        workspace = self.state_dir / "candidates" / candidate_id
        revision = git(workspace, "rev-parse", "HEAD")
        git(
            self.repository,
            "fetch",
            "--no-tags",
            str(workspace),
            f"{revision}:refs/tags/{candidate.git_ref}/{revision}",
        )
        git(self.repository, "update-ref", "refs/heads/" + candidate.git_ref, revision)
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
                candidate["status"] = "paused"
        if identities is None:
            safe_remove_tree(self.state_dir / "candidates", self.state_dir)
        self._persist()

    def refresh_candidate(self, candidate_id: str) -> ProgramBranch:
        """Reopen an undecided candidate on the current main by reapplying its committed change.

        The candidate keeps its identity and holdout lineage. Its evaluation receipt
        is dropped because the evaluated tree no longer matches. A change that no
        longer applies leaves the candidate paused.
        """
        candidate = self.candidate(candidate_id)
        if candidate.status not in {"active", "paused"}:
            raise LifecycleError("Only an undecided candidate can be refreshed")
        workspace = self.state_dir / "candidates" / candidate_id
        if workspace.exists():
            if git(workspace, "status", "--porcelain"):
                raise LifecycleError("Commit all candidate changes before refreshing")
            self.retain_candidate(candidate_id)
        revision = git(self.repository, "rev-parse", "refs/heads/" + candidate.git_ref)
        base = git(self.repository, "rev-parse", "main")
        # Apply a patch instead of rebasing so no candidate merge driver ever runs.
        patch = _git(self.repository, "diff", "--binary", candidate.base_revision, revision)
        fresh = self.state_dir / "candidates" / (candidate_id + ".refresh")
        safe_remove_tree(fresh, self.state_dir / "candidates")
        fresh.mkdir(parents=True)
        try:
            git(fresh, "init", "-b", "main")
            git(fresh, "fetch", "--no-tags", str(self.repository), base)
            git(fresh, "switch", "-c", candidate.git_ref, base)
            git(fresh, "config", "user.name", "EverTree")
            git(fresh, "config", "user.email", "evertree@localhost")
            if patch:
                (fresh.parent / (candidate_id + ".patch")).write_bytes(patch)
                try:
                    git(fresh, "apply", "--index", str(fresh.parent / (candidate_id + ".patch")))
                finally:
                    (fresh.parent / (candidate_id + ".patch")).unlink()
                git(fresh, "commit", "-m", candidate.change_claim)
        except BaseException:
            safe_remove_tree(fresh, self.state_dir / "candidates")
            raise
        if workspace.exists():
            safe_remove_tree(workspace, self.state_dir / "candidates")
        fresh.replace(workspace)
        record = self._data["branches"][candidate_id]
        record.update(
            workspace=str(workspace),
            base_revision=base,
            status="active",
            refreshed_from=revision if revision != candidate.base_revision else None,
        )
        self._data["evaluations"].pop(candidate_id, None)
        self._persist()
        self.retain_candidate(candidate_id)
        return self.candidate(candidate_id)

    def change_fingerprint(self, candidate_id: str) -> str:
        """Identify the committed change by its changed paths and their pre- and post-image blobs.

        A refreshed candidate keeps its fingerprint only if main did not touch
        the files it changes, so its earlier evaluation still describes this change.
        """
        candidate = self.candidate(candidate_id)
        workspace = Path(candidate.workspace)
        revision = git(workspace, "rev-parse", "HEAD")
        raw = git(workspace, "diff", "--raw", "--no-abbrev", candidate.base_revision, revision)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def receipt(self, candidate_id: str) -> dict | None:
        """Return the stored evaluation report, verification and criteria for a candidate."""
        receipt = self._data["evaluations"].get(candidate_id)
        return json.loads(json.dumps(receipt)) if receipt else None

    def branches(self) -> list[ProgramBranch]:
        """List every recorded candidate."""
        return [ProgramBranch(**item) for item in self._data["branches"].values()]

    def _validate_candidate(self, candidate: ProgramBranch) -> str:
        """Require a changed, clean descendant commit confined to allowed candidate paths and imports."""
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
                validate_program_source(source, changed)
        # Acceptance imports only installed core. Shared Program helpers are
        # permitted, but candidate tests cannot replace this gate or its policy.
        if self.validate_layout:
            self.validate_layout(candidate, revision)
        return revision

    async def evaluate(
        self,
        candidate_id: str,
        evaluator: Callable[[ProgramBranch, str], Awaitable[EvaluationReport]],
    ) -> EvaluationReport:
        """Evaluate an unchanged committed candidate and persist acceptance evidence under Core policy."""
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
            self._data.setdefault("certificates", {})[candidate_id] = {
                "dataset_revision": report.dataset_revision,
                "fingerprint": self.change_fingerprint(candidate_id),
            }
            self._persist()
            return report

    def recertifiable(self, candidate_id: str, dataset_revision: str) -> bool:
        """Whether a refreshed candidate may meet its already seen holdout again.

        Only the unchanged change that was evaluated on that holdout qualifies,
        so the holdout's exposure taught this lineage nothing new.
        """
        candidate = self.candidate(candidate_id)
        certificate = self._data.get("certificates", {}).get(candidate_id)
        return bool(
            candidate.refreshed_from
            and certificate
            and certificate["dataset_revision"] == dataset_revision
            and certificate["fingerprint"] == self.change_fingerprint(candidate_id)
        )

    async def choose(
        self,
        candidate_id: str,
        decision: str,
        *,
        reason: str,
        expected_dataset_revision: str | None = None,
        holds_slot: bool = True,
    ) -> str | None:
        """Record an explicit EvaluationChoice; only merge_branch or activate_program activates code.

        holds_slot tells whether the candidate's Program is the active Program of
        its slot. Its branches use branch decisions; a new or alternative Program
        uses Program decisions.
        """
        decisions = BRANCH_DECISIONS if holds_slot else PROGRAM_DECISIONS
        if decision not in decisions:
            raise ValueError(
                "Unsupported EvaluationChoice for this candidate; use one of: "
                + ", ".join(decisions)
            )
        if not reason.strip():
            raise ValueError("EvaluationChoice requires a reason")
        async with self._lock:
            candidate = self.candidate(candidate_id)
            if candidate.status != "active":
                raise LifecycleError("Candidate is not open; refresh it first")
            self.retain_candidate(candidate_id)
            if decisions[decision] != "merged":
                self._data["branches"][candidate_id]["status"] = decisions[decision]
                self._data["choices"].append(
                    {"candidate_id": candidate_id, "decision": decision, "reason": reason}
                )
                self._persist()
                if decisions[decision] != "active":
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
                    "Active code changed; refresh and independently reevaluate candidate"
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
        """Capture candidate branches, evaluation reports and explicit lifecycle choices."""
        return json.loads(json.dumps(self._data))

    def restore(self, snapshot):
        """Replace idle lifecycle state from a snapshot and persist it."""
        if self._lock.locked():
            raise LifecycleError("Cannot restore lifecycle during an operation")
        self._data = json.loads(json.dumps(snapshot))
        self._persist()
