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
`SelfKnowledgeIntegration.exec`; sign in to Codex first. Edit `USER_TASK`, `INPUT_TEXT` and
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

### Debug attribution learning in PyCharm

Open [`src/evertree/debug_attribution.py`](src/evertree/debug_attribution.py) with the same
interpreter and environment, then choose **Debug**. Edit `OBSERVATIONS` and `QUESTION` at
the top. The default case receives separate reports of dogs weighing 8, 5 and 10 kg, then
asks for their average and relative size, including a hypothetical 7 kg dog.

Each report runs the real integration and evidence assessment Programs. For the question,
the model discovers or creates a qualitative property through the ordinary semantic tools;
assessment follows, then a fresh read-only invocation answers from retained knowledge.
The script supplies no graph IDs, cutoffs or expected answer. The in-process harness covers
these mechanisms; application scheduling, worker transport and restart are outside it.

Each run writes to `tmp/debug-attribution/<run>/`. Inspect `observation-1/` through
`observation-3/`, `learned/` and `final/`: `properties.json` contains property definitions,
norm checkpoints and current readings with BeliefData. `answer.json`, `stages.json`,
`trace.json`, `tools.json` and `model-*.md/json` preserve the answer and how it was obtained,
also on failure. Breakpoints do not consume a model deadline in interactive runs.

```sh
uv run python src/evertree/debug_attribution.py
```

### Code conventions

- Keep interfaces and data models minimal: every field, parameter, and option must have a current purpose.
- Keep trusted execution, isolation, and mandatory acceptance checks in `core`, evolving behavior in `processes`, and reusable Program helpers in `common`.
- Call other Programs with `call_program`, including other roles of the same process; do not import their implementations directly. Await each child before further Core work; parallel Program branches are rejected. Only paired semantic-search index reads may overlap at the gateway.
- Write Programs as ordinary async Python. Reach Core and the outside world only through the
  typed `evertree.core.<domain>.api` and `evertree.core.runtime.api` functions (for example
  `from evertree.core.memory.api import retrieve`, `from evertree.core.runtime.api import llm`);
  they own durability. Program code only passes `ctx` on: candidate validation rejects `ctx`
  method calls outside `core`. Recovery returns saved boundary results and reruns local code,
  so do not branch on wall-clock time or randomness. Wrappers for cheap repeatable reads
  call `ctx.step(..., journal=False)` to keep the journal small; recovery repeats them. A new gateway method needs a Core wrapper.
  Child Programs that Core wrappers call are listed in `CALLED_PROGRAMS` (`core/contracts.py`);
  their entrypoints must keep accepting those arguments.
- Use `llm_with_tools(ctx, prompt, instructions=..., tools=..., tool_handler=...)` when a model
  needs tools. Handlers run at workflow level and may use Core API functions; the conversation
  is not one durable step. Recovery replays exchanges and handlers to reconstruct local state
  before continuing.
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
- Generalize from evaluation failures into reusable rules about representation and behavior.
  Keep corpus-specific identities, expected classes, answers and routes out of production
  instructions. Examples may illustrate a general rule with synthetic subjects. Treat a
  revised-prompt rerun as a regression check, not independent evidence of generalization.

SelfKnowledgeIntegration is instructed to preserve nearly every distinct source assertion: shared participants,
named predicate roles, values, exceptions and source qualifications. `focus` sets priority
without excluding the remaining assertions. Native relations support directed reads through
their roles; co-occurrence, inverse duplicates and invented transitive facts are not useful
substitutes. Claims and Notes remain available when their meanings require them. Integration
processes source sections sequentially; failures and budget exhaustion preserve an explicit
unprocessed remainder. A completed section means processing finished, not proven semantic coverage.
Neighboring text windows extend to nearby paragraph boundaries within 1,000 characters per
side, so a short paragraph's subject is not lost to a fixed character cut. Longer context
remains available through the retained original; the window cannot guarantee every antecedent.
Text sections and adaptive splits prefer whole paragraphs. Sentences, lines and words are
fallback boundaries when a paragraph cannot fit or needs further splitting.

SelfKnowledgeIntegration ends each model section through `finish_section(complete, remaining)`.
An ordinary final message is not a completion receipt. A declared remainder or missing receipt
preserves writes and splits the unfinished section; an indivisible remainder is recorded as a
failed gap. Unresolved work and repairs accompany child sections and explicit retries as
unverified model reports, not source evidence. Only an explicit completion decision advances
the processed checkpoint. This is
execution bookkeeping, not an independent proof of semantic coverage.
Completion concerns the current section: work belonging to other sections and information
the source does not supply cannot make that section incomplete. Each entry in `define_relation`'s
`roles` array can include a `description` defining its meaning. Values must match that meaning,
including direction and scope, as well as the declared data type.

Use `graph.search(queries, kinds=[...])` to separate entities, schemas and assertions. After
finding an anchor, use exact `query` and `walk` reads, including taxonomy descendants and their
instances. `graph.sources(subjects=[fact_id])` returns the fact's recorded sources and change
context; `read_source(reference)` reads a chosen fragment directly, with pages for long text.
This route does not depend on ranking the source article in a second text search. The
[corpus audit and integration pilot](artifacts/search-recall/CORPUS-AUDIT.md) records measured
results and limitations; relation counts alone do not establish answer quality or completeness.
The [matched graph-reader diagnostic](artifacts/search-recall/graph-route-evaluation/RESULTS.md)
found less displayed material with transitions, increased answer time and no demonstrated
answer-quality improvement. It does not establish full-corpus acceptance.
Answer composition and verification preserve the requested proposition's participants,
attribution and conditions, and check that the opening conclusion agrees with its caveats.
Finding the right facts does not by itself establish a correct final answer.

## Semantic search configuration

Exact graph reads need no external search service. Hybrid search uses **Redis 8.4+ with Search** and a separate OpenAI embedding API key. A Redis deployment without Search is insufficient. For a local macOS development server, for example:

```sh
docker run --name evertree-search -p 127.0.0.1:6379:6379 -d redis:8.4
export EVERTREE_REDIS_URL=redis://127.0.0.1:6379
# Set OPENAI_API_KEY in the core process environment using your secret manager.
```

On Windows, or for a managed service, set `EVERTREE_REDIS_URL` to the provider's `rediss://` connection URL (TLS, including its credentials). These secrets belong to the trusted core process, never Program arguments or LLM context. Embeddings use OpenAI API billing. Queries use `TIMEOUT 0`; if the managed server enforces a ceiling, configure its timeout policy to fail instead of returning partial results ([Redis configuration](https://redis.io/docs/latest/develop/ai/search-and-query/administration/configuration/)). Index outages produce an explicitly incomplete non-exact search. GraphStore and backups remain authoritative. Indexes are prepared on demand; writes do not start background indexing. The first indexed search after a graph change may take longer while the current index is prepared.

The trusted Core loads Redis, OpenAI and Typesafe settings from `<agent-home>/.env`, without
overriding existing environment variables. Keep `TYPESAFE_API_KEY` there when using Jev.
Secrets never enter Program arguments or model context.

Search accepts `queries`, a nonempty array of names, focused phrases or integer IDs. Independent
queries share index preparation, an embedding request and Redis pipelines. Duplicate queries
are normalized away. Results contain one card per ID, up to 10 per unique query, with query
associations and separate completeness statuses.
Optional `kinds` is a nonempty OR filter shared by the batch and applied before both channel
quotas. Omit it for all kinds; an empty list or unknown kind is an error. Narrow searches cannot
authorize object creation: the name still requires a complete unfiltered search in the current
model invocation. Filtering types does not change RRF or fix ranking among articles of one type.

Optional `<agent-home>/evertree.toml`:

```toml
[semantics]
redis_url_env = "EVERTREE_REDIS_URL"
openai_key_env = "OPENAI_API_KEY"
embedding_model = "text-embedding-3-large"
embedding_dimensions = 3072

[semantics.search]
bm25_candidates = 64
vector_candidates = 64
chunk_tokens = 768
chunk_overlap = 128

[semantics.jev]
enabled = false
model = "jev-1.13.0"
threshold = 0.05
api_key_env = "TYPESAFE_API_KEY"

[semantics.remember]
model = "gpt-6-luna"
effort = "high"

[semantics.read]
context_fraction = 0.6
max_items = 600
# Local fallback for model names not registered by tiktoken:
token_encoding = "o200k_base"
```

Search indexes overlapping passages of retained names and descriptions. Each channel
collapses passage hits to object IDs before its candidate limit, so a long object's
passages cannot fill the quota. Candidate limits are separate from the final ten-per-query
limit. Small indexes use exact vector search; larger indexes use HNSW with an expanded
search window. For comparisons involving several subjects, send a focused query for each
subject in the same array; each then receives its own result budget.
For multi-hop questions, search an initial anchor, read the returned evidence, then use
discovered names, IDs or relations for subsequent searches or graph reads. Batch independent
needs within each step. A completed search reports channel completion; it does not establish
that every requested fact is known or that an unreturned object is absent. Continue until
each part has supporting evidence, or explicitly retain the unresolved parts.
Lexical and vector records are separate within each graph generation, so preparing
embeddings cannot change text scores while the two channels run.

Jev optionally filters deduplicated non-exact candidates before the per-query limit. Lower
`threshold` preserves more candidates; `0` bypasses filtering. Exact matches always bypass Jev.
The initial `0.05` comes from the saved experiment in commit `0abaa54`; its full-corpus
calibration does not establish recall for a new graph or retrieval pipeline. Verify at least
99% relevant-candidate retention on independent labels before relying on filtering. Failed
Jev batches retain their original candidates and return a warning; failed search channels
still make the affected queries incomplete. Jev uses Typesafe API billing, batches up to
128 candidates, also bounded by estimated context size, two requests concurrently and a
10-second timeout. Context packing leaves room below Jev's default per-question limit
([Typesafe context limits](https://docs.typesafe.ai/models#context-length)); oversized
individual cards still retain the usual fail-open behavior.

Graph commits do not start index I/O; query-time generation checks repair missing indexes and prevent reads from a newer restored state. Redis contents are disposable and excluded from state backups. Graph reading, paging and token budgets are described in [Semantics Plane](docs/architecture/Semantics%20Plane.md#exact-slot-reads-and-walks).

## Documentation

- [Architecture](docs/architecture/Overview.md)
- [Program lifecycle](docs/architecture/Process%20Plane/Program%20Lifecycle%20and%20Evolution.md)
- [Conscious step contract](docs/architecture/Cognition%20and%20Attention.md#conscious-step-contract)
- [Knowledge integration](docs/architecture/Semantics%20Plane.md#knowledge-integration)
