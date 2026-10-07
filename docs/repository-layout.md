# Repository Layout

Architectural source: [Program Lifecycle and Evolution — Repository Organization](architecture/Process%20Plane/Program%20Lifecycle%20and%20Evolution.md#repository-organization). This document records how it maps to the Python project.

## Code Areas

- `src/evertree/application.py` — public `EverTree` API, events, and agent startup and shutdown; `src/evertree/_application/` — its internal functional units.
- `src/evertree/core/` — trusted execution, storage, and mandatory verification mechanisms. Their code is not changed through the Program lifecycle; packages are organized by technical responsibility, independently of the graph.
- `src/evertree/processes/` — mutable Programs for the agent's own processes. The directory corresponds to **Self/Process** (the stable node name is `SelfProcess`), and nesting follows its `SUBTYPE_OF` taxonomy. `SelfProcess` belongs to Self through `PART_WHOLE` and is a subtype of the general `Process`; processes in the external world remain in the shared ontology. Composite process steps are described through `PART_WHOLE`, not nested subtypes.
- `src/evertree/common/` — reusable packages and modules that are not tied to a specific process or domain concept. It may contain an ordinary Python package structure organized by responsibility.
- `tests/` — behavior, contract, and integration checks. This is not a second Program directory.
- `artifacts/` — versioned outputs, datasets, and weights; an exact version is addressed by the pair `(relative path, Git commit)`.
- `.state/` — local mutable state: the graph, input log, SQLite DBOS, managed Git repository for Programs, and coordinated state backups. The repository is not copied into backups: commits are retained in the Git remote. Task and candidate working files are disposable. This directory is excluded from Git.
- `tmp/` and `temp/` — disposable working files. Items unchanged for more than 24 hours are automatically deleted at application startup and during maintenance every 5 minutes; pytest also clears these repository directories before tests. For directories, the age of all contents is checked. Symlinks and junctions are not traversed; access errors leave files in place until the next attempt. The system `%TEMP%` is not cleared. Store long-lived results in `artifacts/`; for new temporary code directories, use `cache.temporary_directory()`: its lock protects the directory until the context exits, even when work lasts longer than a day. The age of an arbitrary file in `tmp/` does not protect it from deletion if an external process only reads it.
- `%LOCALAPPDATA%/EverTree/cache/` — shared, recoverable cache for Python, libraries, Codex, and Git across all agents and tests. EverTree source code lives in small, separate environments; changing it does not copy libraries. The cache is not included in backups. The most recently used version of each component is retained; older ones are deleted after all processes release them. Temporary profiles are deleted at shutdown; leftovers from crashed runs are removed during the next cache maintenance.

## Local Application

The public entry point is `evertree.application.EverTree`. Its constructor initializes state, while `start()` and `close()` manage the agent's lifetime. Internal classes with the `Mixin` suffix in `_application/` group methods of this same instance by responsibility. They are not instantiated separately, have no constructors of their own, and do not override one another's methods. This is a code organization for one coordinator, not a set of independent subsystems.

| Module in `src/evertree/_application/` | Responsibility |
| --- | --- |
| `consciousness.py` | Decision loop, context, budget assignment, response verification, and learning from task outcomes |
| `execution.py` | Provider calls, resource accounting, cancellation, and response delivery |
| `programs.py` | Program lookup and execution, runtime traces, candidate creation and evaluation, and activation |
| `persistence.py` | State, bootstrap, input log, backup/restore, and maintenance |
| `tools.py` | Consciousness tool handlers and runtime gateway |
| `prompts.py` | Model instructions, structured response schemas, and consciousness tool definitions |

Prompts and contracts are versioned with the code; no file-based template loader is needed. This approach follows [OpenAI's recommendations for storing prompts in code](https://developers.openai.com/api/docs/guides/prompt-engineering#version-prompts-in-code).

Main execution path: `EverTree.submit()` queues a task; `consciousness._run_queue()` selects it and starts `_execute_task()`; `execution._invoke()` calls the provider; tool calls go through `tools._dispatch_tool()`, and Program execution through `programs._run_program()`. The decision is verified in `consciousness`, the response is delivered in `execution`, and state is saved in `persistence`.

## Core and Processes Boundary

`core` provides trusted mechanisms and mandatory constraints. `processes` contains behavior programs that the agent can improve through a verifiable lifecycle. A process prepares a plan, selects an action, or proposes an update; the core provides execution, checks access, and applies permitted changes. Mandatory Program acceptance criteria belong to the core, even if the agent also has a Program for checking its own decisions. Reusable Program helpers live in `common/`; application coordination lives in `application.py` and `_application/`.

The public APIs `core.graph`, `core.memory`, `core.cognition`, `core.learning`, `core.evaluation`, `core.runtime`, and `core.sandbox` are now packages. Their type names, pickle identities, and annotation namespaces are preserved. `core.codex` is the Codex API; the former `core.codex_provider` retains the namespace of existing types.

| Core package | Responsibility |
| --- | --- |
| `graph/` | Storage, atomic changes, and graph types |
| `memory/` | Traces, provenance, retrieval, retention, and reference types |
| `cognition/` | Tasks, budgets, attention, and protected control rules |
| `learning/` | Contracts, estimators, state, and learning transactions |
| `evaluation/` | Results, scoring, and mandatory acceptance criteria |
| `runtime/` | Execution, worker IPC, and protected access to Git code |
| `sandbox/` | Python environments, AppContainer, and Job Object |
| `codex/` | SDK configuration, protocol, provider calls, and exec-server |
| `programs/` | Trusted bootstrap, lifecycle, structural checks, tests, and experiments |

`values.py` remains a standalone module of immutable values with no dependency on graph storage. Related modules are grouped into a package when such a group already exists. File organization does not require introducing extra state or interfaces; file size alone does not determine boundaries.

## Process Directories and Roles

The agent's own processes are divided into `TaskManagement`, `CognitiveControl`, `MemoryProcessing`, and `Learning`. Directory names are derived from process names in `snake_case`. The root-level system name `SelfProcess` is omitted from source paths.

```text
processes/                           # Self/Process
  __init__.py
  task_management/                  # TaskManagement
    __init__.py
    planning/                       # Planning
      __init__.py
      _exec.py                      # prepares a plan / manages the process
      _model.py                     # only when a process model exists
  cognitive_control/
  memory_processing/
  learning/
```

Each Program has exactly one primary role: `exec` or `model`. `_exec.py` performs the process: it prepares a plan and arguments, selects actions, and manages internal operations. `_model.py` describes, explains, or predicts the process. Using an LLM and having no direct effects do not make a role `model`. All 24 initial Programs perform internal processes and have the `exec` role; empty `_model.py` files are not created. `meta` is allowed only as an `exec` modifier for managing learnable mechanisms.

Each commit contains one version of each Program; a process may have a separate Program for each role. Variants of a program live on Git branches at the same path. Variant directories and `_programs/default` levels are not used.

If an implementation needs several files, its role becomes a package, for example `_exec/implementation.py` and `_exec/helpers.py`. Taxonomy directories and role packages are unambiguously distinguished. A taxonomy directory's `__init__.py` contains only a docstring, with no registration or execution. Directories are created only for types and programs that exist. A composite step is linked to its parent semantically; it does not automatically become its subtype.

The `_exec.py` file and `_exec/` package cannot coexist for the same role; the same rule applies to `model`, regardless of the registered entry point. The validator rejects this conflict.

For a new process, `propose_program(name, role=..., claim=..., parent=...)` accepts a parent name or ID within Self/Process; if `parent` is omitted, `SelfProcess` is used. For an existing process, the same call without `parent` adds a missing role while preserving its ID, parent, and active role. Registering a role a second time, even an inactive one, is forbidden; use `create_candidate` to change it. A proposal creates an inactive Program and candidate branch; independent evaluation and acceptance remain mandatory.

## Lookup and Consistency Checks

`Program` stores a stable ID, `git_path`, role, and entry point; selection uses `active_exec` / `active_model` and `PROGRAM_FOR_PROCESS`. Names and paths do not replace IDs. Runtime executes code from an exact Git commit. The trusted `core/programs/bootstrap.py` is used during initial installation; after that, routing is determined by the graph.

```powershell
uv run python -m evertree.core.programs.layout
```

The command builds the initial graph without starting the application and checks that the agent's taxonomy matches the source: directories, role files, entry points, relationships, and active slots. CI runs it after installing dependencies and before other checks. Unregistered code, a missing implementation, or any mismatch causes the check to fail.

For candidates, the same validator checks the exact commit against the working graph before evaluation and again before activation. An inactive proposal may have no file in `main`; when the selected candidate is checked, its file is required. Candidate code is not imported or executed for this check. Direct imports of another Program, including another role of the same process, are forbidden; use runtime calls. A Program's helpers are imported within its role package.

When a name or parent changes, update the graph, directory, `git_path`, and references/imports consistently. An incomplete move blocks activation. IDs and learning history are preserved, and previous paths remain available in the corresponding commits. Lookup by domain and participants uses semantic relationships, without a second parent or a copy of the source.

## Dependencies and Versions

Standard/external packages and a Program's own helpers are imported normally. Shared utilities are imported from `evertree.common`. Another standalone EverTree Program is called through its declared interface and the runtime, without importing its internal implementation.

An algorithm can be moved to `common/` while leaving features, parameters, weights, and process-specific code in the process. Sharing an algorithm does not mean sharing trained parameters. When common code changes, check all dependent programs; the fixed procedure for accepting improvements must not be changed indirectly through such a dependency.

The managed Programs repository is located at `<home>/.state/program-repository`; active code is in `main`, and a specific version is identified by its commit. The installed trusted core is shipped separately and is not included in a candidate checkout. Each candidate is an independent clone in `.state/lifecycle/candidates`, with no shared mutable Git objects. The active/default branch is `main`; alternatives use the format `codex/program/<process-graph-path>/<role>/<candidate-name>`, for example `codex/program/Self/Process/TaskManagement/Planning/exec/refine-budget`. The process path comes from the graph, and the role distinguishes Programs belonging to one process. A candidate name has 1–3 words and is normalized to lowercase with hyphens; collisions receive suffixes `-2`, `-3`, and so on. The API accepts an explicit `candidate_name`; otherwise, it uses the first three words of the change claim. Invalid path-component characters are percent-encoded; `/` preserves hierarchy. A branch applies to the whole repository, while `ProgramBranch.program_id` retains the Program's stable ID. When a process is renamed, an existing branch keeps its original name; new branches use the current path. An ordinary Git merge does not replace protected runtime checks.

Implemented modules, recovery limitations, and commands are listed in the [v1 implementation map](implementation-v1.md).

The remote active Programs branch is `evertree/programs` in the project's shared remote. Its tree matches local `main`; history also retains commits from alternatives. Local immutable tags `<candidate-branch>/<commit>` retain exact candidate versions, including versions before amend. A commit's presence in history does not mean it has been accepted: activity is determined by a verified selection. Execution and recovery target an exact commit, and published history is not rewritten with force push.
