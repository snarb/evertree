# EverTree

A local agent with a semantic graph, memory, and executable Programs that evolve through verified updates. Available through a CLI and asynchronous Python components; designed for a single installation.


**Program execution and native coding tools use macOS Seatbelt or Windows AppContainer.** Filesystem access is limited to declared inputs, runtime tools and writable task directories. Outgoing internet access is always allowed. Execution fails if the native sandbox is unavailable.

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

On macOS (with Git/Xcode Command Line Tools installed):

```sh
uv run evertree --home ~/agents/my-tree init
uv run evertree --home ~/agents/my-tree doctor
uv run evertree --home ~/agents/my-tree chat
```

`doctor` checks authorization, model availability, and actual filesystem sandbox enforcement, and reports the selected backend.

macOS uses the installed Python runtime and a small source environment containing only declared dependencies. Seatbelt restrictions are inherited by subprocesses; cancellation kills the owned process groups. Codex commands register their separate groups with core before execution, so their descendants can also be stopped on completion or cancellation. This is a launch handshake, with no resource monitoring. macOS commands use stdio; interactive PTY requests are rejected to prevent access to unrelated host terminals. macOS does not enforce aggregate memory/process limits or guarantee cleanup after a host crash or when user code creates a new session. Windows retains its Job Object limits and process-tree ownership. Windows AppContainer permits outgoing internet connections but restricts localhost and private-network access.

The macOS launcher uses the built-in `/usr/bin/sandbox-exec`, which Apple marks deprecated; availability and enforcement are checked rather than falling back to unrestricted execution. Both Apple Silicon and Intel use their installed runtime and the SDK's matching native binary.

## Operational contracts

- **Verified changes:** `core` owns trusted execution and mandatory checks; `processes` contains evolving Programs. Activation requires independent evaluation, passing candidate tests, improvement over the baseline, and an explicit selection decision.
- **Task delivery:** one Task executes at a time. Completion requires acknowledged answer delivery; Python `run()` acknowledges automatically, while custom transports must call `acknowledge_delivery()`. External actions require an `approval_handler`; the CLI requires literal `yes` in a terminal.
- **Network authority:** generated code and native tools may make arbitrary outgoing internet requests, including external writes. They do not inherit host API keys or gain access to protected credential files. Approval handling applies to actions routed through the core gateway, not every network request made by a subprocess.
- **Disposable files:** task workspaces are deleted on completion, failure, or cancellation. Restart retains history and budgets but discards intermediate files and SDK sessions. Commit durable artifacts to Git.
- **Backups are state only:** they exclude code repositories, workspaces, inputs, and generated files. The two latest completed snapshots are retained. Program commits must be published to `evertree/programs` before a snapshot; publication failure preserves the previous backup. The remote defaults to `origin` and can be overridden with `EVERTREE_PROGRAM_REMOTE`.
- **Restore requires matching code:** install the recorded core version from Git first. Restore validates the environment and retrieves Program commits from remote history; it does not replace installed core sources.

## Development

```sh
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

The default suite runs unit and component tests with up to four workers. Integration, native, and opt-in live SDK suites are separate; see the [test guide](tests/README.md).

### Code conventions

- Keep interfaces and data models minimal: every field, parameter, and option must have a current purpose.
- Keep trusted execution, isolation, and mandatory acceptance checks in `core`, evolving behavior in `processes`, and reusable Program helpers in `common`.
- Call other Programs through the runtime, including other roles of the same process; do not import their implementations directly.
- Align `processes/` with the Self/Process `SUBTYPE_OF` taxonomy; `PART_WHOLE` does not define directory nesting. Preserve stable IDs when changing graph names, paths, and references. Validate structural changes with `uv run python -m evertree.core.programs.layout`.

## Documentation

- [Architecture](docs/architecture/Overview.md)
- [Program lifecycle](docs/architecture/Process%20Plane/Program%20Lifecycle%20and%20Evolution.md)

## Semantic search configuration

Exact graph reads need no external search service. Hybrid search uses **Redis 8.4+ with Search** and a separate OpenAI embedding API key. A Redis deployment without Search is insufficient. For a local macOS development server, for example:

```sh
docker run --name evertree-search -p 127.0.0.1:6379:6379 -d redis:8.4
export EVERTREE_REDIS_URL=redis://127.0.0.1:6379
# Set OPENAI_API_KEY in the core process environment using your secret manager.
```

On Windows, or for a managed service, set `EVERTREE_REDIS_URL` to the provider's `rediss://` connection URL (TLS, including its credentials). These secrets belong to the trusted core process, never Program arguments or LLM context. Search decisions use the existing authenticated Codex SDK; embeddings use OpenAI API billing separately. Queries use `TIMEOUT 0`; if the managed server enforces a ceiling, configure its timeout policy to fail instead of returning partial results ([Redis configuration](https://redis.io/docs/latest/develop/ai/search-and-query/administration/configuration/)). Index outages produce an explicitly incomplete non-exact search. GraphStore and backups remain authoritative.

Optional `<agent-home>/evertree.toml`:

```toml
[semantics]
taxonomy_enabled = true
concurrency = 4
redis_url_env = "EVERTREE_REDIS_URL"
openai_key_env = "OPENAI_API_KEY"
embedding_model = "text-embedding-3-large"
embedding_dimensions = 3072

[semantics.search]
model = "gpt-6-luna"
effort = "low"

[semantics.remember]
model = "gpt-6-luna"
effort = "medium"
```

This does not change the consciousness profile. Graph commits schedule index reconciliation; query-time generation checks repair missing indexes and prevent reads from a newer restored state. Redis contents are disposable and excluded from state backups.
