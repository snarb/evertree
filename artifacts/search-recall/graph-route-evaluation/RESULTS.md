# Graph retrieval diagnostic — 2026-10-23

For a self-contained explanation in Russian, including what the 21.7% reduction does
and does not mean, see [the simple report](simple_report.md).

The implementation works mechanically, but this pilot does **not demonstrate improved
answer quality from graph traversal**. Exact queries reduced displayed material while
increasing answer time. Reading retained sources verified passages, but did not eliminate
incorrect participant reasoning. No reader used `walk` or taxonomy traversal.

## What changed

KnowledgeIntegration now aims to preserve nearly every distinct source assertion through
shared identities, named relation roles, scalar values and explicit conditions. It excludes
unsupported co-occurrence links, inverse duplicates and invented transitive facts. Claims
and Notes remain available where their meaning requires them. Compaction is not promised
as automatic repair for bad relations.

The class instruction defines a category by what qualifies an object as a member. Selecting
a Prototype asserts that the object satisfies its definition; every subclass member must
also satisfy its parent's definition. Relation participation has separate named roles.
The employer-specific warning was removed: the original trace establishes a wrong
Organization ID, without establishing the model's reason. No article identities, expected
answers or named classification exceptions enter the production instruction.

Search accepts batched `queries`, optional plural `kinds` and a per-query limit. Kind
filtering precedes channel quotas. Exact graph queries, repeated-relation `walk`, taxonomy
paths, `graph.sources` and paged `read_source` bypass another text-ranking competition.
Filtered absence does not authorize creation as if the whole graph had been searched.
The hybrid control remains unchanged during this graph comparison; Jev is disabled here.

Source processing retains the original, exact fragments and separately readable context.
It prefers paragraph boundaries, processes fresh model sessions sequentially, and retains
unfinished work. `finish_section` distinguishes a completion receipt from ordinary final
text. Failures, call limits, budget exhaustion and recovery preserve writes and remainders.
A receipt still cannot prove that the model extracted every assertion.

## What actually ran

Twelve authorized public articles were processed one at a time, with source-only assertion
checklists and inspections between cases. The final snapshot contains 2,606 active nodes
and 1,116 non-structural relations. All 1,116 have available retained material. Availability
does not establish entailment or a precise fragment choice.

This is a documented mixed-revision diagnostic. Earlier accepted prefixes remain unchanged;
isolated source-boundary regressions were not substituted into the final graph. It is not
a uniform-prompt independent holdout, or a KnowledgeIntegration evaluation over 253 articles.

Each of eight questions ran once in four fresh reader sessions using `gpt-6-luna/high`:
raw article cards; text search over the learned graph; graph search plus transitions; and
transitions plus exact source reading. The three graph methods received the identical final
snapshot. All had the same limits: 16 read calls, eight searches, 16 query entries, 32,000
estimated output tokens and 300 seconds. Both search channels were prepared before timing.
The raw control uses twelve generic `Article N` Prototype cards containing original titles,
metadata and bodies; the learned graph uses its own representation. The comparison between
the three graph methods avoids that raw-versus-learned representation difference.

All 32 readers finished without technical failure or invalid citations. There were still
recoverable tool errors, empty selections and exhausted reading allowances. Those remain
in the traces; successful termination does not turn them into useful reads.

## Measurements

| Reader | Estimated material shown | Answer-session seconds, sum | Reported input tokens | Cached input subset |
| --- | ---: | ---: | ---: | ---: |
| Original article search | 144,591 | 78.22 | 452,827 | 266,752 |
| Graph text search | 161,850 | 94.04 | 452,650 | 243,584 |
| Graph transitions | 126,784 | 124.20 | 794,992 | 589,440 |
| Transitions + sources | 158,574 | 150.54 | 1,343,515 | 1,085,952 |

Compared with text search on the **same graph**, transitions showed 21.7% less material
but took 32.1% longer. On the six in-topic questions alone, the differences were 30.6%
less material and 35.7% longer. These are single diagnostic runs, not latency distributions.
Displayed tokens do not equal total model input: later turns resend earlier context.

The transition reader made 19 `query` calls: 13 nonempty, two empty and four contract
errors. The source reader made seven: four nonempty, one empty and two contract errors.
Some decisive facts were already present in the initial search cards, so a subsequent exact
query is verification, not proof of rescued retrieval. No clean autonomous answer rescued
solely from below the text top-ten limit was established. Controlled route tests are separate.

The source reader made 18 successful `read_source` calls. Actual passages came from articles
matching 12 of 14 gold question/article pairs across the six in-topic questions. Another
report can state the same fact; a gold article not opened is not a missing candidate.
Neither opening a fragment nor its article lineage proves that it supports the answer.

## Answer quality and evaluation limits

A neutral, rotated-label model review checked original articles and each reader's actual
reads. Its mechanically accepted supported-answer counts were 3/6 for original articles,
5/6 for graph text search, 4/6 for transitions and 4/6 for transitions plus sources.
All methods also abstained on both out-of-topic controls. **These are judge counts, not
calibrated accuracy:** the [manual inspection](reader-manual-audit.json) records these limits:

- On the streaming question, the judge applies inconsistent strictness to equivalent
  unsupported subscription qualifiers in three methods. A fair strict rubric must treat
  all three additions equally.
- The privacy question is ambiguous about a former private couple versus a new public
  relationship. Qualified answers cannot be assessed reliably by bare agreement with `No`.
  The source-assisted answer also reverses who attended whose concert in its evidence.
- Another dataset label says `Yes` although the literal question equates two different
  participants: Swift's partner is Kelce; Kelce's invitee is Swift. Only graph text search
  keeps them distinct in the final answer. The other readers had the correct role facts
  available and still answered incorrectly. This is composition failure after retrieval.
- The two null questions are easy subset controls; their labels remain unassessed for the
  full corpus. Abstention here does not prove global absence.

Two question reviews required explicit structural postprocessing. On the first affected
question the judge invented a read index; one retry contradicted its own unsupported-claim
list. Both attempts survive, and the first was retained without selecting a favorable
verdict. On the other question a missing read rating became `uncertain`. Nonexistent reads
are discarded, unknown ratings widen the upper bound, and positive verdicts with reported
gaps can only be downgraded. No semantic relevance label was invented. See
[failures](reviewer-failures.json), [retained judgments](reader-judgments.json) and
[the conservative repair utility](../repair_route_review.py).

The judge's whole-result irrelevant-token bounds were 59,491–120,117 for original articles,
55,368–161,850 for graph text search, 65,788–103,224 for transitions and 57,112–107,512 with
sources. Mixed results contain both useful and unrelated text; these broad overlapping
intervals are not span-level precision and establish no reliable relevance improvement.

## Remaining problems

Article audits retain incorrect attribution, temporal scope, role values and omissions.
Examples include merged offer conditions, misbound live-update timestamps, one omitted
film-viewing platform and one absent director link. Some joinable participants remain
strings; introducing a narrower profession later does not retroactively classify all earlier
instances. Class-only population queries therefore need care.

Readers sometimes select undeclared slots, use a source article as a participant in a
relation without that role, or pass a list to a scalar binding. Correct graph facts also
need correct final role reasoning. `walk` and taxonomy have controlled mechanical coverage
but no observed reader benefit in this pilot. These failures do not justify adding named
article exceptions to production prompts.

## Cost, validation and evidence

Retained construction took at least 13,966 reported seconds (about 3.88 hours), with 4,690
top-level model tool calls, 222,487,478 reported input tokens, 211,352,960 cached input tokens
and 787,737 output tokens. This counts repeated context, not distinct source text. It
excludes embeddings, discarded iterations, isolated regressions and reader/reviewer cost;
interrupted active work may add time. [Construction accounting](construction-usage-final.json)
and [review cost](reviewer-usage.json) remain separate. The latter includes the unused retry.

Final default suite: **966 passed**. Affected evaluation checks: **21 passed**. Ruff,
formatting and Program layout pass. Related native/source/recovery checks passed after the
last production partition change (10 tests); the earlier integration/affected native run
passed 152 with 25 environment skips, and the configured Redis suite separately passed all
25. The later changes affect analysis accounting and tests, not production native boundaries.

Full native traces and checkpoints remain under `tmp/knowledge-graph-routes-v11`.
[Measurements](reader-measurements.json), [comparison](reader-comparison.json),
[manual audit](reader-manual-audit.json) and [iteration record](README.md) preserve hashes,
methods and limitations. Existing unrelated working changes and original dataset records
were preserved. No commit was created.
