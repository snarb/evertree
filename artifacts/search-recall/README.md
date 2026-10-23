# Retrieval recall investigation — 2026-10-21

**Dataset audit correction:** the local sports questions had shortened gold lists.
107/609 questions lost 147 non-sports evidence entries and 42 required articles.
The historical retrieval metrics below do not establish recall for the original
complete questions. In particular, the latest forty require 90 gold sources, not 82;
old returned counts correspond to 78/90 (86.67%) off and 79/90 (87.78%) on.
No retrieval was rerun for this denominator correction. See `dataset-audit.json`,
`legacy-metric-audit.json` and the corpus audit report before using these numbers.

The earlier **20/37 (54.05%)** result combined a lossy corpus import with a very
small candidate pool. It was not a sound general estimate of the retrieval engine.
The following saved measurements used the locally surviving labels. Their forty-question
78/82 and 79/82 counts become **78/90 (86.67%)** and **79/90 (87.78%)** against complete
original evidence lists. Neither the raw-candidate figures below nor these corrected
denominators establish acceptance on the restored corpus. See the
[corpus audit and KnowledgeIntegration pilot](CORPUS-AUDIT.md) for current findings.

## What was missing

The original import created **1,006 article objects for 211 article URLs**, retaining
separate category-tree placements as different graph identities. A source appeared
between one and fifteen times. Those copies competed for the same 7 BM25 / 12 vector
candidate slots and final ten object slots. Deduplicating results by graph ID could
not repair artificial duplicates with different IDs.

Every article card contained only a title and short summary. All **17 missed gold
facts** occur verbatim in the full source body; none occurs verbatim in its imported
summary. This does not imply every summary lost all meaning, but several lost the
specific entities needed for retrieval. For example:

| Missed source | Needed detail absent from its summary |
| --- | --- |
| Top 25 MLB offseason trade candidates | Juan Soto and his batting statistics |
| Canada vs Jamaica, Nations League | Lucas Cavallini's injury withdrawal |
| NFL Fantasy Football Week 5 lineup decisions | Kirk Cousins' 13 fantasy points |
| MLB Winter Meetings tracker | Jung Hoo Lee's 2022 statistics |

[`missed-original.json`](missed-original.json) records all 17 source/query pairs,
their summaries, gold facts and placement counts. No original labels were removed.
Question 209 has a suspicious third gold source: an MLB sportsbook weather-refund
fact for a question about changes in betting lines. It remains in every denominator.

## Controlled stages

| Representation / stage | Original 20 questions, 37 gold source URLs |
| --- | ---: |
| Historical placement/summary import, final results | 20/37 (54.05%) |
| One article per URL, same summaries and 7/12 quotas, diagnostic rank replay | 27/37 (72.97%) |
| Canonical complete bodies, passage retrieval, 64/64 quotas, raw candidates | 37/37 (100%) |
| Same complete bodies, one whole question per query, final ten | 36/37 (97.30%) |

Canonical import retains the **same 363 category distractors** and nine bootstrap
nodes, alongside 211 article objects. It supplies title, source, publication date
and complete body; it never adds gold facts or answers to the graph.

The next **40 distinct query/gold groups**, excluded from the old Jev pilot and the
initial twenty, contain **86 gold URLs**. With frozen 64/64 candidates the actual
Core results retain **86/86 raw candidates**, but only **75/86 (87.21%)** reach the
final ten when an entire compound question occupies one query. These forty are now
diagnostic data, not an untouched final acceptance set. Later query-formulation
validation uses two further disjoint groups of forty, described below.

With Jev enabled, all **123/123** raw gold URLs across the sixty questions survive
filtering, without warnings. Final results are 36/37 and 74/86 in its independently
built index. The one-source difference from the disabled run is not a raw-candidate
filtering loss. A separate alternating off/off/on/off check on the **same** warmed
index produces identical channel ranks and returned IDs; see `paired-stability.json`.
These separate-index top-ten numbers do not justify a general 99% end-to-end claim.

Remaining misses are top-ten competition between different requested subjects.
Examples include a Manchester United ownership/comparison question, and a question
comparing two different injured NFL players. Expanding the candidate pool alone
does not solve this. The public search guidance now explicitly requests a separate
focused query for each object/event in a single batch, preserving useful names,
source and date constraints. Each focus gets its own ten-object budget.

## Implemented fixes

- Configurable 64 BM25 / 64 vector candidates replace the premature 7/12 cutoff.
- Long descriptions are indexed as overlapping 768-token passages with 128-token
  overlap. Each channel collapses passage hits to the best score per graph ID
  **before** applying its candidate quota. Passages never become graph objects.
- Small indexes use exact FLAT vector search; larger indexes use HNSW with a larger
  exploration window. Equal passage scores sort by graph ID before rank fusion.
- Lexical and vector records/indexes are separate inside one content generation.
  Writing vectors into the same HASH records changed BM25 ranks on the identical
  corpus: a diagnostic first/second pass changed all sixty lexical rankings while
  vector rankings stayed unchanged. Vector preparation now leaves lexical documents
  and statistics untouched. Real Redis regressions check scores before/after vector
  population and recovery of a lost vector index.
- Jev packs at most 128 objects and also respects a conservative context estimate.
  Large full-text packets previously returned HTTP 400; count-only batching was
  insufficient for the documented per-question context limit. Cards remain intact,
  concurrency stays at two and failures still retain the original candidates.
- Tool and model instructions explicitly separate subjects in compound questions.

Jev remains `jev-1.13.0` with threshold **0.05**. Its threshold was not tuned on these
queries. See [Typesafe's context limits](https://docs.typesafe.ai/models#context-length)
and [Redis's vector algorithm definitions](https://redis.io/docs/latest/develop/ai/search-and-query/vectors/).

## Focused-query model checks

`plan_queries.py` gives the configured model only question text and the production
query guidance. Source articles, expected answers and gold identities are excluded.
It freezes query arrays before `validate.py --plans ...` measures actual Core search.
The first 100-question run used the initial per-subject guidance. Its formerly
untouched forty-question group returned **84/87 (96.55%)** gold sources both with
and without Jev; every gold source reached the raw candidate pool and survived Jev.

Inspection showed that the model still combined several independently checkable
conditions about one unknown entity into one query. The current guidance adds a
generic device example for this case and excludes topics mentioned only negatively.
The v3 check uses **40 new query/gold groups**, disjoint from the earlier 100 and the
old Jev pilot. Settings and prompt were fixed before this fresh check; they were not
retuned on its misses. Documents are shared, so this is not a document holdout.

| Model-generated queries, one search round per question | Questions | Raw gold | Gold after Jev | Final gold |
| --- | ---: | ---: | ---: | ---: |
| v1 initial development, Jev off | 20 | 37/37 | — | 37/37 |
| v1 diagnostic, Jev off | 40 | 86/86 | — | 81/86 |
| v1 held-out validation, Jev off / on | 40 | 87/87 | 87/87 | 84/87 in each run |
| v3 development, Jev off | 20 | 37/37 | — | 37/37 |
| v3 diagnostic, Jev off | 40 | 86/86 | — | 83/86 |
| v3 fresh validation, Jev off | 40 | 82/82 | — | 78/82 |
| v3 fresh validation, Jev on | 40 | 82/82 | 82/82 | 79/82 |

The fresh forty produce 80 query entries. Both runs return 640 object cards and 620
article-URL results summed across questions. Gold-URL precision is 12.58% off and
12.74% on; gold labels are not exhaustive relevance judgments. Jev emits no warnings,
with **100% measured retention of relevant raw candidates** at unchanged threshold
0.05. Its relevance-to-any-query rule can retain a candidate for one focus which then
competes in another focus. Different final counts are not evidence of raw gold loss.
These samples do not establish a universal 99% retention guarantee.

`focused-v1.json` and `focused-v3.json` preserve prompt inputs, manifests, settings,
per-question query arrays, final URLs, raw/retained gold hits and all misses. Rate
limits interrupted some individual planning calls; the resume path preserved successful
plans and completed the rest in bulk. No hand-crafted gold-aware queries replace the model.

## Adaptive multi-hop checks

A precomputed array can cover several subjects but cannot use facts unavailable in
the initial question. Production guidance now tells the owning model to find an anchor,
inspect evidence and make dependent follow-up searches or graph reads. Independent
needs within each hop remain batched. Core remains a retrieval service; it does not
introduce a nested model planner. Search completion only reports channel completion,
not exhaustive knowledge or proof of absence.

The component scenario exercises actual Core reads across three linked objects, plus
budgets and unseen-citation rejection. The opt-in native model scenario passed: only
the first anchor's name appears in the question, while two opaque identifiers must
be discovered through tool results before reading the 17-day retention answer.
Scripted checks establish mechanics; this live scenario establishes that the native
tool dialogue can follow dependencies on a small controlled graph. The actual question,
reads and answer are retained in `synthetic-multi-hop.json`.

`adaptive.py` evaluates actual native-tool dialogues against the same full-text
sports graph. Search and describe results are unmodified Core results. Each question
has at most three searches, six total query entries and four describes; stopping never
uses labels. Gold sources and answers remain outside model input. It records first-search
source coverage, cumulative coverage, cited-source coverage, unresolved parts and actual
reads. Coverage is separate from whether the answer correctly synthesizes the evidence.
The corpus dialogue run awaits separate permission to expose actual article cards to
Codex; prior question-only planning permission did not cover that payload.

## Warm-index latency

`latency.py` compares four unchanged questions from the original twenty on one
prewarmed corrected index. Document preparation is excluded; every query-embedding
request goes to OpenAI without local query caching. Each mode runs twice, reversing
sequential/batch order in the second repeat. No answer-model call is part of this test.

| Mode | Four sequential calls | One four-query batch |
| --- | ---: | ---: |
| Jev disabled | 1.98 s / 1.38 s | 0.49 s / 0.47 s |
| Jev enabled | 15.35 s / 13.89 s | 7.23 s / 6.99 s |

All calls completed without warnings. `warm-latency.json` records actual timings,
query indices and settings. This is a small latency sample, not an SLA. Batch Jev
judges relevance to any query, so it need not select the same IDs as singleton Jev.
Planning time, cold index preparation and adaptive follow-up time remain separate.

## Evidence and verification

`full-text-unfocused-off.json` and `full-text-unfocused-jev.json` contain actual Core
results, settings, source hashes and per-query raw/retained/returned URL sets.
`summary-ablation.json` preserves the earlier canonical-summary diagnostic. The original
54.05% experiment remains unchanged in `../search-batch-jev/`.

`diagnose.py` saves complete channel ranks for attribution; `validate.py` exercises
SemanticSearch/Core and per-query top-ten limits. Both reuse local embedding caches.
Their times must not be compared with the original uncached embedding timings as
an API latency benchmark. Model-planning time is also separate from retrieval time.

The original retrieval implementation passed 825 fast tests, 163 integration tests
and six affected native tests. The corpus audit and structured-fact fixes add further
regressions; current verification counts are recorded in `CORPUS-AUDIT.md`.

New runs require `--dataset tmp/multihop-restored/sports-closed` (or `full`).
Historical local-label reproduction requires explicit `--historical`. The new reader
preserves all original article metadata and optionally the old category distractors.


## Restored-corpus follow-up (2026-10-22)

All 253 restored articles are now authorized and tested. Forty frozen independent
question/source groups supplied 99 gold source pairs: all 99 reached raw candidates
and all survived Jev at unchanged 0.05, without fallback. The final one-whole-question
cut returned 89/99 off and 88/99 on in separately built indexes. The unchanged saved
model query arrays on the earlier forty questions returned 87/90 with complete labels
off; this repeat is diagnostic. These are distinct samples and retrieval protocols.
The [audit report](CORPUS-AUDIT.md) and `restored-validation/` preserve the full details.
Source-assisted KnowledgeIntegration usage now reads original articles through focused
recall with optional limits; answer accuracy and remaining role errors are reported
separately from source coverage.
