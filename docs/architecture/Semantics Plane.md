---
status: draft
target_version: next
---

## Introduction
#topic_core

**Subsystem question:** “What kind of thing is this?”

The Semantics subsystem describes **static meaning**: concepts and facts about the relationships among them.

**Relationships are the tool of semantics.** They are represented as **hyperedges** (n-ary relations). Different hyperedge types are defined by **relation types** (`RelationType`). An instance of a relation is an **Instance** of that relation with its arguments filled in.

- **Axes:**
  - _Abstraction Ladder:_ genus–species (`SUBTYPE_OF`).
  - _Mereology:_ part–whole (`PART_WHOLE`).

**Key operations:**

1. **Generalization (Ascend):** move up the abstraction ladder (find a supertype).
2. **Detailing (Descend):** move down to instances or parts.
3. **Composition:** assemble a system from parts.

---

## Consciousness Interface

Consciousness uses compact semantic tools; separate Programs handle retrieval and integration of experience. Consciousness and reasoning Programs express insights, emphasis and what matters in their analytical text. Integration preserves distinct source assertions and organizes their shared participants and qualifications without requiring their authors to design graph mutations. Technical processing status tracks unfinished sections separately from semantic completeness. Names are the default address; integer IDs remain available. Ambiguous names return candidates.

| Tool | Purpose |
| --- | --- |
| `graph.search(queries, kinds?, limit=10)` | Find existing objects by name, ID, or indexed stored meaning; optionally restrict to a union of kinds before retrieval quotas. |
| `graph.describe(subject, focus?, at?)` | Describe an object with previews of 7 properties and 7 relations; `focus="properties"` or `focus="relations"` returns the corresponding full list. |
| `graph.read_property(subject, property, at?, parameters?)` | Read a property through Attribution Runtime, preserving uncertainty and sources. |
| `graph.query(relation?, subject?, bindings?, where?, select?, result?, fields?, at?, max_items?, next_page?)` | Match recorded facts by named slots; return projections, unique nodes, counts or existence. |
| `graph.walk(start, relation, from_slot, to_slot, max_depth?, where?, result?, fields?, at?, max_items?, next_page?)` | Follow one relation's node roles breadth-first, preserving full supporting facts. |
| `graph.sources(subjects?, max_items?, next_page?)` | Inventory exact retained sources of selected object/fact IDs across their recorded change history. |
| `read_source(reference?, next_page?)` | Read one exact retained fragment without ranking; continue long content without losing the remainder. |
| `graph.integrate(experience_refs, focus?)` | Integrate recorded experience and analytical results through `KnowledgeIntegration.exec`. |
| `load_tool_set(name)` | Load specialized tools for one logical invocation; see [[Cognition and Attention#Dynamic Tool Sets]]. |

Both reading tools use `subject` and world time `at` (default: now, internally `valid_at`). A description uses one instant. Property discovery and parameter requirements follow [[Attribution Plane#Property Discovery for Consciousness]]. Historical `known_at`, raw graph reads and exact declared-view `graph.view` belong to `low_level_graph_tools`. For explicit graph editing, consciousness loads `graph_write_tools`: the same creation (including Claim), relation, Note, update and delete operations used by integration. Their handlers and Core validation are shared. New analytical sources must first be recorded through `record_analysis`. Public raw `graph.apply` is not exposed.

Prototype descriptions include `parent`, a single card or explicit null when no
parent is recorded. Core enforces at most one `SUBTYPE_OF` parent. This structural read is independent of the bounded relation preview,
so many instance links cannot hide an existing parent or force a redundant search.
Alongside `parent`, `children` lists up to 7 immediate `SUBTYPE_OF` child names, as strings
without descriptions. If there are more, `children_total` precedes the list. A leaf returns
`children: []`. This structural preview stays limited to 7 even with relation/text focus;
`focus="properties"` omits it along with the other structural reads. Use `query` or `walk`
to retrieve more children.

Without focus, `describe` returns at most 7 properties and 7 relations. When a list is shortened,
its `properties_total` or `relations_total` appears before the list and reports the full count.
Complete lists omit these count fields. `focus="properties"` returns all properties without
relations; `focus="relations"` returns all relations without properties. Other focus text filters
both lists, returning all matching properties and up to 7 matching relations, with the filtered
relation count when shortened. Focused lists have no token paging; use `query` for bounded relation
pages when the neighborhood is large. Property discovery never invokes computation.

### Retrieval Contract

1. **Validate the batch:** `queries` is a nonempty array of nonblank text or positive integer IDs. Normalize Unicode, case and whitespace to remove duplicate text queries, retaining the first spelling; numeric names remain distinct from integer IDs. `limit` is a per-query ceiling of 1–10.
2. **Exact first:** resolve every ID or normalized name in GraphStore, respecting `kinds`. Omitted/null means all kinds; a supplied nonempty list is normalized, deduplicated and validated, with OR semantics. Unfiltered canonical names take precedence over same-named facts; explicit kinds select all matching allowed kinds. Exact queries bypass Redis, embeddings and Jev; unresolved IDs are exact empty results.
3. **Parallel retrieval:** one BM25 batch and one vector batch return up to 64 distinct objects each per unresolved query, configured by `[semantics.search]`. Index current names, descriptions, stored properties/conditions, relation schemas and typed fact arguments as overlapping 768-token passages with 128-token overlap. Node-valued roles expose participant names/kinds; reference IDs are excluded from indexed text so they cannot mimic measured values. Current result cards retain those IDs, roles and values for reads and Jev. Participant renames change dependent fact projections and invalidate the derived generation; collapse hits by graph ID using the best passage rank before each channel's object quota. Fetch enough passages to prevent one object's passages consuming another object's quota. Queries share index preparation, batched embeddings and Redis pipelines. Embeddings default to `text-embedding-3-large`, 3072 dimensions and retain original query text. Indexes below 10,000 passages use FLAT for exact vector neighbors; larger ones use HNSW with `EF_RUNTIME >= max(200, passage fetch count)`.
4. **Merge, filter and rank:** fuse lexical and vector ranks separately for each query with reciprocal rank fusion (constant 60). Optional Core-hosted Jev evaluates each unique non-exact candidate once for relevance to any query, including partial utility or possible identity equivalence. Keep probabilities at or above the configured threshold, preserving RRF order. Exact matches are never filtered. Failed Jev batches retain all their candidates and return warnings, without changing search completeness.
5. **Bounded union:** take up to `limit` results per query, then deduplicate by stable ID. Exact matches precede other candidates, which sort by summed RRF across queries and stable ID for ties. Each card includes contributing index channels and query indices. `queries` summaries retain each query's status, exactness, candidate total and returned IDs; cards appear only once. There is no pagination. An index failure marks only affected queries incomplete; the overall status is incomplete when any query is incomplete.

Each SemanticSearch invocation is one retrieval hop. For dependent questions, the owning model first searches an anchor, inspects actual returned facts, then uses discovered names, IDs or relations in subsequent searches, `describe`, `query` or `walk`. Batch independent needs within the current hop; later queries may depend on evidence unavailable in the original question. Track participant roles through each hop and verify that the same unknown satisfies the required predicates; connected participants are not interchangeable. Continue until all requested parts have support or retain explicit unresolved gaps. Channel completion is not exhaustive semantic coverage and cannot establish absence from an unreturned result. The Core search service does not run a nested model planner.

Use one named object or focused meaning per array entry and batch independent queries together. Comparisons involving multiple subjects need separate focused queries per object/event, retaining useful name, source and date constraints; each receives its own top-ten budget. Type and field names embedded in text are keywords, not filters. Inspect candidates with `describe`: `STATE_IDENTITY` and `IDENTITY_TYPE` navigate from a Facet to its Instance, Prototype and other Facets. A new proposed name needs its own complete search in the current model invocation. The shared write handler remembers each query's completeness and candidate presentation separately, including after recovery. Own writes do not invalidate earlier searches. An incomplete repeated search revokes the affected name's earlier confirmation. Explicit searches always execute again; similarity candidates are not proof of equivalence or existence.

`[semantics.jev]` configures `enabled=false`, `model="jev-1.13.0"`, `threshold=0.05` and `api_key_env="TYPESAFE_API_KEY"`. Thresholds must be finite numbers in [0, 1]; zero bypasses filtering. Credentials load only in trusted Core from `.env` with environment precedence. Typesafe receives queries and current graph cards in batches of at most 128, also bounded by a conservative 16,000-token estimate including question overhead; at most two HTTP calls run concurrently, each with a 10-second deadline. Cards are never truncated to fit; a single oversized card still fails open if the server rejects it. Strict Noul answer validation requires exactly the supplied IDs and finite probabilities in [0, 1]. The threshold requires independent validation of ≥99% retention of relevant raw candidates before top-ten truncation. On the restored 253-article diagnostic corpus, a frozen forty-question validation retained all 99/99 labelled relevant candidates at 0.05 without warnings; this is a sample measurement, not a universal recall guarantee.

Runtime keeps the graph unchanged throughout a SemanticSearch call, including gaps between Core operations. BM25 and vector retrieval may overlap within that call; no other Program or write may interleave. Search therefore carries no graph-revision token and has no graph-changed retry protocol. Search reviews belong to one logical model invocation, inherited by its search children; a nested integration or a new conscious turn has its own scope. Core retains its own search-completeness confirmation for the invocation; normal execution and recovery use that same confirmation, never a Program-returned status. Tool handlers replay to reconstruct candidate presentation.

Redis is a derived cache prepared on demand from the current graph. Graph commits do not schedule background indexing. The next indexed search prepares the current content fingerprint, reuses cached embeddings, and removes obsolete index versions after the preceding search has finished. Parallel channels share index preparation; failed embeddings leave lexical retrieval available with an incomplete search status. Loss of Redis data or restoration of an older agent backup rebuilds the cache from GraphStore.

Each content generation owns separate lexical and vector indexes and HASH records.
Populating embeddings never rewrites lexical documents or changes BM25 statistics.
Vector publication waits for its indexed document count; loss of either index is repaired
independently. Generation cleanup retains both current indexes and drops both obsolete ones.


When integrating a substantial source, build useful connected groups incrementally: classes,
identities, their states and assertions. Do not spend the entire call constructing an inventory
or taxonomy and leave its important relationships until last. A prose Claim represents an
independently checkable assertion, not a shortcut for bundling directly representable identities,
state intervals and relationships. Preserve source timezones; runtime location cannot fill a
missing timezone. Unknown boundaries remain unknown. Specific objects participate in their
own facts; their Prototype IDs describe classes and do not stand in for those objects.

Select search kinds by purpose: `relation_type` for schemas, `prototype` for classes,
`instance`/`facet` for participants and states, and `relation_instance`/`claim`/`note` for
assertions. Queries of the same purpose share a batch. A missing narrow result requires
widening or an unresolved gap, never a claim of global absence. Core keys search confirmation
by query, normalized filter and invocation; creation checks only the unfiltered key. Narrow
failures cannot revoke broad confirmation, and narrow successes cannot repair a broad failure.
Both Redis channels apply the kind union before their candidate quotas; each query still has
one final ten-object ceiling across its selected kinds.

### Exact Slot Reads and Walks

Integration and consciousness share the same Core selector as declared `AccessView`s.
`query` accepts any subset of slot bindings without saving a new view or writing a Program.
Native bindings are `{slot, value}` entries with unique slot names. Bindings compare complete
values; `where` uses `contains` for list membership. `subject` matches only node-valued roles,
including lists; an integer in a numeric role is not a node reference. Supply `relation` or
`subject`; slot bindings, filters and projections require a specified relation.

`where` is an AND of `{field, op, value?}` clauses using the existing predicate operators.
Fields are `args.<slot>`, `conditions.<parameter>`, `fact.id` and `fact.name`. Filtering a
recorded condition does not evaluate whether that condition currently holds in the world.
`select` names returned slots; omitted selects all arguments. `matches` (default) retains
one result per fact. `nodes` and `count_nodes` require one selected node-valued slot and
deduplicate node IDs. List slots expand into participants only for those node result modes.
`count_matches` counts facts. Counts finish in one call and report exact totals.
`exists` reports a match, not the truth of the assertion, and stops at the first applicable
match. It returns `exists`, `returned=0` and `has_more=false`, without totals or cards.

`walk` requires node-valued `from_slot` and `to_slot`. For example, `SUBTYPE_OF` from
`supertype` to `type` finds children; reversing the roles finds parents. `max_depth` defaults
to 1; explicit null requests all reachable levels. A breadth-first traversal expands each
(node, applicability) state once and excludes the origin as its own descendant. Distinct
supporting facts are retained through cycles and multiple paths. Results report minimum depth;
a later applicable path can establish applicability despite an earlier unknown path.
Walk result modes are `nodes` (default), `count_nodes` and `exists`.

Heterogeneous paths use successive exact queries or walks, each retaining the relevant named
roles. A taxonomy route walks `SUBTYPE_OF` from `supertype` to `type`, includes the starting
class, then queries `IDENTITY_TYPE` with `args.type in` those IDs and selects `instance`.
It then reads domain predicates of the discovered instances. These selections are independent
of text RRF/top-ten ranking; unconsumed pages still prevent an exhaustive-selection claim.

`graph.sources` accepts nonempty positive integer subject IDs, or a continuation. It follows
each subject's recorded changes and explicit event dependencies, not every neighboring fact or
the wider run arguments/caller context used for retention. Results deduplicate exact
`(event_ref, output_path)` references and retain bindings to subjects and change versions,
including changed fields and the latest-change marker. These are provenance bindings, not an
independent assertion of current evidential support. A rename does not hide earlier sources;
an old source is not automatically support for a corrected assertion. Entity sources refer to
that entity's changes; query its facts and select their IDs for their sources.

`read_source` resolves the chosen exact fragment, exposing a separate context reference for
surrounding material. It returns original text or deterministically serialized JSON, with
Unicode character offsets and `has_more`; offsets do not create fictional output paths.
Both operations obey the existing read-context budget and task-local pagination conventions.
Graph source selections reject changed graph revisions; continuations reject changed or
unavailable underlying events. Missing/non-addressable material is explicit. Reading does not
change retention, restore deleted experience or invoke similarity search, embeddings or Jev.

Without `at`, reads include recorded facts without temporal filtering. With `at`, outside
facts are excluded and unknown applicability remains explicit. Counts split applicable and
unknown matches when needed. Existence is null if only unknown matches exist, false if there
are no matches, and true if an applicable match exists. Declared views retain their existing
UNKNOWN/cardinality contract.

Pages start with `total`, `returned`, `has_more`; cursors stay private to Core. They contain
`items` referencing deduplicated `nodes` and `facts` collections. Fact and projection node
references are explicit `{node: id}` values, distinguishable from scalar integers. Full fact
arguments, descriptions and meaningful properties/conditions survive projection. Fact IDs
retain access to their stored history and provenance. Node cards always contain id/name/kind
and Facet boundaries; `fields` defaults to `["description"]`, with optional `properties` and
`schema`. Properties are discovered without running computations; `read_property` performs
explicit requested computation. Empty optional envelope fields are removed; domain nulls,
empty values, zero and false are not recursively stripped.

`[semantics.read]` configures `context_fraction=0.6`, `max_items=600` and a local fallback
`token_encoding="o200k_base"`. Runtime supplies the selected model's effective context window
and remaining space, reserving 10% of the window for response/framing. A page fits both the
configured context fraction and remaining space. tiktoken counts the final JSON including
metadata and support records; it does not count characters or bytes. A registered model encoding
is preferred; the configured fallback for private names is explicitly a local estimate.
The SDK does not supply an exact preflight tokenizer. Missing context metadata is an error.

The optional model-facing `max_items` only limits item count. `next_page=true` with no selection
arguments continues the latest selection of the same tool in the same task; optionally change
`max_items`. To continue an earlier interleaved selection, repeat its original filters/fields
with `next_page=true`. Core keys selections by their arguments, ignoring optional nulls, object
key order and max_items; explicit `walk.max_depth=null` remains distinct from omitted depth.
Omitted/false next_page starts fresh. A missing, exhausted or stale continuation
returns an error, never silently restarts or switches selections. Private cursors belong to a task,
operation and graph revision and expire at task release/restart or graph changes. Scans finish
synchronously inside one tool call. No scan progress or continuation is exposed to the model.
Existence checks iterate facts lazily, without first collecting all candidates, and stop at the
first applicable match. List reads establish total before serializing
cards; `next_page` retrieves only remaining result items. Walk existence checks inspect outgoing
facts directly: any reachable node requires a first hop, so no full adjacency or deeper traversal
is needed. Facts never split across pages; an oversized first item returns an explicit
error with its ID. Pagination does not automatically fetch remaining results or guarantee that
an entire conversation history fits. Count or filter large results before viewing them.

No Python execution interface or external graph representation is introduced.

### Storage and Models

GraphStore remains authoritative; **Redis 8.4+ with Search** is a rebuildable index. Graph commits do not perform index I/O; the next search prepares the current generation. Content generations include passage settings and prevent restored state from reading a newer index; obsolete unused generations are removed. Index failure cannot undo a graph commit or block exact lookup. BM25 and vector queries retain separate configurable candidate quotas; fuzzy search is omitted. Passage expansion belongs only to the disposable index: it never creates graph objects or changes their identities.

Integration uses **`gpt-6-luna / high`** through Codex SDK. Its model/effort is configurable; consciousness keeps its own profile. Redis and the separate embedding API credentials remain in core. Configuration and local/managed Redis setup are in the repository README.

### Knowledge Integration

`KnowledgeIntegration.exec` receives `experience_refs`: `TraceOutputRef`s to saved messages, materials, observations, Program results, and analytical Notes. These are **materials to examine**; the particular references supporting a materialized assertion are its **grounds**. A complete document can be an input without every saved assertion depending on that entire document. User inputs expose a stable `source_ref` in consciousness context. `focus`, when supplied, directs attention; a caller need not preselect every statement.

Programs call the same mechanism through `call_program(ctx, "knowledge_integration", {"experience_refs": ..., "focus": ...})`. Runtime supplies authoritative task specification and revision, constraints and remaining budget. Caller text cannot replace this context. In the MVP, agent personality, Values and selected Self knowledge do not guide knowledge preservation and are not supplied as integration context. Isolated evaluations use their own task context.

Integration aims to preserve nearly every distinct assertion in supplied experience, including secondary details whose future usefulness is unknown. Repeated wording with the same meaning and grounds, formatting and technical bookkeeping need no duplicate graph fact. This is a semantic coverage objective, not a machine-checked guarantee. `focus` and ordinary analytical emphasis set attention priority without excluding the remaining assertions. Notes remain appropriate for source wording or complete arguments with independent value.

For each distinct assertion, integration identifies participants, predicates, values and qualifications. Relationships and numerical observations use native identities, relation instances or properties. A missing predicate schema can be defined; it does not justify a prose fallback. Reported or uncertain assertions retain attribution and conditions; neither a relation nor a Claim independently verifies truth. Shared participants use node-valued roles so facts can join across sections. Joint predicates retain all their roles rather than losing meaning in pairwise projections. Co-occurrence, invented causality, negative facts from silence, inverse duplicates and inferred transitive shortcuts are excluded. Compaction does not supply an implemented automatic cleanup of arbitrary semantic edges.

Generalization supplements useful operational knowledge. A component and its configuration may
be needed for later diagnosis or modification even when the underlying mechanism is familiar.
Retain the owner, value and unit of such a setting; a general Concept about the mechanism does
not replace that local assertion. Coverage includes qualifiers, exceptions and explicit negative statements.

The model uses declared tools to search/read, create a concept or class, identify an instance, describe a state, define or use a relation, create a Claim, save a Note, update an object or delete objects. Each write selects its grounds. Code assigns permanent IDs and constructs mandatory identity links, schemas and the internal `GraphDelta`. Existing objects are used by ID. The model neither prepares transaction payloads nor reconstructs an execution report.

Each successful tool writes immediately. The shared `update(object, changes, sources)` changes only supplied fields; compound fields replace their previous value without an implicit deep merge. `delete(objects, sources)` removes the listed objects together from the current graph, without cascading; remaining references to a deleted object reject the operation. Deleting current knowledge does not erase its change history or source traces. Core protects identity, executable Programs, assessed evidence and other protected objects, and checks allowed fields, intervals, schemas and references.

Search is an orchestration step before creating identities, not only a prompt suggestion: a nonempty result is shown before creation proceeds; incomplete search cannot authorize creation. `search(queries)` returns a deduplicated union of at most 10 candidates per unique query with no pagination; refine individual queries when none fits. Required object/schema reads are automatic. Own writes do not require repeating an earlier complete search in the same invocation. A failed call returns its error; earlier successful writes remain saved. Core returns permanent object IDs, actual changed object cards and the graph revision.

Integration uses the shared [[Process Plane/Program Layer#Native Model Tools in Programs|`llm_with_tools` interface]] with native tools and a Program-local handler. Source partitioning is deterministic and lossless across structured fields, paragraphs and sentences, retaining original references and neighboring context. Automatic and explicit integration share the partitioner. Core records partial selections as addressable `ExperienceFragments` with exact original paths/ranges and explicit source dependencies. The model receives the selected text/data separately from boundary metadata. Preparation is journaled and repeated calls reuse the retained fragment; write authority remains tied to the original inputs and integration operation. Each section invocation has fresh search-review state and deterministic section/attempt-prefixed write keys. Calls remain sequential. Tool-limit exhaustion preserves writes and bisects the unfinished unit; indivisible failures and provider errors remain explicit rather than processed. An explicit completion decision means the model reports no known remaining work, not that every assertion was successfully represented.

KnowledgeIntegration ends each model section through `finish_section(complete, remaining)`.
An ordinary final message is not a completion receipt. A declared remainder or missing receipt
preserves writes and splits the unfinished section; an indivisible remainder is recorded as a
failed gap. Unresolved work and repairs accompany child sections and explicit retries as
unverified model reports, not source evidence. Only an explicit completion decision advances
the processed checkpoint. This is
execution bookkeeping, not an independent proof of semantic coverage.
Completion is local to the supplied section. A prior report about another section, or a fact
the source never supplies, does not make the current section unfinished. The model retains
uncertainty and reports only outstanding work grounded in the current section or required
for its assertions; it does not turn neighboring context into additional extraction scope.
Boundary context starts with 500 characters on each side and extends to a paragraph boundary
within another 500 characters, supporting blank lines with LF or CRLF. The bounded window
does not prove that every referent is present; the retained original remains available.
Text partitioning and adaptive bisection prefer paragraph boundaries before sentence or line
boundaries, keeping short paragraphs with their local timestamps and qualifications. Oversized
paragraphs still split without dropping characters, using neighboring context for continuation.

The technical result contains successful `writes` and code-generated `processing` state with completed, pending and failed units. The model supplies only its completion decision and any remaining work; code computes the execution record. The application resumes retained pending work, retries failed units only on explicit retry, and drains remaining automatic packets before completion while its task allowance permits. Budget exhaustion or interruption retains the unprocessed tail and its source dependencies. Normal DBOS replay reconstructs tool exchanges without duplicating writes; a failed packet does not authorize marking its source processed.

`save_note` copies an addressable source without regenerating its text. For a typed analytical Note or a runtime analytical-text fragment, it copies the text; other structured sources are retained as JSON. The copied source is always a ground; `sources` supplies only additional grounds and may be empty. Source references retain fragment origin, and runtime schedules remaining fragments.

`create_claim(name, description, sources)` records a separately checkable assertion when existing properties, relations or transitions do not express its meaning precisely enough. The nonempty description states the complete assertion with its conditions and uncertainty; the name labels it for retrieval. The operation uses the same search, source validation, immediate persistence and replay rules as other creations, and is available to both integration and consciousness. It does not assign confidence or create evidence.

The boundary of a Claim is independent revision: if evidence could confirm, reject or correct one
assertion while leaving another open, they need separate representations. Each candidate explanation
therefore retains its own grounds and limits. Necessary conditions and the supporting argument for
one hypothesis stay together; splitting every clause would lose meaning rather than improve it.

The model receives task requirements and source contents with usable references. Full `origin`, revisions, operation keys and other audit metadata stay in Core and trace. Source kind and non-live replay/evaluation mode remain visible because they affect how evidence is interpreted. Relation reads retain their applicability conditions; generated navigation views stay out of model context. Normal continuation uses native tool results without rebuilding a prompt containing the full action history.

| Structure | Reason to create it |
| --- | --- |
| Relation instance | A supported or explicitly uncertain assertion whose independent representation is useful for retrieval, reasoning, checking, or reuse. Inverse navigation uses views. |
| Instance | An identity that must remain recognizable between observations; another mention alone does not create another object. |
| Facet | A meaningful changing aspect of an Instance. Compatible facts about the same state share a Facet; different aspects may overlap in time. |
| Concept | An operationally useful distinction that existing concepts do not express. |
| RelationType | A required meaning and participant roles not expressed by existing schemas; different wording is insufficient. |
| Prototype | A useful class schema or a warranted generalization, linked to a justified broader class. Declaring a class does not establish its typical properties or empirical priors. |
| Claim | An independently checkable assertion lacking an adequate native representation. It may be a hypothesis, supported conclusion or refuted explanation; uncertainty alone does not require a Claim. |
| Note | Self-contained source text worth retrieving intact, such as a short historical speech or an exceptional argument. Also extract graph assertions only when they have independent value. |

A Prototype defines a reusable category and what qualifies an object as its member.
An Instance's class membership asserts that the object satisfies that category's definition.
Select the class by its meaning and check the referenced card; search for or create a suitable
class when none is known. A role identifies how an object participates in a particular relation;
record that participation with the relation's named arguments. An object's association with
another participant does not by itself establish membership in that participant's class.

Specific classes belong in a useful abstraction hierarchy: for example, Pump is a subtype of Equipment. Every member of the child class must also meet the parent class's definition. Integration searches for the nearest justified broader class and reuses it or creates it before the child. Missing graph content alone is not a reason to leave the child parentless. Ordinary definitional classification can organize source objects even when the source does not enumerate their ancestors; it does not establish empirical properties or provide additional independent evidence. Existing classes can acquire the missing `SUBTYPE_OF` relation without a duplicate class. This is an is-a classification, distinct from part-whole or usage relations; a broad root or an unjustified classification can remain parentless. Further ancestors are added for useful shared knowledge, not to exhaust a universal taxonomy.

State time is the time described by the experience, not its recording time. Facet boundaries may be unknown; unknown dates alone neither require a Note nor prevent structured state storage. Relative temporal conditions remain in the description or ordinary relations. A dated read distinguishes applicable, outside and unknown: an unknown boundary is not an infinite interval and does not establish a current state. A prior state is closed only with grounds for a transition. Bulk measurements can stay in an accessible dataset or coherent trace result linked to their object and conditions; one value need not create one graph node. Extraction preserves qualifications, counterexamples, uncertainty and dependencies between grounds and conclusions.

Task requirements, focus and emphasis in the recorded analysis guide attention and useful organization for current and future use. Evidence determines reliability. Structural validity, repeated saving and aggregation do not establish truth or increase belief; evidence assessment remains separate.

Alternative interpretations may already be represented as competing relation instances. Do not postpone a precise graph representation until one interpretation wins, or wrap it in a duplicate Claim solely because it is uncertain. A Claim is useful when the meaning itself is not yet adequately formalized. For numerical comparison, [[Uncertainty and Belief Tracking in the World Model#^def-CompetitionScope|CompetitionScope]] groups mutually exclusive, exhaustive answers to one specified question under the same conditions; its shared Profile represents their competition. Hypotheses that can coexist or answer different questions do not form such a scope merely because they are alternatives in a discussion. The write tools create semantic content and provenance; they neither automatically bind competing objects to a Scope nor assess evidence. After each integration call, runtime sequentially runs [[Uncertainty and Belief Tracking in the World Model#MVP Graph Evidence Assessment|EvidenceAssessment]] for changed and related elements.

Core exposes one checked `semantic.write` path to the admitted integration Program and consciousness's loaded `graph_write_tools`. Integration sources must belong to the supplied experience; explicit consciousness writes may use recorded sources accessible in its context. A `model` role cannot write by declaring or loading tools. Bootstrap, lifecycle and specialized Core operations retain their internal mutation paths.

One operation atomically stores graph changes, required structural links, provenance and its runtime-generated operation result. History records before/after state, recording time and the sources that led to each change; an update creates a new history entry rather than rewriting prior reasoning. Failure rolls back only that operation. Stable operation keys belong to code, not model arguments. Replay returns the original result without duplicating objects, history or provenance; recovery replays tool exchanges and handlers to continue the saved sequence. Isolated evaluations use the same bridge against isolated stores.

Runtime invokes integration between [[Cognition and Attention#Conscious Step Contract|meaningful steps]]. An explicit early invocation remains available; consciousness can also load direct graph tools when it needs precise control. Large experience is split into bounded packets with an internal checkpoint. Normal completion may create nothing. Integration errors are recorded in technical diagnostics, leave successful writes intact and do not block the next conscious step or final answer. A failed packet is not retried at every boundary; unexamined packets remain available for later invocations. User cancellation and shared budget limits still apply.

Retention follows the grounds of each successful write. A write must not pin unrelated input packets through a shared report. [[Memory|Memory's existing compaction lifecycle]] may later compress intermediate details while retaining the significant reasons for mistakes and corrections and their provenance. The direct write interface adds no permanent-retention rule or separate scheduler.

Both semantic Programs follow the normal learning and independent evaluation lifecycle; child calls run outside DBOS steps. Reflection and Consolidation use the same integration path with original sources; their conclusions are not independent observations.

## RelationType: Fact Prototype
#topic_core

(def_id:: entity.RelationType)
> [!definition]
> **`RelationType`** is a concept that defines:
> 1. **The meaning of a fact** (what it asserts and what it does not assert).
> 2. **Its signature:** which slots exist, their labels, roles/types, and cardinalities.
> 3. **Views (projections):** named “views” of the same fact (how to retrieve arguments in different directions) **without creating inverse relations or copying data**.
^def-RelationType

Each role has a specific semantic meaning within that predicate. `define_relation` accepts
an optional `description` for each role, retained in `Slot.description` and exposed through
schema reads and serialization. Supply it when the label alone does not make direction or
scope clear. Core validates structural value types; matching a type does not establish that
the value satisfies the role's meaning. Integration checks the filled assertion against the
source, including participant roles, measured quantity and qualifications.

> [!important]
> Principle: **there is one fact**. “Inverses” and “directions” are **views/projections** (queries), not separate relation instances.

`RelationType` participates in the abstraction ladder like all other types. Abstract relation categories are ordinary `Prototype` nodes without signatures. Concrete predicates have nonempty signatures; specialization stores an explicit role projection and an entailment rationale. These declarations do not enable automatic parent-fact inference. See [[Taxonomy and Relation Governance]].

Use a small set of basic relations; add domain-specific `RelationType`s under the [[Core data structures#Concept Canonicalization and Semantic Linking|shared rules for reusing and creating concepts]].

A reusable relation preserves one stable predicate across subjects. Its name and definition must
agree. Different or opposite meanings require separate predicates or an explicit distinguishing
role; generic association is insufficient when the distinction matters. An assertion's description
cannot negate or repair its relation type. Core checks structural schema conformance; choosing a
semantically faithful predicate remains the responsibility of the writer.

### Signature and Stable Labels
#topic_details

`RelationType` is always allowed to evolve, so **every slot has a stable `label`**. Compatibility and mapping use the `label`; order is secondary.

#### Slot (Inline)

```text
<label> = <ConceptSlot>  "description"     # 1
<label> = <ConceptSlot>? "description"     # 0..1
<label> = <ConceptSlot>* "description"     # 0..N
<label> = <ConceptSlot>+ "description"     # 1..N
```

- `label` is a technical key (addressing + versioning), **not a concept**.
- `value_type` is the technical storage type (`node`, `number`, `string`, etc.).
- `value_concept` references the semantic class of permitted values, such as `AutonomousAgent`.
- `role_concept` references the contextual role, such as `AgentRole`. A role and its permitted value class are distinct.
- The starter template requires both semantic references and role descriptions. Core validates reference existence and technical types; it does not prove arbitrary semantic argument membership.

**Storing arguments in a relation instance:**

`args` is a dictionary keyed by `label`. Each slot value must match the type defined by the `ConceptSlot` contract and its declared cardinality. An argument may be a `Concept`, scalar, or another typed object under the [[Core data structures#Data Typing|shared typing rules]]; a numeric value does not have to be converted into a Concept. Saving objects and links between them follows the [[Core data structures#Objects and References|shared object and reference rules]].

### Views: Projections Over One Fact
#topic_details

(def_id:: entity.View)
> [!definition]
> **View** — a named projection of relation instances: fix the **inputs** slots, optionally apply a `constraints` filter, and return **outputs** values while retaining the source fact for every result.
^def-View

`AccessView` is a declaration within `RelationType`. A shared mechanism exposes declared views as methods on `RelationType` and executes them. A new view requires only a declaration; no separate Python function or `Program` is needed. Named views serve concrete reading patterns. The integration action for a new relation supplies `get_<role>` views with the other roles as inputs and `list0` output cardinality; this provides navigation without asserting uniqueness. Further specialized views can be declared internally when needed.

#### `AccessView` Structure

(formal_id:: entity.AccessView.schema)
```python
AccessView: <InternalNode> {
  name: <string>             "stable view name, unique within RelationType",
  description?: <string>     "meaning of the projection if unclear from its name and slots",
  inputs: <string[]>         "slot labels whose values are supplied when called",
  outputs: <string[]>        "labels of returned slots; order defines tuple element order",
  output_arity: <enum>       "match cardinality: one | optional | list0 | list1",
  constraints?: <Predicate>  "pandas-friendly filter over slots and available relation-instance read fields"
}
```
^spec-AccessView

#### Shared Executor and Result

```python
PARENTAGE.get_parent(child=Bob, valid_at=None, known_at=None)
```

Inputs are passed as named arguments using slot labels; their types and cardinalities come from `RelationType.signature`. The optional service parameters `valid_at` and `known_at` are reserved names and cannot appear in `inputs`. When called, the executor checks that all declared inputs are supplied, their values conform to slot contracts, and no extra arguments are present.

At declaration time, it checks that the view name is unique, valid as a Python method name, and does not conflict with `RelationType` fields or methods. It also checks that labels exist, `inputs` and `outputs` have no duplicates, `outputs` is nonempty, and `constraints` are valid.

If the relation and view name are selected dynamically, call the same declared view using `getattr(relation_type, view_name)(**inputs)`, where `inputs` is a `label → value` dictionary.

`valid_at` and `known_at` have the [[Attribution Plane#Reading State Properties|shared meaning of world time and knowledge time]]. Without `valid_at`, no temporal filter is applied; without `known_at`, current knowledge is used. Facts, their fields, and computed beliefs are read under the same temporal bounds specified by the source contract. If required saved data are insufficient, return `unknown` before checking cardinality; an unavailable read is not replaced by an empty result.

The executor finds facts by equality on input slots, applies `constraints`, builds the projection, and checks `output_arity`. Each matching fact yields one technical record with fields:

```text
value       — the value of the only output slot, or a tuple in outputs order;
source_fact — the source RelationInstance in the version read.
```

A list-valued slot remains a list inside `value`; it is not expanded into additional matches. Different facts with the same projection remain separate results with their own `source_fact`; that alone does not imply independent evidence.

| `output_arity` | Result |
|---|---|
| `one` | Exactly one record |
| `optional` | One record or `None` |
| `list0` | A list of 0..N records |
| `list1` | A list of 1..N records |

A cardinality violation is a contract error. Slot cardinality constrains one fact record, while `output_arity` constrains the number of facts found; the latter is not inferred automatically from the former. Selection such as `latest/max_support/...` is a separate explicit operation over results, not hidden inside `one` or `optional`.

A projection does not create a new fact or evidence. `source_fact` retains source identity and provenance under the [[Core data structures#Objects and References|shared object and reference rules]]. Saved `value` records the read value under the [[Program Layer#^local-values-and-results|read-result rules]]. `BeliefData` / `Profile` is read for the source fact's target through the [[Uncertainty and Belief Tracking in the World Model#Read-Time Computation and Provenance|shared belief interface]], with the temporal bounds of the original query; the view does not store a separate belief copy.

In the notations below, arrows indicate the type of `value` while preserving the described link to `source_fact`. New values are computed, multiple queries combined, and hypotheses resolved by ordinary programs on top of views.

### `constraints`: Predicate Format
#topic_details

`constraints` is one structured predicate over slots and available relation-instance read fields. It filters the set of facts, for example retaining only biological parentage. The format supports tabular execution but does not depend on pandas; it does not include query strings, program calls, or conditions such as “another fact exists.”

(formal_id:: entity.Predicate.schema)
```python
Predicate: <InternalNode> {
  all: <Clause[]> "AND clauses"
}
Clause: <InternalNode> {
  field: <string>          "slot label or field declared by the relation-instance read contract",
  op: <enum>               "== | != | in | not_in | < | <= | > | >= | contains | is_null | not_null",
  value?: <any>            "value or list of values"
}
```
^spec-Predicate

The executor checks that a field exists and is unambiguous, the operation is allowed for its type, and `value` has the right type. `is_null/not_null` take no value; all other operations require one. An absent value in an optional slot is tested with `is_null/not_null`; other comparisons do not match it.

Available fields include slots (`parent`, `child`, `kind`, ...) and explicitly provided read fields (`t`, `window_id`, `source_id`, `rule_version`, ...). Filters on `strength/support`, if provided, use a shared computed belief read for the corresponding target, not a saved snapshot.

```python
constraints = Predicate(all=[
  Clause(field="kind", op="==", value="biological")
])
```

### Formal Entities
#topic_details

#### `<RelationType>` (Relation Type)

(formal_id:: entity.RelationType.schema)
```python
RelationType: <SemanticNode> {
  signature: <Slot[]>      "list of slots (labels + arity + meaning)",
  views?: <AccessView[]>   "named projections over the same fact"
}
```
^spec-RelationType

#### `<Slot>` (Signature Element)

> [!note]
> A Slot is a schema-internal element of `RelationType` (it does not participate in the abstraction ladder as a semantic node).

(formal_id:: entity.Slot.schema)
```python
Slot: <InternalNode> {
  label: <string>           "stable slot key (versioning contract)",
  value_type: <string>      "technical storage type",
  value_concept?: <Prototype> "semantic class of values",
  role_concept?: <Prototype>  "meaning of this contextual position",
  arity: <enum>             "one | optional | list0 | list1",
  description?: <string>    "minimal semantic contract (what it is / is not)"
}
```
^spec-Slot

### Examples
#topic_details

> [!example]
> PARENTAGE (neutral fact + views)
>
> ```python
> RelationType PARENTAGE {
>   name: "PARENTAGE"
>   description: "Parentage fact: parent is a parent of child. It does not include mentorship, teaching, or guardianship unless represented as parentage."
>   signature: [
>     parent = Parent "who is the parent",
>     child  = Child  "who is the child",
>     kind?  = ParentageKind "biological | legal | ... (if distinction is needed)"
>   ]
>   views: [
>     {
>       name: "get_parent"
>       description: "Get the parent(s) of a child"
>       inputs: ["child"]
>       outputs: ["parent"]
>       output_arity: "list0"
>     },
>     {
>       name: "get_child"
>       description: "Get the child(ren) of a parent"
>       inputs: ["parent"]
>       outputs: ["child"]
>       output_arity: "list0"
>     }
>   ]
> }
> ```
>
> Example fact:
> - `PARENTAGE { parent=Alice, child=Bob, kind='biological' }`

```python
matches = PARENTAGE.get_parent(child=Bob)
# Each match contains value=parent and source_fact=the parentage fact.
```

> [!note]
> Inverse navigation (`get_child`) is a view. A separate `CHILD_OF` fact is not needed.

### Rules and Constraints
#topic_details

> [!important]
> 1. **One fact, many views.** Do not create “inverse RelationTypes” just for navigation. Use `views`.
> 2. **A projection does not duplicate the fact.** Saving a read result in a trace does not create copies of source relation instances in the graph.
> 3. **`constraints` is only a filter** in the shared [[#^spec-Predicate|Predicate format]].
> 4. **Selecting one item is outside `RelationType`.** A view follows its declared cardinality; `latest/max_support/...` is a separate operation with an explicit policy.
> 5. **Name a RelationType for the fact's meaning.** Use readable and unambiguous names, both neutral (`PARENTAGE`) and directional (`ON_SURFACE`).

---

### Creating a Facet
#topic_details

An anchored operator may create a `Facet` as a local semantic result of a specific `ProgramRun` (all results are trace-local).

Example:

```python
health_status = diagnose(igor)  # et:op=igor_health_status
```

`SemanticTrace` records not just a technical distribution:

```python
health_status = {"healthy": 0.05, "sick": 0.90, "recovering": 0.05}
```

but Igor's semantic state:

```python
Facet_IgorHealth42 {
  valid_from = "2026-07-17T12:00"
  valid_until = None

  created_by = TraceOutputRef(
    event_ref = <identity of TraceEvent_E19>,
    output_path = "facets.igor_health"
  )
}

HealthStatus(Facet_IgorHealth42) {
  alternatives = [
    CLASSIFIED_AS(Facet_IgorHealth42, Healthy),
    CLASSIFIED_AS(Facet_IgorHealth42, Sick),
    CLASSIFIED_AS(Facet_IgorHealth42, Recovering)
  ]
  belief_data = Profile {
    strengths = {Healthy: 0.05, Sick: 0.90, Recovering: 0.05}
    support = ...
    prior_support = ...
  }
  created_by = TraceOutputRef(
    event_ref = <identity of TraceEvent_E19>,
    output_path = "properties.health_status"
  )
}
```

One `Facet` may be described by multiple compatible facts:

```text
HealthStatus(Facet_IgorHealth42)
→ one CompetitionScope / Profile;

HAS_NUMERIC_VALUE(
  Facet_IgorHealth42,
  Temperature,
  39.1,
  Celsius
)
```

One `TraceEvent` may create a `Facet` and its associated facts at the same time.

By default, this result remains local to `SemanticTrace` and is interpreted in its `Semantic Call Tree` context.

To make the state part of the persistent graph, the caller passes its recorded result to KnowledgeIntegration, which chooses direct writes backed by internal `GraphDelta`s:

```text
local Facet + related facts
→ KnowledgeIntegration
→ checked per-operation writes
→ persistent Facet + related facts
```

Afterward, the state is available to ordinary retrieval and `read_property(...)`.

Writing to the persistent graph does not change the content or reliability of the state. It only means that the agent chose to preserve it as a long-term claim in its active world model. Reliability is still represented through `Belief_data`.

---

## Operational Role of Semantic Relations

^e24496

#topic_core

A semantic relation in EverTree is not only a declarative fact about the world. It also serves two operational roles:

1. **Knowledge cache** — preserves a result of prior reasoning, measurement, `ProgramRun`, or Evaluation so it does not have to be computed again. If a relation is a materialized result, its origin is recovered through the shared provenance mechanism; no redundant memory references are created.
2. **Retrieval index** — creates a fast search path among concepts, processes, programs, factors, outcomes, and memories.

Materialize a semantic relation **only** when it has expected operational value:

- it speeds up retrieval;
- it reduces repeated reasoning;
- it records significant uncertainty or its resolution;
- it supports memory/process/program routing;
- it participates in prediction or planning.

Create a negative or exclusion relation only when the factor was actually considered, caused uncertainty, produced a false candidate, contributed to a model error, or is needed to prune a specific program.

A negative or exclusion relation should be created only if the factor was actually considered, caused uncertainty, produced a false candidate, contributed to a model error, or is needed to prune a specific program.

---

## Evidence Dependency Relation

```python
RelationType EVIDENCE_DEPENDS_ON {
  name: "EVIDENCE_DEPENDS_ON"

  description:
    "Records a material information dependency of evidence on a shared source, observation, premise, or other basis. It does not imply a causal dependency between world objects."

  signature: [
    evidence = Node | RelationInstance
      "Semantic result containing evidence."

    basis = Node | RelationInstance
      "Information basis on which the evidence materially depends."
  ]

  views: [
    {
      name: "get_evidence_dependencies"
      inputs: ["evidence"]
      outputs: ["basis"]
      output_arity: "list0"
    },
    {
      name: "get_dependent_evidence"
      inputs: ["basis"]
      outputs: ["evidence"]
      output_arity: "list0"
    }
  ]
}
```

---

## Axes of the Abstraction Ladder

### Introduction
#topic_core

EverTree's Abstraction Ladder is a set of **hierarchical axes** that support:

- propagation of **activation** (and with it, relevance, properties, and priors);
- transfer of **rewards/value** and generalization of experience (specific ⇄ general);
- multiple **parallel generalization tracks** that consciousness can combine when predicting an episode outcome and selecting actions.

> [!important]
> The “ladder” is not one relation, but **two different axes**, because there are two distinct meanings of “moving up to something more general” in reality:
> 1. _the same object at another level of granularity_ (state → object → type);
> 2. _a more general type_ (species → genus → …).

### Concept Plane
#topic_core

`<HierarchyAxis>`: `<Axis>`

(def_id:: entity.HierarchyAxis)
> [!definition]
> **Hierarchy Axis** (hierarchical inclusion) — an axis defining a **partial order** of “more general / more specific.” It supports **generalization and detailing** without conflating them with attribution. Not all elements have to be directly comparable, but the order must be stable enough to transfer priors and activation.
^def-HierarchyAxis

**Ascend:** move toward the more general (specific → general).  
**Descend:** move toward the more specific (general → specific), implemented through **views/projections** over the same facts; no separate “inverse RelationTypes” are created.

**Minimum operations:**

- `ancestors(x) / descendants(x)` — navigate up/down the hierarchy;
- `common_ancestor(x, y)` — common ancestor (for analogy/generalization);
- `distance(x, y)` (optional) — a rough distance for activation decay.

> [!important]
> **Important semantic boundary:**
> - The Hierarchy Axis is **not about properties** (that is the Attribution Plane: `HAS_NUMERIC_VALUE`, `CLASSIFIED_AS`, and structural property facts).
> - The Hierarchy Axis is **not about “conjunctions of constraints”** or creating new classes from facets. If summary classes (“OnRoad”, “Fast”) are needed, materialize them in Attribution under criteria; that is not a hierarchy axis.

The `RelationType`s for hierarchies below are defined in a contract-oriented style. **Descend is implemented everywhere through views**, so separate RelationTypes such as `CHILD_OF / HAS_PARTS / SUBTYPES_OF` are unnecessary.

#### RelationTypes for Abstraction Ladder Axes
#topic_details

##### `SUBTYPE_OF` (Type ↔ SuperType)

(formal_id:: entity.SUBTYPE_OF.schema)
```python
RelationType SUBTYPE_OF {
  name: "SUBTYPE_OF"
  description: "Taxonomic fact: type is a subtype of its immediate supertype in a strict tree. Used only between Prototype/Type nodes. Not used for Instance/Facet and does not mean 'has a property.'"
  signature: [
    type      = Prototype "more specific type/schema",
    supertype = Prototype "more general type/schema (parent in the tree)"
  ]
  views: [
    {
      name: "get_supertype"
      description: "Get the supertype of a type"
      inputs: ["type"]
      outputs: ["supertype"]
      output_arity: "optional"   # a root type has no parent
    },
    {
      name: "get_subtypes"
      description: "Get the subtypes (types) of a supertype"
      inputs: ["supertype"]
      outputs: ["type"]
      output_arity: "list0"
    }
  ]
}
```
^spec-SUBTYPE_OF

> [!note]
> Notes:
> - This is the **Taxonomy axis** (Type → SuperType).
> - **Descend-Taxonomy** is the inverse query: “find the subtypes of this supertype.”

##### `IDENTITY_TYPE` (Instance ↔ Type)

(formal_id:: entity.IDENTITY_TYPE.schema)
```python
RelationType IDENTITY_TYPE {
  name: "IDENTITY_TYPE"
  description: "Identity-to-type relation: an instance (identity anchor) realizes a type (Prototype). Does not mean type taxonomy (SUBTYPE_OF) and does not describe current state (STATE_IDENTITY)."
  signature: [
    instance = Instance  "a concrete object identity (anchor), extended through time",
    type     = Prototype "type/schema (norms and priors apply to the instance)"
  ]
  views: [
    {
      name: "get_type"
      description: "Get the type of an instance"
      inputs: ["instance"]
      outputs: ["type"]
      output_arity: "one"
    },
    {
      name: "get_instances"
      description: "Get instances of a type"
      inputs: ["type"]
      outputs: ["instance"]
      output_arity: "list0"
    }
  ]
}
```
^spec-IDENTITY-TYPE

> [!note]
> Notes:
> - This is part of the **Granularity axis** (Facet → Instance → Type), specifically the **Instance → Type** segment.
> - **Descend-Granularity** for this segment is the inverse query: “find the instances of this type.”

##### `STATE_IDENTITY` (Facet ↔ Instance)

(formal_id:: entity.STATE_IDENTITY.schema)
```python
RelationType STATE_IDENTITY {
  name: "STATE_IDENTITY"
  description: "State-to-identity relation: a Facet is a slice of an instance's state at a time/window. A Facet is not a separate identity and does not define its type (that is IDENTITY_TYPE)."
  signature: [
    facet    = Facet    "state slice (instance-state) in a time/window; the most flexible level",
    instance = Instance "identity anchor to which this state belongs"
  ]
  views: [
    {
      name: "get_instance"
      description: "Get the instance for a Facet"
      inputs: ["facet"]
      outputs: ["instance"]
      output_arity: "one"
    },
    {
      name: "get_facets"
      description: "Get Facets (states) for an instance"
      inputs: ["instance"]
      outputs: ["facet"]
      output_arity: "list0"
    }
  ]
}
```
^spec-STATE-IDENTITY

> [!note]
> Notes:
> - This is part of the **Granularity axis**, the **Facet → Instance** segment.
> - **Descend-Granularity** for this segment is the inverse query: “give me the Facets (states) of this instance.”

### Granularity Axis (Facet → Instance → Type)
#topic_core

**Essence**  
This axis answers: **“Is this the same object, but at which level of description?”**

It connects three levels along one line:

- **Facet** — “what now / in this episode” (a state slice); see [[Core data structures#^def-Facet|Facet]] ^27292c
- **Instance** — “who/what is this as an identity” (the anchor)
- **Type (Prototype)** — “what is it like by the norm/schema” (the predictive class)

**Why it is part of the abstraction ladder**  
Because it is a strict generalization: from a changing state to a stable identity and then to a general schema from which priors are inherited.

**Propagation (why the axis is useful at runtime)**  
The following naturally propagate along this axis:

- activation and relevance (if a Facet is active, its Instance and Type are likely relevant);
- priors/expectations (Facet inherits priors from Instance/Type);
- rewards and experience generalization (episode reward may carefully update statistics at Instance and Type levels without directly rewriting them).

**Relations and operations (neutral facts + views)**

- `STATE_IDENTITY(facet, instance)` — link state to identity.
  - view: `get_instance(facet) -> instance` _(one)_
  - view: `get_facets(instance) -> facet*` _(list0)_

#### `get_facets`
```text
get_facets(
    instance: Instance,
    valid_at?: time, # keep Facets applicable at the specified world time;
    known_at?: time, # limit results to the agent's knowledge at this time.
) -> list[Facet] | unknown
```

This is the standard temporal read operation over the base `STATE_IDENTITY.get_facets` view and graph history. It passes temporal parameters to the view under the [[#Shared Executor and Result|shared read contract]], checks the linked `Facet` intervals at `valid_at` in the state known at `known_at`, and extracts persistent `Facet`s from the view results. If saved history is insufficient, it returns `unknown` under the [[Attribution Plane#Historical Reconstruction of a Property|shared historical reading rules]].

Trace-local Facets are retrieved from the corresponding `SemanticTrace`. Use `get_facets` when the calling process needs the structure of the states themselves:

```text
get_facets(Igor)
→ which Facets for Igor have been materialized;
```

To obtain the value of a specific property, use the Attribution Plane:

```text
read_property(Igor, HealthStatus)
→ what health value the agent attributes to Igor.
```

An ordinary domain program uses `read_property` when its question concerns a defined `PropertyConcept`. `get_facets` is for structural navigation, historical reconstruction, debugging, and replay.

- `IDENTITY_TYPE(instance, type)` — link identity to type:
  - view: `get_type(instance) -> type` _(one)_
  - view: `get_instances(type) -> instance*` _(list0)_

**Ascend-Granularity (toward the general):**

- `facet → instance` through `STATE_IDENTITY.get_instance`;
- `instance → type` through `IDENTITY_TYPE.get_type`.

**Descend-Granularity (toward the specific):**

- `type → instances` through `IDENTITY_TYPE.get_instances`;
- `instance → facets` through `STATE_IDENTITY.get_facets`.

#### Relationship to [[Uncertainty and Belief Tracking in the World Model]]
#topic_details

> [!abstract]
> **Approach:** do not create a separate “belief graph” for the Semantics Plane. Individual semantic values and relation instances use ordinary `BeliefData`; mutually exclusive and exhaustive alternatives in one `CompetitionScope` use one shared `Profile`, not independent belief records.
>
> `BeliefData` and `Profile` formats remain shared and are not redefined here; see [[Uncertainty and Belief Tracking in the World Model#Belief Representations]].
>
> When confidence across Abstraction Ladder levels needs to be considered, use a computed profile over multiple belief records, not a new form of `Belief_data`:
>
> ```text
> SemanticBeliefProfile = List[LevelBelief]
> LevelBelief = <level, value_U?, belief_data>
> ```
>
> `level` denotes the `facet/episode → instance → prototype₁ → ...` level, and `belief_data` is `BeliefData` or `Profile`.

**Purpose:** separate three kinds of semantic uncertainty without mixing them in one `Belief_data` record:

- **[[Semantics Plane#STATE_IDENTITY (Facet ↔ Instance)|Facet]] / Episode** — the current posterior for a particular case: “what exactly is happening / what happened now?” This is the most flexible level.
- **[[Semantics Plane#IDENTITY_TYPE (Instance ↔ Type)|Instance]]** — stable characteristics of a particular object/system relative to a general prototype: “this particular object behaves differently.” This is the level of individual parameters and local exceptions.
- **Prototype / Type** — confidence in class definitions, typical relationships, mechanisms, and priors: “how the class is defined, how its members usually behave, and how confident we are in that.” This is normally more stable than an episode interpretation and requires grounds covering the generalization across relevant objects and conditions.

In the Semantics Plane, [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]] is conceptually similar to [[#Views: Projections Over One Fact|`AccessView`]] in its role, but is not an `AccessView` object. It is a computed epistemic view of one `CompetitionScope`, not a new semantic fact or a set of copied [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`BeliefData`]] records for alternatives.

**Interpreting scalar `Strength` / `Support` by level:**

At every level, [[Uncertainty and Belief Tracking in the World Model#BeliefData|`Support`]] is the total effective discriminative mass of the target's own evidence, including both supporting and opposing evidence. It does not measure agreement or include the prior; transferable prior backing is represented by `PriorSupport`.

Concepts and Prototypes follow the same [[Uncertainty and Belief Tracking in the World Model#Evaluating Definitions, Models, and Content|assessment and update procedure]]. Their content, scope, and applicable evidence determine the checks. This equivalence preserves the distinction between revising a local Facet / episode belief and a broadly reused class belief.

- **[[Semantics Plane#STATE_IDENTITY (Facet ↔ Instance)|Facet]] / Episode:**
  - [[Uncertainty and Belief Tracking in the World Model#BeliefData|`Strength`]] = scalar confidence in a specific semantic value / relation instance / hypothesis in the current context.
- **[[Semantics Plane#IDENTITY_TYPE (Instance ↔ Type)|Instance]]:**
  - `Strength` = confidence in a local characteristic/correction for this object relative to the prototype.
- **Prototype / Type:**
  - `Strength` = confidence in a class definition, typical relation, rule, prior, or mechanism under its evaluation contract.

> [!note]
> For a `CompetitionScope`, one `LevelBelief` contains the scope's shared [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]]. `SemanticBeliefProfile` remains a view across levels, not a separate epistemic updater.

##### Example Data by Level

> [!example] The question “What is the main source of water on wet asphalt?” defines `CompetitionScope` `{rain, washing, other/mixed source}`.
>
> - **Episode level:**
>   - Profile view: `{rain: 0.55, washing: 0.35, other/mixed: 0.10}`, shared `Support: low`.
> - **Prototype level:**
>   - the relation `rain → wet` has generalized `Strength`;
>   - `Support` includes effective evidence from informative observations and checks, including counterexamples; it can increase while `Strength` decreases.

##### `Belief_data` → Semantic Runtime

Runtime uses `SemanticBeliefProfile` levels differently:

- **Facet / Episode level** — choose the current semantic interpretation: active hypothesis, current object type, current cause, or current relation instance.
- **Instance level** — local exceptions, individual corrections, and instance-specific priors.
- **Prototype level** — general semantic priors, hierarchies, mereology, planning, and generalized mechanisms.

**Update rule:** Facet / episode belief may change quickly from applicable evidence about that case. Prototype / class belief normally changes more slowly and cautiously, requiring sufficient grounds for the general claim and its affected uses. An episode must not directly overwrite the prototype: [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|evidence assessment]] checks local explanations and justifies attribution to the class, using independent cases and boundary checks when needed. A verified counterexample may promptly lower confidence in a universal claim, but does not by itself establish a replacement definition or model. See [[Uncertainty and Belief Tracking in the World Model#Beliefs Across Abstraction Levels|revision across abstraction levels]].

### Taxonomy Axis: Type Taxonomy (Type → SuperType → …)
#topic_core

**Essence**  
This axis answers: **“What is this essentially, as a class of mechanisms?”**

This is the familiar ontological taxonomy:

```text
Dachshund ⊂ Dog ⊂ Animal ⊂ …
```

**Why use single inheritance (a strict tree)**  
Type taxonomy is used as a “skeleton” for:

- inheriting norms and constraints;
- compatibility of Facets and interfaces;
- stable generalization of knowledge.

> [!important]
> Multiple inheritance almost always creates ambiguity about “which norms to inherit,” so the rule is **at most one taxonomic parent**.

Additional classifications are specified through [[Attribution Plane#2. Membership Property Fact|`CLASSIFIED_AS`]] and do not add parents to the inheritance tree.

**Relation and operations (neutral fact + views)**

- `SUBTYPE_OF(type, supertype)` — taxonomic type link:
  - view: `get_supertype(type) -> supertype?` _(optional)_
  - view: `get_subtypes(supertype) -> type*` _(list0)_

**Ascend-T (toward the general):**

- `type → supertype → …` through `SUBTYPE_OF.get_supertype`.

**Descend-T (toward the specific):**

- `supertype → subtypes → …` through `SUBTYPE_OF.get_subtypes`.

---

## Composition Axis (Mereology)
#topic_core

`<MereologyAxis>`: `<Axis>`

**Essence**  
The composition axis models the **part–whole** relationship for systems and objects: “what is it made of?” and “what is it part of?”

(formal_id:: entity.PART_WHOLE.schema)
```python
RelationType PART_WHOLE {
  name: "PART_WHOLE"
  description: "Mereological part–whole fact: part is part of whole. It is not type taxonomy (SUBTYPE_OF) and does not describe state/identity (STATE_IDENTITY/IDENTITY_TYPE). It does not mean 'is similar to' or 'has a property.'"
  signature: [
    part  = Part  "part (subsystem/component/element)",
    whole = Whole "whole (system/aggregate/object containing part)"
  ]
  views: [
    {
      name: "get_wholes"
      description: "Get the whole(s) for a part"
      inputs: ["part"]
      outputs: ["whole"]
      output_arity: "list0"
    },
    {
      name: "get_parts"
      description: "Get the parts of a whole"
      inputs: ["whole"]
      outputs: ["part"]
      output_arity: "list0"
    }
  ]
}
```
^spec-PART-WHOLE

**Ascend-Mereology (toward the more general whole):**

- `part → whole(s)` through `PART_WHOLE.get_wholes`.

**Descend-Mereology (toward more specific components):**

- `whole → parts` through `PART_WHOLE.get_parts`.

> [!note]
> Notes:
> - Mereology is **not** type taxonomy (`SUBTYPE_OF`) and **not** identity granularity (`STATE_IDENTITY`, `IDENTITY_TYPE`).
> - Separate RelationTypes for navigation are unnecessary: Descend/Ascend use views and atomic programs for selection/filtering.
