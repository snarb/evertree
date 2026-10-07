# EverTree

A local agent with a semantic graph, memory, and executable Programs that evolve through verified updates. Available through a CLI and an asynchronous Python API; designed for a single installation.

## Quick start

Requires Python **3.13.16**, Git, [uv](https://docs.astral.sh/uv/), and local Codex authorization. Model calls use `openai-codex` with **gpt-6-luna / high**, without fallback.

**Program execution and native coding tools require Windows AppContainer.** macOS supports development and portable tests; its production sandbox is not implemented. Execution fails if isolation is unavailable.

```sh
uv python install 3.13.16
uv sync --frozen
```

Before application startup, trusted core sources must be committed and pushed to `origin`. Startup verifies publication and stops if sources are dirty or the remote is inaccessible.

On Windows:

```powershell
uv run evertree --home C:\agents\my-tree init
uv run evertree --home C:\agents\my-tree doctor
uv run evertree --home C:\agents\my-tree chat
```

`doctor` checks authorization, model availability, and actual sandbox enforcement. Use `uv run evertree --help` for task, Program, graph, memory, and backup commands.

## Operational contracts

- **Verified changes:** `core` owns trusted execution and mandatory checks; `processes` contains evolving Programs. Activation requires independent evaluation, passing candidate tests, improvement over the baseline, and an explicit selection decision.
- **Task delivery:** one Task executes at a time. Completion requires acknowledged answer delivery; Python `run()` acknowledges automatically, while custom transports must call `acknowledge_delivery()`. External actions require an `approval_handler`; the CLI requires literal `yes` in a terminal.
- **Disposable files:** task workspaces are deleted on completion, failure, or cancellation. Restart retains history and budgets but discards intermediate files and SDK sessions. Commit durable artifacts to Git.
- **Backups are state only:** they exclude code repositories, workspaces, inputs, and generated files. The two latest completed snapshots are retained. Program commits must be published to `evertree/programs` before a snapshot; publication failure preserves the previous backup. The remote defaults to `origin` and can be overridden with `EVERTREE_PROGRAM_REMOTE`.
- **Restore requires matching code:** install the recorded core version from Git first. Restore validates the environment and retrieves Program commits from remote history; it does not replace installed core sources.

## Development

```sh
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

The default suite runs unit and component tests with up to four workers. Integration, Windows-native, and opt-in live SDK suites are separate; see the [test guide](tests/README.md).

## Documentation

- [Architecture](docs/architecture/Overview.md)
- [Program lifecycle](docs/architecture/Process%20Plane/Program%20Lifecycle%20and%20Evolution.md)
