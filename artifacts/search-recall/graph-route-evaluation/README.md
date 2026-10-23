# Graph routes: diagnostic protocol and iteration record

Start with the [simple report in Russian](simple_report.md) for the outcome, comparable
metrics and remaining problems. The [detailed report](RESULTS.md) remains available.

This is the already authorized twelve-article/eight-question pilot. It is a diagnostic,
not evidence of performance over the full 253-article corpus. Retrieval ranking stays
unchanged so that the graph routes can be compared separately.

The final [results and open problems](RESULTS.md) now include all twelve acquisitions,
32 matched reader sessions and eight source-based reviews. Transitions reduced displayed
material but did not demonstrate better supported answers. The chronological iteration
record below retains earlier failures and statements about what was still pending then.

## Acquisition and review

Process one article, review its actual participant identities, role bindings, conditions
and source paths, then continue to the next. Source-only assertion checklists are prepared
before inspecting generated graphs. They are manual diagnostic annotations, not an
independent statistical test set. Minor omissions may remain recorded explicitly; edge
counts never stand in for assertion coverage.

The first iteration, `tmp/knowledge-graph-routes-case-0-v1`, completed technically but failed
the intended representation. Of 68 domain assertions, 64 survived in prose, three lost
qualifications and one was omitted. None had a connected native domain representation.
Its six non-structural relations described article metadata; thirteen body Claims had no
participant links. Another Claim mistakenly promoted a delivery-boundary flag into a fact
that the original article was incomplete. See [the frozen checklist](case-0-checklist.json)
and [the audited result](case-0-audit.json) for source excerpts, IDs and hashes.

The next iteration uses a mandatory participant/predicate/value decision rule, separates
source content from processing metadata, and processes smaller structural sections. Exact
fragments are retained with original locations and independently readable surrounding
context. Semantic coverage is checked after execution, independently of technical completion.

`graph_routes.py --stage acquire --article-limit 1` acquires just the first article;
subsequent `--article-limit N --resume` invocations add one article to the same graph.
The harness requires unchanged frozen inputs and production code for automatic resume.
A changed prompt requires a new output directory. Tool exhaustion, failed sections and
pending work cannot produce a completed acquisition checkpoint. Intermediate progress
reports count invocations and writes only, never completed semantic extraction.

## Second first-article result

The second iteration completed all five sections and created shared product/service identities
with reported-offer and comparison relations. It had no Claims. The source checklist found
meaning for all 68 assertions in graph cards or fields, but 31 retained representation gaps:
several quantities remained strings, some comparison counterparts lacked participant roles,
and the general Fire TV subscription scope was bound to a single example product with the
universal qualification in prose. An uncertain exact iPad price was unnecessarily described
as approximately/possibly. This is not 100% structured coverage. See
[the row-level second-iteration audit](case-0-v2-audit.json).

The last section spent 62 model-tool calls on otherwise empty article headings. The third
iteration makes the distinction between domain assertions and document layout explicit,
requires named comparison counterparts to be node-valued roles, and keeps numerical
magnitudes separate from units. These are general representation rules; no question labels,
expected answers or article-specific templates were added to the production instruction.

## Third first-article result

The third iteration completed all five sections in 522 seconds. Empty trailing headings
correctly caused no writes. Product comparisons acquired counterpart IDs, and screen size,
storage, review share and battery duration acquired numerical values with separate units.
However, all six Audible assertions and all four MGM+ subscription assertions disappeared
from the graph, although their source text was present in the supplied section. Technical
completion therefore did not establish semantic completeness. This iteration is rejected
as the acquisition baseline; the next article has not yet been processed.

The fourth iteration reduces the section target from 1,800 to 900 characters and explicitly
requires substantive offer lines, table rows and notes to be covered even among headings.
This remains a general instruction; it does not name the missed subscriptions or supply
checklist answers to the model. The frozen checklist is unchanged. Shorter sections increase
model invocation cost; that cost must be reported alongside any coverage improvement.

## Fourth first-article result

The fourth iteration completed eight sections in 518.5 seconds. All ten previously omitted
Audible and MGM+ meanings returned. The unchanged 68-row checklist found 66 meanings
preserved in cards or fields, one weakened scope (the eleven-day combined campaign attached
to the Black Friday sale) and one omission (Quest's record-low marker). Twelve rows still
have representation limitations; this is not 66 fully structured, traversable assertions.
Alexa, the Fire TV category and credit issuers sometimes remain strings. The taxonomy is
mostly a broad Product class. See [the fourth-iteration audit](case-0-v4-audit.json).

All 65 non-structural relation instances had available exact retained sources. This mechanical
source check does not certify that the cited text entails every relation. The next article
is processed with the same frozen instruction; residual issues are recorded instead of
indefinitely optimizing this one source. No comparative reader benefit has yet been measured.

## Second-article stopping failure and repair

The next article exposed a separate protocol bug. One model invocation explicitly said
extraction was incomplete after fourteen calls, but the Program ignored its final text and
marked the section processed. Seven market-move assertions and an attributed rate outlook
were absent. Gary Glover was also incorrectly classified as an Organization. See
[the diagnostic audit](case-1-v4-audit.json). Acquisition agreement status, separate completed
and proposed funding, a joined historical shutdown sample and the shared Amazon identity
were preserved, but these successes do not erase the omitted work.

The revised Program requires `finish_section(complete, remaining)`. Missing acknowledgement
or an explicit remainder preserves writes and splits the section; an indivisible remainder
becomes an explicit gap. This does not verify semantic completeness when the model asserts
completion. The regression is first rerun on the 806-character offending section with an
explicit first-article seed, using `recheck_section.py`. That isolated run is not represented
as a resumed full pilot or an independent holdout. The instruction also clarifies recovery
from creation-candidate review. It also added a class-versus-employer warning in response
to one wrong class ID. That warning was too specific and mischaracterized the observation:
the trace shows selection of Organization's ID, not use of the employer's ID. The cause of
that selection was not established.

## Isolated completion and continuation checks

`tmp/knowledge-graph-section-v5` reran the exact offending 806 characters against the first
article's saved graph. The model reported an incomplete section; the Program split it into
two children and continued, preserving all eight previously absent assertions. Gary Glover
was now a Person with a role at Novus Capital. The model also reported duplicate WiseTech
identities, revealing that the reported repair was not yet forwarded to children.

The next revision retains `remaining_work` on split/failed units and supplies it as an
unverified previous-attempt report. `tmp/knowledge-graph-section-v6` used the actual prior
report and graph, not manually supplied answer labels. It updated fact 162 to WiseTech 149,
deleted duplicate 160 and its classification 161, and added linked healthcare-sector and
gold/miner relations. The trace verifies these operations; the model's summary alone was
not counted as proof. Statements found only in neighboring context were not promoted to
unsupported facts of the selected section. This remains a local regression, not evidence
of full-pilot answer accuracy or a completed reader comparison.

## Full second-article recheck

The second-article recheck uses `tmp/knowledge-graph-routes-v7`. Its seed is explicitly
recorded as the audited first-article snapshot from v4; the unsuccessful v4 second-article
graph was excluded. This is a documented mixed-history graph, not a claim that every article
was built by the same prompt revision. All reader variants will use the same final graph.
The seed validator checks a completed input prefix, exact source records and the frozen plan.

The full second article then took 1,084 seconds across fourteen invocations, including three
explicit incomplete decisions. All eight previous omissions were restored. Of seventy
checklist rows, sixty-five meanings were preserved in cards or fields, four had weakened
scope/participant roles, and one had an ambiguous index-weight interpretation. See
[the full row audit](case-1-v7-audit.json). Nine rows retain representation caveats; this is
not 100% correct structured extraction. All 145 non-structural relations across the two
articles had available exact sources. Source availability does not certify their meaning.

The continuation traces also exposed avoidable work: an inherited report can mention work
outside a child section and cause another incomplete decision even when that child's own
facts are represented. The workflow remains finite and completes, but this is recorded as a
latency issue rather than hidden behind the improved coverage. The third article is processed
with unchanged code and instructions before further tuning.

## Third-article transfer check

The unchanged instruction processed the third article in 805 seconds across fourteen
invocations. It reused Amazon, the FTC and their existing case as shared graph participants.
The 64-row source checklist found 62 meanings preserved in cards or fields, one partially
preserved with wrong attribution, and one preserved but contaminated by that misplaced
quotation. Specifically, an adjacent speaker's uncertainty was attached to the next speaker.
The audit records this error rather than teaching the prompt either person's identity.
Sixteen rows have representation caveats, including prose-only roles, inferred currency,
anonymous-speaker grouping and a repeated cost comparison. See [the audit](case-2-v7-audit.json).
All 214 non-structural relations in the three-article graph have available exact sources;
that does not validate the attribution or demonstrate better answers. Continue to another
article with the same instruction before considering further general changes.

## General instructions and diagnostic iteration

After the fourth article, the employer-specific warning was removed. The replacement defines
a class by its membership criterion, requires the selected object's meaning to satisfy that
criterion, and distinguishes relation participation from classification. The `prototype`
tool parameter now explains the same criterion. The historical wrong call and the limits of
its diagnosis are recorded in [the trace analysis](classification-error-analysis.json).
This is a general clarification, not evidence that the classification failure is fixed.
The affected 78 tests and the full 938-test default suite passed; lint, formatting and Program
layout passed. No new semantic-success claim follows from those mechanical checks.

The fourth article finished under the preceding instruction in 784 seconds and eleven
invocations. Its 68-row audit found 66 meanings preserved in cards or fields, one partial
omission and one conflicting field: total yardage per game was put in a rushing-only slot.
Eight rows retain representation caveats. See [the audit](case-3-v7-audit.json). Keep this
acquisition history explicit when importing the completed four-article prefix for later cases.

Production instructions must not contain pilot entity names, their expected classes, graph IDs,
checklist answers or question-specific routes. An observed failure may motivate a general rule
about identity, roles, attribution, values or completion, with a synthetic example explaining
that rule. Define a class through its membership criterion and distinguish class membership
from participation in a relation. Keep source-specific expectations in audit
artifacts, outside acquisition and reader prompts. Continuation reports are the model's own
unverified work notes, not manually injected checklist corrections.

Inspect one article at a time. Record minor unresolved issues instead of adding a special case
for each one. Rechecking an article used to revise instructions is a regression check, not an
independent generalization result. Subsequent articles test transfer before further revision;
this adaptively inspected pilot as a whole remains diagnostic, not an untouched holdout.

The next acquisition directory, `tmp/knowledge-graph-routes-v8`, explicitly imports the four
completed v7 articles and processes the fifth article under the generic membership definition.
It took 472 seconds and eight invocations. Its eleven newly classified instances fit their
class descriptions; this small case does not establish a causal improvement. Of thirty grouped
checklist rows, twenty-six meanings are preserved in cards or fields, three are partial and one
adds unsupported specificity. Missing details include a team affiliation, an explicitly named
venue and two song associations; another number was interpreted more specifically than its
source permits. An ambiguous date was also overinterpreted. See [the audit](case-4-v8-audit.json).
These observations remain evaluation failures rather than new named prompt exceptions.

The sixth article used the same v8 instruction, taking 779 seconds and fourteen invocations.
Two explicit incomplete decisions were followed by saved gross/sales/attendance facts.
The 42 grouped checklist rows include 37 meanings preserved in cards or fields, four with an
incorrect about-subject role despite retained prose, and one omitted qualifier. The attributed
remark schema was reused with an interview outlet in a role meaning the statement's subject.
This is a role-binding error; available source text does not make the stored relation correct.
Class choices remained compatible, including a film contender for an award whose title refers
to a person. See [the source audit](case-5-v8-audit.json). No source-specific rule was added.

The seventh, longer chronology took 1,343 seconds and nineteen invocations, including one
explicit incomplete decision. Of 59 grouped rows, 50 meanings survive in cards or fields,
five are partial and four have event-date, population-scope, date-context or naming concerns.
The reported five games were retained without inventing an additional named game. One game
has a useful shared event identity joining attendee, teams and venue; many other events
remain strings. Reusing a broad sales measure for a narrower report and treating an
announcement date as an event date show why prose coverage cannot certify exact graph reads.
The source itself combines old publication metadata with later body updates. See
[the chronology audit](case-6-v8-audit.json). The production instruction is unchanged.

## Completion scope and interrupted continuation

The next article exposed repeated false incomplete decisions. The model explicitly said its
current fragment was already represented, but treated inherited work present only in adjacent
context as a reason to keep splitting that fragment. The run later progressed; it was manually
interrupted for diagnosis, not classified as a permanent hang. Its partial graph, original
source and processing events were retained in the v8 acquisition directory.

The general completion contract now applies only to supplied assertions and necessary repairs
of the current section. Missing source information and work belonging to another section do
not make it incomplete. Two isolated checks of the same 112-character fragment completed in
one invocation, six calls and zero writes: 17 seconds on the saved partial graph and 14 seconds
on its earlier 1,132-node graph projection before neighboring work was added. Original memory
was retained for source access; the projection is not a complete historical DBOS replay. See
[the recorded regression](completion-scope-regression.json). This tests local workflow
behavior, not independent extraction coverage.

`define_relation` now also exposes the already supported role description, so a schema can
define the meaning, direction and scope of each role. The instruction checks a filled
assertion against the source rather than adding named exceptions. The canonical predicate-name
limit is documented in the tool schema. These changes do not establish a semantic improvement
until inspected on actual acquisitions.

`resume_acquisition.py` continues one interrupted source-only article under an explicitly
recorded new revision. It verifies the completed history prefix, the exact original article
and the latest processing event; it reuses that original reference and the saved graph.
Failed units are retried only with `--retry-failed`. It preserves earlier artifacts and writes
a new completed-prefix checkpoint only when no pending or failed work remains. This diagnostic
continuation is separate from production DBOS recovery. The v9 directory resumes seven
completed sections and nine pending/retried units of article eight from the saved v8 state.

The interrupted eighth article completed in v9 after nine continuation invocations
(525 seconds). Its original source event 4106 and full interrupted graph history were
preserved. All fourteen historical award rows retained year, player, position and team
together. All eighteen new relation schemas included role definitions. Of 34 grouped
checklist rows, 33 meanings survived in cards or fields and the trophy association was
omitted. Overlapping warning facts remain, and five canonical-name errors still occurred
before recovery. See [the audit](case-7-v9-audit.json). This is a mixed-revision continuation,
not an independently validated uniform-prompt result. Later articles use the same v9 code.

## Matched reader comparison

Reader failures and invalid citations are saved as attempted cases with `evaluation_errors`.
Resume skips these recorded attempts instead of selecting a luckier retry. Treat any nonempty
runner error list as a failed supported answer, regardless of an automated judge's verdict;
the raw answer, reads and judge judgment remain inspectable. A graph mutation or changed
production fingerprint still aborts the comparison. Source-listing lineage alone is not reading.

After acquisition is frozen, run these variants against identical questions and the same
model and allowances:

Prepare both search channels on each variant's actual cards with a fixed generic query
before starting reader timing. This query uses no questions or labels, and its results are
not exposed to the reader or accepted as citations. Record preparation time separately in
`routes-index-preparation.json`. Query-embedding/network latency during answering remains
part of observed reader time; this small pilot is not a controlled latency distribution.

| Variant | Available retrieval |
| --- | --- |
| `raw` | Full original article cards, BM25/vector search and sequential refinements |
| `graph_search` | Typed search over the acquired graph, without neighborhood expansion |
| `graph_routes` | The same graph with exact query, repeated-relation walk, taxonomy and properties |
| `graph_sources` | The same graph and routes plus exact source listing and paged source reading |

Each reader receives sixteen retrieval calls, at most eight search calls/sixteen query
entries, and 32,000 tokens of tool output. One final allowance-exhausted response may be
recorded; it cannot supply additional material. The model sees neither labels nor expected
answers. Citation validation requires that the cited graph object or source page was
actually shown. Source lineage alone is not proof of a correct answer or complete reading.
Readers cannot mutate the graph. The manifest pins model settings, source inputs, the
acquired graph and evaluator code; saved answers cannot silently resume under a changed
configuration.

`graph_routes.py --stage review --output <directory>` judges the four completed answer runs
in separate sessions that receive the original twelve articles and labels. Acquisition and
answering never receive those labels. The reviewer sees neutral A–D labels, rotated across
questions, and every actual tool result from each trace rather than only the last cached
card. Earlier rich evidence therefore remains visible even after later compact references.
Freeze answer and trace hashes before review. Changed evidence cannot silently resume a
previous review. Missing or duplicate per-read ratings are rejected, as are verdicts that
claim correctness while listing missing required parts or claim grounding while listing
unsupported claims. A null-query label remains unassessed on this subset.

Read relevance is judged at whole-result granularity: relevant, mixed, irrelevant,
administrative or uncertain. Report fully irrelevant tokens as a lower bound and include
mixed/uncertain tokens in the upper bound; record administrative overhead separately.
These are model-review bounds, not token-level human relevance labels. Inspect decisive
answer and route traces before drawing conclusions from the reviewer output.

Record source coverage, answer correctness with supporting citations, irrelevant material
read, actual query/walk traces, time and model usage. Acquisition cost is separate. Qualify
ambiguous dataset labels instead of treating automated agreement as answer accuracy. Graph
benefit is established only by a measured improvement over the variant without transitions.
No such result is claimed by the first failed acquisition or by controlled mechanism tests.

## Mechanical validation of the fourth-iteration source boundaries

On the current implementation, the default unit/component suite passed 927 tests. The
integration suite plus affected native source preparation, Program LLM and runtime tests
passed 152 tests with 25 environment-dependent skips. Running the Redis search suite
separately against the configured service passed all 25 tests. Ruff checks, formatting,
Program layout and whitespace validation passed. These checks prove tested implementation
boundaries, not the semantic completeness of model-generated graphs.

The ninth article (Kentucky guide) completed in 21 model sections, 1,655 seconds. All 48
source-only grouped checklist meanings were found in cards or fields, with seven caveats
recorded in [its audit](case-8-v9-audit.json). App platforms, loss conditions, bonus-bet
payment and hypothetical examples stayed together. Athletic programs were classified too
narrowly as basketball teams while also carrying football facts; some conference and
achievement detail remains text, limiting traversal. The checklist also overstated one
offer cap absent from the source wording. These are diagnostic grouped checks, not atomic
recall or a comparison against text retrieval. No named exception was added to the prompt.

The tenth article (Vermont guide) completed in 31 invocations, 1,601 seconds, including
one explicit incomplete decision followed by two child sections. Its 45 grouped rows
include 40 meanings preserved in cards/fields and five with conflicting qualification or
weakened owner/time/forecast scope. Ten rows retain caveats. See [the audit](case-9-v9-audit.json).
The $150/eight-$25 source conflict survives rather than being silently repaired. Two
FanDuel offers have a conflicting merged qualification, and a BetRivers-specific odds
rule lost its operator. In the latter case a fixed 500-character preceding window dropped
the operator name 510 characters back. The next revision tests bounded paragraph-aligned
context, without adding operator names or expected conditions to production instructions.
The old graph remains unchanged so that its failures are visible.

## Bounded paragraph context

Neighboring 500-character windows now extend to paragraph boundaries within a further 500
characters per side, including LF/CRLF blank lines. Synthetic tests cover several paragraph
lengths and the long-paragraph bound. On the exact previously failing source fragment, one
native regression retained sportsbook 1745 in the -200 odds fact 1762 and in the separate
stake-return fact 1763. It took 120 seconds and 41 calls. Offer identity remains implicit.
See [the regression record](boundary-context-regression.json), including the graph-projection
limits and the excluded first run with an incorrect end offset. This is one adaptively chosen
regression, not independent generalization evidence. The original ten-article graph remains
unchanged; v10 explicitly imports it and uses the revised context for articles eleven/twelve.
The 958 fast tests, 90 affected tests, eight related integration checks, two native source-preparation
checks, lint, formatting and Program layout pass after the context change.

The eleventh article (Cowboys–49ers live coverage) completed in 23 invocations, 1,384 seconds,
including three early incomplete decisions. Its audit reviews 56 live paragraphs and seven
summary units, not 63 atomic facts. See [the row audit](case-10-v10-audit.json). The shared game
links quarter scores, player stats, timed plays and separate streaming-service access terms.
Some timestamps were lost or bound to the next update; an incompletion was inferred from a
pass short of the line to gain; an unnamed actor was filled in; and one punt qualification
contradicts its description. Nearly complete technical processing does not certify extraction.
A source paragraph containing a timestamp and its continuing sentence had been split across
sections. The next revision prefers paragraphs before sentence boundaries, with fallback for
oversized paragraphs. This changes source partitioning, not the production prompt.

The paragraph-first regression kept 242 passing yards and three passing touchdowns at
10:38 in facts 1945/1946, while preserving the later four-touchdown fact 1853. It completed
in one invocation, 20 calls and 39 seconds. See [the regression record](paragraph-partition-regression.json).
Its supplied source range intentionally changed with the partitioner; this is not a same-text
comparison or independent validation. The 962 fast tests, 96 affected tests and ten native/related
integration checks pass; lint, formatting and Program layout pass. v11 explicitly imports
the eleven completed articles and processes only the final article with this source partitioner.
The paired readers will all use the identical final graph; construction remains a documented
mixed-revision diagnostic rather than a uniform-prompt holdout.

The twelfth article completed in 35 invocations and 2,272 seconds, including four declared
incomplete decisions. The [source-only audit](case-11-v11-audit.json) reviews 15 film groups
and four extra lists. All 18 checked casting pairs keep humans and fictional characters
separate. One Detour platform (Plex) is omitted; Brick has a writer credit but no director
link. Of 68 source viewing options, 67 meanings survive, including four scalar names in one
group and 63 individual platform facts. This is a specific field check, not overall factual
recall or the Jev candidate-retention metric. Some family relations remain prose; class-only
professional populations are incomplete; access-mode strings are inconsistent. All twelve
articles are now technically processed. The identical final graph is ready for the frozen
four-reader comparison, without retroactive human corrections.

A mechanical final source-path check found available retained material for all 1,116
non-structural relations, with no absent source references. Availability does not verify
the relation or the precision of its chosen fragment.

## Completed reader comparison

All 32 frozen readers finished without technical failure. The same-graph comparison showed
161,850 estimated read tokens and 94.04 seconds for text search, 126,784 and 124.20 seconds
with transitions, and 158,574 and 150.54 seconds with direct sources. No reader used `walk`
or taxonomy. Correct retrieved roles still led to an incorrect identity conclusion in three
methods on a question with a contradicted dataset label. The review also exposed inconsistent
judgment of extra claims and two malformed read-rating responses. Raw attempts, conservative
structural repairs and manual findings remain separate in the [final report](RESULTS.md).
This is a negative diagnostic for demonstrated answer-quality benefit, not evidence that
the graph cannot help other questions. No further article-specific prompt tuning followed
the answer comparison. The final default suite passes 966 tests; lint, formatting and Program
layout pass.
