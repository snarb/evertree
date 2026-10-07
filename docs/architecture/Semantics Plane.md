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

## RelationType: Fact Prototype
#topic_core

(def_id:: entity.RelationType)
> [!definition]
> **`RelationType`** is a concept that defines:
> 1. **The meaning of a fact** (what it asserts and what it does not assert).
> 2. **Its signature:** which slots exist, their labels, roles/types, and cardinalities.
> 3. **Views (projections):** named “views” of the same fact (how to retrieve arguments in different directions) **without creating inverse relations or copying data**.
^def-RelationType

> [!important]
> Principle: **there is one fact**. “Inverses” and “directions” are **views/projections** (queries), not separate relation instances.

`RelationType` participates in the abstraction ladder like all other concepts.

Use a small set of basic relations; add domain-specific `RelationType`s under the [[Core data structures#Concept Canonicalization and Semantic Linking|shared rules for reusing and creating concepts]].

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
- `ConceptSlot` is one Concept that defines the semantic type or role of a position:
  - usually a `Role` concept (`Parent`, `Owner`, etc.);
  - sometimes a non-role concept (`Person`, `Entity`) when defining a role is not worthwhile.

**Storing arguments in a relation instance:**

`args` is a dictionary keyed by `label`. Each slot value must match the type defined by the `ConceptSlot` contract and its declared cardinality. An argument may be a `Concept`, scalar, or another typed object under the [[Core data structures#Data Typing|shared typing rules]]; a numeric value does not have to be converted into a Concept. Saving objects and links between them follows the [[Core data structures#Objects and References|shared object and reference rules]].

### Views: Projections Over One Fact
#topic_details

(def_id:: entity.View)
> [!definition]
> **View** — a named projection of relation instances: fix the **inputs** slots, optionally apply a `constraints` filter, and return **outputs** values while retaining the source fact for every result.
^def-View

`AccessView` is a declaration within `RelationType`. A shared mechanism exposes declared views as methods on `RelationType` and executes them. A new view requires only a declaration; no separate Python function or `Program` is needed. Named views are declared for the reading patterns in use, not every possible combination of slots.

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
  concept: <Concept>        "semantic type or role of the position; its contract defines the allowed argument type",
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

To make the state part of the persistent graph, a program explicitly creates a `GraphDelta`:

```text
local Facet + related facts
→ graph-writing operator
→ GraphDelta
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
- **Prototype / Type** — generalized confidence in typical relationships, mechanisms, and priors: “how the world usually works and how confident we are in that.” This is the most inert level.

In the Semantics Plane, [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]] is conceptually similar to [[#Views: Projections Over One Fact|`AccessView`]] in its role, but is not an `AccessView` object. It is a computed epistemic view of one `CompetitionScope`, not a new semantic fact or a set of copied [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`BeliefData`]] records for alternatives.

**Interpreting scalar `Strength` / `Support` by level:**

- **[[Semantics Plane#STATE_IDENTITY (Facet ↔ Instance)|Facet]] / Episode:**
  - [[Uncertainty and Belief Tracking in the World Model#BeliefData|`Strength`]] = scalar confidence in a specific semantic value / relation instance / hypothesis in the current context.
  - [[Uncertainty and Belief Tracking in the World Model#Belief Representations|`Support`]] = quality of current evidence: sensors, observations, confirmations.
- **[[Semantics Plane#IDENTITY_TYPE (Instance ↔ Type)|Instance]]:**
  - `Strength` = confidence in a local characteristic/correction for this object relative to the prototype.
  - `Support` = how consistently this characteristic has appeared for this instance.
- **Prototype / Type:**
  - `Strength` = confidence in a typical relation, rule, prior, or mechanism.
  - `Support` = amount and quality of confirmation: statistics, experiments, reliable sources.

> [!note]
> For a `CompetitionScope`, one `LevelBelief` contains the scope's shared [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]]. `SemanticBeliefProfile` remains a view across levels, not a separate epistemic updater.

##### Example Data by Level

> [!example] The question “What is the main source of water on wet asphalt?” defines `CompetitionScope` `{rain, washing, other/mixed source}`.
>
> - **Episode level:**
>   - Profile view: `{rain: 0.55, washing: 0.35, other/mixed: 0.10}`, shared `Support: low`.
> - **Prototype level:**
>   - the relation `rain → wet` has generalized `Strength`;
>   - `Support` accumulates slowly from repeated confirmations.

##### `Belief_data` → Semantic Runtime

Runtime uses `SemanticBeliefProfile` levels differently:

- **Facet / Episode level** — choose the current semantic interpretation: active hypothesis, current object type, current cause, or current relation instance.
- **Instance level** — local exceptions, individual corrections, and instance-specific priors.
- **Prototype level** — general semantic priors, hierarchies, mereology, planning, and generalized mechanisms.

**Update rule:** episode-level belief may change quickly, but must not directly overwrite prototype-level belief. Prototype-level belief changes more slowly and requires sufficient Support.

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
