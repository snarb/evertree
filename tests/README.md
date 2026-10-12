# Tests

> Prefer the smallest real set of components that proves the behavior. Use Git, subprocesses, DBOS, application startup, or native sandboxes only when their behavior is part of the test.

Complex behavior does not require expensive infrastructure. Most tests should exercise real domain objects and their interactions in one process. Every test has one explainable purpose. A complex or expensive test must include a short docstring stating the contract and why its infrastructure is required.

## Suites

| Directory | Purpose | Infrastructure |
| --- | --- | --- |
| `unit` | Algorithms, validation, classes, and state transitions | Objects in memory |
| `component` | Real components working together, including complex behavioral scenarios | One process; small temporary files when needed |
| `integration` | Git, persistent snapshots, worker IPC, DBOS, application startup/recovery | Real dependencies required by the contract |
| `native` | OS permissions, sandbox enforcement, process ownership, isolated tool environments | macOS Seatbelt / Windows AppContainer |
| `live` | Compatibility with the signed-in SDK and external model | Explicit opt-in; may use account resources |

`pytest` selects only `unit` and `component` by default. A subprocess audit guard covers their setup, execution, and teardown, including subprocess aliases and asyncio subprocess launches; sandbox construction is also rejected. The pytest-xdist worker processes are created outside these test boundaries.

```sh
# Default fast suite, up to four CPU workers
uv run pytest -q
# Portable infrastructure
uv run pytest tests/integration -q
# Native contracts on macOS or Windows, sequentially
uv run pytest tests/native -q -n 0
# Optional outgoing HTTPS smoke (PowerShell: $env:EVERTREE_NETWORK_SMOKE = "1")
EVERTREE_NETWORK_SMOKE=1 uv run pytest tests/native/test_network.py -q -n 0
# All offline suites: both commands are required
uv run pytest tests/unit tests/component tests/integration -q
uv run pytest tests/native -q -n 0
# Diagnose one test without worker startup overhead
uv run pytest tests/component/test_application_flow.py::test_cancelled_event_consumer_releases_subscription -q -n 0
# Inspect setup, call, and teardown costs
uv run pytest --durations=20 -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Live checks require both explicit selection and `EVERTREE_CODEX_INTEGRATION=1`:

```sh
# macOS shell; use $env:EVERTREE_CODEX_INTEGRATION = "1" in PowerShell
EVERTREE_CODEX_INTEGRATION=1 uv run pytest tests/live -q -n 0
```

CI runs the fast and portable integration suites sequentially and in parallel on Linux, macOS, and Windows, using an available Python 3.13 patch release. Separate native jobs on Apple Silicon, Intel macOS, and Windows check filesystem isolation, real Programs/DBOS, executor tools, cancellation, and outgoing HTTPS. Platform skips belong to OS-specific native checks, not entire modules containing portable business rules.

On macOS, native tests must run outside any enclosing sandbox that prohibits applying Seatbelt (for example a sandboxed agent terminal). A nested-sandbox failure is an environment limitation, not grounds to remove the native boundary. macOS uses process groups for cancellation without resource monitoring; Windows retains Job Object limits. The external network smoke is explicitly selected so ordinary local test runs do not depend on an internet endpoint.

After an edit, run affected tests. After a complete change, run related regressions and the fast suite. Run integration/native tests when their boundaries change. Do not repeat the full suite after every local edit. An explicit path selects that suite independently of the default `testpaths`.

## Writing and maintaining tests

- Construct `TaskState` directly for its data invariants, or use `TaskStore.create_task()` for state transitions, budgets, and history. Use `submit()` only when admission or coordinator flow is under test.
- Reuse real graph, memory, learning, and gateway objects. Do not mock the algorithm or rule asserted by a test.
- The component app helper constructs `EverTree` without `start()`, initializes seed state with a fixed revision, and calls trusted source Programs directly. It retains production gateway validation and traces. It substitutes worker transport and backup I/O, so it cannot prove Git, DBOS, restart durability, or sandbox behavior.
- Arithmetic evaluation tests may supply fixed worker results and infrastructure check outcomes while exercising real scoring, aggregation, and acceptance. Tests of those infrastructure checks use the real implementations separately.
- Fixtures that start the application explicitly request `offline_application`. Only those fixtures bypass committed-core verification and obtain a private bare remote. No global fixture creates Git repositories.
- Put reusable helpers in `tests/support`; never import from another test module. Keep helpers narrow and fail on unsupported behavior instead of becoming another application implementation.
- Keep mutable stores, repos, databases, and directories private to each test. Immutable tools may be cached within one pytest worker; each worker owns a separate cache root. Tests of shared-cache locking explicitly create the shared temporary root for their child processes.
- Use portable paths and APIs: unit, component, and portable integration tests must work on macOS and Windows.
- Prefer events and controlled clocks to sleeps. Preserve behavioral catalog IDs when moving or splitting tests. Keep a real boundary test when moving business-rule variants into faster tests.
- Unit, component, and portable integration suites run in parallel by default, including explicitly selected `tests/integration`. `-n auto` uses at most four available CPUs; `-n N` explicitly overrides that. Native/live suites and single-test debugging use `-n 0`. A session fixture runs once per worker, not once for the entire parallel run.

Successful-test temporary directories are removed. Failed-test data from the last two pytest sessions is retained. Test startup does not prune the repository's `tmp` or `temp` directories; cleanup tests only touch their own fixtures.

Agent-created Programs have a separate acceptance contract: committed `tests/test_*.py` files using `unittest.TestCase`, executed by core in a sandbox before acceptance. Repository pytest categories do not change that contract.

## Behavioral coverage

The following inventory preserves the behavioral scenario IDs and acceptance boundaries used by the existing tests. "Contract" below means only the existing boundary is checked; missing orchestration is stated explicitly. Parameterized cases are not additional implemented capabilities.

`ScriptedProvider` fixes external decisions and candidate content. It demonstrates enforcement and coordination, not a model's ability to discover patterns autonomously. Tests that assert worker transport, durable workflow state, or committed code retain real subprocesses. No missing product capability is disguised with an `xfail`.

| Scenarios | Test modules | Coverage and limits |
| --- | --- | --- |
| MEM-01–04, MEM-09, MEM-10, MEM-12 | `test_behavioral_memory` | Real retention, compaction, provenance, protected restoration, structural validation, and retrieval. |
| MEM-05 | `test_behavioral_memory` | Contract: proposals retain supplied frequencies; the frequency aggregator is not implemented. |
| MEM-06 | `test_behavioral_memory` | Contract: retrieval/replay selection does not copy sources; event counting and paraphrase recognition are absent. |
| MEM-07, MEM-13 | Not yet covered | No API for combining frequencies with unknown overlap, or active-state cache. |
| MEM-08 | `test_behavioral_beliefs` | Consolidation and retract compared with an uncompressed control state. |
| MEM-11 | `test_behavioral_memory` | Independent retention reasons; complete Dataset deletion lifecycle is absent. |
| MEM-14 | `test_behavioral_memory` | Separate replay trace, provenance, and live-action prohibition; no complete ReplayTask/Episode orchestration. |
| BEL-01–08, BEL-11–14, BEL-18 | `test_behavioral_beliefs` | Real arithmetic, dependencies, scope, priors, and consolidation; likelihoods are supplied by the test. |
| BEL-08, Program → core | `test_behavioral_control` | A recorded observation and Program flag do not establish likelihood calibration; the unbacked-influence limit applies. |
| BEL-09, BEL-10 | `test_behavioral_beliefs` | Recalculation, immutable assignments, and current mapping; automatic revise/retract TraceEvents are absent. |
| BEL-15 | `test_behavioral_beliefs` | Hypothetical PropertyReading conditions are retained; arbitrary hypothetical inference chains are not covered. |
| BEL-16, BEL-17 | Not yet covered | No unresolved assessment without supplied likelihoods, observation-model-version binding, or reading invalidation/reassessment. |
| BEL-19 | `test_behavioral_beliefs` | Supplied-likelihood updating; automatic SourceReliability estimation/integration is absent. |
| BEL-20 | `test_behavioral_beliefs` | Old scope identities reject different alternatives; new scopes do not inherit evidence. No automatic structural revision. |
| LRN-01, LRN-02 | `test_behavioral_generalization` | Evaluate/select prepared generalizations and retain counterexamples. LRN-01 uses a supplied implementation-count metric; no autonomous common-mechanism synthesis or graph-model unification. |
| LRN-04, LRN-08 | `test_behavioral_generalization`, `test_analytical_programs` | Reflection proposals and analytical Notes retain sources without establishing beliefs or rewriting principles. The owner integrates analytical outputs through KnowledgeIntegration; autonomous scope revision is absent. |
| LRN-05, LRN-07 | `test_behavioral_generalization` | Independent evaluation, lifecycle activation, and execution of a prepared parser with new input. No autonomous debugging or semantic Task-handler selection. |
| LRN-06 | `test_behavioral_generalization` | Compacted audit traces retain failures, hypotheses, checks, and activated revisions. |
| LRN-03, LRN-10–17 | `test_behavioral_learning` | Shared bindings, credit, locks, idempotence, correction, and transaction rollback. |
| LRN-09 | `test_behavioral_evaluation` | Source/slice independence, hidden prediction outcomes, and holdout access through initial memory. |
| LRN-18 | Future; no test | Associative subsystem is explicitly future work. |
| SEM-01 | Not yet covered | No automatic synonym canonicalization; exact-name lookup is not a substitute. |
| SEM-02–05 | `test_behavioral_semantics`, `test_behavioral_control` | Views, multiplicity, UNKNOWN, historical snapshots, temporal belief boundaries, and reader restoration after backup. |
| COG-01, COG-02 | `test_behavioral_tasks`, `test_task_delivery`, `test_behavioral_runtime` | Supplied decisions: requirements, provenance, correction, same-Task clarification, and worker/replay Unicode. Component variants and real durable boundaries are separate. |
| COG-03, COG-04 | `test_behavioral_control` | Serial admission gate, preserved progress/usage, and self-improvement within the total budget. |
| COG-05 | `test_behavioral_tasks` | Mandatory-check gate and negative verifier; no automatic registry of arbitrary required Task checks, so a model's false `verified=True` is not excluded by these cases. |
| ACT-01–03 | Not yet covered | No ActionDistribution, policy executor, or continuation planner; bootstrap Planning returns a proposal. |
| ACT-04, ACT-05 | `test_behavioral_control` | Real ActionGateway: current immutable commands; acceptance is distinct from an Observation or success. |
| ACT-06 | `test_behavioral_control` | Unknown receipt does not trigger resending; pending/reconciliation survive snapshots. Automatic receipt acquisition is absent. |
| EVA-01–04 | `test_behavioral_evaluation` | Statuses, proper scoring, frozen evaluation, hidden outcomes, and refusal without independent evidence. |
| INT-01 | `test_behavioral_memory` | Lessons and evidence remain accessible after compaction; later plan selection is not checked. |
| INT-02 | `test_behavioral_generalization` | Real estimator learns, passes independent checks, and retains `7 → 8` after compaction/restore. No full Program learning/activation/next-Task selection orchestration. |
| INT-03, INT-04 | `test_behavioral_beliefs` | Current reads after retract and separate behavior/belief probability in traces; executable policy and plan revision are absent. |
| INT-05 | `test_behavioral_learning` | Comments stay separate from numeric feedback; a supplied target receives credit or UnresolvedCredit. No automatic causal-target selection from text. |

The catalog contains 77 scenarios: the existing mapping describes full or partial coverage for 68 and gaps for 9. This is a capability inventory, not a claim that every scenario is fully implemented. Module names may occur in more than one suite because business rules and infrastructure boundaries are deliberately separated.

## Performance evidence

Measure the same interpreter, dependency set, and machine before comparing runs. Record sequential and parallel totals, and distinguish an empty tool cache from repeated runs. Integration and native coverage must not disappear to improve the reported fast-suite number. Windows-native performance and enforcement require a Windows run; macOS results cannot stand in for them.

See the migration measurements below for locally verified results and environment limitations.

### Migration measurements — 2026-10-07

Local host: macOS, Python **3.13.13**, Git **2.54.0**, locked runtime dependencies, pytest 9.1.1, pytest-xdist 3.8.0. These historical measurements used an explicitly prepared `.venv` because the former exact Python patch pin was unavailable. Setup now accepts available Python 3.13 patch releases and supports the standard `uv` commands. Times below are pytest-reported totals, excluding dependency installation.

| Run | Result | Time |
| --- | --- | --- |
| Original snapshot, sequential portable selection | 435 passed, 15 skipped, 18 deselected | 138.02 s |
| Original snapshot, repeated alone | 434 passed, 1 failed, 15 skipped, 18 deselected | 132.90 s |
| Final fast suite, sequential (`-n 0`) | 339 passed | 1.51 s |
| Final fast suite, four workers | 339 passed | 1.39 s |
| Final portable integration, sequential (`-n 0`) | 121 passed | 80.16 s |
| Final portable integration, four workers | 121 passed | 25.89 s |

The original snapshot used `-k 'not native and not appcontainer'`; it included expensive coordinator tests and omitted some native-named fake SDK cases. The new fast default deliberately selects a different workload. All **369 original test functions** remain represented across the categories. The migration adds a two-case durable intake/provenance integration scenario and four process-guard cases. The final offline portable total is **460 passing cases**; another 12 native cases require Windows and 2 live cases require explicit SDK opt-in.

The original successful baseline overlapped another validation run and is only a reference, not a controlled speedup measurement. Its repeat ran alone with already installed dependencies and warmed filesystem caches, but failed when a temporary `.git/objects/bitmap-ref-tips_*` file disappeared during Git metadata validation in `test_amending_candidate_keeps_both_committed_revisions`. This pre-existing intermittent Git failure is recorded rather than counted as a successful benchmark. It did not recur in the final sequential or parallel integration runs; this refactor does not claim to fix that production Git race.

Each final test session owns fresh worker-cache directories. No cold-versus-warm Windows tool-distribution benchmark was possible on this macOS host; native Python/AppContainer preparation is not exercised here. Windows CI is configured for both portable execution modes and a separate sequential native suite, but its results were not observed during local implementation.

`--durations=15` identified these remaining costs:

- Fast suite: fake-SDK initialization at 0.22 s; explicit retry/queue scenarios around 0.06 s. Setup/teardown were below these reported call costs.
- Sequential integration: DBOS observation recovery at 3.69 s, accepted parser execution at 3.40 s, and committed generalization evaluation at 3.12 s. These tests intentionally retain real infrastructure.

Lint, formatting, source/taxonomy validation, and `git diff --check` passed. Native/live tests were collected successfully and skipped locally for their documented platform/opt-in requirements.

## Semantic interface checks

`test_semantic_interface` covers normalized exact lookup, ambiguity, atomic names, parallel index retrieval, ranked merging, pagination and temporal property discovery. `test_provider` covers real schema registration at the SDK continuation boundary, idempotent loading, reset on the next invocation and model-mode permission checks using a fake transport. `test_semantic_programs` runs the actual semantic Programs in a DBOS worker, including child calls, invalid-delta repair, replay and an IPC concurrency barrier.

A separate Redis integration test uses a real Redis 8.4+ Search server and deterministic embeddings (no model charges):

```sh
EVERTREE_TEST_REDIS_URL=redis://127.0.0.1:6379 uv run pytest tests/integration/test_redis_search.py -q -n 0
```

It uses private random index namespaces and deletes those test indexes afterward. SDK/Luna tool-set continuation and actual OpenAI embeddings each have opt-in live smoke tests in `tests/live`; embeddings additionally require `EVERTREE_EMBEDDINGS_INTEGRATION=1` and `OPENAI_API_KEY`.

The Redis suite separately tests names and descriptions for concepts, prototypes, Instances, Facets, relation types and facts; KNN uses known vectors to verify ranking and `kind` independently of embedding quality. Exact-name tests assert zero model/index calls.

The separate opt-in `tests/live/test_embeddings.py` checks real OpenAI embeddings with `OPENAI_API_KEY`. Live tests may incur usage charges.

## Conscious steps and integration policy

Step-contract and coordinator tests distinguish intermediate analytical Notes from user messages, enforce finite local budgets, retain working state between iterations and gate completion on integration. Semantic component tests exercise explicit preservation obligations, complete decision coverage, source-specific retention, reuse and the restricted write gateway. These tests use supplied model decisions to check contracts; they do not prove autonomous semantic judgment.

`tests/live/test_knowledge_integration.py` evaluates the actual installed KnowledgeIntegration Program with a real Codex model and real in-process semantic stores. Source-backed cases in `knowledge_integration_cases.json` cover a conditional hypothesis whose uncertainty must survive preservation, a routine series that must not explode into per-reading states, and an intermediate experiment plan that must not become a fabricated final result. A fourth case uses the production consciousness instructions and result schema to check that one experiment-planning step returns a bounded continuation rather than pretending to finish the investigation. Hard assertions check accepted receipts, preservation, retained source access, bounded graph growth and absence of unsupported belief targets. Separate model invocations evaluate meaning and step granularity against explicit criteria, with no generator session history; these are fallible semantic evaluations, not deterministic proofs.

```sh
# Opt-in: actual model calls, including one separate rubric review per case.
EVERTREE_CODEX_INTEGRATION=1 uv run pytest tests/live/test_knowledge_integration.py -q -n 0
```

The harness uses deterministic empty non-exact search indexes over an initially empty domain; exact bootstrap lookup and the production semantic search/commit paths remain active. It tests integration policy and single-step model behavior, not embedding quality, worker isolation, durable recovery or full conscious-loop scheduling. Each model call has a 120-second timeout and the production Program bounds its preparation attempts. Failures retain source cases, model exchanges, graph receipts and rubric results in `semantic-policy-evaluation.json` or `conscious-step-evaluation.json` under the pytest case directory. Without the opt-in variable the cases collect and skip without model calls.
