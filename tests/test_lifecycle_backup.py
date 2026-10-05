from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_runtime import TestProcess, commit_programs

from evertree.core.backup import BackupError, BackupManager, _extended, safe_remove_tree
from evertree.core.evaluation import AcceptanceCriteria
from evertree.core.lifecycle import (
    EvaluationReport,
    LifecycleError,
    ProgramLifecycleRuntime,
    git,
    initialize_seed_repository,
    publish_programs,
    remote_git,
    validate_program_imports,
)
from evertree.core.runtime import ProgramSpec, Runtime


def seed_repository(tmp_path):
    source = tmp_path / "seed"
    program = source / "src" / "evertree" / "processes" / "example.py"
    program.parent.mkdir(parents=True)
    program.write_text("def run(): return {'result': 1}\n", encoding="utf-8")
    repo = tmp_path / "repository"
    initialize_seed_repository(source, repo)
    return repo


def change(
    candidate,
    relative="src/evertree/processes/example.py",
    text="def run(): return {'result': 2}\n",
):
    workspace = Path(candidate.workspace)
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(workspace, "add", ".")
    git(workspace, "commit", "-m", "Candidate")
    return git(workspace, "rev-parse", "HEAD")


def test_amending_candidate_keeps_both_committed_revisions(tmp_path):
    repo = seed_repository(tmp_path)
    lifecycle = ProgramLifecycleRuntime(
        repo, tmp_path / "lifecycle", AcceptanceCriteria(("tests",))
    )
    candidate = lifecycle.create_candidate("program", "Improve result")
    original = change(candidate)
    lifecycle.retain_candidate(candidate.id)
    workspace = Path(candidate.workspace)
    git(workspace, "commit", "--amend", "-m", "Revised candidate")
    amended = lifecycle.retain_candidate(candidate.id)
    assert original != amended
    lifecycle.discard_candidates([candidate.id])
    assert not workspace.exists()
    for revision in (original, amended):
        assert git(repo, "rev-parse", "refs/heads/candidates/" + revision) == revision


def test_single_remote_branch_keeps_history_after_rollback_and_candidate_changes(
    tmp_path, program_remote
):
    repo = seed_repository(tmp_path)
    initial = git(repo, "rev-parse", "main")
    publish_programs(repo, program_remote)
    publish_programs(repo, program_remote)
    assert git(repo, "rev-parse", "evertree/programs") == initial

    git(repo, "commit", "--allow-empty", "-m", "Later version")
    later = git(repo, "rev-parse", "main")
    publish_programs(repo, program_remote)
    git(repo, "reset", "--hard", initial)
    git(repo, "commit", "--allow-empty", "-m", "New work after restore")
    current = git(repo, "rev-parse", "main")
    lifecycle = ProgramLifecycleRuntime(
        repo, tmp_path / "lifecycle", AcceptanceCriteria(("tests",))
    )
    candidate = lifecycle.create_candidate("program", "Unapproved change")
    candidate_revision = change(candidate)
    lifecycle.discard_candidates([candidate.id])
    publish_programs(repo, program_remote)
    published = git(repo, "rev-parse", "evertree/programs")
    publish_programs(repo, program_remote)
    assert git(repo, "rev-parse", "evertree/programs") == published
    assert git(repo, "rev-parse", "main") == current

    remote = Path(program_remote)
    assert remote_git(remote, "for-each-ref", "--format=%(refname)", "refs/heads") == (
        "refs/heads/evertree/programs"
    )
    recovered = tmp_path / "recovered"
    remote_git(
        tmp_path,
        "clone",
        "--single-branch",
        "--branch",
        "evertree/programs",
        program_remote,
        str(recovered),
    )
    for revision in (initial, later, current, candidate_revision):
        assert git(recovered, "merge-base", "--is-ancestor", revision, "HEAD") == ""
    assert git(recovered, "rev-parse", "HEAD^{tree}") == git(repo, "rev-parse", "main^{tree}")


@pytest.mark.parametrize("server_accepted", [False, True])
def test_program_publication_can_retry_after_interrupted_push(
    tmp_path, program_remote, monkeypatch, server_accepted
):
    from evertree.core import lifecycle as module

    repo = seed_repository(tmp_path)
    publish_programs(repo, program_remote)
    previous = git(repo, "rev-parse", "evertree/programs")
    git(repo, "commit", "--allow-empty", "-m", "New version")
    revision = git(repo, "rev-parse", "main")

    def interrupted(repository, *arguments):
        if arguments[0] == "push":
            if server_accepted:
                remote_git(repository, *arguments)
            raise LifecycleError("Connection interrupted")
        return remote_git(repository, *arguments)

    with monkeypatch.context() as patch:
        patch.setattr(module, "remote_git", interrupted)
        with pytest.raises(LifecycleError, match="Connection interrupted"):
            publish_programs(repo, program_remote)
    assert git(repo, "rev-parse", "evertree/programs") == previous
    publish_programs(repo, program_remote)
    remote = Path(program_remote)
    assert remote_git(remote, "rev-parse", "evertree/programs") == revision
    assert remote_git(remote, "for-each-ref", "--format=%(refname)", "refs/heads") == (
        "refs/heads/evertree/programs"
    )


async def test_activation_requires_independent_exact_commit_and_fixed_checks(tmp_path):
    repo = seed_repository(tmp_path)
    lifecycle = ProgramLifecycleRuntime(
        repo,
        tmp_path / "lifecycle",
        AcceptanceCriteria(("program_tests",), target_metric="accuracy", threshold=0.8),
    )
    candidate = lifecycle.create_candidate("program", "Improved rules increase accuracy")
    revision = change(candidate)
    with pytest.raises(LifecycleError, match="No evaluation"):
        await lifecycle.choose(candidate.id, "merge_branch", reason="looks useful")

    async def evaluate(branch, actual_revision):
        assert actual_revision == revision
        return EvaluationReport(
            actual_revision,
            "dataset-v1",
            {"program_tests": True},
            {"accuracy": 0.9},
            True,
            ("source-1",),
            ("trace-1",),
        )

    await lifecycle.evaluate(candidate.id, evaluate)
    assert git(repo, "rev-parse", "main") == candidate.base_revision
    merged = await lifecycle.choose(
        candidate.id, "merge_branch", reason="Independent criteria passed"
    )
    assert merged == revision
    assert git(repo, "rev-parse", "main") == revision
    assert lifecycle.candidate(candidate.id).status == "merged"


async def test_activation_rejects_changed_policy_or_bound_dataset(tmp_path):
    repo = seed_repository(tmp_path)
    policies = {"program": AcceptanceCriteria(("program_tests",), "accuracy", threshold=0.8)}
    lifecycle = ProgramLifecycleRuntime(
        repo, tmp_path / "lifecycle", lambda candidate: policies[candidate.program_id]
    )
    candidate = lifecycle.create_candidate("program", "Improve observed accuracy")
    revision = change(candidate)

    async def evaluate(branch, actual_revision):
        return EvaluationReport(
            actual_revision,
            "heldout-v1",
            {"program_tests": True},
            {"accuracy": 0.9},
            True,
            ("source-1",),
            ("trace-1",),
        )

    await lifecycle.evaluate(candidate.id, evaluate)
    with pytest.raises(LifecycleError, match="dataset changed"):
        await lifecycle.choose(
            candidate.id, "merge_branch", reason="accept", expected_dataset_revision="heldout-v2"
        )
    policies["program"] = AcceptanceCriteria(("program_tests",), "accuracy", threshold=0.7)
    with pytest.raises(LifecycleError, match="criteria changed"):
        await lifecycle.choose(candidate.id, "merge_branch", reason="accept")
    assert git(repo, "rev-parse", "main") == candidate.base_revision
    policies["program"] = AcceptanceCriteria(("program_tests",), "accuracy", threshold=0.8)
    # JSON persistence turns tuples into arrays; equal semantics still match.
    lifecycle = ProgramLifecycleRuntime(
        repo, tmp_path / "lifecycle", lambda branch: policies[branch.program_id]
    )
    assert (
        await lifecycle.choose(
            candidate.id,
            "merge_branch",
            reason="Fixed policy and dataset confirmed",
            expected_dataset_revision="heldout-v1",
        )
        == revision
    )


async def test_lifecycle_rejects_acceptance_dependency_and_changed_commit(tmp_path):
    repo = seed_repository(tmp_path)
    lifecycle = ProgramLifecycleRuntime(
        repo, tmp_path / "lifecycle", AcceptanceCriteria(("checks",))
    )
    protected = lifecycle.create_candidate("program", "Replace acceptance")
    change(protected, "src/evertree/core/evaluation.py", "def always_pass(): return True\n")

    async def evaluate(branch, revision):
        return EvaluationReport(
            revision, "dataset-v1", {"checks": True}, {}, True, ("source-1",), ("trace-1",)
        )

    with pytest.raises(LifecycleError, match="protected"):
        await lifecycle.evaluate(protected.id, evaluate)
    candidate = lifecycle.create_candidate("program", "Improve a rule")
    change(candidate)
    await lifecycle.evaluate(candidate.id, evaluate)
    change(candidate, text="def run(): return {'result': 3}\n")
    with pytest.raises(LifecycleError, match="exact revision"):
        await lifecycle.choose(candidate.id, "merge_branch", reason="earlier result")


def test_candidate_git_config_cannot_execute_fsmonitor(tmp_path):
    repo = seed_repository(tmp_path)
    lifecycle = ProgramLifecycleRuntime(
        repo, tmp_path / "lifecycle", AcceptanceCriteria(("tests",))
    )
    candidate = lifecycle.create_candidate("program", "Check the immutable source")
    change(candidate)
    sentinel = tmp_path / "executed.txt"
    hook = Path(candidate.workspace) / ".git" / "hooks" / "malicious-monitor"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(f"#!/bin/sh\necho escaped > '{sentinel.as_posix()}'\n", encoding="utf-8")
    git(Path(candidate.workspace), "config", "core.fsmonitor", str(hook))
    assert lifecycle._validate_candidate(candidate)
    assert not sentinel.exists()


def test_trusted_staging_never_executes_candidate_or_host_filters(tmp_path, monkeypatch):
    repo = seed_repository(tmp_path)
    sentinel = tmp_path / "escaped-filter.txt"
    executable = repo / ".git" / "untrusted-filter"
    executable.write_text(
        f"#!/bin/sh\necho escaped > '{sentinel.as_posix()}'\nexit 12\n", encoding="utf-8"
    )
    for operation in ("clean", "smudge", "process"):
        git(repo, "config", "filter.untrusted." + operation, str(executable))
    git(repo, "config", "commit.gpgSign", "true")
    git(repo, "config", "gpg.program", str(executable))
    git(repo, "config", "filter.untrusted.required", "true")
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text(
        f'[filter "host"]\n clean = "{executable.as_posix()}"\n required = true\n', encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    (repo / ".gitattributes").write_text(
        "*.py filter=untrusted\n*.txt filter=host\n", encoding="utf-8"
    )
    (repo / "value.py").write_text("value = 3\n", encoding="utf-8")
    (repo / "value.txt").write_text("retained\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Trusted staging")
    assert git(repo, "show", "HEAD:value.py") == "value = 3"
    assert git(repo, "show", "HEAD:value.txt") == "retained"
    assert not sentinel.exists()


def test_missing_candidate_metadata_cannot_discover_or_modify_parent_repository(tmp_path):
    parent = seed_repository(tmp_path)
    nested = parent / "candidate"
    nested.mkdir()
    git(nested, "init", "-b", "main")
    (nested / "candidate.txt").write_text("untrusted candidate", encoding="utf-8")
    safe_remove_tree(nested / ".git", nested)
    revision = git(parent, "rev-parse", "HEAD")
    index = (parent / ".git" / "index").read_bytes()
    with pytest.raises(LifecycleError, match="missing its .git"):
        git(nested, "add", ".")
    assert git(parent, "rev-parse", "HEAD") == revision
    assert (parent / ".git" / "index").read_bytes() == index


@pytest.mark.parametrize("section", ["include", 'includeIf "gitdir:**"', "Include"])
def test_git_rejects_external_includes_before_invoking_git(tmp_path, monkeypatch, section):
    from evertree.core import program_repository

    repo = seed_repository(tmp_path)
    private = tmp_path / "private-canary"
    private.write_text("private-value-must-not-enter-Git-errors", encoding="utf-8")
    with (repo / ".git" / "config").open("a", encoding="utf-8") as config:
        config.write(f'\n[{section}]\n path = "{private.as_posix()}"\n')

    def forbidden_subprocess(*args, **kwargs):
        pytest.fail("Git was invoked before its external include was rejected")

    monkeypatch.setattr(program_repository.subprocess, "run", forbidden_subprocess)
    with pytest.raises(LifecycleError, match="includes are not allowed") as error:
        git(repo, "status", "--porcelain")
    assert "private-value" not in str(error.value)


@pytest.mark.parametrize("relative", ["objects/info/alternates", "commondir", "info/grafts"])
def test_git_rejects_external_metadata_redirects(tmp_path, monkeypatch, relative):
    from evertree.core import program_repository

    repo = seed_repository(tmp_path)
    redirect = repo / ".git" / relative
    redirect.parent.mkdir(parents=True, exist_ok=True)
    redirect.write_text(str(tmp_path / "private-objects"), encoding="utf-8")
    monkeypatch.setattr(
        program_repository.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("Git read a metadata redirect"),
    )
    with pytest.raises(LifecycleError, match="redirect objects"):
        git(repo, "rev-parse", "HEAD")


def test_git_rejects_gitfile_and_nested_metadata_links(tmp_path, monkeypatch):
    import os
    import subprocess

    from evertree.core import program_repository

    repo = seed_repository(tmp_path)
    outside = tmp_path / "outside-metadata"
    outside.mkdir()
    link = repo / ".git" / "linked-state"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(outside, target_is_directory=True)
    with monkeypatch.context() as patch:
        patch.setattr(
            program_repository.subprocess, "run", lambda *a, **kw: pytest.fail("Git read a link")
        )
        with pytest.raises(LifecycleError, match="reparse points"):
            git(repo, "status", "--porcelain")
    if os.name == "nt":
        link.rmdir()
    else:
        link.unlink()
    safe_remove_tree(repo / ".git", repo)
    (repo / ".git").write_text(f"gitdir: {outside}\n", encoding="utf-8")
    with pytest.raises(LifecycleError, match="private .git directory"):
        git(repo, "rev-parse", "HEAD")


def test_git_ignores_replacement_objects_and_candidate_integrity_is_checked(tmp_path):
    import stat
    import zlib

    repo = seed_repository(tmp_path)
    lifecycle = ProgramLifecycleRuntime(
        repo, tmp_path / "lifecycle", AcceptanceCriteria(("tests",))
    )
    candidate = lifecycle.create_candidate("program", "Improve an existing rule")
    revision = change(candidate)
    workspace = Path(candidate.workspace)
    git(workspace, "replace", candidate.base_revision, revision)
    original = git(
        workspace, "show", f"{candidate.base_revision}:src/evertree/processes/example.py"
    )
    assert "'result': 1" in original
    object_path = workspace / ".git" / "objects" / revision[:2] / revision[2:]
    contents = zlib.decompress(object_path.read_bytes())
    assert b"EverTree" in contents
    object_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    object_path.write_bytes(zlib.compress(contents.replace(b"EverTree", b"OtherOne")))
    with pytest.raises(LifecycleError, match="hash mismatch|corrupt"):
        lifecycle._validate_candidate(candidate)


def test_cross_program_imports_require_runtime_but_own_helpers_are_allowed():
    path = "src/evertree/processes/task/_programs/default/implementation.py"
    validate_program_imports(
        "from evertree.processes.task._programs.default.helper import useful", path
    )
    for source in (
        "from evertree.processes.other._programs.default import run",
        "importlib.import_module('evertree.processes.other._programs.default')",
    ):
        with pytest.raises(LifecycleError, match="cross-Program"):
            validate_program_imports(source, path)


async def test_backup_and_cleanup_support_long_paths_and_readonly_git_objects(tmp_path):
    import stat

    dependency = tmp_path / "dependency"
    relative = (
        Path("deep-segment-" + "x" * 40) / ("nested-" + "y" * 40) / ("more-" + "z" * 70) / "object"
    )
    source = _extended(dependency / relative)
    source.parent.mkdir(parents=True)
    source.write_text("fixed object", encoding="utf-8")
    source.chmod(stat.S_IREAD)

    async def gateway(method, payload):
        return None

    runtime = Runtime(tmp_path / "runtime", tmp_path, gateway, process_factory=TestProcess)
    backups = BackupManager(tmp_path / "backups")
    saved = await backups.create(runtime, lambda: {"stable": True})
    assert backups.read(saved)["core"] == {"stable": True}
    assert not (saved / "dependencies").exists()
    safe_remove_tree(dependency, tmp_path)
    assert not dependency.exists()
    safe_remove_tree(saved, backups.root)
    assert not saved.exists()
    with pytest.raises(BackupError, match="outside"):
        safe_remove_tree(tmp_path, tmp_path)


async def test_backup_restores_core_with_matching_durable_journal(tmp_path):
    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "program.py": """
async def run(ctx):
    return {'result': await ctx.step('increment')}
"""
        },
    )
    state = {"count": 0}

    async def gateway(method, payload):
        state["count"] += 1
        return state["count"]

    runtime = Runtime(tmp_path / "runtime", repository, gateway, process_factory=TestProcess)
    spec = ProgramSpec("program", "program.py", revision)
    await runtime.execute("task", spec, {}, run_id="first")
    backups = BackupManager(tmp_path / "backups")
    saved = await backups.create(runtime, lambda: dict(state))
    await runtime.execute("task", spec, {}, run_id="second")
    assert state["count"] == 2
    await backups.restore(
        runtime,
        lambda restored: state.update(restored),
        snapshot_core=lambda: dict(state),
        backup=saved,
    )
    assert state["count"] == 1
    assert not (runtime.state_dir / "journals" / "second").exists()
    first = await runtime.execute("task", spec, {}, run_id="first")
    assert first.result == 1
    assert state["count"] == 1
    (saved / "state.msgpack.zst").write_bytes(b"corrupted")
    with pytest.raises(BackupError, match="changed"):
        backups.read(saved)
    await runtime.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows Git long paths")
def test_managed_git_reads_revision_paths_under_long_temporary_root(tmp_path):
    root = tmp_path / ("nested-" + "a" * 100)
    _extended(root).mkdir(parents=True)
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@localhost")
    relative = "src/evertree/processes/example/_programs/default/implementation.py"
    target = _extended(root / relative)
    target.parent.mkdir(parents=True)
    target.write_text("value = 3\n")
    assert len(str(root / relative)) > 260
    git(root, "add", ".")
    git(root, "commit", "-m", "Long path fixture")
    revision = git(root, "rev-parse", "HEAD")
    assert git(root, "show", f"{revision}:{relative}") == "value = 3"
