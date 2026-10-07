---
status: draft
target_version: next
ToDo:
---

## Introduction
#topic_core

Question: **“What is the object like?”**  
The Attribution Plane handles the properties, dimensions, and classifications of objects, states, and concepts.

(def_id:: et.AttributionPlane)
> [!definition]
> **Attribution Plane** — a plane whose purpose is to represent an object through its properties: to measure, compare, and normalize them, and use them in reasoning. In EverTree, an entity/state `x` is described through **property facts**, and a property reading is returned in the unified format `PropertyReading(U)`.
^def-AttributionPlane

In other words, the **Attribution Plane** is where the agent answers neither *“what is this, essentially?”* nor *“what will happen?”*, but questions such as:

- what color an object is,
- how fast it is,
- whether its risk is high,
- what surface it is on,
- what phase it is in,
- which class it belongs to under a given criterion.

### Key Principles

- `PropertyConcept` is the **type of aspect** we want to know about `x` (for example, `SpeedOfMotion`, `SurfaceUnder`, `UserIntent`, or `RiskLevel`).
- Properties **do not have to be stored as ready-made values inside an object**. Their values are obtained by reading, inference, or normalization; storing the result in the graph is a separate decision.
- **Read inputs** are defined by the contract of the property or its associated `Program`: which conditions refine the question and which data are needed to answer it. They are passed through [[#Operation Parameters|declared parameters]].
- An axis in this plane is an **operational utility for a property**: it reads, computes, compares, and normalizes property values, giving the agent practical access to them.

---

## Attribution Axis
#topic_core

(def_id:: et.AttributionAxis)
> [!definition]
> **Attribution Axis** — an axis within the Attribution Plane that defines one object property as a dimension on a scale `U` and specifies how to read, compare, and normalize that property and use it in reasoning.
^def-AttributionAxis

Intuitively, an axis is a way to answer questions such as:

- “How fast is this object?”
- “How high is the risk?”
- “What phase is the process in?”
- and so on.

An axis defines not only **what is measured**, but also **the form in which the value exists** and **which operations are allowed on it**.

### What an Axis Defines

Each axis in the Attribution Plane defines:

- **Domain (`X`)** — which objects, states, or concepts the property applies to.
- **Scale (`U`)** — the space of allowed values.
- **Measurement result** — the form in which the axis returns the property value.
- **Operation algebra** — which operations are allowed on values on this scale (comparison, distance, membership, normalization, filtering).
- **Update dynamics** — the rules for working with values on scale `U`.

> [!note]
> An axis is not the property itself. `PropertyConcept` defines the meaning of the property, while `AttributionAxis` defines the operational interface for accessing it.

> [!note] Attribution Plane specifics
> In the Attribution Plane, an axis returns not simply `Belief(U)`, but an attribution reading:
>
> ```text
> PropertyReading(U) := <value_U?, belief_data>
> ```
>
> `belief_data` is `BeliefData` for an individual value/claim or a `Profile` for one `CompetitionScope`. The exact contract is defined in [[#Formal Definition]].

---

## Attribution Plane

### Formal Definition
#topic_core

In the **Attribution Plane**, an axis defines an object property as a mapping:

$$
a_p: X \times I_p \rightarrow \mathrm{PropertyReading}(U_p) \cup \{\mathrm{unknown}\}
$$

where:

- **`p`** is `PropertyConcept`, the property being measured;
- **`X`** is the space of objects, states, or concepts to which the property applies;
- **`I_p`** is an allowed set of inputs under the [[#Operation Parameters|property-reading contract]]; this is mathematical notation, not a separate data type;
- **`U_p`** is the scale of values for this property;
- **$\mathrm{PropertyReading}(U_p)$** is an attribution result of the form:

$$
\mathrm{PropertyReading}(U_p) := \langle value_{U_p}?,\ belief\_data \rangle
$$

where:

- **`value_U`** is the property value on scale `U`;
- **`belief_data`** is [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`BeliefData`]] for an individual value/claim or a [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]] of mutually exclusive and exhaustive alternatives within one [[Uncertainty and Belief Tracking in the World Model#^def-CompetitionScope|`CompetitionScope`]].

With `BeliefData`, the `value_U` field is required. For a scope-backed reading, `Profile` is the canonical result; `value_U` is returned only as a derived point view under an explicit selection policy and does not materialize a reliable property fact.

Changing the source does not change scale `U_p`: a qualitative interpretation of a numeric property is returned on its own scale `U_norm` through [[#Numeric ↔ Qualitative Through a Criterion|Criterion]].

Concrete forms of **`value_U`** for each scale type are described in [[#Scale Types]]. General belief-update rules are described in [[Uncertainty and Belief Tracking in the World Model]]. `unknown` means that no applicable reading is available; see [[#5. Unknown]].

---

## Scale Types
#topic_core

Scale `U` defines **what kind of values** an axis returns and **which operations** are allowed on them.

The Attribution Plane uses four basic scale types:

1. **Nominal** — categorical;
2. **Ordinal** — ranked;
3. **Numeric** — numerical;
4. **Circular** — cyclic.

> [!note]
> A scale type determines not only the form of a value, but also the set of allowed operations. That is why it is important to distinguish, for example, a “class” from a “number,” even when both describe the same object.

---

### 1. Categorical Axis (Nominal)

**Meaning:**  
The axis defines classes or categories **with no natural ordering** among them.

This is suitable for properties where it makes sense to ask **“which class?”**, but not **“greater or smaller?”**

**Typical examples:**

- language,
- domain,
- role,
- intent type,
- error class,
- surface category.

Form of `value_U`:

- `value_U = C`, where `C` is one of the allowed values on nominal scale `U`.

The nominal scale type alone does not guarantee that values are mutually exclusive. The epistemic representation is selected according to the semantic contract of the specific Property:

```text
values mutually exclusive + exhaustive
→ one CompetitionScope
→ one Profile in belief_data;

multiple values may be true at once
→ separate binary BeliefTargets.
```

For example, `SQLProblemSolvingLevel(AgentA)` with scale `Low | Medium | High` uses a shared `CompetitionScope` and `Profile` if `Criterion` makes these values mutually exclusive and exhaustive. Independent properties such as `GoodAtSQL`, `GoodAtPython`, and `GoodAtDebugging` do not form such a scope.

**Graph representation:**

- Usually through `CLASSIFIED_AS(entity, C)`, where `C` is an allowed value on the scale of the given `PropertyConcept`, according to a criterion that matches the meaning of the classification and the query conditions.

**Allowed operations:**

- `equals(C1, C2)` — equality;
- `membership(C, S)` — set membership;
- predicates such as `=`, `∈`, and `NOT(...)`.

**Important:** If values have no natural order, the scale is **nominal**, not ordinal or numeric.

**Minimal example:**

- Property: `Language`
- Value: `CLASSIFIED_AS(Message#77, UA)`

---

### 2. Ordinal Axis

**Meaning:**  
The axis defines an **ordering** of values, but not a valid numerical distance between them.

This suits properties where it is meaningful to say:

- higher / lower,
- better / worse,
- more / less important,

but not to say strictly and universally **“by how much.”**

**Typical examples:**

- `RiskLevel`,
- importance,
- urgency,
- priority,
- degree of relevance.

Form of `value_U`:

- `value_U ∈ OrderedClassConcept`, where the classes form an explicitly ordered set.

If ordinal values are mutually exclusive and exhaustive, `belief_data` is the `Profile` for the corresponding `CompetitionScope`. The order of alternatives does not change the epistemic updater.

**Graph representation:**

- Usually through `CLASSIFIED_AS(entity, RiskHigh)` and similar classes.
- The order itself is explicitly defined by the `ValueOrder` structure, not by class names.

**Allowed operations:**

- `compare(c1, c2) -> {less, equal, greater, incomparable}`;
- sorting;
- top-k;
- predicates `>=`, `<=`.

For an ordinal scale, differences such as these cannot be calculated safely:

- `High - Mid`;
- “twice as high.”

If valid deltas and distances matter for a property, use a **numeric** scale instead.

**Minimal example:**

- Property: `RiskLevel`
- Value: `CLASSIFIED_AS(Task#A, RiskHigh)`

---

### 3. Numeric Axis

**Meaning:**  
The axis defines a property as a quantity on a numeric scale, where the following are valid:

- comparison,
- distance,
- ranges,
- deltas,
- and, sometimes, aggregation.

This is the main axis type for quantitative measurements.

**Typical examples:**

- speed,
- mass,
- temperature,
- cost,
- time,
- latency,
- probability,
- risk score.

**Forms of `value_U`:**

- a number (`float`, `int`);
- an interval;
- parameters of a distributional estimate;
- a sketch/quantiles, when the value itself is an approximate estimate.
- `Belief_data` separately.

**Graph representation:**

- A scalar value uses `HAS_NUMERIC_VALUE(entity, property, value[, unit])`.
- An interval, distribution, or other numerical estimate is a typed result under the [[#4. Typed Result or Computation|axis source contract]].

**Allowed operations:**

- `<, >, <=, >=`;
- `in [a,b]`;
- `≈` with a tolerance;
- `distance(v1, v2)`;
- delta;
- normalization relative to a domain.

**Norms and comparability:**  
Numeric axes almost always need interpretation **relative to a domain**:

- `112 km/h` means different things for a car and an airplane;
- `50 ms latency` may be good or bad depending on the type of system.

Numeric values are therefore often supplemented by domain distributions and normalization criteria.

**Minimal example:**

- `HAS_NUMERIC_VALUE(MyCarNow, SpeedOfMotion, 112 km/h)`

---

### 4. Circular Axis

**Meaning:**  
The axis defines values that live **on a circle**, rather than a linear line.

On this scale, the beginning and end coincide:

- `0° ≡ 360°`;
- the end of a cycle returns to the same point.

This matters for phases, angles, periods, and rhythms.

**Typical examples:**

- angle,
- phase,
- seasonal cycle,
- periodicity,
- stages of a recurring process.

**Value form:**

- a number with circular topology;
- or discrete phases, if the cycle is divided into stages.

**Graph representation:**

- Numeric form: `HAS_NUMERIC_VALUE(entity, property, θ[, unit])`
- Discrete form: `CLASSIFIED_AS(entity, Phase3)`

**Allowed operations:**

- `circular_distance(θ1, θ2)` — distance along the shorter arc;
- `≈` with a tolerance on the circle;
- `shift(θ, Δ)` — phase shift (optional).

**Important:** A linear metric breaks the meaning.

For example, the distance between `350°` and `10°` is `20°`, not `340°`.

**Minimal example:**

- `HAS_NUMERIC_VALUE(EngineNow, PhaseAngle, 350 deg)`

---

### Relationship Between Scale Type and Reasoning

The scale type determines **which questions can be asked correctly of an axis**:

- **Nominal** — “is this the same value or not?”
- **Ordinal** — “which is higher/lower?”
- **Numeric** — “by how much greater/closer/farther?”
- **Circular** — “how close are they on the cycle?”

Therefore, choosing a scale type is part of the property's semantic contract, not a cosmetic choice.

---

## Property Facts and Relation-Backed Readings
#topic_core

The Attribution Axis does not itself store a property value. It reads facts or typed results, or computes a value using a model or rule associated with the property.

The following must be distinguished:

- **native property facts** — facts that directly store a property's value in the Attribution Plane;
- **relation-backed readings** — attribution readings whose values are retrieved from a semantic relation instance.

Property facts separate:

- **what is measured** — `PropertyConcept`, such as `SpeedOfMotion` or `UserIntent`;
- **which entity is measured** — `Entity`, `Facet`, `Instance`, or `Prototype`;
- **which value was obtained** — a number or class;
- **the epistemic state of the reading** — `BeliefData` or the shared `Profile` of a scope.

The Attribution Axis uses property value sources applicable to its scale:

1. numeric property fact;
2. membership property fact;
3. relation-backed reading from the Semantics Plane;
4. [[#4. Typed Result or Computation|typed result or computation]] under a declared semantic binding.

---

### 1. Numeric Property Fact

Used when a property value is a number.

```python
RelationType HAS_NUMERIC_VALUE {
  name: "HAS_NUMERIC_VALUE"
  description: "Numeric property fact: an entity has a numeric value for a property. The value is stored as a number (not as a Concept) and carries Belief_data on the edge. It is not a classification (CLASSIFIED_AS) and does not define taxonomy or mereology."
  signature: [
    entity   = Entity   "entity to which the measurement is attached (Facet/Instance/Prototype/...)"
    property = Property "which property is measured (Concept of meaning: SpeedOfMotion, Latency, ...)"
    value    = Number   "numeric value (float/int)"
    unit?    = Unit     "unit of measurement (when applicable)"
  ]
}
```

**Examples:**

- `HAS_NUMERIC_VALUE(MyCarNow, SpeedOfMotion, 112, km/h)`
- `HAS_NUMERIC_VALUE(ServerNow, Latency, 84, ms)`
- `HAS_NUMERIC_VALUE(Object#7, Mass, 12.5, kg)`

---

### 2. Membership Property Fact

Used when a property value is expressed as membership in a class.

```python
RelationType CLASSIFIED_AS {
  name: "CLASSIFIED_AS"
  description: "Fact that an entity belongs to a class_concept. It is a property value if class_concept belongs to the property's scale and Criterion matches the meaning of the classification and the query conditions."
  signature: [
    entity        = Entity       "entity being classified (Facet/Instance/Prototype/...)"
    class_concept = ClassConcept "class/category as a Concept (Fast, OnRoad, RefundIntent, UA, ...)"
  ]
}
```

`CLASSIFIED_AS(entity, C)` counts as a value of property `property` if `C` belongs to its scale and the applicable `Criterion` links the class to the property while preserving the meaning of the evaluated claim. A class such as `Fast` may be a qualitative interpretation of a numeric property, but it does not replace the value on its Numeric scale. Without such a link, the classification remains an independent claim.

If the allowed values of a Property are mutually exclusive and exhaustive, each allowed proposition `CLASSIFIED_AS(entity, C)` denotes an alternative in one [[Uncertainty and Belief Tracking in the World Model#^def-CompetitionScope|`CompetitionScope`]]. Evidence is assigned to the scope as a whole, and `Strength(C)` is read from the shared [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]]; separate beliefs, `Support`, or `PriorSupport` are not created for each `C`.

(def_id:: et.Criterion)
> [!definition]
> **`Criterion`** — a rule that defines the conditions for interpreting or evaluating a claim or result within a particular scope of application.
^def-Criterion

For classification, `Criterion` links `ClassConcept` to `PropertyConcept` and defines the scope, required inputs, and conditions for membership in the class. Together with the scale, it determines whether alternatives are mutually exclusive and exhaustive. The rule does not assert that a specific object belongs to a class; for example, it defines the speed and domain at which an object is considered `Slow`, `Normal`, or `Fast`.

A criterion may be part of a semantic definition or a [[Process Plane/Program Layer#Program Contracts|Program contract]]; a separate node or copy of the rule is not required. Evaluation of numeric values and models follows the [[Uncertainty and Belief Tracking in the World Model#Numeric and Distributional Values|shared numeric belief contract]].

`Profile` represents only epistemic uncertainty among specified alternatives; it does not compensate for an incomplete or ambiguous scale.

If there is only a one-off claim such as “AgentA is good at solving SQL problems,” but no useful general `PropertyConcept` + scale + `Criterion`, do not create an artificial fact `SQLProblemSolvingLevel(AgentA) = High`. The statement remains a [[Core data structures#^def-Claim|`Claim`]] until sufficiently rigorous semantic structure exists.

**Examples:**

- `CLASSIFIED_AS(MyCarNow, Fast)` is a qualitative interpretation of `SpeedOfMotion` under criterion `Fast-from-SpeedOfMotion`.
- `CLASSIFIED_AS(Message#77, UA)` counts as a value of property `Language` if `UA` is an allowed `Language` value.
- `CLASSIFIED_AS(UserMessage#12, RefundIntent)` counts as a value of property `UserIntent` if an intent classification criterion exists.

---

### 3. Relation-Backed Attribution Projection

Used when a property value is not stored as a separate native fact in the Attribution Plane, but is obtained as a projection of a structural relation fact. The structural relation fact itself belongs to its native plane: Semantic, Structural, or Hierarchy, depending on the relation type.

Example:

```python
ON_SURFACE {
  vehicle = MyCar
  surface = Road#17
}
```

Its attribution projection:

```python
SurfaceUnder(MyCar) = Road#17
```

Here:

- `ON_SURFACE(vehicle, surface)` is a native structural relation fact;
- `SurfaceUnder` is a `PropertyConcept` in the Attribution Plane;
- `Road#17` is `value_U`, obtained from the `surface` output slot;
- `belief_data` is inherited from the source relation fact.

The Attribution Plane does not duplicate the structural relation fact. It only defines how to read it as a property value.

The axis uses the [[Semantics Plane#Shared Executor and Result|shared view executor]], passing temporal query parameters from [[#Reading State Properties]]. For `ON_SURFACE`, the `get_surface` view declares `inputs=["vehicle"]`, `outputs=["surface"]`, and `output_arity="list0"`. In the example, `select_one` applies `latest` to `source_fact` metadata and returns `None` when there are no candidates or the policy does not allow a selection:

```python
matches = ON_SURFACE.get_surface(
  vehicle=MyCar,
  valid_at=valid_at, known_at=known_at,
)
if matches is unknown:
  return unknown
match = select_one(matches, policy="latest")
if match is None:
  return unknown

return PropertyReading(
  value_U = match.value,  # Road#17
  belief_data = match.source_fact.belief_data
)
```

Here `source_fact.belief_data` denotes the shared belief reading with the same `valid_at` and `known_at`. This reading does not create a new relation fact or duplicate the original link.

For fast filtering, normalization, or explainability, a summary class may also be materialized:

```python
CLASSIFIED_AS(MyCarNow, OnRoad)
```

Do so only when it provides operational value: faster search, compression, explainability, normalization, or caching an expensive inference.

Such a summary class is governed by `Criterion` / a mapping rule and a Materialization Policy.

---

## Axis Interface
#topic_details

An Attribution axis reads or computes a value through the sources defined for a property and returns [[#Formal Definition|`PropertyReading(U)`]] or `unknown`.

`measure`, `read_property`, and `reconstruct_property` share a contract for sources and [[#Reading State Properties|temporal constraints]]. These constraints also apply when reading a norm or rule for `normalize`. Reading performs the computation specified by the contract within the task budget; it does not search for or train new models. The result receives ordinary [[Memory#^def-ResultProvenance|provenance]]; materialization in the persistent graph is handled separately through [[Core data structures#Updating the Persistent Graph|`GraphDelta`]].

In examples, `fact.belief_data` denotes the computed [[Uncertainty and Belief Tracking in the World Model#Read-Time Computation and Provenance|belief read]] for the corresponding target. A saved historical snapshot does not replace the current estimate.

### Operation Parameters

The contract for a property, criterion, or associated `Program` declares required parameters, their types, and [[Process Plane/Program Layer#^program-semantic-interface|semantic roles]]. Inputs may include the conditions of the question, information about the object itself, external facts, or assumptions. Fixed conditions belong in the contract; changing conditions are passed as named arguments. A saved result uses the conditions attached to it if they match the query.

The task's [[Cognition and Attention#^def-PreparedContext|`PreparedContext`]] is one source for [[Process Plane/Program Layer#^def-ArgumentPreparation|preparing arguments]] for a specific call. Ready arguments can be passed directly. Axis operations do not require a universal `context` parameter.

Conditions that change the meaning of a question are included in the [[Uncertainty and Belief Tracking in the World Model#Belief and BeliefTarget|canonical target]]. Additional observations about the same question refine its estimate. Hypothetical conditions are stated explicitly as assumptions and retain that status in the result.

In the signatures below, `...` denotes additional named parameters specific to a contract. A parameter may be omitted when its value or retrieval method is defined by the contract; missing required data or an ambiguous question yields `unknown`.

---
### `measure`

```text
measure(x, property, *, valid_at=now, known_at=now, ...)
    -> PropertyReading(U) | unknown
```

`measure` reads a property of an already selected object or state `x`. The axis and sources are defined by the property's contract; resolving an Instance state is handled by [[#Reading State Properties|`read_property`]].

---
### Source Applicability Rules

A source must match the property, its scale, and the query conditions, including declared parameters, `valid_at`, and `known_at`. The order of the subsections below does not define priority: the property-reading contract determines which applicable source to use. The absence of a numeric value does not permit returning a class in its place.

#### 1. Numeric Fact

If this fact exists:

```python
HAS_NUMERIC_VALUE(x, property, v)
```

the axis returns:

```python
PropertyReading(
    value_U=v,
    belief_data=fact.belief_data
)
```

where `belief_data` is the value read from the corresponding `HAS_NUMERIC_VALUE` fact.

---
#### 2. Membership Fact

If the property's semantics define a `CompetitionScope` with mutually exclusive and exhaustive alternatives, the axis returns its shared `Profile`, whether or not an individual `CLASSIFIED_AS(x, C)` fact has been selected or materialized:

```text
PropertyReading(
  belief_data = Profile {
    strengths = {
      Low:    0.05,
      Medium: 0.25,
      High:   0.70
    },
    support = ...,
    prior_support = ...
  }
)
```

Under an explicit selection policy, the reading may also return `value_U = High`; this is a derived point view, not a replacement for the `Profile`. Evidence updates the whole scope through the shared `CompetitionScopeUpdater`; other invariants are defined in [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]].

When there is no evidence from the agent's own experience, the specified scope prior applies. Reading does not create the scope or its alternatives: a nominal scale alone does not guarantee mutual exclusivity and exhaustiveness.

For an independent binary classification, reading `CLASSIFIED_AS(x, C)` returns:

```python
PropertyReading(
   value_U=C,
   belief_data=fact.belief_data
)
```

In either case, classes must belong to the requested scale, and `Criterion` must link them to the property, apply to the domain and context, and match the target's meaning. For binary classification, `Strength` estimates class membership and `Support` reflects the evidence assigned to it, accounting for the criterion's applicability.

If only `Fast` is known, find the corresponding `CLASSIFIED_AS(x, Fast)` through a [[Semantics Plane#Views: Projections Over One Fact|relation view]] or retrieval. The [[Uncertainty and Belief Tracking in the World Model#Read-Time Computation and Provenance|shared belief read]] returns `BeliefData` for an independent classification or the `Profile` for its scope, accounting for query conditions and temporal constraints. This information can be used for filtering without a numeric estimate.

A numeric reading of `SpeedOfMotion` remains unavailable until an applicable numeric estimate exists. When a numeric value is available, [[#Numeric Normalization|`normalize`]] returns its qualitative interpretation.

---
#### 3. Relation-Backed Attribution Projection

If a property is defined as an attribution projection of a structural relation fact, for example:

```python
ON_SURFACE { vehicle=x, surface=s }
```

the axis applies the declared source rule (`PropertySource`):

```python
source_relation = ON_SURFACE
source_view = "get_surface"
selection_policy = "latest"
```

and returns:

```python
PropertyReading(value_U=s, belief_data=belief_data)
```

- The original `ON_SURFACE` remains a native relation fact in its own plane.
- If a summary class such as `OnRoad` is created, it must be authorized by a `Criterion` / Materialization Policy.

If the relation fact itself or its arguments are needed, use a view for the relevant `RelationType`. Use `read_property` only when the relation has a defined projection onto a specific `PropertyConcept`.

```text
ON_SURFACE.get_surface(vehicle=MyCar)
→ projections of matching facts, retaining source_fact;

read_property(MyCar, SurfaceUnder)
→ property reading under its source rule, including candidate selection.
```

Both interfaces use the same source facts without duplication.

---
#### 4. Typed Result or Computation

A source may be a saved typed result or a computation from a Program, model, or rule already linked to the property. The [[Process Plane/Program Layer#Semantic Types for Arguments and Results|semantic binding]] defines which object, property, and conditions the result concerns; a matching Python type is not sufficient. This allows reading intervals, distributions, and other numeric estimates while preserving the scalar `HAS_NUMERIC_VALUE` contract.

Save and address the result under the [[Core data structures#Objects and References|general object and reference rules]]. A historical result retains the value used at the time, not a reference to the estimator's mutable current state. A typed output does not automatically become a persistent property fact; the [[Memory#Trace-Local and Persistent Results|general materialization rules]] apply.

---
#### 5. Unknown

If an applicable reading is unavailable, including because required inputs are missing, return:

```python
unknown
```

The absence of a selected class or evidence from the agent's own experience does not by itself mean `unknown`: for a defined scope, follow the [[#2. Membership Fact|Profile reading rules]].

---
### `compare(v1, v2)` / `distance(v1, v2)`

These operations apply only when the property's scale `U` supports them.

- **Nominal:** `equals`, `membership`, and canonicalization/synonym handling when needed. There is no ordering or distance.
- **Ordinal:** `compare`, sorting, top-k. There is an order, but no valid difference value.
- **Numeric:** `compare`, `distance`, differences, ranges, and optimization.
- **Circular:** cyclic closeness, phase shifts, and shortest-arc distance.

For example:

```python
distance(350 deg, 10 deg) -> 20 deg
```

not `340 deg`.

---
### `normalize`

```text
normalize(v | dist, property, domain, *, valid_at=now, known_at=now, ...)
    -> PropertyReading(U_norm) | unknown
```

**Purpose:** convert a raw value into a form interpreted relative to the domain norm.

Normalization is needed because the same numeric value may have different meanings for different object types and contexts.

For example, `112 km/h` may be normal for a car, but impossible or anomalous for a person.

---
#### Numeric Normalization

For numeric scales, normalization uses the domain distribution (quantiles, z-score, and similar methods).

Example:

```python
normalize(112 km/h, SpeedOfMotion, domain=Vehicle)
```

Normalization returns `PropertyReading(U_norm)`, for example:

```python
PropertyReading(
    belief_data=Profile {
        strengths = {Slow: 0.05, Normal: 0.20, Fast: 0.75}
    }
)
```

Under an explicit selection policy, the reading may also return `value_U = Fast`.

---
#### Ordinal / Nominal Values Derived from Numeric Values

For qualitative classes derived from numbers, normalization applies a banding criterion to the supplied value. For example, the value from:

```python
HAS_NUMERIC_VALUE(MyCarNow, SpeedOfMotion, 112 km/h)
```

is interpreted under the criterion:

```python
Fast-from-SpeedOfMotion
```

The result is a qualitative reading under the [[#Numeric Normalization|normalization rules]]. A saved `CLASSIFIED_AS(MyCarNow, Fast)` classification is read independently under the [[#2. Membership Fact|membership-fact rules]]; `normalize` does not search for a classification on the object.

> [!note]
> Normalization does not have to materialize a derived fact. It may return a result lazily; whether to write it to the graph is governed by the Materialization Policy.

### Reading State Properties

#topic_details

To read a state, use a specific `PropertyConcept`, not an abstract `state_variable`.

Primary interface:

```text
read_property(
    subject: Concept,
    property: PropertyConcept,
    *,
    valid_at: time = now,
    known_at: time = now,
    ...
) -> PropertyReading | unknown
```

- `subject` — an object to which the property applies: an Instance, selected Facet, or another Concept.
- `property` — the requested property.
- `valid_at` — world time to which the value applies.
- `known_at` — the time through which the agent's knowledge is considered.

Examples for contracts with the stated parameters:

```text
read_property(Igor, HealthStatus)
read_property(car, SpeedOfMotion, reference_frame=road_frame)
read_property(source, SourceReliability, domain=Programming)
```

General read order:

```text
1. Resolve the object or state under the property contract and time constraints.
2. Get a value from an applicable source under the axis's shared rules.
3. Read BeliefData or the target's Profile under the shared belief contract.
4. Return PropertyReading or unknown.
```

When reading an Instance state, the first step uses [[Semantics Plane#get_facets|persistent Facets]] applicable at `valid_at` and known at `known_at`; a supplied Facet is read directly. For a fact on the Instance itself, a relation projection, or a linked Program, an intermediate Facet is not required.

If `HealthStatus` defines mutually exclusive and exhaustive values, `read_property` returns the shared `Profile` under the [[#2. Membership Fact|membership-fact rule]].

---
### Historical Reconstruction of a Property

#topic_details

To reconstruct the agent's knowledge at an earlier point, use a wrapper around the same read:

```text
reconstruct_property(
    subject: Concept,
    property: PropertyConcept,
    *,
    valid_at: time,
    known_at: time,
    ...
) -> PropertyReading | unknown
```

It calls `read_property` with the same arguments and required `valid_at` and `known_at` values.

The `known_at` limit applies to evidence, actual inputs, code, rules, norms, and model state in every read source, including `measure` and `normalize`. Reconstruction uses a saved result or computes from compatible historical versions; available accuracy is limited by [[Memory#Retention, Compression, and Forgetting|the detail retained in memory]].

**The initial implementation should be simple:** the MVP only needs to support reads at times of available completed [[Cognition and Attention#^agent-backup|agent backups]]:

1. Load the backup corresponding to `known_at` into a separate read-only environment, without resuming workflows.
2. Use the saved data, active evidence, models, and rules. Time-dependent calculations account for the specified `valid_at` and `known_at`.
3. Perform an ordinary property read in that environment.
4. If the required state or dependency is missing, return `unknown`; do not substitute today's data or models.

Reconstruction at every point in time is not required. Reconstruction between backups is permitted when change history is sufficient; the nearest backup must not be presented as the state at a different `known_at`.

A [[Memory#^def-TraceEvent|saved trace]] shows a computation that was actually performed in the past. A new calculation using historical state does not itself mean the agent had that result at the time.

---


## Operational Roles of Attribution Axes
#topic_core

The Attribution Plane does more than store properties. It gives the agent operational access to them:

```text
measure → compare → constrain → filter → select → normalize
```

Distinguish two independent levels:

- **Scale type `U`** — which values the axis returns: `Nominal`, `Ordinal`, `Numeric`, or `Circular`.
- **Axis role in the task** — what the agent does with the value: filter, select, rank, find the nearest match, normalize, or check consistency.

---
### 1. Filtering Role

An axis is used as a constraint for selecting candidates.

This is predicate-based filtering: the agent does not search for “the best” option; it discards anything that fails the condition.

Examples:

- **Nominal:** `Color = Red`; `Language ∈ {EN, UA}`
- **Ordinal:** `RiskLevel >= Medium`; `Priority <= Low`
- **Numeric:** `Latency >= 50 ms AND Latency < 120 ms`
- **Circular:** `circular_distance(Phase, θ) <= 20 deg`; `Phase ≈ 180 deg`

In this mode, the axis must support predicates applicable to its scale:

```python
=, !=, <, >, <=, >=, ≈, (AND/NOT)
```

The meaning of equality depends on scale type:

- for discrete values — exact equality;
- for numeric and circular values — equality within a tolerance;
- for a scope-backed Property — a `Strength` threshold for an alternative in the shared `Profile`.

Filters may combine multiple properties:

```python
Color = Red AND Weight < 10 kg AND SurfaceType = Road
```

or:

```python
Intent = RefundIntent AND AngerLevel >= Medium AND LegalThreat = false
```

This lets the agent form working sets of candidates for reasoning, planning, and action selection.

---
### 2. Selection / Retrieval Role

An axis serves as a selection space when the agent needs to choose, rank, or find suitable values rather than merely check a condition.

In this mode, the axis helps to:

- rank candidates;
- find top-k values;
- find the nearest value;
- search for a value that is slightly larger or smaller;
- choose a minimum or maximum;
- find candidates in a range and rank them;
- choose the next value or candidate nearest a target range.

Examples:

- choose the task with the highest `Priority`;
- find the object whose size is nearest a target;
- first filter users by `RiskLevel >= Medium`, then rank those remaining by `RiskScore`.

Selection / Retrieval naturally support:

- **Ordinal** — sorting, top-k, min/max;
- **Numeric** — distance, difference, nearest value, range search, optimization;
- **Circular** — circular distance, nearest phase, phase shift;
- **Nominal** — only when there is a similarity/canonicalization layer or a selection policy over a `Profile`.

> [!note]
> Selection / Retrieval over an axis is not graph navigation in the general sense. It is selection or search in the value space of a specific property.

---
### 3. Normalization Role

An axis may convert a raw value into a form interpreted relative to the domain norm.

Normalization is needed because the same value may have different meanings for different object types, populations, and contexts. For example, `112 km/h` may be normal for a car but impossible or anomalous for a person.

Normalization may return a qualitative class:

```python
High
```

or an epistemic `Profile` over mutually exclusive and exhaustive classes:

```python
Profile {
  strengths = {Low: 0.05, Mid: 0.20, High: 0.75}
}
```

Normalization may be used before filtering:

```python
LatencyLevel >= Medium
```

or before selection:

```python
filter RiskLevel >= Medium, then rank by normalized RiskScore
```

Normalization itself does not select an object; it changes how the value is interpreted.

> [!note]
> Normalization does not have to materialize a derived fact. It may return a result lazily; whether to write it to the graph is governed by the Materialization Policy.
### 4. Consistency / Sanity Checks

Axes help determine whether a new value is a chimera, a source error, or an observation artifact.

For example, a speed may be too high for the given object type.

Sanity checks use:

- prototype/type norms;
- `Support`;
- population distributions;
- property compatibility;
- instance-level observation history.

---
### 5. Counterfactual / What-If Reasoning

An axis allows the agent to mentally change one property and check what would change.

Examples:

- what would happen if `Mass` increased;
- what would happen if `Latency` decreased;
- what would happen if `UserIntent` changed from `RefundIntent` to `CancellationOnly`;
- what would happen if an object were `Fragile`.

Counterfactual reasoning requires properties to be sufficiently distinct from one another.

If an axis does not represent a real distinction and is only an arbitrary label, what-if reasoning over it will produce false conclusions.

The Attribution Plane provides a fast layer of practical reasoning before more expensive analysis.

---
### 6. Learning Hooks

Attribution axes provide stable attachment points for new observations: a property value can be recorded, compared with an earlier state, used for normalization, or passed to the shared belief-update mechanism.

Details on updating `Strength`, `Support`, instance-level exceptions, and prototype-level statistics are described in [[Uncertainty and Belief Tracking in the World Model]].

---

## Numeric ↔ Qualitative Through a Criterion
#topic_details

Qualitative classes such as `Fast`, `Slow`, `HighRisk`, and `LowTrust` are often based on numeric or structural data but remain separate `ClassConcept`s in the graph.

Distinguish:

- **raw value** — the exact or original value of a property;
- **qualitative class** — a category convenient for reasoning;
- **classification Criterion** — a rule that links the two.

For example:

```text
HAS_NUMERIC_VALUE(E_now, SpeedOfMotion, 112 km/h)
CLASSIFIED_AS(E_now, Fast)
```

The value `112 km/h` is stored as the exact value of the `SpeedOfMotion` property. The class `Fast` is stored as a qualitative interpretation of that value. The classification [[#^def-Criterion|`Criterion`]] defines the conditions under which a value counts as `Fast`.

The epistemic representation of qualitative classes follows the nominal/ordinal scale contract from [[#Scale Types]], not how the class was derived from a numeric value.

---
### Revising a Qualitative Interpretation

The meaning of a classification is defined by its canonical target, not by the current mapper or label text. Retain the rule used, norm data, and material context through [[Memory#^def-ResultProvenance|shared provenance]]. Distinguish:

- **Changing the class definition** — a [[Uncertainty and Belief Tracking in the World Model#Semantic Target Revision|semantic revision]], with a new target if the question's meaning changes.
- **Changing the norm as input to the existing rule**, such as “above the population's current q80” — a change to the conditions the result applies to.
- **Training the mapper while the class meaning stays the same** — a change to how the same question is estimated.

Reassess dependent evidence under the [[Uncertainty and Belief Tracking in the World Model#Evidence Reassessment and Belief Recalculation|shared reassessment rules]]. A new norm or model does not redefine a historical result; a change to the object's actual state follows the ordinary [[Core data structures#Closing a Temporal State|Facet lifecycle]].

---
### Materialization Rule

A qualitative class may be:

1. **computed lazily** when requested;
2. **materialized** as `CLASSIFIED_AS` when it provides value.

Materialization is allowed when a class:

- is often used in filtering or rules;
- speeds up reasoning;
- improves transfer of experience;
- makes results easier to explain;
- reduces the cost of recomputation.

Materialization is prohibited when a class is a cheap alias with no new operational value.

---
## Axis Validity Criteria
#topic_details

An Attribution Axis is a hypothesis that a particular property deserves its own representation.

An axis is valid when it pays for itself through better prediction, action selection, learning, or reduced computational cost.

---

### I. Three Criteria for a Valid Axis

#### 1. Discrimination

An axis must distinguish objects or states.

If all relevant objects have the same value on this axis, it adds no information.

```text
No distinction → no axis.
```

Examples of valid distinctions:

- objects look alike but have different masses;
- users write similar messages but have different intents;
- tasks seem similar but differ in risk level.

---

#### 2. Semantic Stability / Non-Artifactuality

An axis must capture a stable distinction rather than an accidental observation artifact.

The property must retain its meaning when irrelevant observation conditions change.

Example:

- `Color` is valid if an object remains red under different lighting conditions.
- `BrightnessInCurrentPhoto` may be a useful image measurement, but must not replace the stable property `Color`.

Boundary:

```text
Semantic stability does not mean absolute invariance;
it means stability of meaning under permitted context changes.
```

---

#### 3. Operational / Interventional Relevance

An axis must be connected to consequences that can be checked.

Ideally, the agent can intervene and observe how the value on the axis affects the object's behavior.

Example:

- the agent pushes an object;
- a light object moves;
- a heavy object barely moves;
- the `Mass` axis emerges.

If direct intervention is impossible, an axis may still be valid through a stable predictive test.

---

### II. Anti-Patterns

#### 1. Spurious Correlation

The axis captures a spurious correlation without a stable causal or predictive relationship.

Example:

```text
Pirates ↔ global warming
```

---

#### 2. Tautology

The axis duplicates an existing axis without enabling a new operation.

Example:

```text
LengthMeters
LengthFeet
```

---

#### 3. Chimerical Axis

The axis depends on the observer's momentary state rather than on the object or a stable relationship between the object and its context.

Example of a bad axis:

```text
FeelsImportantToMeRightNow
```

It may describe the agent's state, but must not replace a property of the object.

---

#### 4. Pure Alias

The axis adds no new structure and only renames an already available fact.

Example:

```text
ON_SURFACE(MyCar, Road#17)
```

There is no need to materialize a separate derived fact or Facet for `SurfaceUnder` if the value is always cheap to obtain through standard navigation and provides no new operational benefit.

---

### III. Practical Axis Acceptance Test

A new axis is accepted if at least one of the following holds:

1. it improves forecasts on metrics selected in advance [[Process Plane/Program Evaluation and Testing#Evaluation (Quantitative)|for quality evaluation]];
2. it improves action selection;
3. it speeds up filtering or search;
4. it improves transfer of experience between similar cases;
5. it reduces computational cost;
6. it makes reasoning more explainable without reducing accuracy.

If none of these conditions holds, the axis should be rejected or degraded.

## Genesis of New Attribution Axes

#topic_details

AGI creates a new Attribution Axis when existing properties are insufficient for prediction, choice, explanation, or compression of experience.

By default, the number of axes should be the minimum necessary.

```text
More axes ≠ a better model.
A good axis reduces uncertainty or the cost of reasoning.
A bad axis increases noise and overfitting.
```

---

### 1. Prediction Gain / Surprise Reduction

> [!IMPORTANT] Rule: Emergence of a New Axis
> **Concept:** A new axis emerges when objects look the same on existing properties but behave differently.
>
> **Action:** If objects cannot be distinguished in the current property space but produce different consequences, create a candidate axis.

> [!EXAMPLE] Example: Interaction with the Physical World
> AGI sees two visually identical black boxes:
> - the first moves easily;
> - the second barely moves.
>
> They have the same current properties, but respond differently to an action.
>
> **New axis emerges:** `Mass`
>
> > [!SUCCESS] Axis Validation
> > After introducing the `Mass` axis, behavior becomes predictable according to the law:
> > $$F = m \cdot a$$
> > The `Mass` axis **improves the accuracy of behavior forecasts** and is therefore accepted by the system as valid.

---

### 2. Decision Utility

A new axis emerges when a distinct property improves the selection, ranking, or filtering of objects.

> [!TIP] Rule: Identifying a Hidden Axis
> If reaching a goal requires consistently choosing among objects, and existing properties **poorly explain which choices succeed**, create an axis that encodes the **relevant distinction**.

> [!EXAMPLE] Example: Assessing Sources
> AGI must choose which source to trust when sources conflict.
>
> **Inputs:**
> - a forum post;
> - a PubMed article;
> - an internal system log;
> - a user message.
>
> **New axis emerges:** `Credibility`
>
> Sources can now be compared as objects on this axis:
> ```text
> Credibility(RedditPost) = low
> Credibility(PubMedArticle) = high
> Credibility(SystemLog) = very_high
> ```

---

### 3. Compression Gain

> [!TIP]
> **Concept:** A new axis emerges when many observed features change together in a stable way and can be replaced by one more compact variable.
>
> **Rule:** If several sensors or features change in synchrony as a result of one hidden cause, create a candidate axis for that latent variable.

> [!EXAMPLE] Example: A Spinning Coin
> AGI sees a spinning coin. At the same time, these properties change:
> - ellipse shape;
> - highlights;
> - visible contour;
> - aspect ratio;
> - shadows.
>
> Storing every pixel change as an independent property is inefficient.
>
> **Axis emerges:** `RotationAngle`
> One coordinate on this axis explains many observed changes.

---

### 4. Normalization Gain

> [!TIP]
> **Concept:** A new axis or Criterion may emerge when raw values are difficult to compare across domains.

> [!EXAMPLE] Example: Assessing Latency
> A parameter is given: `Latency = 300 ms`.
> This is normal for one service and critical for another.
>
> A normalized axis (or derived qualitative class) is useful in this case.
> **Axis emerges:** `LatencyLevel = High`

---

### 5. Axis Degradation (When to Remove One)

Reconsider an axis if it violates the [[#Axis Validity Criteria|validity criteria]] or if its benefit under the [[#III. Practical Axis Acceptance Test|acceptance criteria]] no longer justifies its cost. Based on the review, retain it, merge it, downgrade it, or remove it.

Infrequent use alone does not mean an axis is useless: it may matter for rare, costly errors. Lack of data about its benefit also does not prove there is none. Stopping active use does not require physically deleting the definition; changes retain the dependencies they need under [[Memory#Retention Obligations|the shared memory obligations]].

---
## Numeric Attribute Representation

#topic_details

This section describes how numeric attributes are represented in EverTree: from the current `value_U` on a numeric scale to domain distributions and qualitative interpretations such as `Low / Mid / High`.

### Numeric Facets: Scalar Metrics and Distributions

#topic_details

This section describes storage forms for scalar measurements and population- or type-level norm statistics. They are used when needed, following the [[Core data structures#Objects and References|shared rules for storing objects]].

Purpose:

- store the current numeric value of a property;
- preserve uncertainty in the measurement representation and epistemic confidence through a [[Uncertainty and Belief Tracking in the World Model#Numeric and Distributional Values|numeric belief]];
- support normalization relative to a type or population;
- allow a number to be mapped to qualitative labels such as `Low`, `Mid`, and `High`.

---

### ScalarMetric

#topic_details

(def_id:: entity.ScalarMetric)
> [!definition]
> **ScalarMetric** is an abstract representation of a numeric axis or numeric property.
> ^def-ScalarMetric

(formal_id:: entity.ScalarMetric.schema)
```python
ScalarMetric: <AbstractConcept> {
  name: <string> "Name of the numeric property or measurement axis: Speed, Temperature, RiskScore, Latency."
}
```
^spec-ScalarMetric

Minimal meaning:

```text
ScalarMetric = numeric PropertyConcept whose values lie on a Numeric scale.
```

Examples:

```text
SpeedOfMotion
Mass
Temperature
Latency
RiskScore
CredibilityScore
```

---

### FacetScalarMetric

#topic_details

(def_id:: entity.FacetScalarMetric)
> [!definition] **FacetScalarMetric** stores a specific numeric value for an object on a specific axis in a specific state or window.
> ^def-FacetScalarMetric

(formal_id:: entity.FacetScalarMetric.schema)
```python
FacetScalarMetric: <Facet> {
  axis: <Axis> "Reference to the numeric axis/property."
  value: <float> "Current numeric value."
  unit?: <Unit> "Unit of measurement, when applicable."
  t?: <time> "Time or window to which the measurement applies."
  confidence?: <float> "Technical assessment of measurement accuracy, if needed separately from Belief_data."
  precision?: <float> "Expected measurement error, if known."
}
```
^spec-FacetScalarMetric

The canonical graph fact for this value is:

```text
HAS_NUMERIC_VALUE(entity, property, value[, unit])
```

`FacetScalarMetric` is an optional implementation form for storing the same scalar value; `HAS_NUMERIC_VALUE` is the semantic form of the fact. They do not require two independently mutable copies of the value or a separate Facet for every measurement.

### Instance-Level Numeric State

#topic_details

If a numeric axis is dynamic and the specific object's local history matters, an Instance may store compact state for that axis.

Supported forms:

1. **RecentSamples**

   A ring buffer of the last `N` values.

   Used when short-term dynamics matter.

2. **InstanceSketch**

   A compact sketch of the value distribution for a specific instance.

   Used when the value is measured frequently and the object's local norm matters.

Principle:

```text
Facet stores the working value "right now".
Instance stores stable local statistics for the object.
History remains in memory / episodes, with detail governed by the shared memory lifecycle.
```

---

### MetricDistribution at the Prototype / Type Level

#topic_details

(def_id:: entity.MetricDistribution)
> [!definition] Each Prototype or Type may store population statistics for numeric metrics through **MetricDistribution**.
> ^def-MetricDistribution

(formal_id:: entity.MetricDistribution.schema)
```python
MetricDistribution: <InternalNode> {
  axis: <Axis> "Reference to the numeric axis/property."
  domain: <Concept> "Type, prototype, population, or other domain whose distribution defines a norm."
  sketch: <Sketch> "t-digest, DDSketch, or another compact distribution sketch."
  drift_policy: <enum> "ema_decay | sliding_window | fixed_window"
  updated_at?: <time> "When the distribution was last updated."
  belief_data: <Belief_data> "Belief that this distribution correctly describes the norm for this domain."
}
```
^spec-MetricDistribution

Purpose:

- store a type-level norm;
- calculate quantiles;
- compare an object with a population;
- map a raw value to a qualitative class;
- track norm drift.

Example:

```text
MetricDistribution(Vehicle, SpeedOfMotion)
MetricDistribution(Query, Latency)
MetricDistribution(UserMessage, AngerScore)
```

---

### QualitativeMapper Within MetricDistribution

#topic_details

The mapping “number → qualitative label” should not be global.

Classes such as `Low`, `Mid`, `High`, `Fast`, `Slow`, and `Expensive` are usually relative to a type, population, and context.

(def_id:: entity.QualitativeMapper)
> [!definition] **QualitativeMapper** is a model that maps a numeric value to a qualitative interpretation using a Criterion. For a population norm, the mapper may use `MetricDistribution` and be stored with it.
> ^def-QualitativeMapper

(formal_id:: entity.QualitativeMapper.schema)
```python
QualitativeMapper: <InternalNode> {
  mode: <enum> "quantile_bins | peak_modes | learned_monotonic"
  labels: <ClassConcept[]> "Qualitative labels: Low, Mid, High, or others."
  boundaries?: <float[]> "Interval boundaries when using hard binning."
  membership_functions?: <Callable[]> "Soft-membership functions when boundaries are gradual."
  hysteresis?: <float> "Protection against frequent label switching due to noise."
}
```
^spec-QualitativeMapper

### Quantile Bins

Default mode.

Used when simple, stable normalization against a type distribution is needed.

Example:

```text
Low  = below q33
Mid  = q33..q66
High = above q66
```

Or, more conservatively:

```text
Low  = below q20
Mid  = q20..q80
High = above q80
```

Stabilization:

- boundaries are not updated on every observation;
- sufficient `support` is required;
- hysteresis is used so labels do not flip because of noise.

Boundary changes follow the [[#Revising a Qualitative Interpretation|shared rules for revising an interpretation]]; a parameter update by itself does not create a new target.

### Peak Modes

Used when the distribution genuinely has several stable modes.

Example:

Movement speed may have the modes:

```text
standing
walking
running
driving
```

If the distribution peaks are stable, qualitative labels may be associated with the modes.

If the modes are unstable, fall back to:

```text
peak_modes → quantile_bins
```

### Learned Monotonic

Used when a qualitative class should correspond to utility, risk, or a supervised signal.

Example:

```text
RiskScore → LowRisk / MidRisk / HighRisk
```

The mapping may be trained so that `HighRisk` corresponds not simply to the top quantile but to a real increase in the probability of a bad outcome.

Allowed models:

- isotonic regression;
- monotonic calibration;
- monotonic binning;
- learned thresholds with constraints.

Constraint:

```text
If a property must be monotonic, the model must preserve the ordering.
```

---

### Point View, Profile, and Overlapping Membership

#topic_details

For a mutually exclusive and exhaustive scale, the qualitative mapper returns a shared `Profile`. A hard label, such as `RiskHigh`, may only be a derived point view under an explicit selection policy; it is not assigned its own `Support` or `PriorSupport`.

If membership functions deliberately allow simultaneous membership in several classes, this is not a `CompetitionScope`: each classification is a separate binary target. Membership degree is then a model value, not epistemic `Strength`.

---

### Composite Axes

#topic_intro #future_versions

(def_id:: et.CompositeAxis)
> [!definition]
> A **Composite Axis** is an attribution axis whose value is computed from several simpler properties.
> ^def-CompositeAxis

A composite axis emerges when individual properties are less useful than their joint projection. It does not merely duplicate features; it identifies a **new, pragmatically useful property** that helps compare, choose, predict, or explain more quickly.

---

> [!EXAMPLE] Examples and Their Practical Use
> - **Size** $= f(\text{Height}, \text{Weight})$
>   *Purpose:* Quickly understand an object's scale and choose an interaction strategy without analyzing height and weight separately.
> - **Momentum** $= \text{Mass} \times \text{Velocity}$
>   *Purpose:* Predict collision force and assess the danger of a moving object.
> - **Danger** $= f(\text{Size}, \text{Aggression}, \text{Distance}, \text{Weapon}, \text{Speed})$
>   *Purpose:* Quickly rank threats and trigger safety behavior.
> - **Source reliability** $= f(\text{Accuracy history}, \text{Provenance}, \text{Type})$
>   *Purpose:* Resolve conflicts in contradictory information.

---

### Synthesis Mechanisms

An axis may be created in three main ways, depending on what is known about the domain:

1. **Explicit formula**
   Used when a physical or logical relationship is known precisely, such as $Momentum = Mass \times Velocity$.
2. **Linear combination (Score)**
   Used for heuristic assessments: $RiskScore = w_1x_1 + w_2x_2 + \dots + w_nx_n$.
   *Requires control of:* input normalization, weight stability, and overfitting checks.
3. **Incremental PCA / Low-Rank Decomposition**
   Used to find latent coordinates and reduce dimensionality when many features change together but no exact formula is known.

---

> [!NOTE] Mathematics: Choosing $k$ for IPCA
> Choose the optimal number of components using a threshold for cumulative explained variance. Let $\lambda_i$ be the eigenvalues (component variances) from IPCA.
>
> Take the **smallest** $k$ that satisfies:
> $$\frac{\sum_{i=1}^{k}\lambda_i}{\sum_{i=1}^{m}\lambda_i} \ge \tau$$
> Here, $m$ is the number of available components and $\tau$ is the target threshold.
>
> **Robust hyperparameters:**
>
> | Parameter | Value | Description |
> | :--- | :--- | :--- |
> | **$\tau$** | `0.95` | Target cumulative variance threshold (default). |
> | **$k_{max}$** | *Custom* | Maximum number of components (memory/speed limit). |
> | **$N_{min}$** | `200–1000` | Stabilization: recalculate $k$ no more often than every $N_{min}$ new observations. |
> | **$\Delta$** | `0.01–0.02` | Hysteresis: update $k$ only if variance improves by at least $\Delta$ (1–2%). |

> [!WARNING] Limitation of Latent Axes
> **Interpretability is not guaranteed.** If a latent axis obtained through PCA has no clear meaning or useful Criterion, it must remain an *internal technical coordinate*, not become a full ontological `PropertyConcept`.
