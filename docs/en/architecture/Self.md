## Self Graph
#topic_core

(def_id:: et.Self)
> [!definition] **Self** — a persistent `Concept` representing the identity of the current agent in its own world model. ^def-Self

It is the primary semantic anchor for knowledge and processes concerning the agent itself.

The agent's own implemented processes are organized in **Self/Process** (`SelfProcess`): `PART_WHOLE(SelfProcess, Self)` denotes membership in the agent, while `SUBTYPE_OF(SelfProcess, Process)` preserves the link to the general process taxonomy. The subtypes `TaskManagement`, `CognitiveControl`, `MemoryProcessing`, and `Learning` group existing processes; program roles are represented by `_exec.py` and `_model.py`. The general `Process` root also continues to describe processes in the external world.

Conceptually, the Self domain is divided as follows:

```text
Self
├─<─ MODELS ───────── SelfModel
│
└─<─ REGULATES ────── SelfRegulation
                      ├─<─ PART_WHOLE ── GoalManagement
                      ├─<─ PART_WHOLE ── AttentionControl
                      ├─<─ PART_WHOLE ── CognitionControl
                      ├─<─ PART_WHOLE ── ResourceControl
                      ├─<─ PART_WHOLE ── Verification
                      ├─<─ PART_WHOLE ── Reflection
                      └─<─ PART_WHOLE ── ProgramImprovement
```

`SelfModel` answers **“How am I actually structured and how do I work?”** `SelfRegulation` answers **“How do I manage myself and improve my work?”** Its main subprocesses are linked through `PART_WHOLE`.

Here, [[Process Plane/Process Ontology and Semantic Interface#PART_WHOLE in Process Responsibility|`PART_WHOLE`]] defines only the semantic decomposition of `SelfRegulation`; implementation, runtime orchestration, and permitted self-changes are defined separately.

---

### SelfModel
#topic_core

(def_id:: et.SelfModel)
> [!definition] **SelfModel** — the part of the semantic graph linked to `Self` that describes the agent itself, its components, states, and behavior. ^def-SelfModel

It uses ordinary EverTree structures:

```text
properties / Facets
→ properties and states;

semantic relations
→ structure and component links;

Claims
→ individual claims about the agent;

ProcessModels
→ how the agent or its components
  behave under different conditions.
```

If an ability has a formally defined `PropertyConcept`, scale, and `Criterion`, it may be represented as a property fact. Otherwise, abilities, limitations, and characteristic errors are represented as a `Claim` or `ProcessModel`.

For example:

```text
"With long workflows, an LLM more often loses requirements."
→ Claim / ProcessModel;

"The cognition context is overloaded right now."
→ state / property.
```

`SelfModel` is updated from `ProgramRun`, Evaluation, observations, and Reflection results.

---

### SelfRegulation
#topic_core

(def_id:: et.SelfRegulation)
> [!definition] **SelfRegulation** — the semantic domain of processes and knowledge through which the agent manages its own behavior, internal states, and learnable mechanisms. ^def-SelfRegulation

Its processes are ordinary `ProcessConcept`s, linked to `Self`, regulated components, and other relevant Concepts through semantic relations.

Programs for these processes are linked through [[Process Plane/Process Ontology and Semantic Interface#^semantic-program-organization|`PROGRAM_FOR_PROCESS`]] and classified through [[Process Plane/Program Layer#Program Roles|`Program.roles`]]. Meta-programs follow the shared [[Process Plane/Program Lifecycle and Evolution#Meta-Program Lifecycle Safety|conservative lifecycle]].

One `Program` with `exec ∈ Program.roles` may orchestrate child Programs and also serve as a reusable subprocess of a parent Program.

#### Exploration

The method and intensity of exploration are chosen individually for each process and each of its parts. Selection accounts for process specifics, risks and constraints, possible value, accumulated experience and uncertainty, available budget, [[Cognition and Attention#Goal, Task, and Task Specification|Tasks]], and the agent's [[#Values|Values]]. Consciousness or a managing `Program` selects suitable mechanisms: hypothesis checks, experiments, search breadth, or an [[Process Plane/Action Selection and Planning#Exploration|exploration policy for action selection]].

---

### Values
#topic_core

(def_id:: et.Value)

> [!definition] **Value** — a stable representation of **which states and outcomes are desirable and important to the agent**. ^def-Value

Values define the high-level direction of behavior:

```text
Values
→ Goal generation / prioritization
→ LearningObjectives / Criteria
→ Attention / Cognition / Action
```

Base Values belong to [[#Meta-Improvement|L4]], are set by the developer, and are not changed by the agent. The agent learns **how to implement them better** through Goals, Programs, and `SelfRegulationPrinciples`.

`Value` is not a hard constraint, a specific `Goal`, or a universal scalar reward.

For the MVP:

```text
EpistemicQuality
→ a state in which the agent's world model is
  true, well-supported, and predicts experience well;

AgentCapability
→ a state in which the agent can reliably and efficiently
  achieve meaningful goals under varied conditions.
```

[[#Self-Improvement Loop|Self-improvement]] is a way to increase `AgentCapability`, not a separate `Value`.

---

### Self-Regulation Principles
#topic_core

(def_id:: et.SelfRegulationPrinciple)

> [!definition] **`SelfRegulationPrinciple`** — a `Concept` representing a generalized, testable rule for **how the agent should organize cognition or its own behavior under specified conditions**. ^def-SelfRegulationPrinciple

`Values` define **what is desirable for the agent**; `Goals`, `LearningObjectives`, and `Criteria` operationalize this in specific tasks, while `SelfRegulationPrinciples` define stable rules for **how the agent should organize its work to achieve them**.

Principles are stored in the semantic graph and retrieved by relevance for context preparation, planning, verification, reflection, and program construction.

Initial `SUBTYPE_OF` subtypes:

```text
SelfRegulationPrinciple
├─<─ SUBTYPE_OF ── PreserveRequirements
├─<─ SUBTYPE_OF ── MinimalSufficientStructure
├─<─ SUBTYPE_OF ── VerifySemanticBlocks
├─<─ SUBTYPE_OF ── SeekIndependentVerification
├─<─ SUBTYPE_OF ── ExternalizeExactState
└─<─ SUBTYPE_OF ── EscalateOnUncertainty
...
PreserveRequirements
→ retain material requirements and scoped constraints
  in structured state; recheck requirements before a significant
  effect, and invariants at relevant control points
  throughout their scope;

MinimalSufficientStructure
→ add a structural element only if it solves
  a specific, necessary task or problem;

VerifySemanticBlocks
→ check every significant condition, transition, action,
  or result against its purpose, local contract,
  and task specification;

SeekIndependentVerification
→ for significant decisions, use verification independent
  of the candidate-producing reasoning path when possible;

ExternalizeExactState
→ represent states, values, constraints, and dependencies
  requiring exact consistency in structured state
  or deterministic computation, not only LLM reasoning;

EscalateOnUncertainty
→ direct conscious attention and verification to places
  with greater uncertainty, novelty, contradiction, or cost of error.
```

Distinguish:

```text
SelfModel:
"LLMs tend to lose requirements
in long workflows."

SelfRegulationPrinciple:
"Preserve material requirements
in structured state and check them before a significant effect."
```

A principle is not a `Value` or hard constraint. It is learnable knowledge: its **effectiveness, scope, and applicability conditions** are refined through experience.

Use semantic relations for efficient navigation:

(formal_id:: et.APPLIES_TO.schema)
```python
APPLIES_TO(
  subject,
  target,
  condition?
)
```
^spec-AppliesTo

(def_id:: et.APPLIES_TO)
> [!definition] **`APPLIES_TO`** — `subject` applies to `target` under the specified conditions. ^def-AppliesTo

(formal_id:: et.ADDRESSES.schema)
```python
ADDRESSES(
  subject,
  problem,
  condition?
)
```
^spec-Addresses

(def_id:: et.ADDRESSES)
> [!definition] **`ADDRESSES`** — `subject` is intended to resolve, reduce, or manage the specified problem. ^def-Addresses

(formal_id:: et.IMPLEMENTS.schema)
```python
IMPLEMENTS(
  implementation,
  specification
)
```
^spec-Implements

(def_id:: et.IMPLEMENTS)
> [!definition] **`IMPLEMENTS`** — `implementation` operationally implements the corresponding rule, mechanism, or specification. ^def-Implements

One principle can therefore apply to [[Core data structures#^def-Prompt|`Prompt`]], `PromptPreparation`, `ProgramSynthesis`, and `Verification` at once, without duplication or multiple inheritance.

Additional semantic links may be added to specific principles when useful for retrieval.

---

### Organizing the Self Semantic Graph
#topic_details

`SelfModel` and `SelfRegulation` use the shared [[Process Plane/Process Ontology and Semantic Interface#^semantic-program-organization|`Concept → ProcessConcept → Program` organization]].

For Self, [[Memory#Retrieval|retrieval]] starts from semantic anchors in the current task and uses linked processes to find relevant Programs, `SelfModel` knowledge, `SelfRegulationPrinciples`, and past experience/Evaluation, without traversing all of the agent's knowledge about itself.

---

## Self-Improvement Loop
#topic_core

(def_id:: et.SelfImprovement)
> [!definition] **Self-improvement** — the process of finding, evaluating, and transferring ways to improve the agent's own mechanisms. ^def-SelfImprovement

[[Process Plane/Action Selection and Planning#^def-SkillDevelopmentProgram|`SkillDevelopmentProgram`]] may handle development of a particular skill using this shared process.

It operates in two modes:

```text
reactive
→ failure, regression, unexpected outcome,
  unexplained mismatch;

proactive
→ look for ways to make existing
  processes more reliable, simpler, faster,
  cheaper, or more generalizable.
```

Reflection therefore analyzes more than problems. Any experience — failure, success, or an ordinary good result — may raise questions:

```text
What can this tell me about how the agent itself works?

What worked especially well, and why?

Can I get the same result
more simply or reliably?

Could the mechanism found here
improve other processes?
```

**One case is enough to create a hypothesis** about a potentially general improvement. It does not provide enough `Support` for a general conclusion, but may have high expected research value and therefore receive high `attention_priority`.

> **Generate improvement hypotheses aggressively; accept changes conservatively.**

### From Experience to a Confirmed Problem

#topic_details

Self-improvement distinguishes four levels:

```text
Incident
→ what actually happened;

Problem / Opportunity Claim
→ which stable agent characteristic
  may explain the result;

Change Claim
→ what change should help, and why;

Implementation
→ the concrete implementation of that change.
```

One incident usually creates only a `Claim`.

Reflection uses the semantic graph and retrieval to find similar, contrasting, and boundary cases, form competing explanations, and determine causal scope: `self / environment / interaction / unresolved`.

When justified, Reflection uses [[Evaluative-Control System#^aggregate-queries|aggregates by period and process subtype]] to select outcomes and traces for investigation, and may initiate [[Learning system#^outcome-credit|credit assignment for a Task or process outcome]].

```text
experience / Evaluation
        ↓
Reflection
        ↓
similar + contrastive + boundary cases
        ↓
competing explanations + causal scope
        ↓
problem / opportunity Claim
about the self component
        ↓
EvidenceAssessment
```

Self-improvement handles the `self` and agent-related part of `interaction`; for `environment`, update the world/process model, while `unresolved` remains a hypothesis.

Evidence rules for reasoning and Claims are defined in the [[Process Plane/Program Lifecycle and Evolution#Claims About a Problem and Claims About an Improvement Method|Program Lifecycle]].

Before structural improvement, two independent conditions must hold:

```text
the problem or opportunity is
supported sufficiently
+
the change has sufficient
expected value.
```

Therefore, high `Support` alone does not mean a problem should be fixed. Conversely, a rare but costly failure may justify a temporary, narrow safeguard before a generalization is complete.

If a confirmed failure acquires a reusable meaning of its own, it may be reified as a `FailureMode` Concept.

---

### From a Problem to a Change Hypothesis
#topic_details

The transition from a problem Claim to multiple alternative change Claims is described in the [[Process Plane/Program Lifecycle and Evolution#Claims About a Problem and Claims About an Improvement Method|Program Lifecycle]]. In self-improvement, check the causal explanation for each approach separately.

For example, if a shorter prompt produces a better result, the agent should not immediately conclude that its length caused the improvement. Test possible explanations using suitable:

```text
A/B comparisons;
ablations;
counterfactuals;
repeated runs;
contrastive and boundary cases.
```

Where possible, one experiment changes one mechanism being tested. If several changes make sense only together, evaluate them as one candidate.

This is necessary for correct causal and learning credit.

---

### Evaluating a Change Claim and Its Implementation
#topic_details

The boundary between a change Claim and its implementation candidates, and their shared lifecycle, is defined in the [[Process Plane/Program Lifecycle and Evolution#Implementing the Selected Approach|Program Lifecycle]].

Preserve the distinction:

```text
failed implementation
≠ the change Claim must be false;

successful implementation
≠ the general principle has been proved.
```

In self-improvement, [[Process Plane/Program Evaluation and Testing#Program Evaluation and Testing|Evaluation]] should check not only the intended improvement but also its robustness:

```text
target metrics
→ what should improve;

guardrails
→ what must not materially deteriorate;

independent / held-out cases
→ whether the change works beyond
  the material used during development;

regressions
→ whether existing behavior was broken;

stability
→ whether quality holds across different contexts,
  edge cases, and long workflows;

cost / complexity
→ whether a local improvement came
  at a disproportionate complexity cost.
```

Evaluation should be independent of candidate generation where possible. Cases used to refine a candidate no longer count as independent confirmation.

If one `EvaluationResult` provides evidence for several Claims or relations, the `EvidenceAssignment[]` created for them retain shared provenance / `EVIDENCE_DEPENDS_ON` and are handled through the shared [[Uncertainty and Belief Tracking in the World Model#Evidence Dependencies|dependency view]], not as independent confirmations.

It is especially important to monitor cumulative degradation:

```text
each individual change looks useful
≠
the system improved after a series of changes.
```

Therefore, periodic regression and system-level evaluations compare the current state not only with the latest local change, but also with stable historical baselines.

Independent candidates may be developed and evaluated in parallel only within one Task; separate Tasks follow the [[Cognition and Attention#^sequential-tasks|shared sequential execution order]]. Changes with overlapping causal/dependency scopes are activated sequentially or evaluated together as one candidate.

`EvaluationChoice` defines the initial activation scope and rollback conditions in proportion to risk. A low-risk `L1` may be activated immediately; for `L2` / `L3`, where applicable, use suitable `shadow / limited scope / probation` stages before full activation.

---

### CognitionControl

**`CognitionControl`** is a learnable `SelfRegulation` process that selects and, when needed, changes the `cognition_mode` of current conscious processing.

Mode selection may consider task complexity, uncertainty, result importance, expected value of additional reasoning, computational cost, and similar factors.

`CognitionControl` operates within the budget set by `ResourceControl` and the L4 hard limits:

```text
ResourceControl
→ how many resources are available;

CognitionControl
→ which processing mode to use now.
```

`CognitionControl` does not decide whether to execute a decision automatically or hand it to consciousness. That is the responsibility of `CommitmentControl`.

Initially, one shared `CognitionControl` Program is used. As it learns, it may refine its strategy or use specialized Programs for particular classes of cognition if they provide a stable advantage.

---

### SelfRegulationPrinciple Lifecycle
#topic_core

Create a [[#^def-SelfRegulationPrinciple|`SelfRegulationPrinciple`]] not when a problem or opportunity is first noticed, but after a **transferable improvement method** has been confirmed. Until then, the rule remains an ordinary `change Claim`.

[[#^def-AppliesTo|`APPLIES_TO(...)`]] records the principle's testable scope. Add [[#^def-Addresses|`ADDRESSES(...)`]] only for an identified problem. Each relation is an independent semantic fact and may have its own [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`BeliefData`]], representing how well supported the relation is, not the effect size.

If new experience challenges an existing principle, do not rewrite it automatically. Create a `Claim` about the needed correction and a candidate semantic revision. The current principle remains canonical knowledge until the change is evaluated.

If a relevant dependency or applicability condition used in assessment changes, review/re-evaluate dependent self Claims, `APPLIES_TO(...)`, and `ADDRESSES(...)`. A dependency change does not automatically lower `Strength`.

---

#### Generalization and Target Search
#topic_details

The scope of generalization is determined by the **shared causal mechanism**, not simple distance in the taxonomy.

```text
confirmed finding
        ↓
identify the suspected
failure / improvement mechanism
        ↓
find through graph + code anchors + provenance:
- other locations with the same mechanism;
- structurally similar operators / control-flow patterns;
- Programs using the same upstream component;
- meta-Programs that created, changed,
  or trained the affected Programs;
        ↓
filter by applicability conditions
        ↓
rank by expected impact
and evaluation value
        ↓
evaluate selected targets
```

If the same problem occurs across several Programs and provenance points to a shared upstream mechanism — for example, `ProgramSynthesisProgram`, `ProgramDebugger`, a learning policy, or a context/prompt generator — the agent should test the hypothesis that **the shared meta-level mechanism should be fixed**, rather than each Program separately.

```text
similar failures
across several Programs
        ↓
shared upstream meta-Program?
        ↓
problem Claim
        ↓
Evaluation on other outputs
of that meta-Program
        ↓
candidate meta-Program change
        ↓
stricter Program Lifecycle
```

Here, `provenance` only helps identify a possible common cause; changing a meta-Program is allowed only after a separate evaluation.

This way, self-improvement can move from a local patch to fixing **the process that systematically produces these errors**.

---

### Meta-Improvement
#topic_details

In the MVP, the final procedure for evaluating and accepting improvements is fixed, including the logic of [[Process Plane/Program Lifecycle and Evolution#EvaluationChoice|`EvaluationChoice`]]. The agent does not autonomously change the procedure's code, settings, or learnable parameters, including through shared dependencies. It may create and select domain-specific tests within this procedure; this does not waive its mandatory checks. Within this limit, the agent continues to improve knowledge, working programs, strategies, model weights, Reflection, and proposal generators.
^meta-improvement-mvp

Problems with the fixed procedure are recorded as [[Core data structures#^def-Claim|Claims]] or [[Cognition and Attention#Goal, Task, and Task Specification|Tasks]] for the developer. Autonomous changes to the procedure are deferred beyond the MVP: checking a new selection mechanism requires a history of successful and unsuccessful improvements and a separate evaluation of which changes it accepts and rejects.

Every self-improvement attempt is itself evaluable experience.

If the agent systematically:

```text
selects the wrong causes;
creates unhelpful changes;
overfits to Evaluation;
transfers principles too broadly;
accepts changes that are later rolled back,
```

Reflection should consider a possible problem in its own meta-mechanisms:

```text
Reflection;
retrieval;
experiment design;
Evaluation;
EvaluationChoice;
transfer policy;
ProgramLifecycleManagement.
```

In this way, the agent improves not only its Programs but also its ability to **find, evaluate, and propagate improvements correctly**.

The levels of self-change describe the general architecture; in the MVP, allowed changes are restricted by the [[#^meta-improvement-mvp|rule above]]. Higher levels have stricter requirements:

```text
L0
→ belief / permitted parameter update;

L1
→ local ProgramBranch
  or narrow semantic change;

L2
→ cross-program change
  or SelfRegulationPrinciple;

L3
→ changes to process meta-Programs
  such as AttentionControl, Reflection, Evaluation,
  ProgramLifecycleManagement, and others;

L4
→ Consciousness / AttentionRuntime core,
  Values, hard constraints,
  provenance and evidence semantics,
  activation / rollback rules,
  and other base invariants.
```

The boundary between the active `AttentionControl` process Program and the fixed `AttentionRuntime` is defined in [[Cognition and Attention#Attention (`Attention`)|`Attention`]].

`L4` is outside autonomous self-improvement. The agent may observe and analyze it, record problems, and create developer-facing Claims or Tasks, but has no write/activation path to L4. Only a developer outside the agent runtime can change it.

The L4 core code should remain minimal: only critical liveness and recovery guarantees, hard limits, and boundaries on permitted changes. Other L4 elements are fixed semantic contracts or invariants, not additional runtime logic. Meta-programs at level `L3` follow the shared [[Process Plane/Program Lifecycle and Evolution#Meta-Program Lifecycle Safety|conservative lifecycle]].

A candidate L3 meta-Program cannot determine its own `Criteria`, evaluation evidence, and `EvaluationChoice` on its own. Acceptance relies on L4 invariants, checks fixed in advance, and Evaluation independent of the candidate; the previous active version may participate but cannot be the only verifier.

---

## Events
#topic_core

In Self, an `Event` is a discrete trigger for starting processing. Under the [[Cognition and Attention#^input-reception|shared input reception rules]], the event is linked to an existing `Task` or a minimal task is created with a reference to its source. If an allowed handler is assigned, it performs automatic `Program` work within that task; if there is no handler or a conscious step is needed, the task goes to the [[Cognition and Attention#Attention (`Attention`)|`AttentionPriorityQueue`]]. The runtime executes known delivery rules, while the task's meaning is refined through `TaskFraming`.

For example, a significant increase or decrease in tension, represented by [[Evaluative-Control System#^def-TensionReduction|`tension_reduction`]], may trigger a Reflection Task and start the [[#From Experience to a Confirmed Problem|self-improvement pipeline]].

`Event` is not a separate learning subsystem: by itself, it does not become [[Uncertainty and Belief Tracking in the World Model#^def-Evidence|evidence]], assign [[Learning system#LearningCredit and UnresolvedCredit|learning credit]], or make a result [[Memory#Trace-Local and Persistent Results|persistent knowledge]].

---

### Shared Lifecycle
#topic_core

`Evaluation` in this diagram uses [[#Evaluating a Change Claim and Its Implementation|the criteria listed above]], while candidate work follows the [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|shared Program Lifecycle]].

```text
experience / Evaluation / audit
        ↓
Reflection
        ↓
Incident
        ↓
similar + contrastive + boundary cases
        ↓
competing causal explanations
        + causal-scope attribution
        ↓
Problem / Opportunity Claim
about the self component
        ↓
EvidenceAssessment
        ↓
confirmed + significant?
        │
        ├─ no
        │   → preserve Claim
        │   → observe / Replay / re-evaluate
        │
        └─ yes
             ↓
        alternative Change Claims
             ↓
        isolated candidate changes
             ↓
        Evaluation
             ↓
        dependency-aware evidence accumulation if needed
             ↓
        EvaluationChoice
             ↓
        risk-proportional activation
             ↓
        fresh / delayed / system-level outcomes
             ↓
        confirm / refine / rollback
             ↓
        reusable rule sufficiently supported?
             │
             ├─ no
             │   → keep local knowledge
             │
             └─ yes
                  ↓
             SelfRegulationPrinciple + scoped beliefs
                  ↓
             progressive transfer
                  ↓
             Evaluation for each expanded scope
                  ↓
             update SelfModel
             + SelfRegulation
             + self-improvement process
```
