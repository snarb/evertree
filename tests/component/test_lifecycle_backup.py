from __future__ import annotations

import pytest

from evertree.core.programs.lifecycle import (
    LifecycleError,
    git,
)


@pytest.mark.parametrize("section", ["include", 'includeIf "gitdir:**"', "Include"])
def test_git_rejects_external_includes_before_invoking_git(tmp_path, monkeypatch, section):
    from evertree.core.runtime import repository as program_repository

    repo = tmp_path / "repository"
    (repo / ".git" / "objects").mkdir(parents=True)
    (repo / ".git" / "config").write_text("[core]\nrepositoryformatversion = 0\n")
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
    from evertree.core.runtime import repository as program_repository

    repo = tmp_path / "repository"
    (repo / ".git" / "objects").mkdir(parents=True)
    (repo / ".git" / "config").write_text("[core]\nrepositoryformatversion = 0\n")
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
