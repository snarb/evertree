---
status: policy
target_version: next
---

# Taxonomy and Relation Governance

## Scope and operational status

This document defines how Evertree gives concepts and relations stable meanings and changes those meanings without silently changing existing knowledge. It applies to the world ontology, relation schemas, process ontology, and the agent's Self graph. It is self-contained policy for future management Programs; each operation below can be used as the basis of a separate instruction.

**MUST** denotes a publication requirement. **SHOULD** denotes the default, with a recorded reason for an exception. A rejected or unresolved proposal is a valid outcome. A successful write is not proof that a semantic decision was correct.

The starter package in [`src/evertree/core/graph/templates/`](../../src/evertree/core/graph/templates/) contains editable definitions, symbolic references, provenance and scope examples. The loader in [`template.py`](../../src/evertree/core/graph/template.py) validates the package, resolves identifiers and installs it through `GraphDelta`. A new application graph receives the package; low-level `GraphStore.bootstrap()` stays minimal. Restoring an existing application uses its saved graph. This release does not upgrade existing graphs automatically.

| Capability | Status and boundary |
|---|---|
| Package validation, identifier resolution and installation | Implemented starter-template mechanism. Invalid installation must leave the graph unchanged. |
| Node and fact storage, signatures, declared views, single-parent and reference checks | Core mechanisms. Their checks do not establish the truth of definitions or assertions. |
| Search, exact reads, local updates and non-cascading deletion | Existing semantic tools. Several separate tool calls do not form one atomic operation. |
| Relation specialization declarations | Stored and validated as declarations. They do not cause automatic predicate projection, materialized parent facts or inherited queries. |
| Semantic comparison, lifecycle orchestration and dependent-evidence reassessment | Normative workflow below. Dedicated automatic taxonomy management Programs are future work. |
| Empirical improvement of LLM navigation | Requires a separate matched evaluation. Structural tests and prepared routes do not demonstrate it. |

When an available operation cannot satisfy a required transaction, evidence reassessment or protection boundary, the writer MUST retain a proposal and use the appropriate future workflow or trusted implementation. It MUST NOT emulate an atomic merge using a sequence of independently committed edits. This document does not grant permission to bypass existing Core guards.

Related contracts: [Semantics Plane](Semantics%20Plane.md), [Core data structures](Core%20data%20structures.md), [Self](Self.md), [process ontology](Process%20Plane/Process%20Ontology%20and%20Semantic%20Interface.md), [uncertainty and belief](Uncertainty%20and%20Belief%20Tracking%20in%20the%20World%20Model.md), and [Program lifecycle](Process%20Plane/Program%20Lifecycle%20and%20Evolution.md).

## The ontology profile

### Foundation and intended coverage

Evertree uses a curated **single-parent SUMO profile** as its foundation. It does not import all SUMO axioms or claim logical equivalence with the complete source ontology. Preserve an applicable source name, definition and parent whenever possible. Select one justified parent where the source has several; preserve the source's complete classification in provenance, without treating the omitted parents as additional active inheritance.

The initial package gives greater detail to software, tools, computer systems, LLM systems, learning, cognition, probability, statistics and evidence. It also provides systematic school-science concepts and a broad vocabulary for social institutions and everyday life. A thematic file is a maintenance unit, not a taxonomic parent. A programming-language concept shared by education, software development and linguistics has one canonical record.

SUMO supplies the upper-ontology reference; [CS2023](https://csed.acm.org/knowledge-areas/) and [SWEBOK](https://www.computer.org/education/bodies-of-knowledge/software-engineering) inform computing coverage. Statistical references include [STATO](https://stato-ontology.org/) and [ProbOnto](https://pmc.ncbi.nlm.nih.gov/articles/PMC5013898/). Using a source for coverage does not mean its definitions or hierarchy have been imported. In particular, STATO's own upper ontology is not a second Evertree inheritance hierarchy. The manifest, rather than this list of websites, records the exact included materials, pinned revisions, attribution and usage conditions.

The template is a starting vocabulary, not a frozen encyclopedia. “Pareto coverage” is a design priority; no percentage of real user tasks is claimed without a representative evaluation.

### What a taxonomic edge means

`SUBTYPE_OF(child, parent)` means **every admissible instance of the child satisfies the parent's definition**, within the definitions' stated scope. It does not mean “usually resembles,” “is part of,” “is used for,” “appears in the same domain,” “is implemented by,” or “temporarily plays the role of.”

Every accepted type except the designated `Entity` root MUST have exactly one accepted parent and a finite path to that root. The graph MUST contain no taxonomic cycle. The taxonomy includes process types, property types, abstract relation categories and concrete predicates. Parent selection never changes the meaning of `SUBTYPE_OF` to obtain a convenient menu.

Siblings are not presumed disjoint or exhaustive. A tree selects one canonical route; it does not prove that source classifications are mutually exclusive. Negation, exclusivity and exhaustive alternatives require separate definitions and justified constraints. Belief in a subtype edge measures confidence in that inclusion; it is not a percentage of parent properties inherited by the child.

Taxonomic inheritance applies to necessary definitional constraints. A typical attribute, population distribution, empirical rate or default behavior is a separately scoped assertion with its own grounds. Do not turn “birds usually fly” into a universal inherited constraint.

Additional perspectives belong in precisely named semantic links and external mappings. A mapping MUST distinguish equivalent meaning, narrower meaning, broader meaning and related subject. A cross-reference or omitted source parent MUST NOT become a hidden second inheritance route. Mapping similarity does not establish predicate entailment or instance identity.

### Representation decisions

| Representation | Meaning and use | Do not confuse with |
|---|---|---|
| Type / `Prototype` | A reusable class with a definition and membership boundary. | One individual, a tag, an observed frequency, or a folder. |
| `Instance` | One enduring identity, linked through `IDENTITY_TYPE` to its accepted type. | A class of similar individuals or a temporary condition. |
| `Facet` | A time-bounded state of one identity, linked through `STATE_IDENTITY`; applicable intervals are half-open. | A second identity or an essential permanent subtype. |
| Role | A context-dependent participation meaning, such as learner, owner or input. | The technical data type or the enduring class of its bearer. |
| Process type | A kind of occurrence or change under `Process`, with boundaries and participants. | One execution, its implementation, or its output. |
| Process occurrence | A particular episode with participants, time, conditions and outcome. | The generic process or every future occurrence. |
| Program | A specific executable or model artifact with an implementation contract and revision. | A process type or a run of that artifact. |
| Program run | One execution of a particular Program revision. | The Program, its algorithm, or its result. |
| Abstract relation category | An ordinary `Prototype` grouping relation meanings. | A callable predicate with an invented empty signature. |
| Concrete `RelationType` | A predicate with a defined assertion, nonempty signature, roles and views. | One true or reported assertion using that predicate. |
| `RelationInstance` / fact | One assertion with arguments, qualifiers, provenance and an epistemic status. | Proof of truth or independent evidence supplied by its schema. |

Use a broad but justified identity type when the source does not establish a narrower one. Other contingent classifications or roles are assertions, not additional identity types. If the source describes a time-scoped condition, keep the condition and interval rather than creating a permanent species of entity.

The implementation's `kind` identifies a storage representation. It does not replace a semantic type. A `number` role can denote a probability, a count or a temperature; a node-valued argument can be a person, program or process. Those distinctions require the subject contract and, where relevant, units and conditions.

### Identity, names and definitions

Canonical names MUST be unique among canonical concepts, prototypes, properties, processes and relation types. Prefer established source spelling and short, discriminating names. Keep English and Russian synonyms for discovery; aliases may be ambiguous and MUST NOT be treated as identity proofs. Technical keys and runtime identifiers are distinct from names.

Before creating or changing a meaning, search names, translations, aliases, nearby parents, related subjects and existing signatures. Read full definitions, exclusions, examples, existing uses and provenance for plausible matches. An incomplete search cannot establish absence. A matching label is a candidate, and a different label is not proof of a different concept.

Two definitions are equivalent only if they agree on intended referents, inclusion and exclusion criteria, scope, temporal interpretation and other decision-relevant constraints. For predicates, they must also agree on complete tuples, roles, argument semantics, conditions and direction. Renaming is appropriate for the same meaning; widening, narrowing or changing that meaning requires semantic revision and may require a new identity.

## Relations are part of the ontology

### Predicate contracts and semantic subjects

Every concrete predicate MUST record:

1. Its canonical meaning, what an asserted tuple entails, and important exclusions.
2. Its single taxonomic parent, which may be an abstract category or another concrete predicate.
3. A nonempty signature with stable slot labels, cardinalities and technical value types.
4. A description of each role's meaning and direction. `value_concept` names the semantic type of permissible values; `role_concept` optionally identifies the contextual role itself. These fields are not interchangeable.
5. Read views with declared input and output slots, cardinality and any constraints.
6. Explicit semantic subject links to the concepts the relationship concerns, and links or signature references to argument types and reusable role concepts.
7. Sources, a pinned source identifier/revision, adaptation rationale where needed, and boundary examples.

For example, a compilation predicate can concern `Compilation`, accept an input typed as source code and an output typed as a program artifact, and use distinct input/output role concepts. A person filling an author role remains a person; the label `author` does not make the argument a kind of role. An implementation accepting a node reference checks the technical type; the writer must additionally establish that this node is appropriate for the semantic value type and the actual participation role.

`RELATION_SUBJECT` organizes what a predicate is about. It is not a universal claim about all members of that subject and not an extra parent. Add subjects that materially support finding or interpreting the relation; do not indiscriminately attach every reachable ancestor. Use signature references for argument types, rather than relying on a subject link to constrain them.

An abstract category such as a family of temporal relations has a definition and parent but no fake signature or views. It is never used as the predicate of a fact. A concrete predicate can describe a change: `RelationType` is not limited to static assertions. A transition predicate, process noun and process occurrence remain distinct representations.

### Views, projection and specialization

One fact can be read in several directions through views. A new reverse lookup does not justify a new inverse predicate or duplicate fact. View cardinalities are assertions about the contract: a `one` result requires a justified uniqueness condition; do not select an arbitrary winner to satisfy it. A view over a joint fact must retain enough source identity and qualifications to reconstruct what was asserted.

When a concrete predicate specializes another concrete predicate, the declaration MUST state an explicit mapping from every required parent role to the corresponding child role. The mapping must preserve role meaning, technical type, semantic type, cardinality, units and conditions. Every valid child tuple, under this mapping, must entail a valid parent tuple. Extra child arguments may refine the assertion, but dropping a condition that the parent requires is not valid specialization.

Do not map slots by position or similar spelling. A narrower permissible argument domain can be justified; a broader one cannot establish the parent contract. An optional child slot cannot satisfy a required parent slot unless the child contract guarantees its presence in the projected cases. Constants, aggregation and conditional transforms require an explicitly supported derivation mechanism; they cannot be hidden inside a simple role map.

Example: a specialized read operation may project its agent, resource and result into a more general read predicate if each role retains its meaning. Counterexamples: a purchase does not entail delivery; guardianship does not entail biological parentage; a prediction does not entail its predicted outcome. Relabeling their roles cannot repair the missing entailment.

Symmetry, reflexivity, transitivity and uniqueness do not automatically descend from a parent predicate. A child's narrower meaning may invalidate them. Any such rule requires its own scope and validation. Querying a parent currently does not automatically query or project all its concrete descendants: specialization declarations are documentation and validation data, not an implemented inference engine.

If projection is implemented later, projected and original assertions MUST retain common provenance and dependency identity. Projection is a derived reading, not new independent evidence. Never materialize inverse or transitive copies merely to improve navigation.

## Processes and Self

World processes follow their general definitions. Learning, belief updating and parameter optimization overlap in application but are different meanings. A learning episode may involve a belief update or an optimization step without being identical to either. Human, animal and computer learning require explicitly applicable definitions; do not broaden a source's psychological concept silently to cover every parameter change.

Describe process participation, input, output, conditions, ordering, control and implementation with appropriate relations. `PART_WHOLE` can describe composition; it does not imply execution order. Temporal precedence does not establish causation. A causal link requires its own scope and grounds. `EVIDENCE_DEPENDS_ON` describes justificatory dependence, not a physical cause or ordinary time ordering.

The starter uses `ABOUT(source, target)` to connect a process definition to a meaningful subject or non-inferential semantic reference. The specialized `PROCESS_SUBJECT` vocabulary in the process design is not installed by this release. It does not assert that the process produces, improves or causes that subject. `PROGRAM_FOR_PROCESS` associates a Program with the process it models or implements; the Program's roles and contract determine which. A predictive model is not thereby an executable implementation of the modeled world process. Preserve a Program's revision and an occurrence's conditions when evaluating results.

`Self` is the current agent's persistent **Instance**, typed as `SoftwareAgent` under SUMO `AutonomousAgent`; it is not the class of all agents. A software-agent subtype describes the operating agent, distinct from an inert software artifact. General world concepts belong in the shared template. Concrete own processes and Programs are connected during application bootstrap.

The own-process taxonomy is rooted at `SelfProcess`, a subtype of the general `Process`. Its initial groups are `SelfSemanticProcessing`, `SelfTaskManagement`, `SelfCognitiveControl`, `SelfMemoryProcessing` and `SelfLearning`. Own processes have explicit names such as `SelfReflection` and `SelfPlanning`, so generic `ReflectionProcess` and `PlanningProcess` retain their world meanings. `PART_WHOLE(SelfProcess, Self)` records the agent's organization; it does not make `Self` a taxonomic parent.

Each own process still has one parent. A cross-reference from `SelfReflection` to the general reflection concept does not create a second subtype edge or silently inherit general assertions. If a link states a process subject, its actual meaning must be aboutness; otherwise choose an explicitly defined non-inferential mapping. Do not invent an implementation relation whose hidden meaning is a second `SUBTYPE_OF`.

Own process identity and runtime dispatch identity MUST survive a naming or directory change. Keep graph names, source directories, catalog entries, Program bindings, active selections, contracts and call sites coherent. The source directory tree follows the own-process `SUBTYPE_OF` hierarchy, not `PART_WHOLE`. A structural change requires the Program layout validator and affected execution checks.

Self descriptions can be wrong and remain open to evidence-based revision. That does not authorize changes to protected identity, values, lifecycle controls or executable bindings. Protection applies to the **effect** of the operation: editing or deleting an incident edge, role, active-program reference or parent to circumvent a protected node is equally prohibited. Schema changes affecting protected facts must be checked against the same boundary. Ordinary taxonomy tools cannot activate Programs or relax Core controls.

## Evidence, time, conflicts and connectivity

### Meaning and evidence are versioned separately

A definition's source establishes provenance and may support a conventional meaning. It does not confirm every empirical assertion made with the concept. Template definitions, examples and navigation links MUST NOT be converted automatically into numerical confidence, `Support` or `PriorSupport`. Unsupported LLM familiarity is not traceable external evidence.

Belief is about a specified target, version, criterion and scope. Keep the original source, observation time, applicable world time, attribution, uncertainty and dependency relationships. Distinguish the current stored assertion from the history of what was asserted or believed. A changed value does not overwrite the previous valid interval. An updated report is not necessarily an additional independent observation.

A semantic change MUST identify which assignments and derived conclusions still apply. Do not copy confidence to a changed meaning, sum confidence values, sum duplicate confirmations during a merge, or give all split meanings the old evidence. Lexical edits that preserve the evaluated proposition need not erase evidence; a rationale must explain why the meaning is unchanged.

Reassessment traverses the dependency closure, not merely adjacent taxonomy nodes. Include inherited classifications, property applicability, rules, projected assertions, priors, cached readings, search projections, and Programs whose contracts use the changed meaning. Invalidate stale derived results before presenting them as current. Keep independently supported facts and reassess their affected grounds rather than deleting all descendants indiscriminately. Until reassessment completes, return an explicit unresolved or stale status where supported, or withhold the affected derived reading.

### Conflict handling

Determine whether apparently conflicting statements share the same identity, predicate, roles, units, time, jurisdiction, source attribution and conditions. Different times or scopes may explain the difference. An apparent contradiction between synonyms may instead reveal two meanings.

When incompatible assertions have the same target, retain both with their grounds. Do not choose the newest, most frequent or highest-confidence wording automatically. Assess source dependence and target-specific discriminating evidence. A source being unreliable in one domain does not mechanically invalidate all its statements. Logical consistency alone is not independent support.

Taxonomic uncertainty has a structural boundary: the accepted tree still has one parent. Retain competing parent proposals as proposals or attributed claims. Use the nearest justified accepted ancestor, or keep the candidate outside the accepted taxonomy until its meaning is resolved. Do not publish multiple parents with low confidence. Do not delete a useful counterexample, unresolved candidate or low-confidence hypothesis solely to make the graph look cleaner.

### Connectivity policy

The accepted **type taxonomy** is rooted and connected. Accepted process and relation types are included, even when no current instance uses them. This enables complete top-down traversal and a stable place for meanings.

The **subject-matter fact graph** need not be connected. An isolated observation, identity or local subgraph may be meaningful without a factual bridge to another subject. An instance still satisfies its structural identity requirements, but structural reachability through a type is not a semantic assertion that its referent interacts with every other referent.

Do not add arbitrary “related to” links, force dubious parents or fabricate empirical facts to eliminate islands. Isolation and low confidence alone are never deletion criteria. Candidate and unresolved material can remain outside the accepted tree with an explicit review context; it must not be mistaken for a validated accepted type.

## Criteria for choosing or changing a parent

Record one of the following reasons. These are different decisions with different evidence requirements.

| Reason | Acceptance requirement |
|---|---|
| Required single-parent projection | The source has multiple applicable parents. Select one semantically valid, stable parent and record source parents, candidates, selected route and rationale. No measured speedup is required. |
| Semantic correction | The current edge violates the definitions, level distinction or scope. Supply the counterexample and justify the corrected edge. No measured speedup is required. |
| Optional navigation optimization | Both old and new edges are semantically correct. Require the matched evaluation and thresholds below before publication. |

First inspect the full definitions and candidate parent chains. Prefer an applicable source parent and the most specific justified necessary inclusion. If more than one remains, prefer the parent's defining dimension over incidental use, then consistency with established siblings and stable familiar source naming. Record the considered alternatives and tie-break. If the choice changes membership or drops a needed distinction, it is a semantic revision, not merely a routing decision.

Before an optional structural optimization, rule out misleading labels, missing aliases, incomplete definitions, conflated meanings and truncated child displays. A simpler repair may resolve the error while preserving the source structure. Keep the structure when evidence is insufficient or gains are small.

### Matched navigation evaluation

Define a route failure before collecting results: failure to reach an independently labeled admissible target within the fixed budget, including a wrong target or a branch from which the target cannot be reached. Evaluate the same independent query intentions on old and proposed versions with the same model, model revision, instructions, decoding settings, budget, root/start policy and complete-child presentation. Freeze the benchmark, scoring and analysis before comparing. Separate exploratory examples from held-out acceptance cases.

Paraphrases of one intention are one statistical unit. Repeated model trials and paraphrases remain paired within that unit; they are not extra independent observations. Record ambiguous acceptable targets explicitly rather than scoring only one arbitrary wording. A purely deterministic route inspection checks reachability, not LLM branch selection.

Let `p_old` and `p_new` be failure rates, and `d = p_old - p_new`. An optional optimization requires all of:

- `d >= 0.03` (at least three percentage points absolute improvement).
- `d / p_old >= 0.20` when `p_old > 0` (at least twenty percent relative reduction). A zero baseline failure rate cannot satisfy this improvement test.
- The lower endpoint of a predeclared 95% paired confidence interval for `d` is strictly positive. Pair at the independent-intention level; for example, use a paired bootstrap over intention clusters rather than treating paraphrases as independent.
- No semantic regression and no worsening in affected priority scenarios. Inspect failures and required semantic contrasts separately; aggregate improvement cannot hide a lost priority route.

These are initial **policy thresholds**, not measured results or a claim of adequate sample size. Report sample sizes, paired outcomes, uncertainty, exclusions and priority breakdowns. If the interval is unreliable, a priority domain lacks cases, or the thresholds are not met, retain the existing correct structure. Change thresholds only through a separately justified policy revision, not after observing a preferred candidate's result.

## Common operation envelope

Every lifecycle operation below uses a complete read set and a proposed atomic write set. A decision record contains the operation, actor, graph revision, affected stable identities, old and proposed meanings, source revisions, reasons, alternatives, dependencies, protection checks, semantic review, mechanical validation and resulting disposition. These are required workflow contents, not a claim that a particular current tool exposes fields with these names.

Read the target nodes, parents, descendants where relevant, incident relations in all argument positions, predicate schemas, signatures, role/value references, views, evidence targets, dependent conclusions and protected Program/Self bindings. For a predicate, include its existing facts and specialized descendants. For a type, include instances, states, properties and contracts that refer to it. Do not infer a complete read set from a bounded search preview.

Stage structural and reference changes together. Validate against the same graph revision used for the decision. If relevant concurrent changes occurred, reread and revalidate; do not silently apply a stale decision. Commit through one trusted transaction/`GraphDelta` where supported, and preserve rollback information. If external code changes or evidence changes cannot join that transaction, use a lifecycle workflow that prevents incompatible versions from becoming active. A half-updated graph must not be advertised as accepted.

History MUST preserve old meaning, decisions and source lineage even when the old record is removed from the current graph. A removed numeric ID is never reused for an unrelated meaning. A symbolic template key also remains attached to its original meaning across revisions; renaming it is not a way to reset evidence or conceal a split.

## Algorithm: create

### 1. Purpose and motivation

Introduce a genuinely missing meaning or assertion while preventing duplicate classes, aliases masquerading as new meanings, and schemas without a usable place in the ontology.

### 2. Inputs and required graph reads

Read the proposed definition, source and scope; names and multilingual aliases; plausible equivalent concepts; parent candidates and full child lists; nearby predicates and role signatures; relevant process, instance and Self bindings. For a new fact, read the complete predicate and all participants, existing equivalent assertions and their provenance.

### 3. Preconditions and decision criteria

Search is complete for plausible alternatives. Existing meanings cannot express the intended content without distortion. A new accepted type has one valid parent and dependency-closed references. A concrete predicate has a valid signature, role/value semantics, subjects and views. Its creation is warranted by a reusable assertion meaning, not merely by a new sentence or reverse direction.

### 4. Sequence of actions

1. Classify the representation: type, identity, state, process, Program, predicate or assertion.
2. Compare candidates by their complete meanings and uses. Reuse an equivalent node or add a warranted alias instead of creating a duplicate.
3. Write the definition, exclusions, aliases, source mapping and boundary examples. Resolve every necessary parent, role, subject and argument type before publication.
4. Choose one justified parent for a type. Record any source projection or adaptation with the proper reason category.
5. For a concrete predicate, define all roles and views and, when its parent is concrete, a valid specialization mapping. For a fact, preserve participants, qualifiers and source grounds without asserting missing information.
6. Stage the node and mandatory structural/semantic links together; validate and commit once.

### 5. Ambiguity and conflicts

If two senses share a name, disambiguate their names and definitions. If the parent or identity is unresolved, retain a proposal or attributed assertion, not an unjustified accepted type. A conflicting report becomes a separately sourced assertion; it does not create a new sense of a predicate solely to avoid conflict.

### 6. Checks before publication

Check uniqueness, reference closure, parent inclusion, root reachability, absence of cycles, representation level, role directions, value types, view contracts and protected neighbors. Test at least one member and one nearby nonmember for an ambiguous type, and a valid and invalid tuple for an ambiguous predicate. Validate provenance and usage conditions.

### 7. Postconditions, dependencies and history

The new meaning is discoverable by its names, aliases, parent and semantic subjects. Required reads show its actual roles and full child list. Store creation grounds and invalidate affected search projections. Definition provenance creates no automatic empirical support; new assertions enter ordinary evidence assessment where supported.

### 8. Examples and counterexamples

Create a source-code concept distinct from a programming language, then a compilation relation whose input role accepts code. Do not create a second programming-language concept merely because one module concerns education and another concerns compilers. Do not create `HAS_CHILD` as a duplicate inverse when an existing parentage predicate already has a child-reading view.

## Algorithm: update

### 1. Purpose and motivation

Improve an existing record while preserving its identity only when the intended referent or meaning remains the same. Prevent apparently cosmetic edits from silently changing old facts or evidence targets.

### 2. Inputs and required graph reads

Read old and proposed definitions, aliases, source revisions, examples, memberships, incident facts, role contracts, views, specializations and full dependent closure. Read historical evaluated versions and active evidence. Include Program bindings and protected references even when the target itself is unprotected.

### 3. Preconditions and decision criteria

Classify the edit as lexical/presentation-only, compatible contract refinement, or semantic change. An edit that changes admissible instances, tuples, time interpretation, units, role meanings or evaluation criteria is semantic even if the name stays unchanged. Preserve identity only with an explicit continuity rationale; otherwise create a new meaning and use split/replacement workflow.

### 4. Sequence of actions

1. Compare old and new meaning against actual uses and boundary examples.
2. Separate unchanged assertions from changed assertions. Identify exactly which dependencies need review.
3. For a predicate change, check every existing fact and descendant mapping; explicitly convert compatible roles or retain the old predicate for incompatible historical facts. Do not reinterpret old arguments by position.
4. Prepare revised sources, examples, aliases and semantic links. Reclassify facts only when their grounds justify it.
5. Stage related structural edits atomically; arrange evidence reassessment before affected derived readings are treated as current.

### 5. Ambiguity and conflicts

Do not broaden a definition to hide counterexamples or narrow it solely to raise confidence. If evidence does not establish which meaning is intended, keep the prior version and a revision proposal. Preserve conflicting source claims and distinguish conventional naming from empirical adequacy.

### 6. Checks before publication

Run common invariants, actual-fact signature checks, role-map validation, prior examples and new counterexamples. Verify that unchanged facts retain their interpretations, source grounds remain attributable, and every incompatible use has an explicit disposition. Apply protection and freshness checks to dependent reads.

### 7. Postconditions, dependencies and history

Store the old meaning and revision reason. Rebuild affected indexes and derived projections. Keep evidence for unchanged targets; reassess changed targets instead of copying confidence. Preserve earlier failures in history. If reassessment is unavailable, the semantic update cannot be published as a fully reassessed current meaning.

### 8. Examples and counterexamples

Adding a Russian synonym for a compiler without changing its definition is lexical. Changing a temperature slot from degrees Celsius to kelvin is semantic and requires explicit conversion and provenance. Replacing “occurred before” with “caused” is not a clarification of the same predicate.

## Algorithm: change parent

### 1. Purpose and motivation

Place an existing accepted type on a better justified canonical route without changing subtype semantics or silently discarding effects of its old ancestry.

### 2. Inputs and required graph reads

Read the child, old and proposed parent definitions, complete ancestor chains, subtree and siblings, source parents and mapping, actual instances, inherited constraints, predicate specializations, dependent assertions and Program directory/binding information. For an optional navigation optimization, read the frozen benchmark and matched results.

### 3. Preconditions and decision criteria

Record required source projection, semantic correction or optional optimization. The new edge satisfies universal inclusion, introduces no cycle and retains one root path. The optional case satisfies every navigation gate; the first two cases need semantic grounds, not an artificial speedup claim. The child's definition is unchanged or a separate semantic revision is included explicitly.

### 4. Sequence of actions

1. Diagnose why the current parent is insufficient and check simpler naming/read repairs.
2. Compare justified alternatives, including source structure, and document the selected reason.
3. Calculate ancestry gained and lost. Review consequences for constraints, classifications, rules and relation projections.
4. If the new parent is a concrete predicate, establish its complete role map; remove or revise invalid old specialization declarations.
5. Replace the old parent edge and related declarations in one transaction. For own processes, synchronize source paths and Program catalog/bindings under the protected lifecycle.

### 5. Ambiguity and conflicts

Never publish both parents temporarily. If no more specific parent is justified, use a justified broader ancestor or retain the unresolved proposal. A wrong current parent must not be retained merely because navigation measurements are absent. A semantically correct parent must not be replaced for an unmeasured aesthetic preference.

### 6. Checks before publication

Verify the complete subtree is acyclic and rooted; every child still satisfies its direct parent; no hidden second-parent inference remains; affected constraints and projections remain valid. Validate priority semantic routes and, if applicable, empirical gates. Run Program layout checks for own-process structural changes.

### 7. Postconditions, dependencies and history

Keep the child's identity and record the old edge, new edge, source alternatives and rationale. Invalidate ancestry-dependent caches and conclusions, and reassess their evidence. Existing direct observations survive unless their meaning actually changed. Update search cards, parent/child displays and any saved structural navigation indexes.

### 8. Examples and counterexamples

Choosing one of several valid source parents is a necessary profile projection. Moving a compiler out of the programming-language class is a semantic correction. Moving an already correctly placed tool into an application-specific folder because that folder is popular is not sufficient; folder membership is not subtype inclusion and popularity is not a navigation evaluation.

## Algorithm: merge

### 1. Purpose and motivation

Unify records that denote the same meaning or identity without losing distinctions, history or evidence dependence. This is not a way to reduce node count by merging merely similar things.

### 2. Inputs and required graph reads

Read complete definitions, aliases, referents, scopes, source mappings, parents, descendants, facts, role contracts, views, specializations, evidence origins, historical revisions and all inbound references. For identity merges, read distinguishing attributes, temporal continuity and source assertions. Include protected and executable references in the closure.

### 3. Preconditions and decision criteria

Equivalence is established, not inferred from equal names or embedding similarity. Predicate equivalence requires a meaning-preserving mapping of the complete signatures and qualifications. Neither record carries a distinct sense, jurisdiction, time scope or implementation revision that must remain addressable. One surviving canonical identity and parent are justified, and every reference has an explicit disposition.

### 4. Sequence of actions

1. Produce an equivalence argument and test nearby distinctions and conflicting uses.
2. Select the survivor using established canonical meaning and provenance; do not choose solely by higher confidence.
3. Map all references and, for predicates, every role by meaning. Preserve non-equivalent historical assertions separately.
4. Group duplicate facts by complete proposition, scope and origin. Keep independent sources distinct; identify shared or copied grounds.
5. Build a single transaction for survivor updates, reference rewrites and retirement/removal of redundant current records. Preserve a historical resolution from retired identities to the decision.
6. Reassess evidence on the unified target with source dependence accounted for.

### 5. Ambiguity and conflicts

If equivalent senses are not established, keep both records and a candidate-match note. Do not merge homonyms or a class with its instance. A real factual disagreement remains visible after deduplication. If existing facts use one predicate in different senses, split those senses before considering a merge.

### 6. Checks before publication

Ensure no dangling reference, duplicate parent, cycle, invalid tuple, lost qualifier or violated protection remains. Verify all child and concrete-predicate mappings. Compare before/after statements for semantic preservation. Confirm that shared evidence is counted once and that merging cannot bypass guarded Self/Program edits.

### 7. Postconditions, dependencies and history

All current references point to the chosen meaning or an explicitly retained historical object. Old identities, aliases and source paths remain explainable through history. Recompute dependent results; do not sum `Support`, `PriorSupport`, confidence or repeated confirmations from both records. Retain the original evidence units and their dependency structure for reassessment and possible rollback.

### 8. Examples and counterexamples

Merge two records for the same compiler release after matching release identity, source and scope. Do not merge a compiler family with one executable build, an algorithm with its implementation, or human memory with computer storage. Two news outlets repeating the same original report do not become two independent confirmations when duplicate fact records merge.

## Algorithm: split

### 1. Purpose and motivation

Separate distinct meanings or overbroad classifications that were previously conflated, while keeping uncertainty about old uses explicit.

### 2. Inputs and required graph reads

Read the original definition and history, conflicting examples, proposed meanings, parent candidates, all uses and descendants, predicate tuples and roles, sources and evidence assignments, search aliases and Program contracts. Identify which original observations discriminate among the proposed meanings.

### 3. Preconditions and decision criteria

There is a substantive distinction in membership, participation, conditions or interpretation. Each new meaning has its own definition and justified parent. New senses need not be an exhaustive partition unless that claim is separately justified. There is an explicit unresolved category for uses whose sources do not determine a sense; it is a review disposition, not a fabricated ontology class.

### 4. Sequence of actions

1. Define the new senses with positive and boundary cases and search for existing equivalent records.
2. Classify each old reference as justified for one meaning, justified for several separate assertions, still valid only for the old general meaning, or unresolved.
3. For a predicate split, map and check each fact against each new signature and role meaning. Do not duplicate facts automatically.
4. Retain the original record if it remains a coherent broader meaning; otherwise retire its conflated meaning while preserving history and unresolved attributed content.
5. Stage new records, justified reference moves, parent changes and source links atomically.
6. Reassess old evidence separately for each supported target, with common origins preserved as dependencies.

### 5. Ambiguity and conflicts

Do not guess a sense from a title when the source context is insufficient. Leave such assertions attached to their original interpretation or as unresolved sourced content until clarified. Do not force overlapping valid senses into disjoint alternatives. If proposed distinctions are only stylistic, use aliases instead of splitting.

### 6. Checks before publication

Verify every moved assertion is entailed by its retained source under the new meaning. Check all references, roles, parents, views, descendant mappings, protection boundaries and old counterexamples. Ensure no evidence assignment was blindly cloned into every target and no ambiguous assertion disappeared.

### 7. Postconditions, dependencies and history

New identities express distinct meanings; the history explains the split and the disposition of each old use. Original evidence remains recoverable. Recompute affected conclusions and search projections. Confidence belongs to each newly assessed target; it is not copied from the broad or conflated original.

### 8. Examples and counterexamples

Split an ambiguous “memory” record into human memory, computer memory and agent memory where the original uses establish those senses; keep unclear reports unresolved. Do not copy one computer-memory performance test as evidence about human recall. Do not split a single algorithm into two concepts solely because English and Russian descriptions use different words.

## Algorithm: delete or retire

### 1. Purpose and motivation

Remove an invalid or redundant current representation when its meaning and references have a safe disposition. Retirement often preserves more explanatory value than deletion; neither action erases recorded history.

### 2. Inputs and required graph reads

Read the target, reason, complete inbound and outbound reference set, descendants, instances, predicate facts, signature/role links, evidence targets and dependency closure, retained sources, historical identity and all protected Self/Program connections. Check whether a replacement, merge or correction would preserve useful content.

### 3. Preconditions and decision criteria

The reason is substantive: erroneous duplication, invalid schema, withdrawn representation with preserved history, or another explicit retention decision. Isolation, low confidence, rarity, inconvenience and a wish to remove counterevidence are insufficient. Every reference and dependent conclusion has a planned disposition. Protected identities and executable contracts follow their own lifecycle, not generic deletion.

### 4. Sequence of actions

1. Prefer correcting an incorrect assertion or retiring a superseded meaning when deletion would hide useful lineage.
2. Distinguish deletion of a record from retraction of the claim it expresses. A retraction preserves the original report and reason; absence of a current fact is not its negation.
3. Plan reparenting, reassignment, retention or removal for every dependent reference. Deleting an abstract category does not authorize deleting its descendants or facts.
4. For predicate removal, migrate only facts with proven meaning-preserving mappings; retain others or reject the operation.
5. Apply permitted structural removals and rewrites atomically. Reject if a necessary reference remains or the available tools cannot perform the required lifecycle safely.

### 5. Ambiguity and conflicts

Keep contested but useful assertions with their epistemic state. A source retracting a claim may oppose it, but does not automatically erase other independent evidence. Preserve uncertainty when the correct replacement is unknown. A protected target cannot be made deletable by first removing its protective-looking edges.

### 6. Checks before publication

Check retention requirements, historical recoverability, no dangling references, connected accepted types, no orphan identity/state, schema validity and exact effect on protected bindings. Verify that cascade effects are explicit. Ordinary deletion has no implicit cascade, and a leaf-only check is insufficient when the leaf appears in predicate signatures.

### 7. Postconditions, dependencies and history

The current graph contains only the intended remaining representation. Preserve the removed meaning, source references, reason and prior evidence in history. Invalidate affected conclusions and indexes; recompute from remaining applicable grounds. Independent assertions do not disappear solely because one dependency was retracted. IDs are not recycled.

### 8. Examples and counterexamples

Remove a duplicate unused draft after proving it has no retained unique meaning or references. Retire a malformed predicate after safely handling its assertions. Do not delete an isolated observation, a strongly refuted hypothesis needed to explain learning, or `PROGRAM_FOR_PROCESS` edges to circumvent protection of an active Program.

## Algorithm: validate

### 1. Purpose and motivation

Establish what a proposed package or graph change actually guarantees: mechanical consistency, reviewed semantics and, only when measured, navigation performance. Validation must not convert plausibility into certainty.

### 2. Inputs and required graph reads

Read the complete candidate package or atomic write set, manifest/source records, referenced definitions, before-state revision, affected closure, algorithm decision record, semantic scenarios, round-trip representation and any optional navigation evidence. Read complete child lists; a truncated preview cannot establish coverage.

### 3. Preconditions and decision criteria

The candidate is reproducible from pinned inputs. Validation operates on the entire dependency closure and has a defined pass/fail result for each layer. Missing evidence for an optional optimization is a rejection of that optimization. Missing semantic review is not repaired by a passing JSON parser.

### 4. Sequence of actions

1. Validate manifest version, source records, module declarations, keys, names, aliases and field shapes. Reject missing files and unresolvable references.
2. Check one parent per accepted non-root type, no cycles, root reachability, correct representation distinctions and no duplicate canonical meanings across modules.
3. Check concrete signatures, role/value references, subject links, views and concrete-parent role mappings; abstract categories must not carry callable schemas.
4. Construct the complete proposed graph and run Core validation without exposing partial installation. Test rejection against invalid input and verify the before-state is unchanged.
5. Review definitions and source fidelity, necessary parent inclusion, boundary cases, scope and provenance/usage conditions. Compare semantic scenarios with the intended distinction.
6. Verify serialization and restoration preserve identities, schemas, links and metadata. Verify that application creation includes the template and restoration does not reseed it.
7. Check full-child reads, names, aliases and semantic discovery routes, including Self/Program coexistence. Run affected tests, related regressions and Program layout/integration checks where their boundaries changed.
8. Evaluate optional navigation changes with the matched procedure when applicable; report those results separately from structural tests.

### 5. Ambiguity and conflicts

Fail closed for malformed structures and unresolved required references. For a semantic disagreement, retain the rejected proposal and the specific unresolved question; do not silently invent a parent, role, source revision or license. A validation disagreement does not itself prove one reviewer's ontology correct. A pinned external identifier must be verified or identified as a local authored term rather than fabricated.

### 6. Checks before publication

Require all mandatory mechanical checks, resolution of semantic blockers and the appropriate protection/lifecycle review. Confirm no successful partial write remains after a rejected package. Verify that test summaries distinguish complete passes, failures, skipped checks and unperformed live evaluations.

### 7. Postconditions, dependencies and history

Publish a validation report tied to the exact candidate and graph revision, including the actual scenarios covered and known limits. Installation records the source package and symbol-to-ID mapping. Preserve rejected-case diagnostics. Validation creates no new empirical evidence about the world's entities, and a deterministic route pass is not counted as a successful LLM trial.

### 8. Examples and counterexamples

Reject a relation with a nonexistent semantic argument type before any node is installed. Accept a coherent abstract relation category without a signature. Reject a concrete predicate with an empty signature or incompatible specialization roles. Do not call a template validated because all IDs resolve while its “compiler” is still classified as a language.

## Release acceptance and ongoing maintenance

The first release MUST cover the prepared semantic distinctions below with explicit definitions and inspectable routes. An executable fixture may verify paths and role contracts; a reviewer must also inspect meaning. The same examples are regression checks after a change, not independent evidence of generalization.

| Required contrast | Semantic failure to detect |
|---|---|
| Language / source code / compiler / execution | Treating a language, a text, a translation tool and an occurrence as one kind. |
| Algorithm / implementation / run / result | Confusing a method with an artifact, episode or output. |
| Learning / belief update / parameter optimization | Treating all changes as the same process or assuming one entails the others. |
| Human / computer / agent memory | Merging biological ability, storage machinery and an agent's retained information. |
| Cause / temporal precedence / evidence dependency | Inferring physical causality from ordering or justificatory dependence. |
| Class / temporary role / state | Turning contextual participation or time-scoped condition into essential identity. |
| General process / own Evertree process | Colliding generic meanings with protected runtime organization or implying a second parent. |

Source upgrades are reviewed package changes, not blind synchronizations. Compare pinned revisions, deleted/renamed terms, changed definitions, parent choices and license conditions. Decide which changes apply to this profile and record local divergences. Do not update a running graph simply because the upstream ontology or checked-in package changed. A later migration facility needs its own lifecycle and rollback contract.

Prioritize growth by observed unresolved tasks, consequential missing distinctions, repeated search failures and stable reusable meaning. Frequency alone is not enough: a rare safety-critical distinction may matter. Add the necessary ancestors, subjects and argument types with every domain fragment. Do not create one node per wording, one domain copy per concept, or unreviewed bulk imports that expand only the apparent coverage.

Report actual included domains, concept/predicate counts, prepared scenario results, source fidelity checks and untested boundaries. Counts do not establish that eighty percent of user needs are covered. Keep a growing set of real independent task intentions for future coverage and LLM navigation evaluation, with source examples, exploratory cases and acceptance cases distinguished.
