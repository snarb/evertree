# Starter ontology sources and reuse conditions

This package is an authored Evertree profile, not an export of SUMO, a complete
curriculum, or a running agent snapshot. Each record identifies the source of
its definition through `source`, `source_id`, and `revision`. File/module
membership is packaging metadata and never establishes subtype inheritance.

## Adopted SUMO core

The adopted source is [`Merge.kif` at commit
`070e44b746a8a87ca675a2051b2bd910016b2c2f`](https://github.com/ontologyportal/sumo/blob/070e44b746a8a87ca675a2051b2bd910016b2c2f/Merge.kif).
The fetched file is 657,280 bytes and has SHA-256
`7a94bb84410888d9760684d7315b0db3bbec88b17da12720b83d706030914b53`.
The revision pins the material actually inspected, rather than the moving
`master` branch or a claim about the latest ontology release.

**Copyright 2004, Institute of Electrical and Electronics Engineers, Inc.
(IEEE). All rights reserved.** SUMO was initially developed at Teknowledge
Corp. The complete source notice is retained in [sumo-notice.txt](sumo-notice.txt).
Its license permits copying, publication, distribution, and derivative works
subject to acknowledging IEEE as source and copyright owner in every use.
The source is supplied as is, with the disclaimers recorded in that notice;
it is not public-domain material.

The source requests citation of Ian Niles and Adam Pease, “Towards a Standard
Upper Ontology,” *Proceedings of FOIS 2001*, Ogunquit, Maine, October 17–19,
2001. The [Ontology Portal](https://ontologyportal.org/) provides project
context.

Records marked `sumo-core` preserve the named source meaning and selected
lineage, using concise paraphrases where practical. The external identifier
is the exact SUMO term, regardless of the local symbolic key. For example,
`sumo.agent` identifies `AutonomousAgent`, not an invented SUMO term `Agent`.
Where a source term has several parents, the record's `single_parent`
adaptation records the choice. Omitted parents do not become concealed extra
inheritance edges. Definitions narrowed to resolve an actual inconsistency
are marked `semantic_correction`; they must not be treated as exact external
equivalences. The profile does not import all SUMO axioms, partition
constraints, disjointness assertions, or theorem-proving behavior.

No text or axioms from `Mid-level-ontology.kif` or SUMO domain modules are
included. Their licensing must be checked independently before any future
import; the core notice is not a blanket license for the whole repository.

## Original Evertree entries

Records marked `evertree` contain original definitions, role contracts,
examples, aliases, and links authored for this starter profile, version
`1.0.0`. Their `source_id` is their stable local key. They may use standard
scientific vocabulary also found in external ontologies; that does not assert
term equivalence, copied definitions, or an imported external hierarchy.

These additions are governed by the Evertree repository's applicable terms.
This file does not introduce a new license grant for the repository or apply
the SUMO license to original Evertree material. Future maintainers must not
infer permission to redistribute third-party material merely because its
subject matter appears in this package.

## Coverage references, not imported definitions

The manifest lists the following references as coverage guides. They are not
record-level definition sources, and their hierarchies are not asserted to
be equivalent to Evertree's type tree.

| Reference | Pinned reference | Use and conditions |
| --- | --- | --- |
| [CS2023](https://csed.acm.org/knowledge-areas/) | ACM/IEEE-CS/AAAI Computer Science Curricula 2023, final report published 2024 | Knowledge-area coverage checklist for independently authored software and computing definitions. No report passages, tables, or curriculum taxonomy are redistributed. Copyright remains with the respective publishers. |
| [SWEBOK](https://www.computer.org/education/bodies-of-knowledge/software-engineering) | IEEE Computer Society, Guide to the Software Engineering Body of Knowledge, version 4.0a | Software-engineering coverage checklist. No guide text is incorporated and no permission to redistribute the guide is inferred. |
| [STATO](https://stato-ontology.org/) | Website scope inspected 2026-10-23 | Guidance on statistical methods, study designs, assumptions and measurements. No STATO release, identifiers, definitions or axioms are imported. The website's attribution notice does not substitute for checking a particular future ontology artifact's license and revision. |
| [ProbOnto](https://doi.org/10.1093/bioinformatics/btw170) | Swat et al., *Bioinformatics*, 2016, DOI `10.1093/bioinformatics/btw170` | Bibliographic guidance on distribution coverage. No paper text or ontology axioms are copied; no exact equivalence to ProbOnto classes is claimed. |

School and everyday material consists of original, concise definitions with
explicit scope. The package does not claim alignment with a particular
country's school curriculum, exhaustive legal coverage, or measured coverage
of 80% of user tasks. Local legal, geographical and institutional assertions
still require their own jurisdiction, time, source and evidence.

## Adding a source

Before incorporating external definitions or structure, pin a retrievable
revision, retain the required notices, state whether the use is an import,
adaptation, mapping, or coverage reference, and record the source identifiers
on affected entries. A mutable website access date is sufficient only for a
nonimported coverage reference. It is not a substitute for a pinned ontology
artifact when importing its terms. Reusing an upstream label alone does not
establish semantic equivalence or authority for empirical claims.
