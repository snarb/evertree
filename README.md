# EverTree

A local agent with a semantic graph, memory, and executable Programs that evolve through verified updates. Available through a CLI and asynchronous Python components; designed for a single installation.

**Program execution and native coding tools use macOS Seatbelt or Windows AppContainer.** Filesystem access is limited to declared inputs, runtime tools and writable task directories. Outgoing internet access is always allowed. Execution fails if the native sandbox is unavailable.

```sh
uv python install 3.13
uv sync --frozen
```

The project uses Python 3.13 and accepts its patch releases. `.python-version`
and CI select that minor version so setup can use an available interpreter.
Installation and the portable test suites support Linux, macOS, and Windows;
native Program execution requires the macOS or Windows sandbox described above.

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

macOS commands run under the built-in `/usr/bin/sandbox-exec` (deprecated by Apple; availability and enforcement are checked, with no unrestricted fallback). Subprocesses inherit the restrictions and cancellation kills owned process groups, but macOS enforces no aggregate memory/process limits and does not guarantee cleanup after a host crash or when user code starts a new session. Interactive PTY requests are rejected. Windows uses Job Object limits and process-tree ownership; AppContainer allows outgoing internet but restricts localhost and private networks.

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

### Debug experience integration in PyCharm

Open [`src/evertree/debug_integration.py`](src/evertree/debug_integration.py), select the
project's `.venv` interpreter, and choose **Debug**. The script calls the real Codex model from
`KnowledgeIntegration.exec`; sign in to Codex first. Edit `USER_TASK`, `INPUT_TEXT` and
`CONSCIOUS_ANALYSIS` at the top of the script.

`EVERTREE_REDIS_URL` (or `EVERTREE_TEST_REDIS_URL`) and `OPENAI_API_KEY` are read from the
Git-ignored repository-root `.env`; variables already set in the environment take precedence.
Search needs Redis 8.4+ with Search ([configuration](#semantic-search-configuration)); optional
repository-root `evertree.toml` applies as for an agent home. Each run uses an isolated graph and
Redis namespace and writes its output under `tmp/debug-integration/<run>/`. Breakpoints and
timeout options are listed in the script's docstring.

```sh
uv run python src/evertree/debug_integration.py
```

### Code conventions

- Keep interfaces and data models minimal: every field, parameter, and option must have a current purpose.
- Keep trusted execution, isolation, and mandatory acceptance checks in `core`, evolving behavior in `processes`, and reusable Program helpers in `common`.
- Call other Programs through the runtime, including other roles of the same process; do not import their implementations directly.
- Use `ctx.agent(payload, tools=..., tool_handler=..., max_tool_calls=..., stop_when=...)`
  when a model needs tools. Handlers run at workflow level and may call `ctx.call` or
  `ctx.step`; do not wrap the entire tool conversation in a durable step. Recovery
  replays exchanges and handlers to reconstruct local state before continuing.
- Align `processes/` with the Self/Process `SUBTYPE_OF` taxonomy; `PART_WHOLE` does not define directory nesting. Preserve stable IDs when changing graph names, paths, and references. Validate structural changes with `uv run python -m evertree.core.programs.layout`.

### Comments and docstrings

**Comments**: short and clear; explain *why*, not *what*. Add them only where:

- behavior is non-obvious or complex;
- a bug was caused by misunderstanding the logic — note the pitfall to prevent repeats.

Don't comment trivial code, restate the code, or leave changelog notes. Update or remove
stale comments when changing code.

**Docstrings**: required for public methods of components. For internal methods, only if
they are non-trivial and their purpose isn't clear at a glance. Cover purpose, non-obvious
parameters and non-obvious side effects. Keep them concise.

### Model prompts

- Assign semantic judgment to the model and deterministic work to code. Generate IDs,
  bookkeeping, transaction payloads and execution reports from actual operations; do not ask
  the model to reconstruct them. Prefer actions that express intent over storage internals.
  Keep semantic choices explicit, including which sources support each result. Request a
  rationale only when a consumer needs it to understand a decision.
- Provide native tools for model-selected operations. Keep structured response schemas
  for results such as plans and assessments; do not encode tool calls as action lists
  in the final response. Tool descriptions, permissions and handlers must agree.
- Make each invocation self-contained: state its purpose, define necessary domain terms,
  explain the input and describe the required decision. Assume no access to project docs.
- Use short sections and explicit field meanings. Specify units, allowed choices, empty
  values and what to do when evidence is missing. Keep instructions consistent with schemas.
- Select model inputs explicitly. Include a field only if it can change this decision,
  identify a usable object/source, or support a required action. Keep hashes, runtime IDs,
  checkpoints and audit metadata in storage; expose only their decision-relevant meaning.
- Remove duplicate text and empty bookkeeping. Preserve source content, uncertainty,
  conditions and usable references; never strip arbitrary domain fields by name.
- Format instructions and JSON for reading. On retries include the rejected draft and
  its current error, so the next call can repair it. Do not request unused output fields.
- Test the constructed input and its consumers together: necessary meaning survives,
  audit noise stays out, references resolve, and the response can be applied. Use live
  evaluations for model judgment; scripted tests only establish mechanical contracts.

## Semantic search configuration

Exact graph reads need no external search service. Hybrid search uses **Redis 8.4+ with Search** and a separate OpenAI embedding API key. A Redis deployment without Search is insufficient. For a local macOS development server, for example:

```sh
docker run --name evertree-search -p 127.0.0.1:6379:6379 -d redis:8.4
export EVERTREE_REDIS_URL=redis://127.0.0.1:6379
# Set OPENAI_API_KEY in the core process environment using your secret manager.
```

On Windows, or for a managed service, set `EVERTREE_REDIS_URL` to the provider's `rediss://` connection URL (TLS, including its credentials). These secrets belong to the trusted core process, never Program arguments or LLM context. Embeddings use OpenAI API billing. Queries use `TIMEOUT 0`; if the managed server enforces a ceiling, configure its timeout policy to fail instead of returning partial results ([Redis configuration](https://redis.io/docs/latest/develop/ai/search-and-query/administration/configuration/)). Index outages produce an explicitly incomplete non-exact search. GraphStore and backups remain authoritative.

Optional `<agent-home>/evertree.toml`:

```toml
[semantics]
redis_url_env = "EVERTREE_REDIS_URL"
openai_key_env = "OPENAI_API_KEY"
embedding_model = "text-embedding-3-large"
embedding_dimensions = 3072

[semantics.remember]
model = "gpt-6-luna"
effort = "high"

[semantics.read]
context_fraction = 0.6
max_items = 600
# Local fallback for model names not registered by tiktoken:
token_encoding = "o200k_base"
```

Graph commits schedule index reconciliation; query-time generation checks repair missing indexes and prevent reads from a newer restored state. Redis contents are disposable and excluded from state backups. Graph reading, paging and token budgets are described in [Semantics Plane](docs/architecture/Semantics%20Plane.md#exact-slot-reads-and-walks).

## Documentation

- [Architecture](docs/architecture/Overview.md)
- [Program lifecycle](docs/architecture/Process%20Plane/Program%20Lifecycle%20and%20Evolution.md)
- [Conscious step contract](docs/architecture/Cognition%20and%20Attention.md#conscious-step-contract)
- [Knowledge integration](docs/architecture/Semantics%20Plane.md#knowledge-integration)
