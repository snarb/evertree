# EverTree

A local agent with a semantic graph, executable Programs, memory, and verified updates. Interfaces: a CLI and an asynchronous Python API.

**EverTree targets a single installation. Its architecture does not add support for independent installations.**

Development and portable tests target **macOS and Windows**. Production execution of Programs and native coding tools currently requires **Windows AppContainer**. A production macOS sandbox is a separate implementation milestone; passing portable tests does not establish native isolation on macOS.

## Setup and use

Requirements: Python **3.13.16**, Git, [uv](https://docs.astral.sh/uv/) with that Python version available, and local Codex authorization for model calls. All LLM requests use the official `openai-codex` Python SDK with **gpt-6-luna**, effort **high**. There is no model fallback on availability errors. Node.js is not required.

```sh
uv python install 3.13.16
uv sync --frozen
```

On Windows:

```powershell
uv run evertree --home C:\agents\my-tree init
uv run evertree --home C:\agents\my-tree doctor
uv run evertree --home C:\agents\my-tree chat
uv run evertree --home C:\agents\my-tree run "Create and test a CSV processing function"
uv run evertree --home C:\agents\my-tree tasks list
uv run evertree --home C:\agents\my-tree tasks show TASK_ID
uv run evertree --home C:\agents\my-tree tasks resume TASK_ID "Answer to the clarification"
uv run evertree --home C:\agents\my-tree tasks cancel TASK_ID
uv run evertree --home C:\agents\my-tree programs
uv run evertree --home C:\agents\my-tree graph Self
uv run evertree --home C:\agents\my-tree memory "CSV processing"
uv run evertree --home C:\agents\my-tree traces
uv run evertree --home C:\agents\my-tree backup
uv run evertree --home C:\agents\my-tree backup --list
uv run evertree --home C:\agents\my-tree restore BACKUP_NAME
```

`doctor` checks authorization, Luna/high, and actual AppContainer enforcement. If the sandbox is unavailable, Program execution fails; an ordinary Python process is never a production fallback.

The CLI and Python API share the same core. One Task executes at a time; queued inputs are persisted immediately. A clarification continues the same Task. Input accepted during controller execution or verification reaches the next controller call before delivery. An answer is generated, verified, and delivered; only acknowledged delivery permits successful completion.

```python
import asyncio
from evertree import EverTree

async def main():
    async with EverTree(r"C:\agents\my-tree") as tree:
        result = await tree.run("Create and test a small Python module")
        print(result["answer"])

asyncio.run(main())
```

For custom transports use `submit()`, `events()`, and `acknowledge_delivery()`. `run()` automatically acknowledges receipt by its caller. `resume()` continues a saved task; `cancel()` stops execution. External actions require an `approval_handler`; the CLI requires literal `yes` and denies approval without a terminal.

`events()` creates an independent subscription to new events. Open it before `submit()` using `async with tree.events() as events:`. Without subscribers, streaming events do not accumulate in queues; their journal remains in Memory. A late subscriber receives a pending, unacknowledged answer. Each controller turn uses a complete prepared context without appending SDK session history again.

The Python API accepts external numeric feedback through `supervisor_feedback(SupervisorFeedback(value=-2, comment="Reason"), source_id="feedback-1", task_id=...)`; `SupervisorFeedback` is exported by `evertree`. Values range from −5 to +5. Comments remain with the original observation; feedback alone does not start learning. `save_prediction()` links the original `TraceOutputRef` to a semantic target and context. `PredictionEvaluator` matches it against recorded observations. For composite observations, `observe(..., projections=..., context=...)` specifies paths to individual values without copying the payload.

Consciousness chooses a finite task budget and an optional self-improvement share, preserving accumulated usage when revising them. Skill development required by the current task uses its main budget; optional work for future benefit requires an allocated share. Approval waiting time is excluded from `active_time_minutes`. Technical call timeouts are separate. `run --max-minutes N` sets a user limit. Initial framing is limited to one model call and a five-minute technical timeout.

## Program execution and safety

A new Task initially gets an empty workspace. Each top-level Program run extracts the selected commit of the managed Program repository, copies the small worker entrypoint, and launches a separate Python worker with DBOS in an AppContainer. Nested Program calls share that worker. A Job Object owns the process tree. Programs have no network capabilities; graph, memory, model, and action access goes through validated JSON IPC.

New code is developed in a separate candidate checkout. Acceptance requires an independent dataset, mandatory checks, improvement over the baseline, and an explicit `EvaluationChoice`. Insufficient evidence leaves the candidate inactive. Developers bind independent checks using `datasets.create()` and `bind_evaluation()`; the agent cannot substitute its own expected answers for hidden outcomes.

A candidate must contain executable `unittest` tests in `tests/test_*.py`. Core runs them from the exact candidate commit in a separate AppContainer and records exit status, results, and output. Missing tests, an entirely skipped suite, errors, or timeout block activation. This check is separate from syntax validation and independent dataset evaluation. These candidate tests are distinct from this repository's pytest categories.

For coding, the SDK uses the official Codex `exec-server` inside an EverTree-owned AppContainer. Commands and filesystem tools access the selected workspace; model credentials stay in the trusted SDK process. A Python `websockets` bridge connects the SDK to server stdio through a loopback WebSocket with a unique token per invocation. This does not require installing Codex's elevated Windows sandbox or changing its global ACLs. Requests to broaden tool permissions are rejected; external actions use core's separate approval boundary.

Python and worker dependencies, Codex, and Git are cached separately under `%LOCALAPPDATA%/EverTree/cache`, outside agent state and backups. Source changes create only a small EverTree source environment that reuses the existing libraries. **Python and all dependencies are not recopied for each task or Program run.** The cache retains the latest used version and versions leased by active processes. File locks protect concurrent use. Temporary profiles are removed on close; crash leftovers are cleaned during later maintenance. Files that cannot yet be removed are retried with a warning.

## Persistence

Backup includes graph, memory, event traces, tasks, parameters, ledger, lifecycle decisions, and DBOS journals. It excludes code repositories, workspaces, input files, and generated files. The two latest completed snapshots are retained.

Before publishing a snapshot, Program commits are pushed to the permanent `evertree/programs` branch. A failed push preserves the previous backup and emits `maintenance_error`. The default remote is the project's `origin`; override it with `EVERTREE_PROGRAM_REMOTE` or `EverTree(..., program_remote=...)`. Restore retrieves the required commit from that history. Committed alternatives and pre-rollback versions remain available; history is never force-pushed.

Before ordinary application startup, trusted core sources must be committed and pushed to `origin`. The application refreshes remote references and verifies publication; dirty sources or an inaccessible remote stop startup. It never commits core automatically. Snapshots record the core commit, source hashes, and environment versions; restore validates them without replacing installed sources. Install the matching project version from Git before transferring state.

Task workspaces are removed on completion, failure, or cancellation. Temporary execution sources and evaluation directories are removed after processes stop. After restart, unfinished work starts again with retained history and budgets; SDK sessions and intermediate files are discarded. Request required input files again and commit durable artifacts to Git.

## Development and testing

> Prefer the smallest real set of components that proves the behavior. Use Git, subprocesses, DBOS, application startup, or native sandboxes only when their behavior is part of the test.

This applies to complex behavioral scenarios as well as unit tests. Create task/store objects directly when input admission is not the behavior under test. The default suite contains only `unit` and `component` tests; it rejects subprocess creation from tested code. `pytest-xdist` runs up to four workers by default. Each worker has a private tool cache, and tests own their mutable state.

```sh
# Default: fast unit and component tests, no LLM or worker subprocesses
uv run pytest -q
# Real Git, persistence, IPC, DBOS, and application lifecycle
uv run pytest tests/integration -q
# Windows sandbox and process ownership
uv run pytest tests/native -q -n 0
# Static checks and taxonomy consistency
uv run ruff check src tests
uv run ruff format --check src tests
uv run python -m evertree.core.programs.layout
```

After a local edit, run affected tests. After completing a change, run related regressions and the fast suite. Run infrastructure suites when changing their boundaries; do not repeat the full suite after every edit. For one test or sequential debugging, add `-n 0`. Live SDK tests require explicit `EVERTREE_CODEX_INTEGRATION=1` and selection of `tests/live`; they are excluded from ordinary CI.

CI runs fast and portable integration tests sequentially and in parallel on macOS and Windows, with a separate Windows-native job. Successful-test temporary data is removed; failed-test data from the last two pytest sessions is retained for diagnosis. See the [test guide and behavioral coverage](tests/README.md) for categories, purposes, commands, and measurement limits.

On Windows, `uv run python -m evertree.demo --home C:\agents\demo` demonstrates creation, validation, activation, improvement against a new dataset, and reuse after restart with a fake provider. It still uses real native workers.

## Code organization

**`core` contains trusted execution, storage, and mandatory validation. `processes` contains graph-registered behavioral Programs that can evolve through the verified lifecycle.** Planning, argument preparation, and action selection belong to `processes`; isolation, access checks, transactions, and mandatory acceptance conditions belong to `core`. Shared Program helpers live in `common`; `application` coordinates the system.

Core packages are grouped by technical responsibility: `graph/`, `memory/`, `cognition/`, `learning/`, `evaluation/`, `runtime/`, `sandbox/`, `codex/`, and `programs/`. Their directory structure need not appear in the semantic graph.

`src/evertree/processes/` corresponds to **Self/Process** (`SelfProcess`). Its initial subtypes are `task_management`, `cognitive_control`, `memory_processing`, and `learning`. `SelfProcess` belongs to Self and is also a subtype of the general Process concept used for external processes. Directory nesting represents `SUBTYPE_OF`; composite steps use separate `PART_WHOLE` relationships.

Within a process, `_exec.py` performs it and `_model.py` describes, explains, or predicts it. For example, planning uses `task_management/planning/_exec.py`. Only implemented roles are created; LLM use or absence of direct effects does not make a Program a model. Multi-file implementations use role packages such as `_exec/implementation.py` and `_exec/helpers.py`. There are no empty levels or `default` variants. Taxonomy `__init__.py` files neither register nor execute Programs.

Each commit contains **one version of each Program**, with alternatives in Git branches at the same paths:

| Git ref | Purpose |
| --- | --- |
| `main` | Active/default managed Program branch |
| `codex/program/<process-graph-path>/<role>/<candidate-name>` | Alternative implementation |
| Remote `evertree/programs` | Publication of active Program code and retained history |

`process-graph-path` is the full graph path, such as `Self/Process/TaskManagement/Planning`. `role` is `exec` or `model`. Candidate names use one to three lowercase hyphenated words, such as `refine-budget`, with `-2`, `-3`, etc. for collisions. Example: `codex/program/Self/Process/TaskManagement/Planning/exec/refine-budget`.

Invalid ref-component characters are percent-encoded while `/` preserves hierarchy. Internal Program and candidate IDs remain stable. Existing branches retain their original path after a process rename; new branches use the current path. An explicit `candidate_name` overrides the default first three words of the change claim. The model is instructed to select meaningful names.

Different roles are different Programs without duplicated version directories. Local `<candidate-branch>/<commit>` tags retain exact alternative revisions. Their presence in remote history does not imply acceptance: execution, evaluation, and restore address exact commits.

`propose_program(name, role=..., claim=..., parent=...)` creates a process under a parent name or ID within Self/Process; the default is `SelfProcess`. For an existing process, omitting `parent` adds a missing role without replacing its identity. Re-registering a role, even inactive, is rejected; use `create_candidate` for changes. A new role becomes active only after evaluation and acceptance.

CI compares source layout against the seed graph. Lifecycle checks the exact candidate commit against the working graph before evaluation and activation. Incorrect taxonomy, roles, unregistered code, or missing Programs block acceptance. See [repository layout](docs/repository-layout.md).

[Architecture](docs/architecture/Overview.md) · [Repository](docs/repository-layout.md) · [Implementation and checks](docs/implementation-v1.md)
