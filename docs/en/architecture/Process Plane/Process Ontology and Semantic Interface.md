Process ontology organizes Concepts, processes, and their Programs through semantic relationships.

### Program Canonicalization and Deduplication

Programs are organized through semantic links according to [[Core data structures#^04821b|Concept Canonicalization and Semantic Linking]].

### Program-Scoped Semantic Links

The agent may [[Semantics Plane#^e24496|cache]] results of analyzing process relationships and factors through semantic links. It creates them only when justified. A link may concern the process itself or be scoped by program when it depends on a particular `Program` implementation.

Examples:

```text
PROGRAM_CORRELATES(program, factor, target)
PROGRAM_FACTOR_ROLE(program, factor, target, role)
PROGRAM_NO_EFFECT(program, factor, target)
PROGRAM_EXCLUDES(program, concept_or_relation)
```

These links are not global truths about the world. They record knowledge useful to a particular program.

`PROGRAM_EXCLUDES(program, x)` means that the program intentionally excludes `x` from its representation of the process as irrelevant, redundant, or unused by its approach.

[[#^0c1eb8|CONTROL_CONFLICT RelationType]]

### TransitionType (Relation)

To describe “which transition occurred,” EverTree uses a `TransitionType` (relation).

**`TransitionType`** is a process-relation concept: a type of n-ary change over time.

Linguistically, `TransitionType` corresponds to an event predicate, usually a verb or verb phrase that describes change over time: `BURNS(fuel)`, `MARRIES(person_a, person_b)`, `CONVINCES(person_a, person_b)`.

It defines:

- the meaning of the change;
- the argument signature;
- the roles of transition participants.

The distinction:

- [[Semantics Plane#^def-RelationType|`RelationType`]] — a static relation: `PART_WHOLE(wheel, car)`;
- `TransitionType` — a dynamic relation: `BREAKS(agent, object)`.

A process noun, such as **“Burning,”** is a `ProcessConcept`. The verbal transition **“burns / sets on fire”** is a `TransitionType`.

`TransitionType` belongs to the shared abstraction hierarchy and participates in [[Core data structures#^04821b|Concept Canonicalization and Semantic Linking]].

### ProcessConcept

**`ProcessConcept` is usually a noun or nominalized process concept**, for example “Burning” or “Engine Start.”

Linguistically, it is usually expressed as a noun or nominalization of a process.

It answers the question: what process is this?

```python
ProcessConcept: Concept {
  name: <string>
    "Process name as a nominalized process concept: Burning, EngineStart, PokerHandProcess."

  description?: <string>
    "Brief description of the process's meaning and boundaries."

  primary_transition_type?: <TransitionType>
    "The main verbal TransitionType through which the process is usually expressed."

  active_model?: <Program>
    "The currently selected Program with model ∈ Program.roles."

  active_exec?: <Program>
    "The currently selected Program with exec ∈ Program.roles."

  belief_data?: <BeliefData>
    "Confidence in the current operational understanding of the process."
}
```

**`Process`** is the general root concept of the process taxonomy. All other process types are linked to it directly or through ancestors by [[Semantics Plane#^spec-SUBTYPE_OF|`SUBTYPE_OF`]]. It is a concrete graph concept; `ProcessConcept` denotes the type of objects being passed. The taxonomy links kinds of processes; composite process steps are described separately.
^def-ProcessRoot

The agent's own processes form the `SelfProcess` subtree (the **Self/Process** representation). It is linked to the general `Process` through `SUBTYPE_OF` and to Self through `PART_WHOLE`. The general `Process` is not moved under Self: it also organizes processes in the external world. The initial subtypes in the agent's branch are `TaskManagement`, `CognitiveControl`, `MemoryProcessing`, and `Learning`; `src/evertree/processes/` represents exactly this branch.

### Semantic Organization: Concept → ProcessConcept → Program

The primary semantic anchor is `Concept`. Processes concerning that subject are linked to it, and Programs that model or execute those processes are linked to the processes.
^semantic-program-organization

#### PROCESS_SUBJECT

```text
PROCESS_SUBJECT(process: ProcessConcept, subject: Concept)
```

`subject` is the primary semantic Concept around which this `ProcessConcept` is organized. The link supports stable organization and retrieval:

```text
PROCESS_SUBJECT(PromptPreparation, Prompt)
PROCESS_SUBJECT(PromptEvaluation, Prompt)
PROCESS_SUBJECT(PromptOptimization, Prompt)
```

It does not replace more precise semantic relations:

```text
PromptPreparation → PRODUCES / TRANSFORMS → Prompt
PromptEvaluation → EVALUATES → Prompt
PromptOptimization → IMPROVES → Prompt
```

Do not assign `PROCESS_SUBJECT` artificially when a process has no natural primary subject.

#### PROGRAM_FOR_PROCESS

```text
PROGRAM_FOR_PROCESS(program: Program, process: ProcessConcept)
```

The link means that a `Program` models or implements the process described by this `ProcessConcept`; its specific function is defined by [[Program Layer#Program Roles|`Program.roles`]]. It covers all Programs for the process: active, candidate, alternative, rejected, and archived.

`ProcessConcept.active_model` and `ProcessConcept.active_exec` refer to the currently selected Programs with the corresponding primary roles among all `PROGRAM_FOR_PROCESS` links for that process.

A `Program` usually has one primary process. If a mechanism truly represents several processes as a unit, it is preferable to create the corresponding composite `ProcessConcept`.

#### Semantic Scope and Implementation Contracts

These levels are not interchangeable:

```text
ProcessConcept
→ semantic scope of the process;

PROGRAM_FOR_PROCESS
→ which Programs belong to the process;

Program.read_contract / Program.output_contract
→ what a specific implementation actually
  reads, predicts, or changes.
```

A particular `Program` contract may cover only part of the process's semantic scope. The model's scope is defined by its inputs, outputs, and conditions of applicability; a complete description of every other process aspect is not required to run or evaluate it. The taxonomy and links to programs provide organization and retrieval, while detail is added as needed in practice so that the model is not expanded without benefit to its tasks.

A contract that exceeds the process boundaries or contradicts its meaning may require [[Program Lifecycle and Evolution#Structural Revision|structural revision]]. An uncovered part requires revision of a particular program only when its contract is violated or a confirmed gap prevents its stated purpose. A new [[#PART_WHOLE in Process Responsibility|`PART_WHOLE`]] or [[#PROCESS_VARIABLE|`PROCESS_VARIABLE`]] link alone does not require such a revision.

#### Examples

Optimizing a [[Core data structures#^def-Prompt|`Prompt`]]:

```text
Prompt                                      # Concept
   ↑
PROCESS_SUBJECT
   │
PromptOptimization                          # ProcessConcept
   ↑
PROGRAM_FOR_PROCESS
   │
PromptOptimizationProgram                   # Program
   └── roles = {exec}

PromptOptimization
   ↑
PROGRAM_FOR_PROCESS
   │
PromptOptimizationOutcomeModel
   └── roles = {model}
```

`Prompt` is the subject of these processes, while preparation, evaluation, and improvement are performed by linked `Program`s. Different variants may serve the same semantic interface for different models; the [[Core data structures#^note-claim-prompt-evaluation|evaluation result]] applies to the tested versions and conditions, not to every variant at once.

Self-improvement:

```text
Program                                     # Concept
   ↑
PROCESS_SUBJECT
   │
ProgramImprovement                          # ProcessConcept
   ↑
PROGRAM_FOR_PROCESS
   │
ProgramLifecycleManagement
   └── roles = {exec, meta}

ProgramImprovement
   ↑
PROGRAM_FOR_PROCESS
   │
ImprovementOutcomeModel
   └── roles = {model}
```

### Routing Observations

(def_id:: entity.ProcessRouter)
> **`ProcessRouter`** — a program that uses the meaning of an observation and task context to identify a suitable process and its specific execution for the caller: consciousness or the `exec` program running the task.
> ^def-ProcessRouter

The Router is called within an already established `Task` context; [[Cognition and Attention#^input-reception|input reception and initial task binding]] happen before this call. If a tool result is already associated with a waiting call, the runtime delivers it directly. The Router is needed when the semantic recipient must be identified or reconsidered; it is not a mandatory step for every input.

The Router uses semantic graph search: participants, temporal relationships, [[#^semantic-program-organization|process scope and associated Programs]], and the context of recently active executions. It matches an observation to a specific object and episode: two attempts to start the same engine may belong to separate executions of the same process.

For one context, the standard path uses one selected working program or composition. When delegating, this is an `exec` program and the models and subprograms it calls; consciousness may also directly organize a separate call. The caller uses the Router result to continue an appropriate existing execution; a new one is created when a separate episode begins or new task work is needed. Each observation does not create a new run by itself. The [[Cognition and Attention#^durable-program-execution|runtime]] manages live or unloaded execution state.

Several aspects of an observation may require different subprograms within this composition. This does not mean selecting all alternative models or independently running every process found. Alternatives remain available for explicit evaluation and improvement in separate tasks.

If there is no suitable process, program, or unambiguous execution binding, the Router returns an unresolved case to the caller. Consciousness investigates it within the current task; when needed, an `exec` program requests [[Cognition and Attention#Attention (`Attention`)|conscious processing]] for its task. Program creation or change goes through the [[Program Lifecycle and Evolution|Program Lifecycle]]; a search result alone does not create a ready-made model.

After an execution is selected, the caller asks the runtime to deliver the observation to its [[Program Layer#^process-observation-input|shared typed input]]. The Router identifies a suitable recipient; the executing program interprets the observation within the process, determines its current state, and chooses the appropriate processing branches. This keeps responsibility for actions in one place and avoids automatically running every candidate.

After selecting a target program, consciousness or the calling `exec` program may prepare [[Program Layer#^def-ArgumentPreparation|`ArgumentPreparation`]] according to its interface and [[Program Layer#^program-input-requirements|`requirements`]], call it, and use its [[Program Layer#^program-feedback|feedback]]. [[Cognition and Attention#^def-Perception|`Perception`]] prepares assigned observations but does not select or invoke the process program. This is nested work within the [[Cognition and Attention#^agent-processing-cycle|general agent cycle]]; the interaction is shown in the [[Program Layer#^perception-requirements-feedback|perception example]].

### Process Responsibility Structure

#topic_core

`ProcessConcept` defines the meaning of a process: what kind of process it is and what its conceptual boundaries are.

**Process Responsibility Scope** is a working responsibility structure derived from:

- `ProcessConcept.description`;
- `PART_WHOLE(part, process)`;
- `REALIZES_PROCESS(transition_type, process_concept)`;
- subtype/special-case links;
- semantic links created after analysis.

It answers:

```text
Which concepts, changes, participants, and outcomes belong to this process
at the level of meaning?
```

#### `PART_WHOLE` in Process Responsibility

In the Process Plane, `PART_WHOLE(part, process)` defines the semantic structure of a process: which significant parts make up the process as a whole.

The general meaning of `PART_WHOLE` remains mereological:

```text
part is a component of whole (composition)
```

In a process context, this means:

```text
part belongs to the semantic structure of the process and may contribute
to its explanation, prediction, memory retrieval, or evaluation.
```

`PART_WHOLE` alone does not mean that a program must read or predict that part. It only says that the part belongs to the process's semantic structure.

Different cases are possible:

```text
part stable in episode
→ may be input/context for a program

part changes in episode
→ may become a PROCESS_VARIABLE of the process

part changes, is not covered by the program, and a gap is found in its
contract or purpose
→ structural revision

part turns out to be irrelevant
→ consciousness may remove the link, weaken it, or retain it as a weak semantic association
```

For example:

```text
PART_WHOLE(CardDeal, PokerHandProcess)
```

If a process part is recognized as significant for evaluating process models, the agent may additionally create:

```text
PROCESS_VARIABLE(process, part_or_axis)
```

#### PROCESS_VARIABLE

`PROCESS_VARIABLE(process, variable)` is a semantic link indicating that `variable` is a significant changing quantity used to describe the dynamics of this process.

```text
PART_WHOLE
→ which parts make up the process;

PROCESS_VARIABLE
→ significant changing quantities of the process;

TRAJECTOR
→ the primary perspective from which the process is considered.
```

`PROCESS_VARIABLE` belongs to the process semantic model and does not depend on a specific `Program` implementation.

A variable may be:

```text
observable
→ has an independent observation path;

latent
→ inferred by a model and checked
  through observable consequences;

deterministic or random;
native property or relation/transition-backed reading.
```

Observability is determined relative to a specific process, context, and evaluator; it is not stored as a permanent variable type.

The link does not mean that every process model must return a prediction for the variable.

A quantity selected for prediction serves as a [[Program Layer#^def-PredictionTarget|`PredictionTarget`]] in the model contract. This role does not automatically create a separate Concept or estimator.

The boundary between process semantic scope and coverage by a specific implementation is defined in [[#^semantic-program-organization|Semantic Organization]]. Anchored claims separately describe the implementation's internal semantic structure.

Comparing these levels gives:

```text
required output is missing during ProgramRun
→ structural revision;

process variable is not covered by a Program but is required by its
contract or purpose
→ structural revision;

prediction and observations are available for checking
→ applicable metrics; prediction_unexpectedness if there is a basis for calibration.
```

Direct [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] is calculated for an observable variable when a saved prediction, a calibration basis, and sufficient observations not inferred from that prediction are available. Process randomness and dependencies among observations are accounted for; observations outside the evaluation conditions and insufficient data do not produce a zero signal.

A latent variable receives indirect evidence through observable claims and downstream outcomes that depend on it.

`PROCESS_VARIABLE` should reference a typed quantity with a defined value space and reading method. Raw `RelationType` and `TransitionType` are not used directly; instead, define relation-backed or transition-backed variables.

Examples:

```text
PROCESS_VARIABLE(PokerHandProcess, CardDeal)

PROCESS_VARIABLE(DiseaseProcess, PatientHealthStatus)

PROCESS_VARIABLE(EngineStartProcess, EngineStartOutcome)

PROCESS_VARIABLE(VehicleMovement, SurfaceUnder)
```

Create the link only when the variable is expected to help model the process and is semantically justified. Do not use it for technical runtime variables or minor changes that do not warrant independent modeling.

If a change in `x` is observed but the active process program does not predict it, determine whether the prediction was required and whether the observation falls within the program's scope. A contract violation or confirmed model gap is passed to structural revision.

If a quantity actually changes during the process, is semantically part of its dynamics, and modeling it is expected to be useful, represent it as a `PROCESS_VARIABLE`.

If these conditions do not hold, the quantity either does not strictly belong to the process or is not significant enough to model independently.

The boundary between significant and insignificant variables is often ambiguous; it may change as experience accumulates and is part of learning the process model. It is determined by the learnable metaprogram:

```text
ProcessVariableCurationProgram
```

#### Random Variables as Process State Variables
#topic_core

A random variable is treated in the same way as a `PROCESS_VARIABLE` modeled by a particular program.

Example: a poker hand.

```text
PART_WHOLE(CardDeal, PokerHandProcess)
PROCESS_VARIABLE(PokerHandProcess, CardDeal)
```

At the start of a hand:

```text
CardDeal.value = None
```

After the deal:

```text
CardDeal.value = [Ah, Ks]
```

The fact that `CardDeal.value` is unknown before the deal does not replace a prediction. If a program is required to model `CardDeal` but returns no prediction, structural revision is required; numerical `prediction_unexpectedness` is not calculated for a missing prediction.

A correct program does not have to guess the specific cards in advance. It should return a probability profile:

```text
P(card_deal | deck_state, known_cards, rules)
```

Learning dynamics:

```text
1. Observe that the program does not model CardDeal → analyze program coverage.
2. The agent confirms that omitting a CardDeal model violates the contract
   or obstructs the program's purpose → structural revision.
3. Create/strengthen PROCESS_VARIABLE(PokerHandProcess, CardDeal).
4. A ProgramBranch adds a probabilistic CardDeal model.
5. Selected observations are checked through prediction_unexpectedness,
   accounting for the randomness of the deal.
```

Randomness is accounted for in the prediction representation and evaluation. Select a distribution or a particular statistic, such as the mean, under the [[Learning system#Forecast Representation and Learning Objective|shared modeling rules]].

#### TRAJECTOR

`TRAJECTOR(process, entity_or_axis)` is a semantic link identifying the primary participant or point of view through which a process is usually described.

Meaning:

```text
entity_or_axis — the main participant/bearer of the process perspective.
```

Examples:

```text
TRAJECTOR(DiseaseProcess, Patient)
TRAJECTOR(PokerProcess, Player)
```

`TRAJECTOR` does not define `prediction_unexpectedness` or impose a requirement on a program. It is a hint for:

- retrieving processes by participant;
- selecting a perspective for explanation;
- searching memory;
- structural alignment.

Consciousness may change or remove `TRAJECTOR` if the current process perspective becomes unhelpful.

### Link to Noun Concepts

The link between `ProcessConcept` and `TransitionType` is defined by the semantic relation:

```text
REALIZES_PROCESS(transition_type, process_concept)
```

Meaning:

```text
TransitionType is a verbal way of realizing or expressing a ProcessConcept.
```

Example:

```text
REALIZES_PROCESS(BURNS, Burning)
```

This link connects linguistic forms of the same process in EverTree.

---

### Action Conflict Control via RelationType
^0c1eb8

Sometimes an action is physically possible, but the agent understands that it conflicts with a value, supervisor expectation, safety constraint, or stable rule of behavior. Recording this in semantic memory matters when it helps avoid material risks or supports generalization.

#### Motivation

The semantic `CONTROL_CONFLICT` relation is not for runtime blocking. It is for memory, reflection, generalization, and future program improvement, and should be used only when justified; the agent should not clutter memory with immaterial links.

#### RelationType

(formal_id:: relation.CONTROL_CONFLICT.schema)
```python
RelationType CONTROL_CONFLICT {
  name: "CONTROL_CONFLICT"

  description:
    "A semantic relation recording that an action, operator, or program conflicts with a control constraint, value, supervisor expectation, or safety constraint in a specified scope. It is not a runtime action-selection filter and does not enforce a prohibition by itself."

  signature: [
    subject = ActionConcept
      "What conflicts"

    constraint = Concept | SignalPattern
      "What it conflicts with: a value, supervisor expectation, safety constraint, goal constraint, or expected negative signal."

    scope = Process | Program | ContextPattern | Global
      "Where the conflict applies."

    expected_signals? = dict[SignalChannel, ExpectedOutcomeSignal]
      "Optional prediction of evaluations, such as a negative value on the supervisor_feedback_signal channel."
  ]
}
```

The form of `ExpectedOutcomeSignal` is defined by the [[Program Layer#Expected Signals|signal prediction contract]].
