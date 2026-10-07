# Repository Layout

## Code Areas

Paths below are relative to `src/evertree/`.

| Path | Responsibility |
| --- | --- |
| `application.py`, `_application/` | Public `EverTree` API and coordination. Internal mixins group methods of one instance, not independent services. |
| `core/` | Trusted execution, storage, isolation, and mandatory acceptance checks; outside the mutable Program lifecycle. Organized by technical responsibility. |
| `processes/` | Evolving Programs for the agent's behavior; organized by the semantic graph. |
| `common/` | Reusable Program helpers. Sharing an algorithm does not imply sharing learned parameters. |

## Process Directories and Roles

`processes/` maps to **Self/Process** (`SelfProcess`). Directories use `snake_case` and follow `SUBTYPE_OF`; composite steps use graph `PART_WHOLE` links, not directory nesting.

```text
processes/task_management/planning/
  __init__.py       # taxonomy only: docstring, no registration or execution
  _exec.py          # performs the process
  _model.py         # describes or predicts it; only if implemented
```

- A role may instead be a package such as `_exec/implementation.py`; `_exec.py` and `_exec/` cannot coexist. Create only implemented roles and taxonomy levels.
- Planning and action selection are `exec` behavior. Using an LLM does not make a Program a `model`.
- Call other Programs, including another role of the same process, through the runtime. Direct imports are limited to ordinary dependencies, the Program's own helpers, and `common`.
- Keep one version per Program per commit. Alternatives belong on Git branches at the same paths, without variant directories.
- Renames must update the graph, directory, `git_path`, and references together while preserving stable IDs.

## Dependencies and Versions

The managed Program repository lives at `<home>/.state/program-repository`; trusted core is installed separately. Active code is on `main`; each candidate gets an independent clone under `.state/lifecycle/candidates`.

Candidate branches use `codex/program/<process-graph-path>/<role>/<candidate-name>`, for example `codex/program/Self/Process/TaskManagement/Planning/exec/refine-budget`. Published history is retained on remote `evertree/programs` without force pushes. Execution and restore use exact commits; presence in Git history does not imply acceptance.

## State and Artifacts

- `artifacts/` holds durable outputs, datasets, and weights, addressed by `(relative path, Git commit)`.
- `<home>/.state/` holds mutable state, journals, backups, and disposable workspaces. Backups exclude code and workspace files; see [operational contracts](../README.md#operational-contracts).
- Repository `tmp/` and `temp/` are cleaned after 24 hours without modification. Use `cache.temporary_directory()` to protect active temporary code directories; reading a file alone does not protect it from cleanup.
- `%LOCALAPPDATA%/EverTree/cache/` holds recoverable Python, dependency, Codex, and Git distributions outside state and backups. Source changes reuse cached dependencies.

## Lookup and Consistency Checks

```sh
uv run python -m evertree.core.programs.layout
```

Checks source paths, roles, entry points, and graph relationships against the seed graph without application startup. Candidate evaluation and activation check the exact commit against the working graph. Unregistered code, missing Programs, and inconsistent moves block acceptance. Changes to `common` require checking dependent Programs.

See [Program lifecycle architecture](architecture/Process%20Plane/Program%20Lifecycle%20and%20Evolution.md) and [test suites](../tests/README.md).
