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
| `evidence` | Text-based end-to-end belief cases: integration then evidence assessment ([catalog](evidence/README.md)) | Explicit opt-in; real model, Redis Search and embeddings |

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

Execution-order checks cover the single Program call chain, parent/sibling rejection,
paired search channels, external graph-write exclusion, and deferred memory maintenance.
Search reviews belong to one model invocation and survive its own writes. Recovery tests
also cover a completed search child returned by DBOS before a new creation, using the
retained Core confirmation. Program-returned completion cannot authorize creation; a later
incomplete search revokes earlier confirmation. RPC timeout tests cover root and child
Programs, repeated cancellation, and draining both successful and failed Core replies. Query/walk pagination still rejects
continuation after a write. Redis tests verify on-demand replacement and cache reconstruction;
no graph commit starts index I/O.

`test_semantic_interface` covers normalized exact lookup, ambiguity, atomic names, parallel index retrieval, ranked merging, the 20-result search ceiling and temporal property discovery. `test_provider` covers real schema registration at the SDK continuation boundary, idempotent loading, reset on the next invocation and model-mode permission checks using a fake transport. `test_program_agents` checks the shared native-tool bridge's role restrictions, schema validation and call limits. `test_semantic_programs` runs the actual semantic Programs in a DBOS worker, including tool repair, child calls, replay and an IPC concurrency barrier.

Program tool tests should call the declared `tool_handler` through the provider interface.
Recovery checks must verify that durable tool exchanges replay callback computations and
child operations to reconstruct local execution without repeating completed writes or provenance.
An interrupted transient SDK invocation may resume with the completed tool transcript;
normal continuation must use native calls and results. Check the same authority boundary
in isolated evaluation. Normal model completion with no writes is valid. Each successful
operation must already be visible with permanent IDs and source-backed history; a later
failed call must leave those writes intact.

A separate Redis integration test uses a real Redis 8.4+ Search server and deterministic embeddings (no model charges):

```sh
EVERTREE_TEST_REDIS_URL=redis://127.0.0.1:6379 uv run pytest tests/integration/test_redis_search.py -q -n 0
```

It uses private random index namespaces and deletes those test indexes afterward. SDK/Luna tool-set continuation and actual OpenAI embeddings each have opt-in live smoke tests in `tests/live`; embeddings additionally require `EVERTREE_EMBEDDINGS_INTEGRATION=1` and `OPENAI_API_KEY`.

The Redis suite separately tests names and descriptions for concepts, prototypes, Instances, Facets, relation types and facts; KNN uses known vectors to verify ranking and `kind` independently of embedding quality. Exact-name tests assert zero model/index calls.

The separate opt-in `tests/live/test_embeddings.py` checks real OpenAI embeddings with `OPENAI_API_KEY`. Live tests may incur usage charges.

## Conscious steps and integration policy

Step-contract and coordinator tests distinguish intermediate analytical Notes from user messages, enforce finite local budgets and retain working state between iterations. Integration failures must not block continuation or final delivery, and failed packets must not retry at every boundary. Semantic component tests exercise shared direct writes (including Claims without automatic belief assignment), updates and deletes, per-operation history and sources, idempotent recovery, source-specific retention and the checked write gateway. Model-mode calls remain read-only even when tools are loaded. These tests supply native tool calls to check mechanical contracts; they do not prove autonomous semantic judgment.

`tests/live/test_knowledge_integration.py` evaluates the actual installed KnowledgeIntegration Program with a real Codex model and real in-process semantic stores. Source-backed cases in `knowledge_integration_cases.json` cover a conditional hypothesis whose uncertainty must survive preservation, a routine series that must not explode into per-reading states, and an intermediate experiment plan that must not become a fabricated final result. A fourth case uses the production consciousness instructions and result schema to check that one experiment-planning step returns a bounded continuation rather than pretending to finish the investigation. Hard assertions check actual write results, retained source access, bounded graph growth and absence of unsupported belief targets. The semantic rubric checks whether important meaning expressed in the source text was usefully retained; no structured preservation flag imposes a runtime obligation. Separate model invocations evaluate meaning and step granularity against explicit criteria, with no generator session history; these are fallible semantic evaluations, not deterministic proofs.

```sh
# Opt-in: actual model calls, including one separate rubric review per case.
EVERTREE_CODEX_INTEGRATION=1 uv run pytest tests/live/test_knowledge_integration.py -q -n 0
```

The harness uses deterministic empty non-exact search indexes over an initially empty domain; exact bootstrap lookup and the production semantic search/write paths remain active. The integration model receives native tools with actual handlers. It tests integration policy and single-step model behavior, not embedding quality, worker isolation, durable recovery or full conscious-loop scheduling. Each model invocation has a 120-second timeout and the production Program bounds its tool calls. Failures retain source cases, model exchanges, actual graph write results and rubric results in `semantic-policy-evaluation.json` or `conscious-step-evaluation.json` under the pytest case directory. Without the opt-in variable the cases collect and skip without model calls.

`tests/live/test_attribution_learning.py` checks three acquisition paths through the real KnowledgeIntegration model and native semantic tools: separate reports of individual measurements, a source's classification bands, and a published frequency table. It serializes and restores the actual graph, attribution, belief, learning and memory stores, then uses a separate model invocation with no earlier conversation to answer through `summarize_property`. Hard assertions check calculations, frequency weights, source provenance, conditional labels, comparison direction and unchanged graph/belief/learning state during use. A separate model review checks the explanation's source meaning and limits on generalization; that review is a fallible semantic evaluation, not a deterministic proof.

Six additional cases cover repeated reports and correction, conflicting guides, grouped intervals, breed-specific scope, selection with an unknown value, and transfer to parcel masses in different units. Their hard assertions use the actual runtime reports and saved identities; an independent rubric checks the answer's meaning. Each run records the production source hash so results can be associated with the code that ran.

Both attribution readers import the production `NUMERIC_READ_INSTRUCTIONS` used by consciousness. That contract requires runtime summaries for retained measurements and tables, and an actual interpretation for each requested guide; search descriptions serve discovery. A correct free-text category alone therefore does not pass the API-use assertions. Failure to demonstrate that path is recorded separately from an incorrect category or numeric result. KnowledgeIntegration also reads back an explicit numeric guide or frequency table before finishing; the tests verify what was actually retained and read, not merely whether the instruction was present.

```sh
EVERTREE_CODEX_INTEGRATION=1 EVERTREE_EMBEDDINGS_INTEGRATION=1 uv run pytest tests/live/test_attribution_learning.py -q -n 0 -o tmp_path_retention_policy=all
```

The attribution harness uses a real `RedisSearchIndex` with OpenAI embeddings over an initially empty domain, so later use must retrieve the knowledge the model saved. It loads the repository semantic configuration and debug `.env`; configured Redis Search and an embeddings credential are required in addition to both opt-in flags. Each case has a private namespace derived from its pytest directory; teardown deletes only that namespace's indexes and keys. The in-process semantic writes, reads and serialized restoration are real, but worker recovery, durable backup, a real application restart and full scheduler/DBOS orchestration are outside this test. Each case writes source packets, model exchanges, retrieval configuration, saved stores, actual usage calls, runtime reports and the independent review to `attribution-learning.json` in its pytest directory, including on failure. Shared native-dialogue setup is in `tests/support/live_semantics.py`; it does not substitute the summary calculations or integration decisions.

When acquisition completed but later model use failed, `EVERTREE_ATTRIBUTION_LEARNED_ARTIFACT` can name the original `attribution-learning.json` for a reader-only retry of that exact selected case. The harness verifies the case and source packets, completed acquisition invocations, complete snapshots and matching production hash; an interrupted acquisition is rejected. The new artifact records the original path and SHA256. This checks reuse of the same completed acquisition, not another learning run, and preserves the original failure. Successful runs also assert that the production source hash did not change while the test ran.

The [Attribution Plane implementation plan](../docs/plans/attribution-plane-mvp.md) retains the initial numeric MVP's acquisition/use evidence, checkpoints and reader-only retries as history. That earlier validation was not one clean nine-case run on its final version. An observation answer passed hard checks but one rubric criterion rejected the word “measurements” despite preserved source attribution. After clarifying that this word alone does not claim firsthand verification, two independent reviews accepted the unchanged answer and rejected a negative control falsely claiming personal verification. The original pytest failure remains a failure; the review artifact is separate evidence. The full-plane acceptance described below uses new acquisitions on a later common checkpoint. A small number of successful runs does not estimate real-world coverage or model reliability.

`tests/live/test_attribution_norm_learning.py` extends that descriptive MVP with actual relative-scale learning. Separate natural-language messages report dogs at 8, 5 and 10 kg through real KnowledgeIntegration; another naturally asks which are small, medium or large relative to each other, including a hypothetical 7 kg dog. It supplies neither property IDs nor a train command. That question runs through the production conscious work step, semantic tools, analysis recording and normal integration/evidence assessment. The agent must retain the qualitative property and fitted checkpoint, and GraphEvidenceAssessment must assess source-backed categorical Profiles. After serialized restoration, a fresh reader must use those Profiles for actual dogs, `interpret_property` for the hypothetical value and `select_properties` for an explicit alternative-strength ranking. A subsequent correction from 8 to 9 kg checks automatic refresh outside reads, reassessment, stable criterion meaning and preservation of the original checkpoint. This is a new live acceptance path; the earlier numeric MVP passes do not prove it.

```sh
EVERTREE_CODEX_INTEGRATION=1 EVERTREE_EMBEDDINGS_INTEGRATION=1 uv run pytest tests/live/test_attribution_norm_learning.py -q -n 0 -o tmp_path_retention_policy=all
```

The norm harness uses real Redis Search, OpenAI embeddings and model calls, with the same private namespace and cleanup discipline as the numeric harness. Its `attribution-norm-learning.json` retains source packets, the application/conscious transcript, integration and assessment exchanges, learned/restored stores, usage calls, correction and source hashes on both success and failure. It uses the component application boundary: task framing, scheduler and worker/backup substitutes remain outside this live check, while the conscious invocation and integration are real. Separate integration/native suites exercise transport and durable storage. This establishes the executed learning/use path, not calibrated probabilities or representative coverage of all dogs.

Live helpers use the application's model and reasoning-effort settings, while retaining an explicit request override. Earlier runs forced `gpt-6-luna/medium`; the fresh runs numbered 08 use the application's actual `gpt-6-luna/high` configuration. These are different evaluation settings for the same model and must not be merged into a single reliability estimate. A hypothetical value at a displayed boundary is checked against the retained criterion's exact numbers; a separate component test verifies that the exact default quantiles classify 7 kg as Small.

After deterministic read checks, a separate model reviews population scope, tentative confidence, reported-source meaning and the conditional hypothetical example. Its payload is limited to the synthetic source packets, actual answer, compact norm metadata and Profile strengths; it receives no saved graph, memory, earlier transcript or filesystem paths. Requests, events and verdicts remain in the case artifact. The rubric judges meaning without requiring specific wording or equating an unassessed source with an unreliable one.

The same live file also checks a learned scale from one anonymous frequency table: 3/6/9/12 kg with counts 1/3/4/2 yields count 10 and fitted boundaries 6/9. A fresh reader must interpret hypothetical 7 kg as the middle class through the saved norm and explicit distribution reference. The test rejects invented individual dogs and verifies read-only restoration. Its artifact is `attribution-table-norm-learning.json`.

Final full-plane acceptance passed all 11 unique live cases on source hash `51f6e0ae2d76372ce70d1cddc3552709d85b0529eb74eff680b639d363376400` and the application's `gpt-6-luna/high` configuration: two learned-norm paths and all nine descriptive cases. Two complementary runs produced 4 passed/7 deselected and 7 passed/2 deselected, with fresh acquisitions and unchanged source hashes; this was not one combined invocation. All descriptive cases and the observation/Profile case passed their independent semantic review. The implementation plan records artifact paths, exact durations, deterministic/integration/native results and earlier failures separately.

The grouped-interval oracle accepts an empty classification list or an explicit `unknown` when no categorical criterion exists; it rejects invented categories. Its component regression uses real retained interval data and negative controls. The semantic rubric also distinguishes “reliability has not been assessed” from “the source is unreliable because it is unassessed.” Clarifying either acceptance rule does not turn an earlier pytest failure into a pass: unchanged-answer checks and independent reviews are retained separately.

All guide fixtures with inclusive upper bounds check the exact saved boundaries and inclusivity flags as well as the runtime report. Correct interior classifications alone cannot pass a rule that maps an endpoint to the wrong class. Component controls cover each fixture's boundaries and converted units, accepting the inclusive rule and rejecting the same rule with an exclusive first boundary.

The deterministic attribution suites separate the following contracts:

- `test_attribution_norms.py`: weighted quantiles over full retained data, sparse and degenerate cases, interval precision, domain/conditions, hysteresis, revision changes and old checkpoints.
- `test_attribution_evidence.py`: primary-source reuse, norm applicability distinct from subject belief, categorical scopes, withdrawal and stale assessments, state identity rather than timestamp identity, no read mutation and restored Profile bindings.
- `test_attribution_sources.py`: saved scalar/interval/normal/quantile results, units and exact semantic binding, model Program children and computed selection without read materialization.
- `test_attribution_selection.py`: valid scale operations, explicit Profile predicates, shared graph-evidence projection and unknown preservation.
- `tests/integration/test_attribution_persistence.py`: real BackupManager files and verification, read-only exact-checkpoint reconstruction and model child execution/replay through worker IPC. A completed worker result passes through the production trace sink into backup, then a historical read recovers its exact arguments, world time, Program revision and output reference. Missing or mismatched completed results return UNKNOWN, including a later retained unknown result; current code is never executed as historical fallback. This does not claim a full application restart.

The automatic evidence phase assesses at most 20 pending qualitative questions per invocation. Remaining subjects retain UNKNOWN until a later phase; reading does not trigger assessment. This limit does not truncate fitting data or freshness dependencies.

`tests/live/test_integration_search_flow.py` separately exercises the real model, Redis Search and OpenAI embeddings against an existing pump class, two pump identities and their states. It checks reuse of the known identity and interval, creation of the missing interval, and navigation through `describe`, both with an exact stored name and a longer stored name requiring similarity retrieval. It uses the debug harness configuration from repository `.env` and deletes its private Redis indexes afterward. `search-flow.json` records actual model calls and results; `calls.json` also includes handler-inserted searches, individual retrieval channels and writes. Keep successful artifacts when comparing prompt variants:

```sh
EVERTREE_CODEX_INTEGRATION=1 EVERTREE_EMBEDDINGS_INTEGRATION=1 uv run pytest tests/live/test_integration_search_flow.py -q -n 0 -o tmp_path_retention_policy=all
```

Compare query meaning, candidate ranks, followed IDs, redundant reads and creation retries alongside the final graph. These small live cases expose retrieval-flow problems but do not establish recall on a large corpus or guarantee a particular model call sequence. `tests/component/test_integration_search_flow.py` deterministically checks that the projected reads expose the Facet → Instance → Prototype/state path without another search.

The same live suite also checks creating an absent parent class, reusing an existing parent, adding the missing parent link to an existing class, classifying a thermometer, correcting a known Facet's interval while preserving its identity/history, and avoiding per-reading graph expansion for a routine series. It checks graph structure and temporal invariants rather than exact class labels or prose. Candidate review must allow repeating creation with the same name; renaming restarts search. The component suite checks this path with nonempty neighbor results and verifies the resulting parent link.

### Large technical graph

`tests/data/datacenter_experience.txt` is a synthetic 2,100-word report about one data
center. Shared report context (including UTC and the year) accompanies each packet.
Six connected chapters cover hydraulics, electrical backup, message delivery,
network/TLS, storage/recovery, and uncertain incident explanations. Stable equipment IDs,
aliases, two languages, similar terms in different domains, historical intervals and
cross-subsystem dependencies make it harder than the small pump fixture. The text states
its fictional scope; its parameters are test data, not operating recommendations.

`tests/live/test_large_graph_search.py` first feeds these chapters to the real integrator.
No domain nodes are manually seeded. It saves each packet's graph, traces, calls and metrics,
then freezes a baseline. Each large packet has a 300-second model invocation limit and the
production tool-call bound; a timeout retains partial writes and fails the build check.
Size checks require at least 100 total nodes and 50 non-fact nodes,
so structural edges alone cannot satisfy the large-graph requirement. Failed build packets
are recorded and remain visible; no successful retries silently replace them.
The meaning audit also validates every retained source reference, checks the recorded UTC
intervals and rejects class IDs used as physical components in this fixture. These checks
are deliberately independent of node count; inspect the actual relations and Claims for
unsupported assertions and missing useful connections as well.
Graph metrics separately report domain relations and instances without them: a large
inventory with only class/state links is not evidence of a well-connected operational model.

The second stage runs 16 fixed search probes on that graph: exact IDs, aliases, paraphrases,
English queries for Russian material, related objects, ambiguous technical terms and an
absent subject. `retrieval-summary.json` separates missing representations from retrieval
misses. Critical-target recall is **not** full semantic recall/precision: relevance of other
returned neighbors requires reviewing `cards.json` and `retrieval.json` independently.

The third stage forks the same baseline for each of four updates:
a new interval under an existing alias; correction of a UPS interval; a new sibling pump
reusing the known class; and alternative explanations of a digital incident. It checks
identity preservation and records all actual model queries, errors, time and token usage.
Interval corrections must retain prior history, cite new grounds and leave the other UPS's
states unchanged. New alias observations must preserve their own date and time interval.
Each update starts from the same baseline so changes from an earlier scenario cannot
help a later one. Review hypotheses and generalizations in the resulting graph in addition
to the structural assertions. This is a substantial opt-in run with real API costs:

```sh
EVERTREE_LARGE_GRAPH_INTEGRATION=1 uv run pytest tests/live/test_large_graph_search.py -q -n 0 --basetemp=tmp/large-graph-evaluation -o tmp_path_retention_policy=all
```

The semantic regression checks require a distinct CACHE-1, use a separate model rubric to inspect
its retention setting, hydraulic separation and independently revisable incident hypotheses, then
correct the cache lifetime while checking identity, unchanged history and unrelated timeout settings.
`tests/live/test_semantic_distinctions.py` adds machine vision, thermal control and artifact delivery
cases. They test operational settings, power/control and signing/distribution distinctions, separate
candidate explanations, and a conditional hypothesis whose joint conditions must stay together.
The generating model sees the source and ordinary task context, not the evaluation criteria.
The rubric accepts equivalent representations and records node-specific reasons; it is fallible
and runs only in tests, with no production validation call or preservation contract.
Use the same large-graph opt-in and optionally a saved snapshot to test new domains among existing
knowledge. Each case forks that snapshot independently. Inspect `integration/{history,metrics,snapshot}.json`
and `review/{input,events,review}.json` under the retained pytest directory.

To iterate on search without paying for graph construction again, set
`EVERTREE_LARGE_GRAPH_SNAPSHOT` to an absolute path to the saved `baseline.json` and use a
**different** `--basetemp`; pytest clears its destination at startup. Select
`-k search_on_identical` to run only retrieval. Keep the snapshot's source report and metrics
with it, so improvements to search are not confused with changes to graph construction.


### Exact graph reads and output budgets

`tests/component/test_graph_queries.py` exercises partial slot bindings, typed participants,
scalar/list roles, conditions, counts, cycles, temporal uncertainty, private continuation scope,
interleaved selections, exhausted pages, and final JSON
token budgets. Its local BPE vocabulary needs no downloads. Provider tests check selected-model
context metadata; Program-agent and semantic-worker tests verify budget transport and durable
replay. The native Program-agent test also covers bootstrap without revision-owned logging helpers.
These tests establish mechanics, not semantic model judgment or server-exact token counts for
private model aliases.
