# Evertree starter ontology

This editable package seeds a **new application's** graph. It is not an agent snapshot, a complete SUMO import, or a measured claim about user-task coverage. Low-level `GraphStore.bootstrap()` deliberately installs only its nine foundational nodes. Existing applications restore their saved graphs without installing or upgrading this package.

The governing contract is [Taxonomy and Relation Governance](../../../../../docs/architecture/Taxonomy%20and%20Relation%20Governance.md). See [SOURCES.md](SOURCES.md), [sumo-notice.txt](sumo-notice.txt), and [manifest.json](manifest.json) for source scope, pinned revisions and attribution. Domain definitions are locally authored; external curricula inform coverage without being copied as class hierarchies.

[VALIDATION.md](VALIDATION.md) records the completed checks, prepared scenarios and untested boundaries for this release.

## Contents

| Module | Records | Scope |
|---|---:|---|
| `foundation.json` | 64 | SUMO spine and shared representation distinctions |
| `software.json` | 262 | Languages, code, constructs, algorithms, structures, development, tools, systems, security and operations |
| `intelligence.json` | 165 | Cognition, reflection, generalization, human/computer learning, ML/RL, language models and agent harnesses |
| `statistics.json` | 135 | Probability, distributions, estimation, tests, design, uncertainty and evidence |
| `world.json` | 404 | School mathematics/sciences/geography, psychology, law, institutions, economy, politics and everyday activities |
| `relations.json` | 70 | Abstract relation families, role types and 32 concrete predicates |

There are 1,100 canonical records: 1,068 `Prototype` definitions and 32 concrete `RelationType` definitions. Installation currently creates 1,190 taxonomic/semantic facts in addition to those records. Files are maintenance modules, never implicit parents. Shared meanings occur once and may be referenced from multiple modules.

`scenarios.json` contains 56 priority-domain intentions and `world_scenarios.json` contains 21 broader intentions. They specify targets, contrasts and expected ancestors. Tests exercise real parent chains and complete child reads for these 77 authored scenarios. They **do not test whether an LLM chooses the correct route** or estimate the frequency of these needs among users. The separate runtime scenario checks general versus Self processes. No optional navigation reparenting is included; no improvement claim or confidence interval is reported.

## Record contract

`key` is a stable symbolic identity. `name` is a canonical name, distinct from aliases. `definition`, English/Russian `aliases`, `examples`, `counterexamples`, `source`, `adaptation` and `links` retain the meaning and provenance. `parent` names one other key; only `sumo.entity` has `null`. Rename a label without changing its key only when the meaning is unchanged. The loader assigns numeric identities and reconciles the minimal core bindings without replacing their IDs.

`source` contains a manifest source key, original source identifier, and matching pinned revision. `coverage_sources` identifies reference works used to guide breadth, not imported definitions or equivalence assertions. An adaptation records `kind` and `reason`; optional navigation adaptations additionally require the policy's evidence record. The numerical validation gate checks declared evidence; it cannot prove the independence or quality of the underlying experiment.

A semantic `links` entry has `relation` and `target` keys. It uses a declared binary relation with `source` and `target` node roles. These references are actual graph facts after installation. Relation definitions additionally declare `subjects`; the loader materializes `RELATION_SUBJECT` facts.

A concrete predicate declares:

- `signature`: each slot has `label`, technical `value_type`, `arity`, semantic `value_concept`, contextual `role_concept`, and `description`;
- `views`: named input/output projections with explicit cardinality;
- `subjects`: concepts the relation is about;
- `specialization`, only for a concrete parent: `parent`, `roles` mapping **parent slot → child slot**, and an entailment explanation.

A category of relations is an ordinary `Prototype`, without `signature`, `views` or dummy roles. Specialization is stored as a declaration; views query the named predicate's actual facts and do not synthesize parent assertions. Runtime validates reference existence, structural typing and specialization parent/role consistency. Template validation additionally checks semantic narrowing. General semantic argument membership and empirical truth remain governance responsibilities.

Optional view `constraints` use the Core predicate form `{"all": [{"field": "source", "op": "in", "value": ["sumo.entity"]}]}`. Values for node-valued slots are symbolic keys, including keys inside lists; the loader resolves them along with signature references. String and numeric conditions retain their literal values. Constraints are preserved through graph serialization and applied by the normal view query mechanism.

## Editing and validation

1. Search the package before adding a record; read definitions and contrasting examples.
2. Choose a valid inclusion parent. Preserve applicable source classifications; record justified source projections or corrections.
3. Add every referenced concept, role and relation, or reuse an existing key. Update source metadata when introducing a new source.
4. Add an independent scenario for a new ambiguity. Do not count paraphrases as independent evaluation cases.
5. Validate and run affected tests:

```sh
uv run python -m evertree.core.graph.template
uv run pytest tests/component/test_graph_template.py -q
uv run python -m evertree.core.programs.layout
```

`read_template()` validates JSON modules without changing a graph. `install_template(graph, provenance=...)` installs on an empty or minimal graph inside a rollback boundary; failed installation restores nodes, history and ID allocation. It refuses live-graph reinstallation. Records retain source/revision metadata; generated facts retain the originating template key/source, and all changes carry the caller's producer provenance.

The application then creates Self as a `SoftwareAgent` instance, its own `Self*` process types and concrete Programs. Their bindings and non-inferential subject links are runtime bootstrap data, not identities embedded in this package. Accepted types form a rooted taxonomy; subject facts may remain disconnected when no meaningful relation exists.
