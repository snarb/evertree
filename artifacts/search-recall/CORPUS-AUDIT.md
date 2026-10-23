# Corpus integrity and KnowledgeIntegration evaluation

The audit is pinned to the authors' [MultiHop-RAG repository](https://github.com/yixuantt/MultiHop-RAG)
and its linked [dataset release](https://huggingface.co/datasets/yixuantt/MultiHopRAG/tree/71ac0d0bd1f951d2d6b70311f7d2ae404e1ffa82).
The current GitHub tree contains code and links to the authors' Hugging Face data;
the data files were downloaded from that pinned release, not recrawled news pages.

## Current graph diagnostic status — 2026-10-23

The implementation now supports plural kind filters, exact graph-source reading and
resumable source sections. Class definitions use general membership criteria, without
pilot-specific identity hints. The 12-article source-only acquisition has completed under
documented successive revisions; its identical final snapshot is used for all readers.
All 32 readers and eight question reviews have finished. The
[matched comparison](graph-route-evaluation/RESULTS.md) does not demonstrate better supported
answers from transitions. Relative to text search on the same graph, transitions showed
21.7% less material but took 32.1% longer. No reader used `walk` or taxonomy. The report
separates judge errors, an ambiguous question and a contradicted original answer label.

The [iteration log and source-only audits](graph-route-evaluation/README.md) retain actual
failures, including misplaced temporal/participant scope, one missing film-platform option
and one missing director relation. Technical completion and retained source availability
do not establish complete extraction. The final mechanical source check finds retained
material for all 1,116 non-structural relations. Construction cost is recorded separately
in [the retained-work accounting](graph-route-evaluation/construction-usage-final.json).

## Findings

| Check | Result |
| --- | ---: |
| Original corpus | 609 articles, 2,556 questions |
| Original gold evidence | 6,084 fragments, all present in their linked article bodies |
| Local sports articles identical to original complete records | 211/211 |
| Local questions identical to original complete records | 502/609 |
| Questions with shortened evidence lists | 107/609 (17.57%) |
| Omitted evidence entries | 147 |
| Additional required non-sports articles | 42 |
| Restored sports-related subset | 253 articles, 609 questions, 1,410 evidence entries |
| Null queries in original / local sports subset | 301 / 0 |

No local article body was truncated relative to the original. The defect was in
category filtering of **evidence lists**, while the questions and answers remained
unchanged. A comparison or temporal question could therefore require an entertainment
or technology article which was absent from both the corpus and the local gold list.
Checking only the surviving local labels concealed this defect. Filtering also turned
104 originally multi-document questions into apparent single-source questions. Restored
questions all require two to four distinct sources: 481 use two, 95 use three and 33 use four. For example, local
question 3 compares sports streaming coverage to Polygon's entertainment report;
its second source was removed. Local question 5 lost two entertainment sources
about Taylor Swift and Travis Kelce.

`dataset-audit.json` identifies every affected question and missing URL. No labels
were manually repaired or discarded: restoration copies the authors' complete records.
All restored quoted facts are present in the corresponding bodies. Literal matching
establishes source availability, not that every original question/answer is semantically
well formed. The suspicious extra evidence in old question 209 exists in the original
and remains flagged rather than silently deleted.

## Consequences for previous metrics

The latest forty-question set has **90 original gold sources**, not 82. Eight
questions lost one source each. The earlier 78/82 and 79/82 results correspond to
**78/90 (86.67%)** and **79/90 (87.78%)** with original gold denominators. These are
denominator corrections, not new retrieval runs. The old 100% raw-candidate claims
apply only to locally surviving labels; eight original sources were impossible to
retrieve from the 211-article corpus. `legacy-metric-audit.json` preserves corrections
for every saved focused-query group. Prior runs remain unchanged as historical evidence.

## Reproduction and restored copies

```sh
PYTHONPATH=. uv run python artifacts/search-recall/audit.py \
  --local /Users/pavlo_konovalov/repos/semgraph \
  --original tmp/multihop-original --output tmp/multihop-restored
```

The original download manifest with pinned revision, SHA-256 and byte counts is in
`dataset-audit.json`. The audit writes `tmp/multihop-restored/full/` and
`tmp/multihop-restored/sports-closed/`, each with separate `articles.json`,
`questions.json` and a fingerprinted manifest. It never changes the semgraph checkout.
Full article records preserve title, author, source, date, category, URL and body;
source ingestion never includes answer labels or gold facts. `read_dataset` refuses
modified files, broken source joins and missing quoted facts before a paid evaluation.

## KnowledgeIntegration pilot

The following sections retain the earlier pilot and its limitations. The current graph-route
iteration has a separate [acquisition and evaluation log](graph-route-evaluation/README.md):
source-only assertion audits, explicit completion/recovery checks and the planned four-way
reader comparison. It uses typed search, exact graph transitions and `graph.sources` /
`read_source`. Its inspected acquisitions remain diagnostic and include recorded instruction
history; source availability and added relations do not establish better answers. Comparative
reader results are recorded in the [current comparison](graph-route-evaluation/RESULTS.md).

`integrated.py --stage prepare` freezes twelve articles: eight source-selected reports
for three diagnostic questions, plus four fixed distractors. It selects three further
questions with different gold-source groups covered by those reports, and two original
null queries as easy out-of-topic abstention controls. These eight cases are a diagnostic
pilot with shared documents, not an independent full-corpus acceptance sample.

Acquisition supplies each complete source and a general future-use task to the real
KnowledgeIntegration Program. No question, gold fact, expected answer or source-selection
rationale enters that dialogue. Checkpoints serialize actual graph, source traces,
beliefs, attribution and learning stores. The `--analyze` variant first records a
source-grounded analytical Note explaining entities, predicates, roles and qualifications;
it changes the input analysis and leaves KnowledgeIntegration instructions unchanged.

Usage runs fresh read-only native dialogues against either raw article cards or restored
learned graph. The strict graph-only mode can search, describe, query, walk and read properties, and cannot
open raw source memory. A separate `graph_sources` mode uses the actual production `recall`
interface and keeps graph-object and memory-event citations in separate ID namespaces.
Source-assisted results must be reported separately from graph-only results. It validates cited IDs and ensures reads
do not mutate learned stores. Source lineage is reported separately from semantic answer
correctness: provenance from an article does not prove the stored fact answers the question.

The structural check distinguishes domain relation instances from bootstrap identity and
class links, records schemas/participant roles and connected components, and inspects whether
an assertion's values, conditions and attribution survived. Counts alone cannot establish
quality. Generic associations and links among summaries are not substitutes for the source's
actual predicates. Meaning checks and answer checks must precede an optimization claim.

The calculation companion is `corpus-integrity.ipynb`; it reruns the deterministic
checks locally without contacting a model or API.

Future retrieval runners now require `--dataset` pointing at an audited restored copy.
Reproducing the old labels requires explicit `--historical`; it cannot silently be
used as an acceptance run. Optional `--source` and `--pilot` retain original category
distractors and exclude old pilot question/source groups, while gold labels always
come from the restored dataset. All original metadata stays in article cards.

## Integration diagnosis and changes

The original four completed sources produced **27 Claims, one Note and zero domain
relations**. Analysis alone on one source produced ten Claims and no domain relations.
Changing the general integration instructions alone was unreliable: one attempt timed
out after partial relation writes; its completed retry again saved seven Claims and
one Note. These attempts remain recorded, including the timeout.

Prioritizing connected facts through the existing `focus` input produced **107 domain
relations** across twelve sources, separately from 70 mandatory type/identity links.
On the first four matching sources this variant produced 47 domain relations and no
Claims/Notes, compared with the baseline's zero. A source-only comparison of retained
meaning against the articles, followed by actual KnowledgeIntegration calls, increased
the graph to **227 domain relations** and 105 mandatory links. Neither acquisition nor
the coverage analysis received questions, answers, gold evidence or QA results. This
coverage pass is an evaluation workflow; it is not an extra automatic production call.
The exact tested connected-fact priority is now the production default when callers
omit `focus`; explicit caller focus remains intact.

Retrieval had a separate concrete defect: description-free facts were indexed only
by name/description. Their participant identities, numerical values, conditions and
schemas did not reach BM25, embeddings or Jev. Many distinct assertions therefore
looked identical. Core now projects typed arguments, current participant names/kinds,
stored properties and relation schemas consistently into retrieval, Jev and result cards.
Reference IDs remain available for reads but are removed from indexed argument text;
opaque data IDs and measured numbers remain intact. Renaming a participant changes
its dependent facts' derived index generation. A real Redis regression uses 96 same-name
facts, exceeding the 64-object channel quota, and finds the final fact by its participant
and value before and after a rename.

Initial graph-only answers still lost promotional and subscription conditions.
With the supplementary graph and corrected reader, questions 4 and 81 now recover
Caesars' conditional up-to-$1,000 offer, including its unconfirmed Vermont status.
Question 19 still exposes missing subscription/availability meaning: source-only gap
analysis selected some viewing information, but integration did not retain enough of it.
The four-highlight analytical limit is selective, not a coverage guarantee. Increasing
edge counts has therefore improved useful answers but has not established exhaustive
source preservation or 99% answer recall.

The original label for question 261 is ambiguous about the unnamed individual;
question 2205 appears to conflate Swift's partner (Kelce) with Kelce's invitee (Swift).
Original records are preserved. A separate question/source-only oracle withholds labels
and answer runs; its results must not be confused with independent model acceptance.
The first answer judge also rewarded an evidence-gap abstention as a negative answer;
those initial verdicts are retained as diagnostic evidence and are not valid accuracy
scores. Revised judging explicitly distinguishes unknown from No and checks role bindings.

`knowledge-integration-pilot.json` preserves trial counts and code fingerprints. Detailed
local source snapshots and native dialogues remain in the corresponding
`tmp/knowledge-integration-corpus-*` directories. The corrected reader uses a frozen
acquisition and records its hash separately from the reader hash; evaluating changed
code requires explicit `--acquisition-revision`, rather than silently relabelling a run.

A fresh ordinary production call with no explicit `focus` on the first pilot article
completed with **16 domain relations**, ten mandatory links, ten instances and no
Claims/Notes. This verifies the default path with actual native tools; it is one
article, not a twelve-article replication. A separate semantic review found all sixteen
relations source-supported; it flagged one promotion code kept in description/extras
rather than its structured eligibility field, missing other offers, and implicit rather
than structured temporal bounds. These remain representation-quality limitations.

The separate label-blind oracle still answered Yes to question 2205 despite listing
partner=Kelce and invitee=Swift in its own role bindings. Revised judging also rewarded
question 261's unresolved required characterization. These contradictions demonstrate
that the automatic judges are insufficient for a trustworthy aggregate accuracy score.
Compact actual answers, both judging attempts, the oracle and manual flags are preserved
in `knowledge-integration-evaluation/`. Nothing is silently repaired to match a label.

## Restored-corpus validation — 2026-10-22

The user authorized all 253 articles and selected graph + retained sources as the usage
contract. `restored-validation-plan.json` froze forty further question/source groups,
excluding 148 observed questions and their complete original source groups. It contains
99 gold question/source pairs. Its earlier prepared/pending status is historical; the
runs below completed under the new authorization. Selection, original source hashes,
exclusions, settings, actual queries and returned URLs are preserved in
`restored-validation/`.

| Run | Raw gold sources | After Jev | Final source recall | Gold-URL precision proxy |
| --- | ---: | ---: | ---: | ---: |
| Independent 40, whole question per query, Jev off | 99/99 | 99/99 | 89/99 (89.90%) | 89/400 (22.25%) |
| Same questions, Jev 0.05 | 99/99 | 99/99 | 88/99 (88.89%) | 88/400 (22.00%) |
| Prior 40, unchanged model-generated query arrays, Jev off | 90/90 | 90/90 | 87/90 (96.67%) | 87/647 (13.45%) |
| Same prior 40, Jev 0.05 | 90/90 | 90/90 | 87/90 (96.67%) | 87/653 (13.32%) |

The independent sample meets the ≥99% **measured relevant-candidate retention** target
at the preselected threshold 0.05: all 99 survive, without timeouts, warnings or fallback.
The threshold was not tuned on this sample. Forty cases do not establish a population-wide
99% guarantee. Jev now explicitly judges all supplied card fields, including typed roles,
values and conditions; its old instruction mentioned only names and descriptions.

The final top-ten cut still loses sources when several needs share a whole-question
query. These are one-round retrieval results, not adaptive answer recall. Prior frozen
query arrays are a repeat diagnostic, not another independent validation; query/source
matching uses original question text rather than assuming old local indices still match.
All runs use 253 source cards plus bootstrap, with zero category-tree distractors. The
first independent runner's generic representation sentence incorrectly mentioned retained
category distractors; its explicit `category_distractors=0` and node count are authoritative.
The sentence is fixed for subsequent runs. Source-URL gold lists are not exhaustive relevance
labels, so their precision proxy cannot measure all partially useful candidates.

Off/on runs rebuild separate indexes; the one-source final difference is not evidence
that Jev removed a gold candidate. All 99/99 gold candidates survived its actual filtering.
A paired same-index test is required to isolate ranking or filter effects; the earlier
paired stability experiment is retained separately.

## Graph with retained sources

The first eight-case source-assisted run used the actual production recall API and read
original articles, but its combined ten-result memory request overloaded the comparison:
question 19 incorrectly said the game report contained no subscription terms, although
those terms are literally present. Source availability alone did not ensure correct reading.

`recall` now accepts an optional **limit from one through ten**, default ten. Instructions
request one source/title and one required clause at a time with a small limit, and explicit
verification of original passages. Source-assisted evaluation uses an exec invocation,
matching the current consciousness tool declaration, exposes only graph reads and recall,
and verifies graph, belief, attribution, evaluation and learning stores remain unchanged.
Graph and memory citation IDs retain separate namespaces.

A new eight-case run with this reading policy correctly cites Peacock/NBCSports requiring
a subscription, Fubo's free trial, and Polygon's free-with-ads/library-card options for
question 19. It also reads both original timelines for question 25 and preserves the
conditional/promotional scope for questions 4 and 81. Both original null-query controls
still abstain. Questions 261 and 2205 remain semantic/role caveats: the reader still conflates
privacy attribution or participants, and the original 2205 Yes label itself appears inconsistent
with literal role binding. These are not claimed as correct merely because a label or judge
agrees. The pilot has shared sources and observed cases; no independent overall answer-accuracy
percentage is reported. Compact source-assisted answers and version receipts are preserved
as `knowledge-integration-evaluation/sources-v2-*` and `sources-v3-*`.

Current verification: **842 fast tests**, **29 related Redis/DBOS integration tests**,
and the affected native Program tool test pass. The preceding complete integration run
passed 164 tests and seven affected native tests; this follow-up changes recall
selection/guidance, Jev card guidance and audit runners. Ruff lint, formatting and Program
layout validation pass.

## Warm-index latency on the restored corpus

Four unchanged questions ran sequentially and as one batch against the same warm
253-article index. Document preparation was excluded; query embeddings called OpenAI
without local cache. Two repeats reversed ordering. No other Jev experiment ran
concurrently. Every search completed without warnings or fail-open fallback.

| Mode | Four sequential calls (two repeats) | One batch (two repeats) |
| --- | ---: | ---: |
| Jev off | 1.435 s / 1.417 s | 0.483 s / 0.497 s |
| Jev 0.05 | 15.577 s / 15.643 s | 7.841 s / 8.375 s |

This is a small latency sample, not an SLA. It excludes planning and answer synthesis.
Batch Jev relevance is to any supplied query, so sequential and batched filtering need
not return identical candidate sets. Exact times, input hashes and settings are saved
in `restored-validation/warm-latency-*`.

## What a missing final result means

The 99 denominator counts **question/gold-source pairs**, not 99 distinct documents
or 99 independently verified necessary sources. For independent off, ten pairs across
eight questions were absent from the returned top-ten sets, although each was in that
question's raw and retained candidate sets. On, eleven pairs across nine questions were
absent. The tests issue one search round; they do not test answer correctness or adaptive
recovery. No article was deleted, no embedding lost, and Jev retained these candidates.

A cache-only replay (`explain_misses.py`) rebuilt a private Redis index and captured
actual lexical, vector and fused positions. External embedding calls were forbidden;
all channels completed. The resulting ranks are diagnostic replays, not recovered historical
ranks. `restored-validation/miss-rank-replay.json` retains per-query top-ten competitors,
missing-source ranks, relevant gold snippets and whether each original miss recurs.

For the three off-mode misses in the frozen query-array sample:

| Case | Relevant subquery | BM25 rank | Vector rank | Fused rank |
| --- | --- | ---: | ---: | ---: |
| 17 | 49ers offence despite McCaffrey not scoring | 2 | 28 | 11 |
| 275 | Oddsmakers changing lines with new information | 6 | 28 | 17 |
| 155 | Sportsbooks and four conditions in one phrase | 11 | 16 | 15 |

The first two plans already contain two separate queries: decomposition alone did not
prevent loss. Rank fusion demotes a strong lexical match when its semantic rank is lower,
while more generally related objects score well in both channels. The last plan still
puts four independent conditions in one query. Jev is a permissive filter and deliberately
does not rerank; retaining a useful object does not promote it into the final ten.
This identifies final selection/fusion as a concrete problem, beyond candidate retrieval.
Increasing the candidate pool alone cannot fix these ranks at an unchanged top-ten cut.

Gold necessity also needs adjudication: case 407 compares October CBS and December
Independent reporting about the Swift/Kelce relationship, but its original gold list
also includes a Fox article whose quoted fact is Swift commenting on a viral CD-opening
video. That extra fact does not establish the requested comparison. It remains in all
original-label denominators, but should not automatically be described as a necessary
missing proof. Original labels are preserved; no favourable corrected score is substituted.
