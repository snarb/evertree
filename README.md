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

### Debug experience integration in PyCharm

Open [`src/evertree/debug_integration.py`](src/evertree/debug_integration.py), select the
project's `.venv` Python interpreter, and choose **Debug**. No command-line parameters are
needed. The script always calls the real Codex model from `KnowledgeIntegration.exec`.

Before running, sign in to Codex. The script loads `EVERTREE_REDIS_URL` and `OPENAI_API_KEY`
from repository-root `.env`; variables already set in PyCharm or the shell
take precedence. For this isolated harness, `EVERTREE_TEST_REDIS_URL` is also accepted when
the regular Redis URL is absent. This file is ignored by Git and its values are never
printed or included in model input. Search uses the production
`RedisSearchIndex` with Redis 8.4+ Search and OpenAI embeddings; see
[search configuration](#semantic-search-configuration). Missing variables are reported before
model calls. Codex and embeddings consume account resources. Optional repository-root
`evertree.toml` selects the semantic model and search settings just as for an agent home.

```sh
uv run python src/evertree/debug_integration.py
```

Edit `USER_TASK`, `INPUT_TEXT`, and `CONSCIOUS_ANALYSIS` at the top of the script. These are
the user task, a paragraph describing pump Н-1, and a supplied intermediate analytical Note.
The integrator's LLM calls native semantic tools and chooses their sources. Tool handlers
assign permanent IDs and immediately save each checked operation with its sources and history.
Normal model completion ends integration; no write is required for routine material. There are no scripted
model responses or predetermined graph objects. The example
asks to preserve the pump's two observed state intervals; the actual representation is chosen
by the model and validated by Core.

Useful breakpoints:

- `DebugSession.record_experience`: source references and the analytical Note with its emphasis in text.
- `knowledge_integration/_exec.py:handle_tool`: native tool dispatch, search, schema reads and repair.
- `common/integration_actions.py`: shared operation schemas and graph tool dispatch.
- `DebugSession.model`: actual Codex request, declared tools and provider events.
- `SemanticService.write`: operation validation, idempotence and atomic persistence.
- `CoreOperations.apply_delta`, then `GraphStore.apply`: graph mutation and provenance.
- `DebugSession.run`, at `return created`: inspect the graph, trace and successful writes together.

Each run uses an isolated bootstrap graph and Redis namespace, writing `graph.json`,
`trace.json`, `result.json` and `calls.json` under `tmp/debug-integration/<run>/`, also on
failure. Each model request also has a readable `model-*.md` file with its tool definitions
and a separate JSON provider transcript.
The path is printed before execution. Ordinary Python breakpoints work because the
Program and Core execute in one process. This harness invokes the integrator directly;
application scheduling, worker admission and durable restart are outside its scope.

### Code conventions

- Keep interfaces and data models minimal: every field, parameter, and option must have a current purpose.
- Keep trusted execution, isolation, and mandatory acceptance checks in `core`, evolving behavior in `processes`, and reusable Program helpers in `common`.
- Call other Programs through the runtime, including other roles of the same process; do not import their implementations directly.
- Use `ctx.agent(payload, tools=..., tool_handler=..., max_tool_calls=..., stop_when=...)`
  when a model needs tools. Handlers run at workflow level and may call `ctx.call` or
  `ctx.step`; do not wrap the entire tool conversation in a durable step. Recovery
  replays exchanges and handlers to reconstruct local state before continuing.
- Align `processes/` with the Self/Process `SUBTYPE_OF` taxonomy; `PART_WHOLE` does not define directory nesting. Preserve stable IDs when changing graph names, paths, and references. Validate structural changes with `uv run python -m evertree.core.programs.layout`.

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
effort = "medium"
```

This does not change the consciousness profile. Graph commits schedule index reconciliation; query-time generation checks repair missing indexes and prevent reads from a newer restored state. Redis contents are disposable and excluded from state backups.

### Conscious steps and experience integration

Consciousness works in bounded iterations: a local objective, related tool or Program calls, and an explicit analytical Note. The result may be an intermediate plan or hypothesis. The latest Note and working plan remain available to the next iteration through task state and trace; only a separately composed `user_message` is delivered to the user.

Between steps, `KnowledgeIntegration` examines recorded experience and independently saves useful facts, connections and insights. Emphasis and requests to remember something belong in ordinary analytical text. References point to already recorded material; callers need not pre-extract every statement or assign review statuses. The runtime supplies task and Self context. Use `graph.integrate(experience_refs, focus=None)` or `ctx.call("knowledge_integration", ...)` when integration is needed earlier. For precise graph editing, consciousness can load `graph_write_tools`, sharing integration’s creation, relation, Note, `update` and `delete` operations. Each operation saves permanent IDs, history and sources immediately; later failures leave previous writes intact. Public raw `graph.apply` is unavailable.

The `semantics.remember` configuration above selects the integration model profile. Internal checkpoints bound packet processing, and runtime operation keys prevent repeated writes on recovery. Integration failures enter technical diagnostics without blocking the next step or final delivery; answer verification, input freshness and task constraints still apply. Memory compaction may later reduce intermediate detail while retaining significant reasons and provenance. See [the conscious step contract](docs/architecture/Cognition%20and%20Attention.md#conscious-step-contract) and [knowledge integration](docs/architecture/Semantics%20Plane.md#knowledge-integration).
