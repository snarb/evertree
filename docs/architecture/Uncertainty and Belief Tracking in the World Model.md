---
status: draft
target_version: next
ToDo:
---

## Introduction

#topic_core

EverTree uses a belief model where the agent's knowledge may be incomplete or wrong: for observations, hypotheses, states, semantic relationships, process models, and other claims about the world or the agent itself.

In EverTree, [[#^def-BeliefData|`BeliefData`]] is not updated directly. Relevant experience is transformed into [[#^def-EvidenceAssignment|`EvidenceAssignment`]], and the current `Strength`, `Support`, and, when there are competing alternatives, [[#^def-Profile|`Profile`]] are computed from active evidence. Similar evidence may be consolidated into a more compact representation if its combined influence and the granularity needed for future learning, `revise/retract`, dependency accounting, and temporal dynamics are preserved.

---

## Belief Model
#topic_core

### Core Concepts and Semantic Boundaries
#topic_core

#### Belief and BeliefTarget
#topic_core

(def_id:: entity.Belief)
> [!definition] **Belief** — the agent's current epistemic relation to a canonically defined semantic target: how far available evidence supports treating a claim, value, or one of the allowed answers as true or justified. ^def-Belief

(def_id:: entity.BeliefTarget)
> [!definition] **BeliefTarget** — a canonically defined semantic unit updated as one epistemic whole: a binary claim, an evaluated value/model, or a [[#^def-CompetitionScope|`CompetitionScope`]]. An alternative within a scope is not an independent target with its own `Support`. ^def-BeliefTarget

#topic_details

Examples using [[Core data structures#^def-Facet|`Facet`]] and [[Core data structures#^def-Claim|`Claim`]] as target forms:

```text
HealthStatus(IgorHealth@T1)
→ which health state applies to the Igor instance's Facet at T1;

PART_WHOLE(Wheel#7, Car#1)
→ whether Wheel#7 is part of Car#1;

"The Earth may cease to exist at any moment"
→ a Claim, if a more suitable semantic structure has not yet been defined.
```

#topic_core

[[#^def-BeliefTarget|`BeliefTarget`]] always refers to a canonically defined object, property, or claim in EverTree's semantic graph:

```text
property target
→ (semantic_object, PropertyConcept) with conditions defining the meaning of the evaluated quantity/model;

independent classification target
→ CLASSIFIED_AS(semantic_object, ClassConcept);

scope-backed property target
→ CompetitionScope for a question about (semantic_object, PropertyConcept) under specified semantic conditions;

relation target
→ RelationType + fully specified arguments;

transition target
→ TransitionType + fully specified arguments;

CompetitionScope
→ a semantic question + its complete set of alternatives;

Program target
→ (Program, program_revision);

Claim
→ an explicitly stated, checkable claim for which no suitable structured representation exists yet.
```

[[Core data structures#^def-Note|`Note`]] and [[Core data structures#^def-Prompt|`Prompt`]] may also be complete semantic targets under the [[Core data structures#^note-claim-prompt-evaluation|shared evaluation contract]], with specified `Criterion` and scope. An arbitrary Python object or technical structure cannot be a `BeliefTarget`.

Existing semantic structure also defines **which values are allowed**:

```text
HealthStatus + AttributionAxis
→ Healthy | Sick | Recovering | ...

PART_WHOLE(...)
→ true | false

CompetitionScope
→ its alternatives.

Claim
→ true | false
```

Conditions defining the meaning of a question must be unambiguous in the target's semantic representation. For example, the reliability of one source in programming and in medicine concerns different targets. Additional observations or switching estimators for the same question do not by themselves change the target; the current belief value is not part of its identity either.

---

#### Generic `Belief(U)` Interface
#topic_core

(def_id:: entity.BeliefU)
> [!definition] **`Belief(U)`** — a general belief interface for a value in space `U`:
> `value_U` is the asserted or evaluated value. It may be a class, state, number, interval, model parameters, outcome profile, or another typed structure required by the corresponding Program.
> [[#^def-BeliefData|`BeliefData`]] represents the agent's epistemic confidence in that value. ^def-BeliefU

(formal_id:: entity.BeliefU.schema)
```text
Belief(U) := <value_U, BeliefData>
```
^spec-BeliefU

`U` may represent a class, state, hypothesis, relation, number, parameter, distribution, or another typed quantity.

#topic_details

For example:

```text
value_U = transition_probability = 0.7
```

#topic_core

Any quantity describing the world or process itself belongs in `value_U` or model parameters, not in `BeliefData`.

---

#### BeliefData
#topic_core

(def_id:: entity.BeliefData)
> [!definition] **BeliefData** — the standard computed read representation of a belief's epistemic state:
> `BeliefData` is not changed directly.
> - `Strength ∈ [0,1]` — how strongly the agent currently believes the corresponding `value_U`;
> - `Support ≥ 0` — the total effective discriminative mass of the target's own active evidence;
> - `PriorSupport ≥ 0` — the effective discriminative mass of traceable upstream evidence supporting the target's current prior. `PriorSupport` may be nonzero before the agent has its own experience if the prior is supported by traceable external or upstream evidence. Unsupported parametric knowledge from an LLM does not create `PriorSupport`. ^def-BeliefData

(formal_id:: entity.BeliefData.schema)
```text
BeliefData = <Strength, Support, PriorSupport>
```
^spec-BeliefData

#topic_details

`Support` counts only the target's own evidence; it does not include the prior.

`PriorSupport` distinguishes beliefs with the same `Strength` and `Support` but different prior foundations:

```text
Strength = 0.9
Support = 0
PriorSupport = 0
→ a strong prior without traceable evidence;

Strength = 0.9
Support = 0
PriorSupport = high
→ the target has no evidence of its own yet,
  but the prior is supported by transferable upstream evidence.
```

This matters especially when transferring knowledge between [[Core data structures#^def-Prototype|Prototype]], [[Core data structures#^def-Instance|Instance]], and [[Core data structures#^def-Facet|Facet]] levels:

```text
Prototype
→ prior for Instance
→ prior for Facet
```

`PriorSupport` is not a copy of the source belief's `Support`. Transfer accounts for applicability to the current target, dependencies between evidence, and the prohibition against counting the same underlying evidence again through both `Support` and `PriorSupport`.

Therefore, `Support` and `PriorSupport` must not automatically be added into a single confidence measure.

`Support` is also not the number of observations. A relevant check may fail to distinguish alternatives and have `evidence_mass = 0`; the number and structure of checks performed are tracked separately through [[#^def-EvidenceStats|`EvidenceStats`]].

Exact rules for computing `Strength`, `Support`, `PriorSupport`, and [[#^def-Profile|`Profile`]], including prior resolution and upstream evidence transfer, are defined in [[#Belief Updating]].

---
#### EvidenceStats
#topic_core

(def_id:: entity.EvidenceStats)
> [!definition] **EvidenceStats** — a computed view describing the amount and structure of a target's **own active evidence**. It is not part of `BeliefData` and is not a semantic object. ^def-EvidenceStats

```python
EvidenceStats {
  evidence_count: int
    "Number of logical evidence units after deduplication
     and dependency accounting, including non-discriminating checks."

  max_component_mass: float
    "Maximum effective evidence mass of one logical unit."

  max_component_effect: float
    "Maximum effective effect of one logical unit
     on the updater state."
}
```

#topic_details

The following states are distinct:

```text
Support = 0
evidence_count = 0
→ the target has not been investigated;

Support = 0
evidence_count > 0
→ relevant checks were performed,
  but they yielded no discriminative evidence.
```

Consolidation does not change `EvidenceStats`: the statistics describe the represented logical evidence units, not the number of physical [[#^def-EvidenceAssignment|`EvidenceAssignment`s]].

[[#^def-EvidenceStats|`EvidenceStats`]] does not describe evidence behind `PriorSupport`. When needed, its structure is reconstructed through the prior's provenance; a separate `PriorEvidenceStats` is not introduced in the MVP.

---
#### Epistemic Uncertainty vs. Model Variability
#topic_core

EverTree distinguishes:

```text
model uncertainty / variability
→ what the model itself says about possible states of the world;

epistemic uncertainty
→ how confident the agent is that the model or estimate is correct.
```

#topic_details

For example:

```text
value_U:
OutcomeProfile {
    Success = 0.5
    Failure = 0.5
}

BeliefData:
Strength = 0.95
Support = high
```

This means the agent is fairly confident that the process really has approximately equally likely outcomes.

#topic_core

Therefore, high process variability does not imply low epistemic confidence, and a nearly deterministic forecast does not imply that the agent has high confidence in it. Epistemic confidence is read through [[#^def-BeliefData|`BeliefData`]].

Similarly, uncertainty among `Low | Medium | High` for a categorical or ordinal Property is epistemic uncertainty represented by [[#^def-Profile|`Profile`]]. It does not turn those values into an `OutcomeProfile`: `OutcomeProfile` describes variability in the modeled process itself, not the agent's uncertainty about which alternative is true.

This distinction applies to all belief forms and updaters described below.

### Belief Representations
#topic_core

For an individual assertion or evaluated `value_U`, use the general [[#^def-BeliefU|`Belief(U)`]] interface: `value_U` plus [[#^def-BeliefData|`BeliefData`]]. For one question with mutually exclusive and exhaustive alternatives, the shared epistemic read representation is [[#^def-Profile|`Profile`]]: it replaces a set of independent `Belief(U)` values; it is not a new kind of `value_U`.

---
#### Binary Belief
#topic_core

Use this for an assertion that can be true or false and does not require explicitly representing the alternative `¬H`.

#topic_details

For example:

```text
value_U = "Sensor#7 calibrated"

BeliefData:
  Strength = 0.91
  Support = ...
```

#topic_core

`Strength` expresses the agent's current epistemic confidence in the assertion.

The updater's internal state may use suitable sufficient statistics; externally, the belief is read through [[#^def-BeliefData|`BeliefData`]].

---
#### CompetitionScope and Mutually Exclusive Alternatives

#topic_core

(def_id:: entity.CompetitionScope)
> [!definition] **CompetitionScope** — the semantic scope of one question with mutually exclusive and exhaustive alternatives: exactly one alternative is true in every admissible state. ^def-CompetitionScope

`CompetitionScope` is defined by the question and its alternatives, not by their semantic type. It applies equally to competing hypotheses and to categorical or ordinal Property values when the scale and [[Attribution Plane#^def-Criterion|`Criterion`]] define such a set.

#topic_details

```text
Where is the only reward?

CompetitionScope:
  BehindDoorA
  BehindDoorB
  BehindDoorC
```

The same scope applies to a discrete Property:

```text
What is SQLProblemSolvingLevel(AgentA)?

CompetitionScope:
  Low
  Medium
  High
```

`Low`, `Medium`, and `High` are alternatives for one target, not three independent beliefs.

If multiple assertions or classifications may be true at the same time, they do not form a `CompetitionScope`; represent them as separate binary beliefs.

```text
Rain contributed to WetRoad
StreetWasher contributed to WetRoad

GoodAtSQL(AgentA)
GoodAtPython(AgentA)
GoodAtDebugging(AgentA)
```

Such statements may all have high `Strength` at the same time.

The alternatives must cover all admissible answers. If the named alternatives do not do so, add an ordinary semantic alternative for the remaining case.

```text
Which source caused the event?

CompetitionScope:
  SourceA
  SourceB
  OtherSource
```

```text
What triggered the alarm?

CompetitionScope:
  Fire
  Intrusion
  NoTrigger
```

`OtherSource` covers a different source, and `NoTrigger` covers the absence of a trigger. These are ordinary alternatives within a specific scope.

`CompetitionScope` contains only possible states of the world; not knowing which alternative is true is represented by the epistemic state, not by a separate alternative.

If an observation shows that two alternatives may be true at once, or that an admissible state is not covered by the scope, the `CompetitionScope` structure itself is wrong:

```text
scope invariant violation
→ structural revision
```

The set of alternatives is part of the `CompetitionScope`'s semantic identity. Changing it creates a new version of the scope; existing evidence is reassessed when needed, and simple renormalization is not allowed.

If compatible assertions require a joint distribution or interactions, use a model-specific joint model. A universal joint model is not required for the MVP.

---
##### CompetitionScope Profile
#topic_core

(def_id:: entity.Profile)
> [!definition] **Profile** — a shared computed representation of epistemic belief across the alternatives of one `CompetitionScope`, whether the alternatives are hypotheses or Property values. ^def-Profile

```python
Profile {
  strengths: <dict[alternative, float]>
  support: <float>
  prior_support: <float>
}
```

For each alternative `a`:

```text
Strength(a)
→ the current epistemic probability of that alternative.
```

$$
\sum_k Strength(a_k)=1
$$

`Support` applies to the entire `CompetitionScope`:

```text
Support
→ total effective discriminative evidence mass;

PriorSupport
→ backing for the prior distribution, when derived from other beliefs.
```

Separate `Support(a)` and `PriorSupport(a)` values are not used: evidence and prior evaluate the question/scope as a whole.

When the target has no evidence of its own:

$$
Strength(a_k)=p_{0,k}, \qquad Support=0
$$

`Profile` is computed at read time and is not stored separately. An immutable [[Memory#^def-OperatorOutput|`OperatorOutput`]] may record a historical `Profile` read snapshot for provenance; it is not updated and is not the source of the current `Profile`.

A scope-backed Property uses the same `Profile` and `CompetitionScopeUpdater` as competing hypotheses.

---
#### Probabilistic Process Outcomes
#topic_core

Some processes may have multiple possible outcomes even when the process model is correct and complete.

#topic_details

For example:

```text
CardDeal
→ a set of possible cards;

unfair coin
→ Heads 0.7
→ Tails 0.3
```

#topic_core

In this case, the probabilities belong to the modeled process itself and are part of `value_U`, not `Strength`.

Represent discrete outcomes with:

```python
OutcomeProfile {
  Heads: 0.7
  Tails: 0.3
}
```

The agent's epistemic confidence that this distribution is correct is expressed separately through [[#^def-BeliefData|`BeliefData`]]:

```text
Belief(
  value_U = OutcomeProfile(...),
  BeliefData = ...
)
```

Continuous random outcomes use the corresponding `OutcomeDistribution`.

#topic_details

An `OutcomeProfile` itself may be trained by its own estimator, for example through counts or Beta / Dirichlet statistics. This updates `value_U`, not epistemic `Strength`.

---
#### Numeric and Distributional Values
#topic_core

Numeric `value_U` may use whatever representation a specific model requires:

```text
single value;
interval;
model parameters;
empirical or parametric distribution;
another typed numeric structure.
```

#topic_details

For example:

```text
value_U = 12.4 kg
```

or:

```text
value_U = Interval(12.1, 12.7) kg
```

Model-specific uncertainty about `value_U` itself is stored in the representation or sufficient state of the relevant estimator.

For example:

```text
Beta / Dirichlet concentration;
Gaussian variance / precision / covariance;
posterior interval;
sample count
```

These are not generic `BeliefData.Support`.

#topic_core

[[#^def-BeliefData|`BeliefData`]] for numeric or distributional `value_U` applies to an explicitly defined [[#^def-BeliefTarget|semantic target]]: a claim about the correctness of a specific estimate or model under stated conditions. A claim about an individual measurement and a claim about model quality are different targets. If the meaning is already represented by a property or model, use its existing target; create a separate [[Core data structures#^def-Claim|`Claim`]] only when no suitable representation exists.

[[Attribution Plane#^def-Criterion|`Criterion`]] defines the checking rule and conditions in the target contract or checking Program. Use a metric or loss when required by the meaning of the check; a binary predicate does not require a separate numeric metric. A claim that a model is suitable requires a defined acceptance condition within the stated applicability domain.

#topic_details

Empirical distributions are based on saved observations; summaries such as mean, variance, and quantiles are computed on demand. For very large volumes, [[Memory#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]] or a specialized model Program may create a compact representation with an explicitly permitted loss of detail.

For a parametric model, its parameters are part of `value_U`; model-specific uncertainty about those parameters is estimator state.

Choose the representation according to reasoning, prediction, and control needs. Use a more complex representation only when a simpler one loses information that matters in practice.

---
### Belief Updating
#topic_core

```text
prior
+ active EvidenceAssignment[]
        ↓
target-specific updater
        ↓
internal sufficient state
        ↓
BeliefData / Profile
```

> If the complex `value_U` itself is updated—for example, numeric model parameters or an `OutcomeDistribution`—a model-specific estimator from the [[Learning system#^def-LearningSystem|Learning System]] updates `value_U`, while the belief updater separately estimates confidence in the resulting model.

---
#### Prior Resolution and `PriorSupport`

#topic_core

A prior may be specified directly or obtained by transferring a more general or related belief between [[Core data structures#^def-Prototype|Prototype]], [[Core data structures#^def-Instance|Instance]], and [[Core data structures#^def-Facet|Facet]]:

```text
Prototype
→ prior for Instance;

Instance
→ prior for Facet.
```

`resolve_prior(target)` determines the target's state before its own active evidence; for competing alternatives, the initial distribution is a [[#^def-Profile|`Profile`]]:

```text
prior
→ initial Strength / Profile;

PriorSupport
→ effective discriminative mass of traceable upstream evidence
  supporting the prior.
```

#topic_details

When a new target is created, `resolve_prior` reuses an applicable prior model or a saved result for the same target and input state. LLMs and retrieval/web search may be used to prepare or revise a model through the [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]]; a new target does not itself require a new LLM call. Assess the grounds that were found for reliability, applicability, and dependencies, then separate them by relation to the target:

```text
direct evidence for the current target
→ EvidenceAssignment(target)
→ Support;

evidence for another, more general, or related belief
→ transfer to prior
→ PriorSupport.
```

#topic_core

The same underlying evidence cannot be counted through both `Support` and `PriorSupport`.

#topic_details

General pipeline:

```text
upstream beliefs / models
+ LLM / web research when needed
        ↓
assessment + dependency filtering
        ↓
┌──────────────────────────────┐
│ direct evidence              │
│ → EvidenceAssignment[]       │
│                              │
│ upstream evidence            │
│ → prior + PriorSupport       │
└──────────────────────────────┘
        ↓
target-specific updater
        ↓
initial Strength / Profile + Support
```

#topic_core

If there is no sufficient traceable basis, use a prepared bounded base prior from an LLM or an explicit program fallback. Exact calibration is not required to begin work:

```text
base prior
→ PriorSupport = 0.
```

When transferring, do not copy `PriorSupport` from the source belief's `Support`. Count only effective evidence mass that remains applicable to the target after accounting for dependencies and overlap with its own evidence.

Key invariants:

```text
prior does not increase the target's own Support;

Prototype → Instance → Facet
does not itself create new evidence; resolve_prior must check applicability;

PriorSupport comes only from traceable upstream evidence;

the same underlying evidence is not counted again
through both Support and PriorSupport;

PriorSupport uses the same Support scale
as the current target's updater.
```

`resolve_prior` does not assign final `Strength`; it determines the prior and its backing. The target-specific updater computes `Strength / Profile` after accounting for the target's own active evidence.

---
##### LLM Prior Proposal

#topic_details

Use an LLM prior proposal to prepare or revise a prior model when no suitable applicable estimate is available. One call may estimate several targets; rereading a prior and receiving new evidence do not require eliciting an estimate from the LLM again. Retrieval / web search are performed within the preparation budget; search itself does not create `PriorSupport`.

For a binary target, the LLM returns a numeric `P(target is true)`; for a `CompetitionScope`, it returns one normalized [[#^def-Profile|`Profile`]] over all alternatives. This is the probability that the target is true; the quality of the estimation method is represented separately through backing and [[#Calibration|calibration]].

A numeric output is selected for direct use by the updater. Probability words are acceptable as an alternative protocol only with predefined values and conversion to numbers. Categories such as `low / medium / high` for applicability and reliability in the response describe the grounds and do not replace `P(target)`. Neither the response format nor an instruction to “be calibrated” ensures calibration by itself.

LLM probability estimates are sensitive to wording, framing, and elicitation order. Therefore, use a stable, versioned prompt, model, generation settings, and output transformation. Changes to these are treated as changes to the prediction mechanism for subsequent calibration.

Pass `target`, [[Attribution Plane#^def-Criterion|`Criterion`]], context, horizon, `known_at`, permitted background, and references to excluded direct evidence in structured form. Separate the grounds before estimating the prior: the updater handles the target's own evidence separately.

Draft base prompt, to be adapted:

> Estimate `P(target is true)` given the Criterion, context, horizon, `known_at`, and allowed prior background. For a CompetitionScope, return one normalized probability vector over all supplied alternatives.
>
> Start from an applicable base rate if available; identify its reference class and source. If none is available, say so. Consider material background both for and against the target. Discount weak, inapplicable, stale, unreliable, or dependent background. Exclude direct evidence that the updater will account for separately.
>
> Return your raw probability estimate before programmatic limits, the source references that materially informed it, and a short summary of assumptions and missing information. Use only information available by `known_at`. Do not invent sources or base rates. If traceable backing is unavailable, return a rough estimate and explicitly state that limitation.

If a proposal already incorporates direct evidence, it cannot be used as a prior alongside the same evidence in the updater; recalculate the prior using permitted background. An instruction containing `known_at` does not guarantee that the LLM's weights lack knowledge of a future outcome; historical evaluation requires a separate leakage check.

When relevant [[#^def-CalibrationStats|`CalibrationStats`]] are available, they may provide feedback on past overconfidence or underconfidence of the prediction mechanism. They do not increase `PriorSupport`.

The LLM returns:

```python
LLMPriorProposal {
  raw_prior: probability | Profile;
  basis_summary; // base rate / reference class, if available; assumptions and gaps

  material_evidence: [
    {
      source_refs;
      direction: supports | opposes;
      applicability: low | medium | high;
      reliability: low | medium | high;
      dependency_refs?;
      summary;
    }
  ];
}
```

`LLMPriorProposal` does not automatically contribute to `PriorSupport`. `resolve_prior` first checks its `material_evidence` for applicability, reliability, dependencies, and traceability; only effective evidence mass that passes these checks is counted in `PriorSupport`.

`material_evidence` includes only grounds that materially affected `raw_prior`. Several messages based on one observation, dataset, or study count as dependent evidence.

Retrieval increases the available evidence but does not by itself make a prior more reliable; noisy, irrelevant, or dependent sources may instead create false confidence. Therefore, assess the content and provenance of material evidence; source reputation is only one reliability indicator.

Evaluate numeric and categorical protocols on independently resolved cases from their respective target families under the [[Process Plane/Program Evaluation and Testing|evaluation rules]]: proper scores, calibration, and the usefulness of differences among forecasts. Repeated sampling and a separate LLM judge are not part of the required evaluation path.

Grounds for selecting the protocol include:

- [Tao et al. (2025)](https://arxiv.org/html/2505.23854v1): verbal uncertainty performed better on average across the studied models, but not for every model; it was evaluated by a separate LLM judge. This does not prove the advantage of three fixed categories.
- [Subramani et al., ACUTE (2026)](https://arxiv.org/abs/2606.07822): evaluations learned from internal activations increased the usefulness of confidence estimates with low calibration error on the studied tasks. The method requires data and access to activations; changing the prompt alone cannot reproduce the result.

These studies primarily examine correctness of model answers. Transfer of their results to priors for arbitrary processes must be checked separately.

---
##### Unsupported LLM Prior

#topic_details

A prior component without traceable evidence backing has:

```text
PriorSupport = 0
```

and is bounded in the MVP by:

```text
binary:
prior ∈ [0.25, 0.75];

CompetitionScope:
max_k prior_k ≤ 0.75.
```

Code first bounds the unsupported proposal's own strength, then limits its aggregate influence together with approximate contributions under the [[#Limiting Unsupported Influence|shared rule]]. For an admissible binary proposal with no backing and no other contributions, the result is `clamp(raw_prior, 0.25, 0.75)`. For a scope, preserve normalization and positive [[#^def-Profile|`Profile`]] components. This limit is not empirical calibration.

When material evidence exists, the final prior may go beyond this limit only to the extent that the stronger estimate is actually justified by that evidence. The mere presence of a source does not remove the cap.

When approximate assessments are added, the unsupported prior and their contributions use [[#Limiting Unsupported Influence|one shared limit on influence over the target]]. Weakening each contribution separately does not replace limiting their sum.

---
##### Evidence-Backed Prior

#topic_details

Backing evidence may come from:

```text
the agent's own experience and upstream beliefs / models;
transfer from Prototype → Instance → Facet;
external observations, datasets, and retrieved sources.
```

Therefore, a new Program may have `PriorSupport > 0` before the agent has its own experience.

`resolve_prior` determines effective backing while accounting for:

```text
applicability;
reliability;
dependencies;
temporal applicability.
```

`PriorSupport` is not a count of sources, LLM confidence, or a source-reputation score. It is expressed on the support scale of the current target's updater.

When transferring an upstream belief, do not copy its `Support / PriorSupport`; count only the applicable part of its underlying evidence.

---
#### Evidence Contribution and Support

#topic_core

For an epistemic updater, `contribution` and `evidence_mass` form one mathematical contract:

```text
contribution
→ direction and magnitude of evidence's effect on the belief;

evidence_mass ≥ 0
→ discriminative mass of that effect.
```

#topic_details

`evidence_mass` is not the number of observations or a general measure of how thoroughly the question has been investigated. Therefore, relevant [[#^def-Evidence|evidence]] may have:

```text
contribution = 0
evidence_mass = 0
```

and still be included in [[#^def-EvidenceStats|`EvidenceStats`]].

For atomic evidence, `evidence_mass` is not specified independently; it is deterministically derived from `contribution` under the specific updater's rules.

`BinaryBeliefUpdater` and `CompetitionScopeUpdater` use natural logarithms; `evidence_mass` and `Support` are measured in `nats` for these updaters.

After consolidation, `evidence_mass` may exceed an assignment's net effect because contributions from represented components may partially cancel one another.

When reading, temporal, dependency, and unsupported-influence policies transform:

```text
(contribution, evidence_mass)
        ↓
current adjustment
        ↓
(effective contribution, effective evidence_mass)
```

The adjustment must preserve the updater-specific invariant between effect and mass: weakening discriminative evidence cannot leave an effect on `Strength` or [[#^def-Profile|`Profile`]] that exceeds the corresponding effective mass.

For simple scalar attenuation `a ∈ [0,1]`:

```text
Δ̃ = aΔ
m̃ = am
```

Dependency adjustment may handle several related evidence items jointly and does not have to reduce to an independent multiplier for every assignment.

#topic_core

The target's current own `Support` is:

```text
Support = Σ effective evidence_mass
```

after any required dependency consolidation.

Prior is not included in `Support`.

#topic_details

For consolidated evidence, adjustment must use a retained representation sufficient to preserve the consolidation invariant. One shared adjustment to net contribution is acceptable only if it is equivalent to adjusting the represented components.

---
##### Limiting Unsupported Influence
#topic_core

In the MVP, all approximate estimates that affect one target in a given read context share one common limit. It includes an unsupported prior, contributions from unverified observation models, and influence from assumptions about unknown sources. A new handler, program version, or repeated assessment does not create an additional limit.

An estimate is considered grounded in a domain when the model and its material assumptions are supported by applicable external grounds or independent evaluation. LLM confidence, the presence of a citation, and the number of runs do not prove this by themselves. With partial support, separate the unsupported part; if the model cannot separate it, treat the entire relevant contribution as approximate.

Apply the limit to the combined influence of approximate estimates after accounting for time and dependencies. Grounded evidence retains its contribution and may move the final probability outside the bounds for an unsupported prior. Do not clip the entire final posterior.

#topic_details

Internal calculations distinguish:

- `z_base` — the grounded part of the prior: log-odds for a binary target or centered log-weights for a scope. If absent, use zero, corresponding to `0.5` or a uniform Profile. This is a reference point for the limit, not a claim about real base rates.
- `v₀` — the unsupported residual prior bias in the same coordinates, not yet represented as separate contributions.
- `W` — approximate own and transferable upstream contributions after temporal/dependency adjustment; `W_prior` is the transferable subset.

If a proposal does not allow its grounded part to be separated, treat all its bias as unsupported; do not add grounds already used in the proposal again as separate contributions. Before taking logarithms, the prior must meet the [[#Target-Specific Belief Updaters|updater contract]]: probabilities must be finite and strictly between `0` and `1`, with scope probabilities also normalized. Replace an inadmissible proposal with the declared fallback.

Define the bias magnitude as `d(x) = |x|` for a binary target and `d(x) = max(x) − min(x)` for a centered scope vector. First bound the strength of the proposal itself:

```text
u₀ = v₀                       when d(v₀) ≤ B
u₀ = [B / d(v₀)] × v₀         when d(v₀) > B
```

This prevents an extreme LLM self-estimate from using almost the entire shared limit through a large raw logit. Then limit the total assumed influence:

```text
M = d(u₀) + Σ_{i ∈ W} m_i
a = 1                         when M = 0
a = min(1, B / M)             when M > 0

u₀_eff = a × u₀
Δ_i_eff = a × Δ_i             for i ∈ W
m_i_eff = a × m_i             for i ∈ W
```

The total mass of limited influence cannot exceed `B`. Count it before opposite contributions cancel each other, so their net does not hide the magnitude of unsupported influences.

`B` is a versioned calculation-policy setting, measured in `nats`. In the MVP, values are aligned with [[#Unsupported LLM Prior|initial-prior limits]]:

```text
binary: B = ln(3)
scope with K ≥ 2 alternatives: B = ln(3 × (K − 1))
```

Without grounded evidence, this gives binary probability in `[0.25, 0.75]` and `max_k p_k ≤ 0.75`. For a scope, the probability ratio between any two alternatives is also limited: `p_i / p_j ≤ 3 × (K − 1)`. For a large number of alternatives, this does not guarantee a large absolute probability for each one.

An unsupported prior uses the influence limit but creates neither `Support` nor `PriorSupport`. Effective mass from own evidence contributes to `Support`; transferable upstream evidence contributes to `PriorSupport`; count each ground once. Preserve original contributions and compute coefficient `a` at read time. In updater formulas, `p₀` means the prior after this adjustment; the original prior proposal is not changed by the count of own observations.

Assemble the prior in the same coordinates:

```text
z_prior = z_base + a × u₀ + Σ_{i ∈ W_prior} a × Δ_i
```

For a binary target, `p₀ = sigmoid(z_prior)`; for a scope, `p₀ = softmax(z_prior)`. Grounded upstream contributions are already included in `z_base`. The updater adds own evidence separately; none of these contributions are duplicated within `v₀`.

This is a conservative MVP heuristic, not a guarantee of an exact Bayesian posterior or empirical calibration. Changing the limit or removing it for a specific family requires applicable independent grounds and ordinary evaluation of the program change. Renaming a model, increasing the number of unverified examples, or transferring through another belief does not remove the limit.

Model applicability, version, grounds used, and indicators of unsupported influence are retained in the assessment's internal data and [[Memory#^def-ResultProvenance|provenance]]. Consolidation preserves the distinction among these contributions, their original masses, and dependencies needed for recomputation. They must not be merged into a single net contribution if that would make the limit or a grounded revision impossible to reproduce.

#### Calibration

#topic_core

(def_id:: entity.Calibration)
> [!definition] **Calibration** — the correspondence between the agent's probabilistic predictions and the observed frequency of outcomes. If the agent returns a probability near `p` for a set of comparable cases, the corresponding outcome should occur at approximately frequency `p`. ^def-Calibration

Calibration does not require a separate subsystem. Systematic miscalibration is evidence for training the mechanism that produces the prediction through the ordinary [[Learning system#^def-LearningSystem|Learning System]]: a parameter update or structural revision. When needed, that mechanism may include a learnable output transformation, or calibrator. Its evaluation, including interval coverage and relevant contexts, follows the [[Process Plane/Program Evaluation and Testing#^prediction-calibration-sharpness|general rules for forecast calibration]]; a separate calibrator is not required.

##### CalibrationStats

#topic_core

(def_id:: entity.CalibrationStats)
> [!definition] **CalibrationStats** — optional compact calibration statistics for a **repeatable semantic type** of [[#^def-BeliefTarget|**BeliefTarget**]], accumulated from the agent's own predictions and their independently observed outcomes. ^def-CalibrationStats

#topic_details

Specific targets:

```text
DIES_WITHIN_30D(Patient#1)
DIES_WITHIN_30D(Patient#2)
DIES_WITHIN_30D(Patient#3)
```

may share statistics:

```text
DIES_WITHIN_30D
→ CalibrationStats
```

if they represent the same prediction type and concern comparable conditions. For target types with no accumulated or applicable statistics:

```text
CalibrationStats = None
```

For scalar probabilities in the MVP:

```python
CalibrationStats {
  bins: <CalibrationBin[]>
}

CalibrationBin {
  probability_range: <Interval[float]>
    "Range of predicted probabilities."

  count: <int>
    "Number of represented logical resolved predictions."

  probability_sum: <float>
    "Sum of predicted probabilities."

  positive_count: <int>
    "Number of cases in which the predicted outcome occurred."
}
```

For each bin:

```text
mean predicted probability = probability_sum / count
observed frequency         = positive_count / count
```

Their difference indicates miscalibration.

Other forms of probabilistic prediction use the corresponding model-specific mergeable sufficient state.

##### Calibration Lifecycle

#topic_details

One calibration unit corresponds to one logical prediction made **before** an independently observed outcome. Rereading or technically recomputing the same prediction does not create a new unit.

```text
own probabilistic prediction
        ↓
independently observed outcome
        ↓
update CalibrationStats
        ↓
ordinary Learning by the responsible mechanism
```

An unresolved or ambiguous outcome is not counted as a negative one.

[[#^def-CalibrationStats|`CalibrationStats`]] is updated from checks of the agent's own predictions. A check case may come from live experience or an external source if the agent can form a prediction using information available before the outcome and then compare it independently with a reliable observed outcome. Other parties' predictions or published calibration estimates are not merged directly into `CalibrationStats`.

After a significant regime change, new experience is accumulated in separate `CalibrationStats` for the new regime; an arbitrary `recent` window is not used.

After standard memory consolidation, enough statistics should remain that the calibration estimate does not change materially:

```text
calibration(raw compatible predictions)
≈
calibration(retained CalibrationStats)
```

#### Target-Specific Belief Updaters

#topic_details

##### Binary Belief Updater

#topic_details

For a binary [[#^def-BeliefTarget|`BeliefTarget`]], the contribution from [[#^def-Evidence|`Evidence`]] is a signed log-evidence value:

```text
Δ > 0
→ evidence supports the target;

Δ < 0
→ evidence supports its negation;

Δ = 0
→ evidence is relevant but does not distinguish the two possibilities.
```

For atomic evidence, `m_i = |Δ_i|`. During consolidation, `Δ_merge = Σ_i Δ_i` and `m_merge = Σ_i m_i` are retained, so `|Δ_merge| ≤ m_merge` even when contributions cancel each other.

Given prior $p_0$:

$$
z =
\operatorname{logit}(p_0)
+
\sum_i \tilde{\Delta}_i
$$

$$
Strength = \sigma(z)
$$

[[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]] computes the contribution as a log-likelihood ratio using a known, learned, or explicitly approximate [[#Evidence → Contribution Calculation|observation model]]. Approximate contributions are allowed before calibration and remain subject to the general influence limit.

`Support` is calculated under the shared `Evidence contribution` contract from effective evidence mass and is not redefined here.

For a revisable belief:

$$
0 < p_0 < 1
$$

Hard-impossible states are specified by semantic constraints, not prior values of $0$ or $1$.

---

##### CompetitionScope Updater

#topic_details

`CompetitionScopeUpdater` is shared by every `CompetitionScope`: it does not distinguish hypotheses from categorical or ordinal Property values and operates in unnormalized log-weight space.

One [[#^def-EvidenceAssignment|`EvidenceAssignment`]] assesses the scope as a whole. Its contribution is a vector of relative log-evidence:

```text
Δ_i = {
  a1: Δ_i,1,
  ...
  ak: Δ_i,k
}
```

A shared additive offset is irrelevant: adding the same constant to every component does not change the result. Therefore, contributions are stored in a canonical form, such as one with zero mean.

For an atomic assignment:

$$
m_i = \max_k \Delta_{i,k} - \min_k \Delta_{i,k}
$$

For a consolidated assignment:

$$
\Delta_{\text{merge},k} = \sum_i \Delta_{i,k}
$$

$$
m_{\text{merge}} = \sum_i m_i
$$

Therefore:

$$
\max_k \Delta_{\text{merge},k}
- \min_k \Delta_{\text{merge},k}
\le m_{\text{merge}}
$$

For each alternative $a_k$:

$$
z_k =
\ln p_{0,k}
+
\sum_i \widetilde{\Delta}_{i,k}
$$

[[#^def-Profile|`Profile`]] is calculated using softmax:

$$
Profile(a_k) =
\frac{\exp(z_k)}
{\sum_j \exp(z_j)}
$$

Therefore:

$$
\sum_k Profile(a_k)=1
$$

and:

$$
Strength(a_k)=Profile(a_k)
$$

The total `Support` for the scope is:

$$
Support =
\sum_i \widetilde m_i
$$

For all alternatives:

$$
p_{0,k}>0,
\qquad
\sum_k p_{0,k}=1
$$

All contributions are finite. A hard-impossible alternative is specified by a structural constraint on `CompetitionScope`, not by $p_{0,k}=0$ or $\Delta=-\infty$.

One source [[#^def-Evidence|evidence]] increases the scope's `Support` exactly once, even if it distinguishes several alternatives.

Evidence:

```text
A: +5
B: +5
C: +5
```

is equivalent to a zero relative contribution and therefore has:

```text
evidence_mass = 0
```

It does not change `Profile` or `Support`, but remains a relevant check and is counted in [[#^def-EvidenceStats|EvidenceStats.evidence_count]].

#### Consolidation Invariant

#topic_core

Several compatible [[#^def-EvidenceAssignment|`EvidenceAssignment`]] instances may be replaced by one consolidated `EvidenceAssignment`.

For each supported read context, current temporal and dependency policies, and the overall limit on unsupported influence, the following should hold:

```text
belief(E1, ..., En)
≈
belief(merge(E1, ..., En))
```

within the precision permitted by the specific updater.

That is, consolidation must not materially change:

```text
Strength / Profile;
Support;
EvidenceStats.
```

#topic_details

On merge, preserve aggregate evidence mass and logical multiplicity:

```text
m_merge     = Σ m_i
count_merge = Σ count_i
```

where `count` is the number of represented logical evidence units, not the number of physical `EvidenceAssignment` instances.

The consolidated representation also preserves the minimum structure needed for supported temporal or dependency adjustments and for expected `revise/retract` operations.

[[Memory#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]] additionally retains:

```text
at least one characteristic source observation / experience;
significant exceptions and counterexamples.
```

Materially different sources, dependency branches, regimes, independent checks, or significant confirmations and refutations are not merged when their differences remain epistemically useful.

After successful consolidation, other interchangeable routine observations and source `EvidenceAssignment` instances may be deleted under the shared [[Memory#^def-Memory|Memory lifecycle]].

Thus:

```text
consolidated EvidenceAssignment
→ retains the group's aggregate epistemic influence
  and necessary statistics about its structure;

representative observation
→ retains a specific example of experience
  represented by that group.
```

## Evidence Model

#topic_core

### Evidence

#topic_core

(def_id:: entity.Evidence)
> [!definition] **Evidence** is experience or a check result relevant to a specific belief, whether or not it changes that belief. ^def-Evidence

A relevant check that does not distinguish alternatives is also evidence:

```text
Δ = 0
evidence_mass = 0
```

It does not change `Strength` or increase `Support`, but it creates an [[#^def-EvidenceAssignment|EvidenceAssignment]] and records that the question was actually investigated.

Distinguish:

```text
Observation / EvaluationResult / other experience
→ what happened or was obtained;

EvidenceAssignment
→ what contribution that experience makes to a specific belief.
```

One source of experience may provide evidence for several beliefs.

---

### Evidence Sources

#topic_core

Main evidence sources:

```text
Observation
→ independently obtained fact about the world or a state;

EvaluationResult
→ result of an explicit check of a prediction,
  Note, Claim, Prompt, Program, or another testable object;

realized outcome
→ actual result of an action or process;

derived result
→ result of reasoning, simulation, or another Program,
  when its use as evidence is explicitly justified.
```

A derived result, including [[Core data structures#^def-Note|Note]] and [[Core data structures#^def-Claim|Claim]], does not automatically become evidence. Its grounds and dependencies must be recoverable through [[Memory#^def-ResultProvenance|provenance]] so the same source experience does not strengthen a belief repeatedly through multiple derived conclusions.

A prior is not new evidence. It specifies the initial belief state before the target accumulates its own evidence.

---

### EvidenceAssignment

#topic_core

(def_id:: entity.EvidenceAssignment)
> [!definition] **EvidenceAssignment** is the immutable contribution of one logical evidence unit, or an admissibly consolidated group of evidence, to a specific target. ^def-EvidenceAssignment

```python
EvidenceAssignment {
  target: <BeliefTarget>
    "Canonical semantic target to which the evidence is assigned."

  contribution: <UpdaterContribution>
    "Updater-specific sufficient representation of this evidence's effect on the target."

  evidence_mass?: <float>
    "Discriminative evidence mass for an epistemic updater that
     supports generic Support.
     For atomic evidence it is deterministically derived from contribution;
     after consolidation it retains the total mass of the components."

  observed_scope?: <time | TimeInterval>
    "World time to which the evidence applies;
     after consolidation it may cover an interval."
}
```

[[#^def-EvidenceAssignment|`EvidenceAssignment`]] is an ordinary immutable [[Memory#^def-OperatorOutput|`OperatorOutput`]]; there is no separate evidence store. Sources, data used for assessment, and program versions are recovered through shared [[Memory#^def-ResultProvenance|provenance]].

`contribution` is not `Strength`, `Support`, or `value_U`; its form and meaning are defined by the target's epistemic updater.

`evidence_mass` is mathematically linked to `contribution` by the epistemic updater's contract and is not assigned independently.

#topic_details

After consolidation, the representation must preserve the minimum sufficient statistics needed to recover [[#^def-EvidenceStats|`EvidenceStats`]] after the original assignments are deleted:

```text
evidence_count;
max_component_mass;
max_component_effect.
```

This component summary is a technical part of the consolidated representation, not a separate semantic object or public `EvidenceAssignment` field.

---

#### UpdaterContribution Contract

#topic_core

The form of `UpdaterContribution` is defined by the mechanism that updates the target:

```text
BinaryBeliefUpdater
→ signed log-evidence;

CompetitionScopeUpdater
→ relative log-evidence vector;

other epistemic belief updater
→ updater-specific sufficient evidence representation.
```

`UpdaterContribution` must be sufficient for deterministic reduction, merge, revision/retraction, and belief recomputation.

### EvidenceAssessmentProgram

#topic_core

(def_id:: entity.EvidenceAssessmentProgram)
> [!definition] **EvidenceAssessmentProgram** is an evidence-model Program that determines which [[#^def-BeliefTarget|`BeliefTarget`]] instances the received experience is relevant to, assesses its epistemic contribution, and creates [[#^def-EvidenceAssignment|`EvidenceAssignment[]`]]. ^def-EvidenceAssessmentProgram

This is a learnable program. Its main numerical question is how expected the received observation is under each possible target state. The code uses these assessments to compute a contribution to belief. An approximate initial model is allowed; its [[#Limiting Unsupported Influence|aggregate influence is limited]] until there are sufficient grounds to trust the calculation.

```text
Observation / EvaluationResult / derived result
+ source + provenance
        ↓
EvidenceAssessmentProgram
        ↓
EvidenceAssignment[BeliefTarget][]
```

The Belief System owns [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]], the `EvidenceAssignment` instances it creates, and their lifecycle. `LearningCoordinator` only calls this contract.

#topic_details

When assessing a prediction result, use the following flow, retained as a [[Memory#^def-ProgramRun|`ProgramRun`]]:

```text
ProgramRun → observable claim
+ independent Observation
→ EvaluationResult
+ provenance
→ EvidenceAssessmentProgram
→ EvidenceAssignment[]
```

Assessment distinguishes:

```text
observable claim
→ direct evidence from checking it;

latent claim
→ indirect evidence through dependent observable predictions;

OperatorConcept / Program
→ evidence about the mechanism's correctness or applicability;

policy / action-selection mechanism
→ evidence about the quality of the choice made.
```

Evidence is first assigned to the most directly checked level. A more general belief gets a separate `EvidenceAssignment` only when local explanations are insufficient and repeated independent results are genuinely informative about the general mechanism.

Provenance limits the set of possible `BeliefTarget` instances, but by itself does not prove which target the evidence applies to.

```text
provenance
→ which BeliefTarget instances could have been affected;

EvidenceAssessmentProgram
→ which BeliefTarget receives the evidence;

belief updater
→ how contributions are aggregated into epistemic state.
```

#topic_core

The Program does not assign learning credit or update belief or parameter state. `CreditAssignmentProgram` determines [[Learning system#LearningCredit and UnresolvedCredit|credit for the selected LearningTarget]], and `UpdatePlanner` selects the state to update. A belief updater recomputes [[#^def-BeliefData|`BeliefData`]]; an estimator or optimizer computes new parameter state, which the shared update mechanism saves.

Usually `LearningCoordinator` calls `EvidenceAssessmentProgram`; `resolve_prior` may also call it for retrieved sources. Evidence assessment does not require an evaluable `ProgramRun` or a learnable component.

#topic_details

`EvidenceAssessmentProgram` may take into account:

```text
source reliability;
measurement or observation quality;
applicability to the target;
whether evidence is direct or indirect;
known dependencies on other evidence.
```

A relevant check that does not distinguish alternatives still creates an `EvidenceAssignment` with `contribution = 0` and `evidence_mass = 0`.

For `CompetitionScope`, one source creates one `EvidenceAssignment` for the entire scope, with a contribution covering all alternatives. If the same source applies to several compatible beliefs, each may receive a separate assignment.

If the relation between evidence and target remains ambiguous, assessment either creates assignments under an applicable model that accounts for the ambiguity or creates no assignment and leaves the case `unresolved`. Approximate assessments remain subject to the general limit on unsupported influence. Unanchored implementation details do not receive independent evidence.

The internal numeric assessment returns `UpdaterContribution`; the program's public result is `EvidenceAssignment[]`.

For epistemic updaters, `evidence_mass` is then deterministically derived from the contribution and is not assigned independently.

There is no universal rule such as:

```text
contribution = reliability × applicability
```

because the contribution depends on the conditional observation model. If an observation is equally expected when the target is true and false, it yields `Δ = 0`; conditionally independent repetitions of such non-distinguishing observations do not strengthen belief.

Inputs used and the version of `EvidenceAssessmentProgram` are retained through the ordinary `ProgramRun` and provenance.

Important:

> `Contribution` records the evidence assessment accepted when the assignment was created. A later change in knowledge about the source does not automatically change an existing assignment.

#### Evidence → Contribution Calculation

#topic_core

The observation model describes which check results or source messages are possible under each target state:

```text
H — target state: 0/1 for a binary target or an alternative in a scope;
h — a particular state;
R — a possible observation result; r — the result received;
C — context, source, method of obtaining the observation, and regime;

q_h(r | C) — modeled probability of result r for discrete R,
             or density for continuous R when H = h in context C.
```

For a binary target, two estimates are required: one when the claim is true (`H = 1`) and one when it is false (`H = 0`). A single number for “confidence in the evidence” is not enough: an observation is informative when it is expected differently under these two states.

```text
received experience and extracted meaning
→ suitable target and observation model
→ likelihood of received r under each target state
→ log-evidence contribution
→ EvidenceAssignment
→ account for dependencies, time, and influence limits
→ BeliefData / Profile
```

The program defines the result space `R` and a normalized distribution over it for each `h`; for discrete results, `Σ_r q_h(r | C) = 1`. The received `r` selects an outcome from the distribution; the fact `R = r` itself is not included among the conditions `C`. If a binary target's negation combines several states, the model specifies their composition and the mixture used.

#topic_details

For a binary target:

$$
Δ = \ln \frac{q_1(r\mid C)}{q_0(r\mid C)}.
$$

For example, a check is positive in `80%` of cases when `H` is true and in `20%` when it is false. A positive result yields `Δ = ln(4)`. With prior `0.5`, a justified model gives posterior `0.8`; if these frequencies are only an LLM's current proposal, the limit on unsupported influence applies.

For a `CompetitionScope`, calculate `ℓ_k = ln q_k(r | C)` and `Δ_k = ℓ_k − mean_j ℓ_j`. One assignment contains the whole vector. Mass and aggregation follow the [[#Target-Specific Belief Updaters|updater contracts]].

Likelihoods and priors use consistent context. Summing separate log-likelihood ratios gives an exact Bayesian update in the selected model when observations are conditionally independent under each target state. Different sources and the absence of known dependencies do not guarantee this by themselves. Dependent observations require a joint model or [[#Evidence Dependencies|conditional information gain that accounts for evidence already used]]; a heuristic correction gives an approximate calculation and remains subject to the limit on unsupported influence.

For a continuous observation, compare densities with respect to the same measure or probabilities over predefined intervals. The model specifies smoothing that keeps the log-likelihoods used finite while preserving normalization. Zero frequencies in a small sample do not prove that an outcome is impossible. Hard impossibility is specified by semantic constraints.

#### Ways to Obtain an Observation Model

#topic_core

One version of a program may select its assessment method by evidence type and context. For one logical evidence item, select one final assessment; results from different methods are not added as independent confirmations.

| Method | When Used | If Grounds Are Insufficient |
|---|---|---|
| Known observation model | An applicable test protocol, measurement model, or published error characteristics exist. | Check transfer to this source and context; treat the unsupported portion as approximate. |
| Trained model | Comparable observations and independently resolved states of `H` are available. | Reuse a more general model or a smoothed initial estimate; limit influence until independent checking. |
| Explicit heuristic | There is a meaningful way to estimate conditional distributions, but data are limited; an LLM may prepare a rule or initial table. | Retain assumptions and gaps, apply the shared influence limit, and leave the case `unresolved` if no meaningful estimate is possible. |

An LLM may prepare a table, rule, or model code for a family of processes. It is given states `H`, the observation protocol, possible results `R`, and permitted context `C`. It returns normalized conditional distributions, sources, and brief applicability limits. Numeric format and grounding requirements follow the [[#LLM Prior Proposal|shared protocol for probabilistic proposals]], but the output here is `P(R | H, C)`, not `P(H)`.

Lack of exact calibration does not block work. Lack of a meaningful relationship between evidence and target is not replaced with a zero contribution: `Δ = 0` means the model assessed the check as non-distinguishing.

Conditional tables, counts, and logarithms are enough for the MVP. A universal probabilistic programming or differentiable inference library is not required; a specialized model may use one internally if the task justifies it.

#### Training the Evidence Model

#topic_core

An initial learnable implementation is a table of result `R` frequencies separately for true and false `H`, or for each scope alternative, under comparable contexts. Contexts are grouped by declared model features; the identity of a new target does not by itself create a new row. One shared table serves a process family; separate state is created when data show significant differences between sources, conditions, or regimes.

#topic_details

A simple smoothed estimator is:

$$
q_h(r\mid C)=
\frac{n_{h,r,C}+\kappa\pi_{h,r,C}}
{\sum_{r'}n_{h,r',C}+\kappa}.
$$

Here, `n` is the count of resolved cases, `π` is an initial normalized distribution with `π_{h,r,C} > 0` for every permitted result, and `κ > 0` is the smoothing strength. The initial distribution comes from an applicable shared model, external data, or a limited LLM proposal. Its pseudocounts are not real observations and do not create `Support / PriorSupport`.

A training case contains context, observation `r`, and an independently established state `h`. After resolving a case, update the corresponding table row through the [[Learning system#LearningCoordinator|ordinary learning pipeline]]. First evaluate the saved prediction; only then may the case be used for training. To check `q_h`, the distribution forecast must be produced without access to the evaluated `r`: in advance or in an independent evaluation run.

The agent's current belief, another LLM's agreement, and a repeated message from the same source do not become independent labels of truth. An unresolved outcome is not counted as false. Correcting a label adjusts the prior training contribution under the [[Learning system#Correcting Experience Already Used|shared rules]]; resolving the same case again does not increase the number of independent examples.

Sample applicability, selection bias, and separation of training and evaluation follow the [[Process Plane/Program Evaluation and Testing#Prediction Evaluation Protocol|shared protocol]]. Check conditional distributions and beliefs derived from them in significant contexts. Error-model counts and [[#^def-CalibrationStats|CalibrationStats]] have different meanings: the former train the model; the latter describe forecast quality.

As data become available, the table may be replaced with regression, a calibrator, or a specialized model under the [[Process Plane/Program Lifecycle and Evolution#Preparing Initial Models|shared model selection and evaluation rules]].

#### Assessment Lifecycle

#topic_core

Preparing and changing the program follows the [[Process Plane/Program Lifecycle and Evolution#Preparing Initial Models|shared Program Lifecycle]]. The following path is sufficient for an initial version:

1. **Prepare the family.** Reuse applicable models and rules; define observations, targets, contexts, and initial conditional distributions. If needed, one limited LLM/research session fills gaps. Save the result as program code, settings, or a model artifact.
2. **Handle ordinary events in code.** Select a handler by observation type and context, obtain model parameters, and calculate contributions. A new process instance, target, or semantic anchor under a known contract does not require an LLM call.
3. **Assess a new case as a shared batch.** First use an applicable shared handler. If that is insufficient, one assessment owner gathers related targets and already extracted data into a shared program/event batch. Make one LLM request for the batch. It returns assessments for several targets, from which code creates assignments, or proposes a reusable rule.
4. **Accumulate independent checks.** Resolved cases train the observation model and source error model. Until quality is confirmed, the shared limit on unsupported influence applies; the number of processed messages alone does not remove it.
5. **Review material changes.** In response to persistent error, new conditions, or an unsuitable evidence format, refine the model or separate a regime. One unusual outcome does not by itself require a new program. Reassess affected old evidence through `revise`.

#topic_details

A batch is a set of inputs to an existing program. If perception or another program has already extracted the message's meaning, assessment uses that result. When this path has an LLM perform both extraction and assessment, combine them in one call.

Reads of prior and [[#^def-SourceReliability|SourceReliability]], handlers for individual anchors, and child programs use ready models. Their need for an LLM is passed to the batch owner; do not make separate assessment requests for each anchor. A retry of a technically failed request uses the same batch and budget; do not request additional responses just to reconcile assessments. All costs count against the [[Cognition and Attention|Task and its child runs]]. If the LLM is unavailable, times out, or exhausts its allocated budget, use the declared approximate path or retain `unresolved`; continue handling known cases within the Task budget. Exhausting the overall budget follows the ordinary Task stop and review rules.

Reprocessing a batch uses its saved result while its inputs, models, and applicability conditions remain valid. During reassessment, retain the [[#Logical Evidence Identity and Duplicate Prevention|identity of source evidence]] and perform `revise`.

External research follows the [[Process Plane/Program Lifecycle and Evolution#Stage 1: gather_relevant_info|shared program preparation rules]]. Ordinary reads and new evidence do not start web search.

When a regime changes, previous checks are not automatically transferred to the new conditions. First reassess model applicability; use the shared limited-influence fallback for an unconfirmed regime. The previous handler continues to serve stable cases. Check new code or models on independent cases, accounting for cost, before replacing the active version.

#### Common Cases and Applicability Limits

#topic_details

| Case | Rule |
|---|---|
| Pass/fail check or measurement | Use a test error model, density, or predefined intervals; error magnitude alone is not a contribution. |
| Source message | Use a [[#Source Reliability Estimation|conditional model of its messages]]; high overall accuracy is not the same as a large likelihood ratio. |
| Several alternatives | Assess the entire scope with one vector; adding or removing alternatives requires checking model applicability. |
| Repeats, paraphrases, shared premise | Account for [[#Evidence Dependencies|dependencies]] before summing; several texts do not guarantee several confirmations. |
| Expected message not received | This is evidence only under a defined observation protocol and grounds to believe the message would have been detected. |
| Contradictory observations | Retain both sides with provenance, check source, dependencies, and regime; contradiction does not automatically make a rare outcome unreliable. |
| Parameters of the assessed model change | Evidence about a fixed version does not automatically support the new version; evidence about the learning mechanism applies only under the relevant Criterion and context. |

#### Evidence for TRIGGER and CONDITION

#topic_details

[[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]] creates different kinds of evidence for beliefs about `TRIGGER` and `CONDITION`:

```text
TRIGGER:
updated as an active causal relation
"what actually led to the transition"

CONDITION:
updated as an applicability boundary
"under what conditions the transition is possible / impossible"
```

If a transition occurs, create:

```text
active TRIGGER
→ supporting EvidenceAssignment

valid CONDITION
→ supporting EvidenceAssignment
```

If the transition does not occur:

```text
failed TRIGGER
→ opposing EvidenceAssignment
  or evidence for a narrower context;

missing / false CONDITION
→ blocking evidence
  for the corresponding applicability boundary.
```

If experience is evaluated and selected for learning, `CreditAssignmentProgram` may separately issue [[Learning system#LearningCredit and UnresolvedCredit|LearningCredit]] for the corresponding [[Learning system#^def-LearningTarget|LearningTarget]]; `UpdatePlanner` selects the states of related learnable components. [[#^def-EvidenceAssignment|`EvidenceAssignment`]] and `LearningCredit` are not the same output.

---

### Evidence Dependencies

#topic_core

Several [[#^def-Evidence|evidence]] items may share a source, observation, premise, or computational result, so they must not automatically be treated as independent.

Dependencies are derived from:

```text
provenance
+ EVIDENCE_DEPENDS_ON relations
        ↓
dependency view
        ↓
updater
```

`provenance` shows computational dependencies. `EVIDENCE_DEPENDS_ON` records additional information dependencies identified through reasoning or learning.

#topic_details

For example:

```text
EVIDENCE_DEPENDS_ON(SiteAReport, ReutersReport)
EVIDENCE_DEPENDS_ON(SiteBReport, ReutersReport)
EVIDENCE_DEPENDS_ON(SiteCReport, ReutersReport)
```

means that the three publications are not three independent confirmations.

`dependency view` is a computed representation; a separate `DependencyGroup` entity and `dependency_group_id` field in [[#^def-EvidenceAssignment|`EvidenceAssignment`]] are not needed.

In the MVP, paraphrases of one primary source use one contribution from the source observation. If dependent reports add information, use a joint model or a model of conditional information gain that accounts for evidence already used. Without such a model, use one preselected, most direct representation of the source; the selection must not depend on which contribution supports the target more strongly. Retain the other reports for provenance and review, but they do not increase `Support` as independent confirmations.

Evidence used as a condition for such information gain is retained in the dependencies. Changing or retracting it requires reassessment of the dependent contribution.

#### Dependency-Aware Consolidation

#topic_details

Dependency structure is consolidated together with evidence.

If several evidence items have one common primary source, they may be collapsed into one [[#^def-EvidenceAssignment|`EvidenceAssignment`]] that retains the dependency on that source.

For example:

```text
700 reposts ← Reuters
250 reposts ← AP
50 independent checks
```

may be represented as:

```text
Reuters-derived evidence → consolidated EvidenceAssignment
AP-derived evidence      → consolidated EvidenceAssignment
independent checks       → separate or independently consolidated EvidenceAssignment instances
```

[[Memory#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]] does not merge evidence across materially different dependency branches if doing so would change belief or eliminate an expected ability to `revise/retract`, reassess a source, or analyze independent confirmations.

Understanding of dependencies is itself revisable: if another shared source or an independent check is discovered later, semantic relations and dependent belief contributions may be reconsidered.

---

### Logical Evidence Identity and Duplicate Prevention

#topic_core

The same logical evidence must not influence one target more than once.

#topic_details

The logical identity of an evidence assignment is defined by this key:

```text
evidence_key =
(
  source_evidence_ref,
  target_ref
)
```

`target_ref` is the stable identity of [[#^def-BeliefTarget|`BeliefTarget`]] under the [[Core data structures#Objects and References|shared object and reference rule]]. `source_evidence_ref` addresses one logical evidence unit, usually through:

```text
TraceOutputRef(event_ref, output_path)
```

where `output_path` points to the corresponding semantic result.

There is at most one current logical assignment for each `evidence_key`.

If one source affects a target in several ways, [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]] combines them into one `contribution` instead of creating multiple independent assignments.

If one [[Memory#^def-OperatorOutput|`OperatorOutput`]] contains multiple independent evidence units, each must have a different semantic `output_path`.

Repeat processing:

```text
same evidence_key + equivalent assessment
→ no-op;

same evidence_key + changed assessment
→ revise the existing assignment.
```

The assignment role and version of `EvidenceAssessmentProgram` are not part of `evidence_key`: changing how the same source evidence is assessed does not create new independent evidence.

`evidence_key` prevents double counting the same logical source result. Dependencies between different evidence items that share a basis are handled separately through the `dependency view`.

Redelivery or retry uses the identity of the source event. Two genuinely different observations with the same values have different identities; identical text is not a deduplication rule. A corrected observation remains linked to the previous logical evidence and revises its contribution.

Logical evidence identities are retained during consolidation; compact representation of them follows the `Consolidation invariant` rules.

After lossy consolidation, the lifecycle operates at the granularity that the representation actually retains.

---

### Evidence Lifecycle

#topic_core

#### Active Evidence

#topic_core

[[#^def-EvidenceAssignment|`EvidenceAssignment`]] is immutable, but its assessment may be revised, retracted, or replaced by a consolidated representation. Therefore, the system separately specifies which representation of each logical evidence item is used now.

#topic_details

The lifecycle applies to logical evidence (`evidence_key`), not to a specific immutable `EvidenceAssignment` record: after revision or consolidation, one logical evidence item may be represented by another record, while one consolidated assignment may represent several `evidence_key` values. Therefore, current state is stored separately from the assignment itself.

The current state of logical evidence is given by a mapping:

```text
current_evidence[evidence_key]
→ assignment_ref | RETRACTED
```

(def_id:: entity.ActiveEvidence)
> [!definition] The target's **active evidence** is the set of unique `EvidenceAssignment` instances currently referenced by its `evidence_key` values. ^def-ActiveEvidence

```text
active_assignments(target)
→ unique active EvidenceAssignment[]
```

Thus `revise`, `retract`, and consolidation change the current mapping without rewriting past `EvidenceAssignment` records.

#topic_core

Distinguish:

```text
active
→ assignment currently selected to represent logical evidence;
  applicability to a read is checked separately;

effective
→ size of its current contribution after temporal
  and dependency adjustment and the shared influence limit.
```

Therefore, active evidence may have zero effective contribution, for example a relevant non-distinguishing check with `Δ = 0`.

---

#### Evidence Revision and Retraction

#topic_core

Ordinary new evidence creates a new [[#^def-EvidenceAssignment|`EvidenceAssignment`]] and does not change past records.

Use `revise` and `retract` only when the assessment of **previously assigned evidence** changes.

---

##### Revising Evidence

#topic_details

`revise` replaces the current assignment for this `evidence_key` with a new one:

```text
K: E_old
   ↓ revise
K: E_new
```

`E_old` remains an immutable historical record. For atomic evidence it no longer belongs to active evidence; for a consolidated representation, the coordinated replacement rules below apply.

##### Retracting Evidence

#topic_details

`retract` excludes previously assigned evidence from the current belief:

```text
K: E_old
   ↓ retract
K: RETRACTED
```

`retract` does not create evidence for the opposite claim.

If a target has no active evidence of its own, its state reflects [[#^def-EvidenceStats|`EvidenceStats`]]:

```text
active evidence = ∅
→ Strength is determined by the prior
→ Support = 0
→ PriorSupport is determined by prior backing
→ EvidenceStats reflects the absence of active evidence
```

##### Lifecycle State

#topic_details

A change is applied atomically only if the expected state still matches:

```text
current_evidence[K] == expected_old_state
```

If another process has already changed the state, recalculate the operation relative to the new state.

When publishing a new or revised assignment, the runtime also checks [[#Read-Time Freshness|whether its grounds are current]] within the same protected operation. A stale result is not published as current; a repeated assessment follows the shared lifecycle.

A successful `revise` or `retract` atomically updates `current_evidence` and is recorded by a [[Memory#^def-TraceEvent|`TraceEvent`]] retaining [[Memory#^def-ResultProvenance|provenance]] and operation history.

If one consolidated assignment represents several `evidence_key` values, revising a component replaces the representation for every affected key consistently: the component's new contribution and the remaining aggregate must not contain the same evidence. The old aggregate is excluded from active evidence in full. If the component can no longer be isolated from retained data, revise at the group's retained granularity and explicitly state the loss of precision; partially excluding one key must not be presented as removing its contribution from the remaining aggregate.

`GraphDelta` is not used for evidence lifecycle: it applies to changes in the semantic graph.

##### Semantic Target Revision

#topic_core

A change in epistemic assessment must be distinguished from a change in the world state and from a change in the meaning of the target itself.

```text
assessment of previously assigned evidence changed
→ revise / retract EvidenceAssignment;

new evidence changed belief about the same target
→ target stays the same;
→ recompute value_U / BeliefData / Profile;

world state changed
→ ordinary temporal / semantic change to the world model
  through GraphDelta;

meaning of a property, relation, Criterion,
or CompetitionScope changed
→ semantic structural revision;
→ if the identity of the question being assessed changed,
  create a new target.
```

A change to current `value_U` by itself does not create a new target. See [[Attribution Plane#^def-Criterion|Criterion]] for its canonical definition; its read representations remain [[#^def-BeliefData|`BeliefData`]] and [[#^def-Profile|`Profile`]].

#topic_details

For example:

```text
Mass(Object#7):
12.4 → 12.5
```

may be a new estimate of the same quantity, `Mass(Object#7)`.

A change in the real world state is also not an evidence `retract`:

```text
close_facet_state
→ the state really existed,
  but is no longer current;

retract EvidenceAssignment
→ specific evidence is no longer
  used as grounds for belief.
```

#topic_core

Semantic changes to the persistent graph are made through `GraphDelta`. `revise/retract` apply to the lifecycle of [[#^def-EvidenceAssignment|`EvidenceAssignment`]] and do not require a separate `BeliefUpdate` entity; their history is retained through immutable assignments, lifecycle records, and `TraceEvent` with provenance.

---

#### Temporal Consolidation

#topic_details

World time to which [[#^def-EvidenceAssignment|`EvidenceAssignment`]] applies is specified through `observed_scope`:

```text
atomic evidence
→ a specific point in time;

consolidated evidence
→ interval [t_from, t_until).
```

`known_at` is the as-of time for the agent's knowledge, used for historical reads; it is not part of `observed_scope` or the semantic identity of evidence.

[[Memory#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]] may combine evidence from different times only if the loss of temporal detail does not materially change its future use.

```text
nearby, homogeneous evidence
→ may be combined;
```

Interval size is selected adaptively: dense, older routine evidence can usually be represented over a larger interval, while recent, rare, variable, or possibly near a regime change should be represented in greater detail.

Temporal and dependency adjustments, when needed, are applied while computing belief, not by changing saved evidence. Consolidation is allowed only if the retained representation contains enough information for the supported adjustments.

If a later change to adjustment policy requires detail that has been lost:

```text
retained aggregate is sufficient
→ recompute;

source experience is retained
→ reassess;

source details were deleted
→ use the aggregate with known loss of precision.
```

Do not consolidate across a confirmed boundary between materially different regimes. If the boundary is uncertain, `MemoryConsolidationProgram` prefers less compression.

As with other evidence consolidation, retain characteristic representatives, exceptions, counterexamples, and cases needed to analyze regime changes.

---

## Provenance, Reassessment, and Recalculation

#topic_core

### Read-Time Computation and Provenance

#topic_core

Current epistemic state is computed when read:

```text
prior + PriorSupport
+ active EvidenceAssignment[]
        ↓
temporal / dependency adjustment
+ shared limit on unsupported influence
        ↓
target-specific updater
        ↓
BeliefData / Profile
+ EvidenceStats
```

If `value_U` itself is trained by an estimator, it is computed separately from that estimator's observations / sufficient state.

A read does not write anything. A new [[#^def-EvidenceAssignment|`EvidenceAssignment`]] is created only for new evidence or an explicit reassessment of old evidence; provenance for each assignment is retained by the ordinary provenance mechanism. A successful read returns computed [[#^def-BeliefData|`BeliefData`]], [[#^def-Profile|`Profile`]], and [[#^def-EvidenceStats|`EvidenceStats`]]; if a current assessment is unavailable, it returns `unknown` under the rules below.

#### Read-Time Freshness

#topic_core

A read uses a consistent state of the prior, active evidence, applicable models, and policies. Saved assessments and caches remain usable while their input, model states, and applicability conditions remain valid for the query. This includes derived inputs used as current knowledge; a change outside their scope does not require reassessment.

If the required recalculation can be performed as ordinary read-time computation, return the recalculated result. If a new assessment is needed but has not been performed, return `unknown` with the reason and affected grounds. A stale contribution must not be silently excluded or zeroed: this could remove refuting evidence. Waiting for reassessment is not itself `retract`.

The caller or consciousness organizes [[#Assessment Lifecycle|batch reassessment]] through the existing Learning pipeline in the current [[Cognition and Attention#Goal, Task, and Task Specification|Task]], when needed, and retries the read. Until an applicable assessment is obtained, the result remains `unknown`; the old number is not used as current.

These rules also apply to reads through planes and materialized results. During [[Attribution Plane#Historical Reconstruction of a Property|historical reading]], applicability is checked at `known_at`; later changes do not rewrite earlier snapshots or their grounds.

---

### Finding Affected EvidenceAssignments

#topic_details

Reassess old evidence if relevant knowledge used to create it changes, such as the source error model, its dependencies, or the logic of [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]]. Provenance records model versions and the model state used, allowing affected assignments to be found.

Find affected assignments through existing dependencies:

```text
provenance
+ EVIDENCE_DEPENDS_ON
→ affected EvidenceAssignment[]
```

### Evidence Reassessment and Belief Recalculation

#topic_details

If knowledge used to assess old evidence changes, reassess affected [[#^def-EvidenceAssignment|`EvidenceAssignment`]] instances through [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]]:

```text
relevant knowledge changed
→ affected EvidenceAssignment[]
→ rerun EvidenceAssessmentProgram
→ replace old assignment with a new assessment under current grounds,
  even if the numeric contribution is unchanged
→ recalculate belief
```

#topic_core

An updater recalculates only its own target. Effects on other beliefs pass through the ordinary Learning pipeline by creating new evidence, not through a hidden cascade of updates.

A change in likelihoods requires a new assessment and `revise`: the saved raw contribution is immutable. A change only to an applicable discount policy or shared influence limit requires recalculating the effective view. Reassessment retains the identity of the source evidence and its dependencies; the history of earlier assessments and predictions remains available for Evaluation.

### Recalculation After Consolidation

#topic_core

After source [[#^def-EvidenceAssignment|`EvidenceAssignment`]] instances are deleted, the precision of future `revise/retract` is limited to the granularity of the retained consolidated evidence. Consolidation does not have to be reversible. It may intentionally trade the ability to revise routine evidence individually for a more compact representation if [[Memory#^def-CompactionValidationProgram|`CompactionValidationProgram`]] considers that loss acceptable.

---

### Source Reliability Estimation

#topic_core

(def_id:: entity.SourceReliability)
> [!definition] **SourceReliability** is an ordinary `PropertyConcept` describing the expected correctness of information from a source in a given scope. A learnable Program that assesses this property is associated with it. ^def-SourceReliability

```text
read_property(source, SourceReliability, domain=Programming)
        ↓
SourceReliability Program
        ↓
value_U + BeliefData
```

#topic_details

In this example, the property contract defines `domain` as the scope in which reliability is assessed. The Program may use a prior, past experience, [[Memory#^def-ResultProvenance|provenance]], and semantic relations of the source, and improves through the ordinary [[Learning system#^def-LearningSystem|Learning System]]. Reliability in one domain is not automatically transferred to another.

Calculating a contribution requires a conditional message model, such as `P(report positive | H, C)` and `P(report positive | ¬H, C)`. The same program or an associated module reused by different assessments provides it. The source's overall accuracy alone does not determine these probabilities. A source that always answers “yes” does not distinguish `H` from `¬H`, even if it is often correct because `H` has a high base rate.

When a target is extracted from a source's own statement, “the source says H” is determined by the selection method. The truth frequency of such statements cannot recover the two conditional probabilities without a selection model. Training requires an explicitly specified message-generation procedure and response space; without them, use an approximate whole-message model with limited influence or leave the case `unresolved`.

If the observation model already accounts for source errors, do not apply source reliability a second time as a multiplier to the same contribution. Assessing the source changes the assessment model and affected assessments; it does not create another independent confirmation for every message.

For a new user source, an initial presumption of cooperation assigns correctness `0.75` within the declared scope. This is a heuristic without backing; it does not replace the conditional error model. Belonging to system logs or an API does not make every content claim infallible: confirmed receipt of a message and truth of its content are different targets.

Knowledge about the source is stored in the ordinary semantic graph: area of expertise, how information was obtained, known limitations, and dependencies. Numeric counts and parameters belong to estimator state. Large datasets, model tables, and checkpoints may be stored as [[Core data structures#^def-Artifact|versioned artifacts]] referenced from the graph with provenance.

Each parameter set has one write owner. Standard training goes through the [[Learning system#PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher|shared update mechanism]]; a graph cache and artifact do not independently accumulate the same counts. A cached assessment records the state version it used.

Assessment is lazy: a rarely used source uses a shared model without separate state. Frequent or significant interaction may lead to its own statistics and cache. A read uses a ready model and does not launch hidden LLM/research; an unknown source uses the [[#Assessment Lifecycle|shared fallback]]. Training uses independently resolved cases under the [[#Training the Evidence Model|same protocol]] as the evidence model.

When needed, model `Truthfulness` similarly as a separate `PropertyConcept`: a source may be honest but unreliable due to limited knowledge.

---

### Updater or Program Changes

#topic_details

If a new updater can use saved contributions directly:

```text
active EvidenceAssignment[]
→ new updater
→ recomputed belief
```

If the new rule requires information no longer present in the contributions:

```text
retained source experience
→ reassessment
→ new EvidenceAssignment instances.
```

If the necessary source data have already been irreversibly deleted, exact recalculation with the new model is impossible. The system uses remaining consolidated evidence at its known granularity or obtains new evidence.

#topic_details

Thus, provenance makes it possible to find and reassess the grounds for belief, while the extent of possible recalculation is determined by the level of detail memory actually retains.

---

## World-Model Integration

#topic_core

### Runtime Use of Beliefs

#topic_core

At runtime, current [[#^def-Belief|belief]] is one input to reasoning, planning, and control.

The basic interface for an individual claim or value is:

```text
value_U
+ BeliefData {
    Strength,
    Support,
    PriorSupport
  }
```

When needed, use computed [[#^def-EvidenceStats|`EvidenceStats`]] with it.

For a `CompetitionScope`, use one computed [[#^def-Profile|`Profile`]] instead of independent belief records for alternatives; do not reduce it to only the most likely alternative.

High `Support` does not eliminate uncertainty between alternatives:

```text
Profile:
A = 0.5
B = 0.5

Support = high
```

means that much discriminative evidence has accumulated, but it does not give one alternative sufficient advantage over the other. High `Support` alone is not grounds to choose one.

#topic_details

If `value_U` is a numeric or distributional structure, runtime uses representations needed for the task, for example:

```text
point estimate;
interval;
mean / variance;
quantile;
P(value_U ∈ range).
```

These are computed from the corresponding Program's `value_U` and are not additional `BeliefData` fields.

`Strength` / `Profile` express current belief and may be used directly for prediction and expected-value reasoning. They are not independent measures of how strongly evidence supports the belief.

[[#^def-BeliefData|`BeliefData`]], `Profile`, `EvidenceStats`, characteristics of `value_U`, [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]], and other relevant signals may be used by control mechanisms to calculate `attention_priority`, make [[Self#Exploration|local research choices]], and determine commitment.

For decisions where the quality of grounds matters, the controlling Program must consider not only `Strength` / `Profile` but, when needed, also `Support`, `PriorSupport`, `EvidenceStats`, entropy, and the cost of error.

---

### Beliefs Across Abstraction Levels

#topic_core

Beliefs may concern different representation levels of an object: [[Core data structures#^def-Facet|Facet]], [[Memory#^def-Episode|Episode]], [[Core data structures#^def-Instance|Instance]], and [[Core data structures#^def-Prototype|Prototype]].

```text
Facet / Episode
→ belief about a specific state or case;

Instance
→ belief about a specific object;

Prototype
→ belief about a type / class of objects.
```

#topic_details

For example:

```text
Facet:
"Igor is ill now"

Instance:
"Igor has chronic condition X"

Prototype:
"People with condition X tend to have symptom Y"
```

#topic_core

At every level, `Strength` and `Support` have the same meaning:

```text
Strength
→ how strongly the agent believes the claim;

Support
→ how much effective evidence supports it.
```

[[#^def-Evidence|Evidence]] initially applies to the level it directly supports.

#topic_details

```text
observation of a specific state
→ Facet / Episode belief;

recurring experience about one specific object
→ may become evidence for an Instance belief;

experience across objects of one type
→ may become evidence for a Prototype belief.
```

Transfer of evidence to a more general level is performed through [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]] only when the generalization is justified.

Conversely, a more general level may be used as a prior:

```text
Prototype
→ prior for Instance;

Instance
→ prior for a specific Facet / Episode.
```

A prior is not the child target's own evidence and does not increase its `Support`. If a prior comes from another belief, its effective backing is returned separately as `PriorSupport`.

One source of evidence must also not be counted again across several levels. For example, experience about a specific `Instance` that was already used to build a `Prototype` must not return to the same `Instance` through the Prototype as independent confirmation.

---

### Beliefs Across Planes

#topic_core

All planes use the same epistemic representations:

```text
individual claim / value
→ value_U + BeliefData;

mutually exclusive + exhaustive alternatives
→ CompetitionScope + Profile.
```

Only the semantic target differs. The form of an individual `value_U` is determined by the nature of the modeled quantity and the needs of the corresponding Program.

#### Attribution Plane

#topic_core

[[#^def-Belief|Belief]] concerns the value of an object's property or the scope of its discrete scale.

```text
Igor.HealthStatus
→ Profile {Healthy: ..., Sick: ..., Recovering: ...};

MyCar.Speed = 112 km/h
→ BeliefData.
```

Mutually exclusive and exhaustive values use a shared [[#^def-Profile|`Profile`]]; an individual `value_U` uses [[#^def-BeliefData|`BeliefData`]].

#### Semantics Plane

#topic_core

[[#^def-Belief|Belief]] concerns a semantic relation fact.

```text
PART_WHOLE(Wheel, Car)
CAUSES_UNDER(Infection, Death, NoTreatment)
```

`Strength` means the agent's confidence in the relation itself.

If a relation contains a quantity, such as a heritability coefficient or effect size, that quantity is part of `value_U` or the relation's parameters, not `Strength`.

#### Process Plane

#topic_core

[[#^def-Belief|Belief]] concerns a claim about a process state, transition, condition, cause, or model.

For example:

```text
"FuelPresent is a CONDITION for starting the engine"

"Rain caused WetRoad in this case"
```

Distinguish belief from the parameters of the model itself:

```text
transition probability;
OutcomeProfile;
effect magnitude;
expected signal
→ model values;

BeliefData
→ how strongly the agent believes
  the corresponding model or estimate is correct.
```

A `Program` with `model ∈ Program.roles` is itself a testable process model. The same principle applies to semantically significant `OperatorConcept`, `TRIGGER`, and `CONDITION`.

#### Association Plane

#topic_core

Activation, co-activation, and associative weights describe the dynamics of activity propagation and are not beliefs by themselves.

[[#^def-BeliefData|`BeliefData`]] appears only if the agent turns a discovered associative pattern into an explicit claim about the world or its own model.

---

One fact may be used in several planes without creating new evidence.

```text
native fact
→ projection / view in another Plane
→ same grounds for belief
```

Create a new [[#^def-EvidenceAssignment|`EvidenceAssignment`]] only when new grounds appear or a separate conclusion is justifiably assigned to the relevant belief by [[#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]].
