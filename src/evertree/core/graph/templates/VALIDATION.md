# Starter ontology validation — 2026-10-23

This report covers the editable `1.0.0` package, its validator/loader, new-application bootstrap, semantic read/search projections, and separation of the world ontology from Self and Programs. See [README.md](README.md) for the record contract and [the governance policy](../../../../../docs/architecture/Taxonomy%20and%20Relation%20Governance.md) for lifecycle algorithms.

## Included material

| Module | Canonical records |
|---|---:|
| Foundation | 64 |
| Software, tools and computer systems | 262 |
| Intelligence, learning, ML/RL and agent systems | 165 |
| Probability, statistics and evidence | 135 |
| School disciplines, institutions and everyday concepts | 404 |
| Relations and roles | 70 |
| **Total** | **1,100** |

The records comprise 1,068 Prototypes and 32 concrete RelationTypes. Installation produces 1,190 taxonomic/semantic facts, for 2,290 nodes before adding application-specific Self and Programs. All 1,100 records have English and Russian aliases. Boundary examples and counterexamples are supplied together for 79 records. Two predicates carry explicit specialization declarations.

There are 73 records attributed to the pinned SUMO core and 1,027 original Evertree definitions. [SOURCES.md](SOURCES.md) identifies the inspected revision, file checksum, retained notice and nonimported coverage references. CS2023, SWEBOK, STATO and ProbOnto guide coverage; these labels do not assert imported definitions or exact external equivalence.

Recorded adaptations comprise six mandatory single-parent selections and fifteen semantic corrections. There are **zero optional navigation adaptations**. The policy's 20% relative / 3-percentage-point absolute improvement and positive lower 95% paired-confidence-bound thresholds are acceptance rules, not observed results.

## Prepared scenarios

The real graph-read regression traverses 56 priority-domain routes from [scenarios.json](scenarios.json) and 21 broader routes from [world_scenarios.json](world_scenarios.json). Each route follows the actual parent chain from Entity and reads the complete children at every step; expected ancestors and distinct excluded destinations are checked. A separate application regression checks general processes against the corresponding Self processes and concrete Programs.

| Required distinction | Prepared coverage |
|---|---|
| Language / source code / compiler / execution | Separate language, source-code, compiler, compilation and execution intentions |
| Algorithm / implementation / run / result | Separate destinations and appropriate artifact/process ancestry |
| Learning / belief update / parameter optimization | Separate process meanings and scope |
| Human / computer / agent memory | Distinct representations and parent paths |
| Cause / temporal precedence / evidence dependence | Distinct concrete predicates, subjects and argument contracts |
| Class / temporary role / state | Separate membership, participation and execution-state concepts |
| General / own Evertree process | Generic reflection/planning routes plus bootstrap and protection regressions |
| School and common-world ambiguities | Equation vs theorem; number vs notation; circle vs disk; energy vs motion; reflection of light vs reflection in thinking; element vs atom; population vs species; glacier body vs region; emotion vs trait; contract vs agreement process; role vs person; price vs payment; news report vs event; schedule vs activity |

These are authored structural and representation checks. They are **not an LLM branch-selection experiment**, a representative task sample, a complete school-curriculum audit, or evidence of 80% real-user coverage. No model-navigation success rate or improvement interval has been measured for this release.

## Contracts exercised

- Unique keys/names, one parent, cycle rejection, root reachability and cross-module dependency closure.
- Source pins, relation subjects, signature references, contextual roles, view labels, concrete-versus-abstract representation, and specialization projection/narrowing.
- Invalid-package rejection before publication, including late Core-contract failure after ID reservation: nodes, history and next-ID allocation are restored.
- Exact template serialization/restoration, constrained-view filtering after restoration, and rejection of dangling symbolic references in view conditions.
- Minimal nine-node Core bootstrap versus full new-application bootstrap; refusal to reinstall a template over a live graph.
- Parent and child reads for predicates/processes; complete child lists for traversal; aliases and semantic links/signatures reaching both the search document and model-facing projection.
- Coexistence of world types, Self as a SoftwareAgent identity, Self-prefixed own processes, executable Programs and their source layouts/bindings.
- Structural edge creation/update/deletion cannot bypass protection of Self, own process contracts or Program bindings.

## Execution environment and interpretation

Checks run on macOS with Python 3.13.13. Commands use the existing repository environment with `UV_CACHE_DIR=/private/tmp/evertree-uv-cache` and `UV_NO_SYNC=1`: dependency synchronization was not part of these checks. Integration/native tests run outside the enclosing agent sandbox because their local IPC and nested OS isolation require it. The native lifecycle mirror runs independently with four workers; the other native tests run sequentially, following the test guide.

The Redis suite uses the configured test endpoint, isolated random index namespaces, cleanup of its own data, and deterministic embeddings. It does not make paid model or embedding calls. Windows-only contracts and opt-in outgoing HTTPS remain separate from the exercised macOS boundary.

## Final check results

All results below follow the final executable-source change, including support for constrained views. Subsequent edits only add documentation. Durations reflect concurrent local suites and are not controlled performance comparisons.

| Check | Result |
|---|---|
| `uv run pytest tests/component/test_graph_template.py tests/component/test_graph_queries.py -q` | 48 passed |
| `uv run pytest -q` | 1,025 passed, 130.01 s |
| `uv run pytest tests/integration -q` | 143 passed, 25 skipped, 153.32 s |
| `uv run pytest tests/integration/test_redis_search.py -q -n 0` with the test endpoint loaded | 25 passed, 100.37 s; exercises all 25 Redis cases skipped by the preceding default run |
| `uv run pytest tests/native --ignore=tests/native/test_lifecycle_mirror.py -q -n 0` | 25 passed, 4 skipped, 180.46 s |
| `uv run pytest tests/native/test_lifecycle_mirror.py -q -n 4` | 16 passed, 165.19 s |
| `uv run python -m evertree.core.graph.template` | Valid: 1,100 types and 1,190 links |
| `uv run python -m evertree.core.programs.layout` | Self/Process taxonomy, Program roles and source paths synchronized |
| `uv run ruff check src tests` | Passed |
| `uv run ruff format --check src tests` | Passed; 358 files formatted |
| `git diff --check` | Passed |

The completed offline selections therefore cover 1,025 unit/component cases, 168 integration cases including Redis, and 41 native cases. The targeted 48-case run overlaps the full fast suite and is not added again. Four native skips cover three Windows-only checks and the explicitly opt-in external-network smoke; they are not reported as passes.

## Remaining boundaries

Dedicated automatic taxonomy creation/merge/split/retirement Programs remain future work. The document specifies their semantic review, atomicity, history and evidence obligations without asserting that separate existing tool calls implement those workflows. Predicate specialization is retained and validated as a declaration; no inherited query inference is installed. General semantic argument membership and empirical truth are not established by storage-type validation.

Restoration reads the saved ontology. No automatic migration or update of existing agents is included. No live LLM navigation benchmark, Windows-native run or paid-model acceptance run is claimed.
