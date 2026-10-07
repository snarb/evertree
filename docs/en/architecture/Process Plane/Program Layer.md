### Program

#topic_core

**Program** — a stable identity for a Python-backed mechanism that models or executes a process.

`Program` defines a persistent graph identity for a program. A specific code version is identified by its Git commit. The active version is the code for that `Program` on the repository's `main` branch.

One `Program` may call other `Program`s. This is ordinary program composition, not a separate type.

```python
Program: Concept {
  name: <string>
    "Short program name."

  description?: <string>
    "What the program does, where it applies, and its boundaries."

  roles: <set["model" | "exec" | "meta" | "simulation"]>
    "The program's primary role and optional modifiers."

  git_path: <string>
    "Path to the Python file or module in the Git repository."

  requirements?: <string> = None
    "Textual program requirements considered when preparing its input."

  effect_contract?: <string[]>
    "Classes of effects the program may perform: predict, simulate, mutate_internal, act_external."

  read_contract?: <Concept[] | RelationType[] | TransitionType[]>
    "What the program actually reads."

  output_contract?: <Concept[] | RelationType[] | TransitionType[] | PropertyConcept[]>
    "What the program actually predicts, creates, changes, or deletes."

  dual_program?: <Program>
    "A related program with the other primary role: model for exec, or exec for model."

  alternative_to?: <Program>
    "The program this Program is an alternative to, if they are competing approaches."

  active_branches?: <ProgramBranch[]>
    "Live change branches for this program, pending an EvaluationChoice."

  lifecycle_status: "idea" | "initial_code_version" | "verified_by_cognition" | "active" | "candidate" | "rejected" | "archived"
    "The program's current lifecycle state."

  belief_data?: <BeliefData>
    "Computed belief view for the active program revision."
}
```

#### Program Roles

#topic_core

`roles` classifies the `Program` mechanism. The set contains exactly one primary role:

```text
model | exec
```

and may contain modifiers:

```text
meta
simulation
```

Invariant:

```text
meta ∈ Program.roles
→ exec ∈ Program.roles
```

Role is determined by a program's purpose, not by whether it uses an LLM or has direct effects. Preparing a plan or arguments and selecting the next step execute internal processes, so they are `exec`; predicting process outcomes, costs, or transitions is `model`. In source code, an implemented role is stored in `_exec.py` or `_model.py`; helpers for a role may live in a package with the same name.

Role semantics:

```text
model
→ Program describes, explains, or predicts a process;
→ it does not itself select an external or internal action.

exec
→ Program executes a process, selects actions, calls
  other Programs, and performs allowed internal or external effects.

meta
→ an exec program builds, checks, selects, trains,
  improves, or manages the lifecycle of other learnable
  agent mechanisms, including Programs.

simulation
→ Program is also intended to work with simulated
  states or processes: it creates or operates in a simulation,
  rollout, self-play, or optimization environment.
```

Examples:

```text
PokerModel.roles = {model}
PromptPreparationProgram.roles = {exec}
ProgramLifecycleManagement.roles = {exec, meta}
PokerSimulator.roles = {model, simulation}
SelfPlayProgram.roles = {exec, simulation}
```

#topic_details

The `simulation` modifier describes the mechanism's purpose, not the mode of a particular run. If one `Program` runs with both live and simulated state, runtime/environment context defines the mode, including the existing [[Memory#^def-ProgramRun|`ProgramRun.run_mode`]]. Add a separate field only when genuinely needed.

#### Belief About a Program

#topic_core

The epistemic [[Uncertainty and Belief Tracking in the World Model#^def-BeliefTarget|target]] is the pair `(Program, program_revision)`: a stable identity does not have one belief shared by all revisions. The primary claim being checked depends on the primary role:

```text
model ∈ Program.roles
→ how accurately the revision describes the corresponding process;

exec ∈ Program.roles
→ how reliably the revision implements its intended behavior.
```

Modifiers add requirements to this claim:

```text
simulation ∈ Program.roles
→ how reliably the revision works with the stated simulated
  states or processes; for model, this includes accurately
  reproducing material dynamics;

meta ∈ Program.roles
→ how reliably the revision performs its stated operations
  on other learnable agent mechanisms.
```

#### Program as a Process-Transition Interface

#topic_core

Programs may describe or execute a process as an n-ary transition between input and output interfaces, operating on concepts and relations as symbols for real objects.

Example:

```text
PersonA + PersonB
→ FamilyRelation(PersonA, PersonB)
```

Programs may create, delete, modify, merge, and split concepts, and create or break links between them.

### Program Contracts

#topic_core

Program contracts describe what a specific implementation actually reads, predicts, creates, changes, or deletes. Their distinction from the semantic scope of a process is defined in [[Process Ontology and Semantic Interface#^semantic-program-organization|Semantic Organization]].

`roles` classifies the mechanism, while `effect_contract` limits the classes of effects it may perform. These fields answer different questions.

#### ProgramDesign

#topic_core

**`ProgramDesign`** is a typed description of a program's design decisions. Required fields help an LLM explicitly consider material questions when creating or revising code. Each `Program` uses an appropriate profile; internal helper functions do not need separate descriptions.

The profile and completed `design` object are stored with the code and apply to `(Program, program_revision)`. They are available to the generator and reviewer before the program runs. These are version metadata; a separate graph identity and retransmission on every call are unnecessary.

```python
from pydantic import BaseModel, ConfigDict, Field


class ProgramDesign(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    applicability: str = Field(
        min_length=1,
        description="Conditions of applicability and material assumptions; "
                    "what to do when it is unknown whether they hold.",
    )
    adaptation: str = Field(
        min_length=1,
        description="How to detect when assumptions are no longer valid "
                    "or conditions change, including a change in process mode, "
                    "environment, participants, or their behavior; what response "
                    "is planned and who is responsible for revision.",
    )
    learning: str = Field(
        min_length=1,
        description="What is learned, from which data, by whom, and when; "
                    "how improvement is checked, or why the mechanism is fixed.",
    )


class PolicyDesign(ProgramDesign):
    exploration: str = Field(
        min_length=1,
        description="Where and by what mechanism useful new experience is obtained; "
                    "how risk and budget are handled; which programs are responsible, "
                    "or why exploration is not currently used.",
    )
```

`ProgramDesign` also applies to process models. `PolicyDesign` is required for programs that control process behavior or select actions: [[Cognition and Attention#^def-TaskManagingProgram|`TaskManagingProgram`]], policies, and the corresponding [[Action Selection and Planning#Process Management and Skill Development|skill-development programs]]. A model does not organize exploration itself; the `exec` program using it describes that work.

`adaptation` describes when and how to reconsider an approach as conditions change; `exploration` is the purposeful acquisition of knowledge for future decisions; `learning` changes learnable components based on experience. Adaptation may use exploration and learning or may only select an existing model or strategy. Exploration can be useful even under stable conditions when material knowledge is still missing.

Fields have no default values. Each answer explicitly describes a local mechanism, delegation to a named responsible program, or a justified statement that the field does not apply. These cases may be combined. `adaptation` does not require a separate mode-change detector: reconsideration may be triggered by environmental events, Evaluation results, or control-program rules.

When a program is generated and reviewed, the LLM receives the schema and its `description` fields, the completed `design`, and the implementation. Pydantic checks that answers are present and correctly shaped; [[Program Lifecycle and Evolution|Program Lifecycle]] checks their substance and correspondence to the code, including early branching and the actual learning path. A nonempty string alone does not prove that a mechanism works.

The description refers to existing [[Cognition and Attention#Goal, Task, and Task Specification|task goals, constraints, and budgets]], contracts, and subprograms without redefining them. Parameters and references used by runtime belong in the typed executable interface; `design` text explains the decision. A docstring may add explanation without duplicating these fields. [[#Program Input Requirements|`Program.requirements`]] retains its separate role in input preparation.

#topic_details

Profiles may be extended through inheritance while retaining the meaning of required questions. Inapplicability must be stated explicitly; a question cannot be removed or made optional to accommodate one implementation. Choose another profile when the program's purpose differs. Changes to the schema itself go through Program Lifecycle, which checks which required questions remain. For example, an evaluation-based policy profile may add `value_semantics` to define the quantity, horizon, and scale.

Profile inheritance does not define control flow. The implementation remains ordinary Python functions and classes and need not inherit from `BaseModel`. [[Action Selection and Planning|Policies]] use existing selection functions or optional templates from a suitable family; there is no required score-computation method or distribution-building method in a base class for all `exec` programs.

#### Semantic Types for Arguments and Results
^program-semantic-interface

#topic_core

Parameters and results of any `Program` may have a Python type that defines their representation in code and a semantic type—a reference to an EverTree [[Core data structures#^def-Concept|`Concept`]]. For example, `str` may represent a word, paragraph, or document; a separate Python class for every meaning is unnecessary.

The Python signature and **explicit** semantic bindings form one interface without a duplicate argument list. A parameter name and the string contents do not replace a binding. When needed, the interface specifies a role, constraints, and permitted transformations: the type “word” defines the kind of value, while the role “word to analyze” defines its purpose in the call. Text clarifies the contract without duplicating the meanings of Concepts.

Call preparation accounts for both types and task requirements. Checking the Python type alone is insufficient: semantic suitability, object selection, and transformations must also be justified. For example, joining messages into a word is valid if the task defines them as its parts; the “word” type alone does not establish that relationship.

[[Memory#Automatic Recording of Program Arguments|Actual arguments]] are bound to interface parameters, while the [[Memory#^def-OperatorOutput|`OperatorOutput`]] contract defines the meaning of the result and its named parts. Passing a value does not require a separate persistent node: [[Memory#^def-ResultProvenance|provenance]] and the [[Core data structures#Objects and References|general object and reference rules]] apply.

#### Local Variables and Semantic Results
^local-values-and-results

#topic_core

Local variables do not need separate semantic labels: the meaning of values is defined by the [[#^program-semantic-interface|argument and result contracts]]. Assigning an existing result to another variable does not create a new semantic result. Material computations are recorded through [[#Code Anchors|anchored operations]] with provenance. Saving a changed value creates a new result; previous versions remain immutable.

#topic_details

Conscious reading records the exact value or a reference to the saved version. References needed to resume the task remain in execution state. Retention of results is defined by [[Memory#Lifecycle|Memory]], independently of a local variable's lifetime.

Recorded results are stored in the trace by default; large values are stored in an [[Core data structures#^def-Artifact|`Artifact`]] referenced exactly by the trace. Adding a result to the persistent graph requires [[Core data structures#Updating the Persistent Graph|`GraphDelta`]].

#### Program Input Requirements
^program-input-requirements

#topic_core

`Program.requirements: str | None` contains optional [[Cognition and Attention#^def-Requirement|requirements]] for preparing the called program's inputs. They are available **before the call**, without running the program, and capture material conditions not yet expressed through justified structure.

[[Cognition and Attention#^def-Consciousness|Consciousness]] or the calling `exec` program selects the program, reads its interface, and organizes [[#^def-ArgumentPreparation|argument preparation]] to meet the requirements. [[Cognition and Attention#^def-Perception|Perception]] provides observations; the caller is responsible for choosing and calling a process program.

##### Choosing Structure or Text
^program-requirement-representation

#topic_core

**Prefer structure whenever it preserves meaning and is justified by reuse, processing, or verification.** First use existing [[#^program-semantic-interface|Concepts and Python interfaces]], relations, and constraints; extend the interface minimally when needed. The absence of a field does not justify free text. Create new Concepts under the [[Core data structures#Concept Canonicalization and Semantic Linking|canonicalization rules]], without duplicates or requiring a new Python class.

The benefit of structure must justify its development and maintenance. Precise checking of an important condition may justify structure even for a rare case; there is no need to wait for repeated failures.

Text retains the **unformalized remainder**—exceptions and nuances without a stable representation. A flag such as `special_document_mode=True` does not formalize meaning that is still unclear. Even a frequent nuance should remain text when a schema would repeat the ambiguity or lose exceptions.

Rarity, surprise, and variability do not determine the representation. A changing threshold remains a number; an unknown value of a known type remains an explicitly unknown value of that type. Complex extraction does not require free text: an LLM may fill a structured field. A new combination of known conditions can be expressed with existing Concepts and relations.

`str` does not mean an unstructured interface: a word, document, and free-form instruction can be arguments with different semantic roles. Pass source text as an argument, not inside `requirements`.

Repeated extraction of one condition from `requirements` is a reason to consider moving it into a minimal structure. After verifying that meaning, exceptions, and allowed cases are preserved, the structure becomes canonical; text retains only the remaining nuances and explanations rather than defining the contract a second time. If nothing remains, set `requirements = None`.

Textual requirements are binding: the caller organizes execution and available checks rather than merely forwarding the string. Structural checks are not replaced by interpreting the same requirements with an LLM again.

##### Stable Contract and Current-Call Refinement

#topic_details

`requirements` is the textual part of the versioned program input contract; changes go through [[Program Lifecycle and Evolution|Program Lifecycle]]. Before proposing a refinement through [[#^program-feedback|feedback]] or the current task, the program or consciousness analyzes the new observation.

For the current case, the caller first uses existing parameters and preparation. An unformalized nuance is passed through `arguments_formatter(..., instructions=...)` or through explicitly read [[Cognition and Attention|Task]] data and is recorded in the trace. For LLM preparation, it is included in the actual request. This refinement does not overwrite `Program.requirements`; if the interface and preparation logic are insufficient, they must be revised. The choice between structure and text is independent of the choice between a stable contract and current-call input.

#### Unified Program Result

#topic_core

(def_id:: entity.ProgramResult)
> [!definition]
> **`ProgramResult[T]`** — the required form of a successful return from any EverTree `Program`.
> ^def-ProgramResult

```python
class ProgramResult[T](OperatorOutput):
    result: T
    feedback: str | None = None
```

```python
return ProgramResult(result=forecast)
return ProgramResult(result=forecast, feedback="More frequent measurements would help the next forecast.")
```

One shared form simplifies handling by the caller and tracer. `result` retains its technical and semantic types; `None` is allowed only when permitted by `T`. Helper Python functions and anchored operators that are not `Program`s keep their own return forms.

Required return data are defined in the `ProgramResult.result` schema; runtime checks their presence and conformance to the schema at return. Omitting required data violates the contract.

The wrapper inherits from [[Memory#^def-OperatorOutput|`OperatorOutput`]] and is recorded in full in the trace. Domain logic and “Program → forecast” schemas use `.result`; `.feedback` has a separate meaning and is not part of the forecast or observation.

`requirements` and `feedback` are strings, without separate Python `Requirement` / `Feedback` objects; wrapping them in [[Core data structures#^def-Note|`Note`]] is unnecessary.

#### Textual Feedback
^program-feedback

#topic_core

(def_id:: entity.Feedback)
> [!definition]
> **Feedback** — an assessment of completed work and justified suggestions for improvement, including after successful cases.
> ^def-Feedback

```python
ProgramResult.feedback: str | None = None
```

Use `None` when there is no substantive feedback; an LLM call solely to fill this field is unnecessary.

Feedback is returned with the result to the immediate caller. That caller decides whether to use the suggestions and whom to pass them to, accounting for role, task, budget, and requirements. For example, a model may suggest changing perception granularity; the calling `exec` program or consciousness changes the setting. A parent may use feedback from completed child calls while continuing its work.

Feedback is not broadcast automatically; this interface does not define intermediate messages from an unfinished `Program`. Feedback itself does not change a contract or trigger training. [[Evaluative-Control System#^def-SupervisorFeedbackSignal|`supervisor_feedback_signal`]] is a separate external assessment with a numeric value and optional comment. Consciousness may refine preparation on its own.

#### Graph Instructions and Prompt
^program-text-dependencies

#topic_details

A [[Core data structures#^def-Note|`Note`]] may explain code or serve as an instruction. A program explicitly reads an instruction; a link that merely explains code does not add text to the LLM context. A [[#Code Anchors|Code Anchor]] links a computation to an operator, while a Note that is read becomes one of its dependencies.

A [[Core data structures#^def-Prompt|`Prompt`]] defines a [[Core data structures#^prompt-configuration|message template, target models, generation defaults, and response schema]]. Placeholders use the [[#^program-semantic-interface|semantic interface]] without duplicating types or roles; values are prepared before substitution. `Program` defines preparation and invocation logic.

By default, instruction dependencies, including Prompts, are pinned to immutable versions. Replacing a reference changes the Program's Git revision and goes through [[Program Lifecycle and Evolution|Program Lifecycle]]. Mutable graph knowledge may be read as input, preserving the actual state for [[Memory#^def-ResultProvenance|provenance]] and execution recovery.

Dynamic instruction selection is allowed under explicit program rules; record the selected versions in the trace. The [[#Belief About a Program|belief about a Program revision]] concerns how these rules behave within the verified applicability domain. Success of one option does not validate the others: [[Core data structures#^note-claim-prompt-evaluation|evaluation]] accounts for text version, model, and context.

For every LLM call, the trace saves the actual request (instructions, history, tool results), the ID and available version of the model, final settings after defaults and overrides, and links to source data. References to a template or Note are not enough: the text or its interpretation may have changed.

If a parameter is omitted and the provider's default is unknown, the trace records the omission and that uncertainty. [[Core data structures#^note-claim-prompt-evaluation|Prompt evaluation]] applies to the actual configuration, not just `target_llms` or template defaults.

#### Read Contract

#topic_core

`read_contract` lists the Concepts (including operators), relation types, and transition types that a program actually reads but does not write.

#### Output Contract

#topic_core

`output_contract` lists the Concepts, relation types, property axes, or transition types that a program actually predicts, creates, changes, or deletes.

Required predictions and Profiles are defined by the specific implementation's contract. A link `PROCESS_VARIABLE(process, x)` does not by itself require every program for that process to predict `x`: [[Process Ontology and Semantic Interface#^semantic-program-organization|process semantic scope and implementation coverage differ]]. A missing required prediction needs to be analyzed and the program corrected.

#### Expected Signals

#topic_core

**`ExpectedOutcomeSignal`** is a forecast of the value of a selected [[Evaluative-Control System#^def-SignalChannel|`SignalChannel`]] under the shared [[#PredictionTarget and Forecast Contract|forecast contract]]. It is a role of a typed model result, not a separate evaluation channel or mandatory runtime class.

A `Program` may include expected signals in the typed `ProgramResult.result` payload alongside its domain result:

```text
ProgramResult.result
→ domain result
+ optional expected signals
```

Expected signals let a parent program use a shared interface to assess consequences of a result, compare alternatives, make a commitment, or direct attention.

Programs may return forecasts for selected channels when their result is an independent outcome that could affect later control:

```text
ExecutableProgram
→ may return expected signals for proposed actions,
  candidates, or branches before execution;

Declarative Model
→ may return expected signals when forecasting consequences
  helps with selection or attention;

Program with meta or simulation modifier
→ returns them when its result is evaluated
  through shared signal channels.
```

Technical utilities and internal computations with no independent control significance do not return expected signals.

#topic_details

If a parent program needs the consequences of an intermediate branch before continuing, make that branch a child `Program`.

```text
ordinary internal computation
→ anchored operator;

independently evaluated outcome
→ child Program
→ expected signals.
```

Expected signals are a sparse part of the result:

```python
expected_signals?: <dict[SignalChannel, ExpectedOutcomeSignal]>
```

For this dictionary, the contract defines the subject, conditions, and horizon for each channel. If several forecasts for one channel are needed, distinguish them in the program's typed payload. A numeric supervisor-feedback forecast belongs in `value`; an optional `comment` explains the actual assessment.

An absent channel means that the program does not model it, not that a zero effect is expected. Consciousness selects channels and forecast points based on [[Learning system#Selecting Learnable Components and Learning Mode|process importance and modeling cost]]. Predictors for every signal are not created for every semantic operator by default. An operator having `BeliefData` does not require its own signal predictor.

### Learnable and Fixed Components

#topic_core

A **learnable part of a program** is estimator state or program parameters that are intended to be updated from data without changing code or contract—for example, outcome counts, a learnable value `V`, regression coefficients, or policy parameters.

[[Learning system#LearningCredit and UnresolvedCredit|`LearningCredit`]] applies to a [[Learning system#^def-LearningTarget|`LearningTarget`]] and its use in the context of experience; for forecast training this is a [[#^def-PredictionTarget|`PredictionTarget`]]. [[Learning system#PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher|`UpdatePlanner`]] selects the specific state or parameters to update. Policy parameters may be learned from independently evaluated decision consequences without a forecast of their own.

A **fixed component** is a part that parameter learning does not change, such as code, an explicit rule, or a specified threshold. It may be changed through [[Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]]; “fixed” does not mean immutable forever.

One program may combine both kinds of component. A value `V` that is constant across inputs may still be learnable, while a specified constant is fixed. A component whose learning is paused retains its acquired state and may remain in use; resuming training does not require recreating it.

---
## Program Roles: Declarative Models and Executable Programs

### Declarative Models

#topic_core

A **ProcessModel** describes how concepts change and which causal relationships lead to which outcomes. It is a base process model (part of the “world model”) and is technically a `Program` with `model ∈ Program.roles`.

It may describe:

- processes and interactions in the external world;
- lifecycles of concepts and relations;
- behavior of internal programs and changes to the agent's internal structures.

It is used for prediction and analysis.

A ProcessModel describes, predicts, and explains. Unlike an ExecutableProgram, it has no active nodes (agent actions); it does not, for example, answer the user.

For training Declarative Models, use [[Memory#^def-Observation|observations and outcomes]], including evaluations of `supervisor_feedback_signal` and `tension_reduction`. Training data and loss function are defined by the specific model algorithm. [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] diagnoses a discrepancy in a specific forecast and motivates analysis; it is not a universal loss function.

#topic_details

A ProcessModel may predict transitions, domain outcomes (such as a game's final score), and selected [[#Expected Signals|expected signals]] for states and actions. Domain forecasts do not have to be general agent signals. The model returns a forecast; the program using it selects the action.

Action selection takes place inside an `ExecutableProgram` through ordinary control flow or a call to an [[Action Selection and Planning|policy program]]. A policy returns `ProgramResult[ActionDistribution]`; the caller selects an action from the distribution using a shared function and organizes its execution. A deterministic choice is represented by probability `1` for a single action. The controlling `exec` program saves its own `ProgramResult[T]` and may make several decisions, wait for an observation, or finish without an action.

```text
Declarative Model, when needed
→ forecasts / expected signals for the decision context

Verification, when required
→ sufficiently verified candidate set

CommitmentControl
→ automatic
  or consciousness_selection

if automatic:
    policy(...)
    → ProgramResult[ActionDistribution]
    → sample_action(distribution)
    → ActionCandidate

if consciousness_selection:
    → Consciousness
```

Responsibilities of [[Action Selection and Planning#Process Management and Skill Development|`TaskManagingProgram` and `SkillDevelopmentProgram`]] include organizing Evaluation and the selected learning path; sampling from the distribution does not initiate either by itself. The calling program determines the order of applicable Verification and CommitmentControl from the decision context.

In Declarative Models, expected values for individual signals are added only for selected channels and program points: states, transitions, `ActionConcept`, or `PROCESS_VARIABLE`. Modeling a process does not require forecasting supervisor feedback or other general signals. Add such a forecast when the signal is part of the modeled subject or its evaluation is expected to help control.

If a separate learnable numeric predictor for a signal is needed, the MVP supports `V` and linear regression `Ax+b` over input parameters, such as the size of a poker pot. A fixed value or an estimate from an existing model may suffice. More complex separate predictors, such as XGBoost or MLP, are reserved for later versions and justified cases. This limitation applies to separate numeric signal predictors, not all [[#Estimator|estimators]] for process models.

---
#### `PredictionTarget` and Forecast Contract

#topic_core

> [!definition]
> **`PredictionTarget`** — a semantically defined quantity, event, or state selected for forecasting: a score, temperature, game outcome, property, composite object state, or selected signal.
> ^def-PredictionTarget

For forecast training, `PredictionTarget` is a specific kind of [[Learning system#^def-LearningTarget|`LearningTarget`]]: credit concerns what the model is learning to predict. Other `LearningTarget`s may denote actions, decisions, or inferences used without having their own forecast.

The target's meaning is defined by an existing `Concept` and its graph links; a separate node or Python class for the forecast-target role is unnecessary. For a property, `PropertyConcept` defines its meaning, while [[Attribution Plane#Attribution Axis|`AttributionAxis`]] defines its value space and read interface. [[Process Ontology and Semantic Interface#PROCESS_VARIABLE|`PROCESS_VARIABLE`]] links a material quantity to a process; [[#Output Contract|`output_contract`]] and [[#^program-semantic-interface|semantic interface bindings]] define coverage by a specific model. A process may have many forecast targets; each model covers selected targets.

One target may be predicted by several estimators; one estimator may predict several targets. A formula or rule may produce a forecast without learnable state.

The contract for each forecast output defines:

- **What and whose value:** the semantic target, subject, and answer form—a value, mean, event probability, distribution, or state.
- **When and under which conditions:** the horizon and available information, plus the assumed first action and continuation when they affect the result.
- **How it will be checked:** how to obtain and match the observed outcome; for a latent quantity, which consequences can be checked.

Fixed conditions belong in the versioned contract; changing conditions are passed as typed arguments. Use references to Concepts and relations; text explains any unformalized remainder. A separate mandatory `ForecastSpec` is not introduced. The configuration of a shared estimator may collect these references and settings, but does not duplicate graph definitions.

For example, a stack change, its conditional mean, the probability of winning at least `X`, and the task objective of obtaining `X` have different meanings. A forecast of future `prediction_unexpectedness` concerns a specified model and evaluation conditions; it does not replace the evaluation itself or become an optimization target.

---
#### Direct Outcome Forecast

#topic_core

A model may forecast an outcome without traversing a continuation tree, using a rule, formula, accumulated statistics, or an [[#Estimator|estimator]]. The external interface defines the question to the model; an estimator is one possible way to compute the answer. For example:

```python
PokerReturnModel.run(
    view: PokerView, first_action: ActionCandidate
) -> ProgramResult[float]
```

The semantic binding for the result means the expected change in the specified player's stack from the current point to the end of the hand, given the first action `first_action` and declared continuation. The model does not perform the action. It estimates only conditions it supports; passing it a different policy does not automatically make the forecast applicable to that policy.

A state forecast estimates the outcome under a specified continuation; a state-and-action forecast also fixes the first action. Names such as `predict_state_value` and `predict_action_value` are acceptable for such numeric estimates, but they are not required `ProcessModel` methods. A forecast of the current state does not itself compare candidates: that requires estimates for each action or a transition model plus an estimate of the next state.

A forecast may directly serve as a score when it matches the selection criterion; otherwise, the policy also accounts for costs, constraints, and risk. The choice between forecasting a distribution and one characteristic follows the [[Learning system#Forecast Representation and Learning Objective|general modeling rules]]. Such forecasts are used both by a policy without search and to evaluate remaining outcomes during [[Action Selection and Planning#Evaluating Continuations|planning]].

---
#### `Estimator`

#topic_details

(def_id:: entity.Estimator)
> [!definition]
> **`Estimator`** — a reusable component that builds a numeric, probabilistic, or categorical model of a dependency from data and uses it to produce estimates.
> ^def-Estimator

An `Estimator` is not required for every [[#Declarative Models|ProcessModel]]; use one when part of the model is naturally learned from data and it is useful to isolate or reuse that mechanism.

**Means and frequencies updated from experience for forecasting are the simplest learnable estimators.** Ready-made implementations let the agent configure a forecast without rewriting accumulation and training for each program point.

Basic implementations include running means and frequencies, their bucketed variants, and regression over features. Select the forecast form and metrics under the [[Learning system#Forecast Representation and Learning Objective|general modeling rules]].

Linear regression `Ax+b` is suitable for numeric quantities. For probabilities, use frequencies or a model with output in `[0, 1]`, such as logistic regression; an arbitrary linear output is not a probability.

Minimal interface of an internal component:

```python
estimator.predict(inputs: Inputs) -> Forecast
```

`Inputs` and `Forecast` are concrete types defined by the component contract. A result may be a number, distribution, or composite forecast. If a forecast may be unavailable, express that in the output type—for example, `float | None`—and handle it explicitly in the caller. The [[Learning system#Estimator Initial State|initial estimate]] is defined by contract; absence of data does not itself mean zero.

An internal helper may return an ordinary number. At the model `Program` boundary, it is included in `ProgramResult[T]`; a standalone anchored operator formats its result as a domain [[Memory#^def-OperatorOutput|`OperatorOutput`]] with a semantic contract. Accumulators also provide `statistics()` with a typed observation summary: sample count, mean and spread, or category counts. For an empty sample, counts are zero while empirical estimates of mean, probabilities, and spread are unavailable; a prior is not presented as observed data.

When creating or revising a program, [[Learning system#Selecting Learnable Components and Learning Mode|consciousness selects]] useful targets and forecast points, first checking ready-made models and rules. For the selected estimator, the program links the [[#`PredictionTarget` and Forecast Contract|forecast contract]] to the component, input preparation, and retrieval of the actual outcome. This binding lets the standard mechanism match experience and update state:

```python
# Inside PokerReturnModel.run(view, first_action):
features = decision_features(view, first_action)
return ProgramResult(result=return_estimator.predict(features))
```

An [[#Code Anchors|Anchor]] links the call location to the graph and trace. For training, retain the features used, estimator state version, and original forecast with provenance; [[Learning system#Prediction and Observation|`PREDICTS`]] makes it findable for evaluation. Information revealed later, such as an opponent's cards, must not be added to the features for an earlier decision. `predict` does not train the component: applicable outcomes go through Evaluation and [[Learning system#LearningCoordinator|`LearningCoordinator`]], the specific updater computes new state, and the shared mechanism applies the update. This also applies to simple running-count accumulators.

An Anchor does not itself define a homogeneous sample: different states and actions may pass through one branch. A mean over past visits is a forecast only if its applicability to current conditions is justified. For example, average winnings after `fold` with weak hands and after `call` with strong hands do not compare these actions in the same situation. Admissible experience, outcomes for unchosen actions, repeat accounting, and local adaptation follow the [[Learning system#Selecting Learnable Components and Learning Mode|general learning rules]].

Statistics from different points may use shared estimator state when their contracts are explicitly compatible. Matching `PredictionTarget` alone does not merge samples; predictors for every target are not automatically created at every anchor. [[Attribution Plane#Instance-Level Numeric State|`InstanceSketch`]] and [[Attribution Plane#MetricDistribution at the Prototype / Type Level|`MetricDistribution`]] may provide statistical mechanisms, but descriptions of past observations or norms do not replace a forecast contract.

---

#### Relation to Reflection

#topic_details

A ProcessModel may describe not only the external world, but also the agent's own programs among its Executable Programs. This is the basis for self-observation, self-programming, and meta-learning.

### Executable Programs

#topic_core

An **ExecutableProgram** is a `Program` with `exec ∈ Program.roles` that selects actions, calls programs, and may change the agent's internal or external state.

It may use Declarative Process Models as subprograms, but differs in that it can:

- create, change, or delete relations and concepts;
- simulate and optimize agent policies, including regulating attention;
- send a response to the user and perform other external actions according to the [[Cognition and Attention#^actions-and-user-response|shared action cycle]].

When an existing process model or part of one should be reused, the ExecutableProgram calls Declarative Models and their subfunctions. An ExecutableProgram may call a Declarative Model, but not the other way around.

Executable Programs learn and improve from observations, outcomes, and Evaluation results against a selected [[Learning system#^def-LearningSignal|learning objective]]. Evaluation signals may help select experience; `tension_reduction` alone does not confirm improvement.

#topic_details

For example, an ExecutableProgram can learn a verified strategy by imitation when there is not yet a ProcessModel with adequate predictive signals.

An ExecutableProgram may use expected signals to choose branches and actions. After execution, it creates realized outcomes and signals, which are then compared with the expected ones.

### Program Calls During Task Execution
^process-observation-input

#topic_core

Argument preparation connects available data to the parameters of the selected program. The call is organized by consciousness or an `exec` program within a [[Cognition and Attention#^def-TaskExecution|Task]], including observation and Reflection; its place in agent work is shown in the [[Cognition and Attention#^agent-processing-cycle|overall cycle]].

**Source material**, or a **data source**, is a message, document, measurement, or command result from which a program input is prepared. A source reference identifies where a fragment came from.
^preparation-source

The material is retained so that different representations can be prepared for specific work. [[Cognition and Attention#^def-Perception|Perception]] may represent an entire block as an observation: extracting every atomic fact generically would require knowing the specifics of every process. Different representations retain shared provenance.

[[Cognition and Attention#^input-reception|Input reception]] saves data and links it to a Task. A tool result with a known call ID is returned to the calling program or waiting Task. For a new observation, consciousness or an `exec` program may use [[Process Ontology and Semantic Interface#^def-ProcessRouter|ProcessRouter]] to identify the process and a suitable program. If the input is ambiguous, the caller clarifies it or requests conscious analysis. Creating a Task, choosing a Focus, and launching the identified program remain separate decisions.

#### Choosing the Next Episode-Processing Step
^next-episode-step

#topic_details

For input associated with a Task and [[Memory#^def-Episode|Episode]], the [[Cognition and Attention#^context-preparation|prepare_context]] program assembles a `PreparedContext`: selected past experience and the complete current input. Further processing is managed by the consciousness or [[Cognition and Attention#^def-TaskManagingProgram|TaskManagingProgram]] that receives this context.

> [!definition]
> **EpisodeStep** — data for one next step in processing an episode, such as a paragraph or a measurement window.
> ^def-EpisodeStep

The following contract covers splitting **text**: messages, documents, and tool output. For measurements, time-window selection programs use domain types and their own contracts.

> [!definition]
> **TextInput** — immutable text made from ordered ranges of saved text values, such as message fragments or a specific version of an essay.
> ^def-TextInput

```python
class TextSpan(OperatorOutput):
    source: TraceOutputRef
    start: int
    stop: int

class TextInput(OperatorOutput):
    parts: tuple[TextSpan, ...]

    def read(self) -> str: ...
```

- `source` is a [[Memory#Recording Provenance|TraceOutputRef]] to a saved Python string `source_text`; large texts may be stored in [[Core data structures#^def-Artifact|Artifact]].
- `TextSpan` is a range `[start, stop)` validated by `0 <= start < stop <= len(source_text)`.
- `read()` joins ranges in order without separators; `parts=()` yields empty text. Splitting changes the ranges without copying the remainder.

For text held in a local variable, use a reference to its [[#^local-values-and-results|saved version]]. Assembling, reordering, and editing parts are separate operations that retain provenance; they do not change saved snapshots. When processed parts are corrected, the caller reconsiders dependent results.

For text, an `EpisodeStep` is represented by the selected `TextInput`:

```python
class NextEpisodeStep(OperatorOutput):
    step: TextInput | None
    remaining: TextInput

def get_next_episode_step(
    text: TextInput,
    prepared_context: PreparedContext,
    *,
    complete: bool,
    program: Program | None = None,
) -> ProgramResult[NextEpisodeStep]: ...
```

`prepared_context` specifies task conditions; `program`, when known, specifies the target call's contract.

**`complete` means that transmission of this particular input has ended.** `TaskManagingProgram` or consciousness sets it: `True` for a ready document or a separately received message; `False` while content is arriving in parts, until an established end such as user confirmation or stream closure. The managing program or consciousness clarifies an uncertain boundary; the splitting program does not guess.

When a step is ready, `step` contains a non-empty beginning of the text and `remaining` contains the rest: `text.read() == step.read() + remaining.read()`. Step size is learnable; verified splitting may run as ordinary code. If no step is ready, return `step=None` and the original text as `remaining`.

The control program or consciousness proceeds as follows:

1. Assemble `TextInput` from the input, saved remainder, and required semantic values; the Task determines how the parts relate.
2. Call `get_next_episode_step(text, prepared_context, complete=...)`.
3. If a `step` is returned, pass it to the target program through [[#^def-ArgumentPreparation|argument preparation]], which may read it as `str`. Continue with `remaining` after processing.
4. If `step=None`: when `complete=False`, retain the remainder and wait for continuation or clarification; when `complete=True`, an empty remainder ends parsing, while a non-empty one requires a different split or clarification.

Execution state stores the remainder; the selected step is retained until processing completes or it is explicitly skipped, so work can continue after a failure. A related continuation or end signal updates the input and `complete`, then resumes step selection; the signal may arrive without new text.

A later addition becomes new input and may require reconsidering results. Running out of text does not finish the Task. Splitting retains provenance and does not create independent observations; helper calls do not require a new `EpisodeStep`.

#### Argument Preparation

#topic_core

(def_id:: entity.ArgumentPreparation)
> [!definition]
> **ArgumentPreparation** is a [[Process Ontology and Semantic Interface#ProcessConcept|ProcessConcept]] describing how arguments for a selected program are prepared from its interface, the purpose of the call, and available data.
> ^def-ArgumentPreparation

Programs that implement preparation select and transform data, bind it to parameters, and check the contract. A signature alone is not enough: a type such as “word” does not specify which word is needed or whether two messages are parts of one word.

#topic_details

```python
Arguments = dict[str, object]  # parameter names → values

class ArgumentsNotReady(OperatorOutput):
    reason: str
    partial_arguments: Arguments

def arguments_formatter(
    program: Program,
    prepared_context: PreparedContext,
    *,
    sources: tuple[TraceOutputRef, ...] = (),
    known_arguments: Arguments | None = None,
    instructions: str | None = None,
) -> ProgramResult[Arguments | ArgumentsNotReady]: ...
```

| Argument | Purpose |
| --- | --- |
| `program` | Target program: interface revision, semantic types, and `requirements`. |
| `prepared_context` | Task and Episode conditions, current input, and selected information. |
| `sources` | Additional sources from the current execution to obtain arguments. |
| `known_arguments` | Bindings to parameters already supplied. The preparer validates them and retains them when building the full argument set. |
| `instructions` | Preparation clarification not yet expressed by the contract, context, or data. |

The calling `exec` program or consciousness specifies sources, ready bindings, and instructions. `sources` contains [[Memory#Recording Provenance|TraceOutputRef]] references to saved operation or program results, such as a selected `EpisodeStep` or assembled text. A reference provides access to the value, its semantics, and provenance without copying data or passing all local variables. Local variable names do not determine correspondence to target parameters.

When `sources` is empty, data from `PreparedContext` is used. A supplied `EpisodeStep` defines the material to process; context helps interpret it and prepare related arguments. Only the caller may change step boundaries. One argument may combine sources, and one source may provide several arguments. An argument does not have to become an `Observation`.

The preparer reads `instructions`, for example: “Include the section heading together with the paragraph in `excerpt`.” The caller may refine them based on feedback. Conditions on the target program's behavior are passed as its arguments: “assess clarity only” is expressed through `criteria`.

For example, the letter is known, but the word must be extracted from a saved step `step_ref`:

```python
prepared = arguments_formatter(
    count_letter_in_word,
    prepared_context,
    sources=(step_ref,),
    known_arguments={"letter": "r"},
)
```

(def_id:: entity.ArgumentsNotReady)
> [!definition]
> **ArgumentsNotReady** is the result of incomplete preparation: `reason` explains missing data, ambiguity, or an unmet condition; `partial_arguments` contains usable parameter bindings.
> ^def-ArgumentsNotReady

[[#^def-ProgramResult|`ProgramResult.result`]] contains:

- `Arguments` — all required arguments are set and input conditions in the contract are met. Parameters with defaults may be omitted; `None` or an unknown value allowed by the contract does not mean preparation is incomplete.
- `ArgumentsNotReady` — the caller obtains more data, clarifies the selection, waits, or changes preparation; on retry, it passes current `partial_arguments` as `known_arguments`.

An inability to prepare a call is expressed in `.result`; `feedback` suggests improvements. Argument provenance is retained in the trace. The caller launches the target program; the full `PreparedContext` is passed only if the target has a corresponding parameter.

Preparation uses perception results and the [[#^source-access-preparation|shared read and transformation operations]], including context assembly when context is needed as an argument. Local assembly of an LLM request inside a target program uses its arguments and permitted reads; for example, it selects a document section for [[Core data structures#^def-Prompt|Prompt]] without rerunning [[Cognition and Attention#^context-preparation|ContextPreparation]] for the entire Task.

With ready arguments and satisfied conditions, call the program directly. The caller supplies inputs to `arguments_formatter`. Known preparation operations may run as ordinary code without an LLM.

#### Nested Call Cycle
^input-preparation-pipeline

#topic_core

```text
PreparedContext + current execution values
→ consciousness or calling exec within Task / Episode
→ select next work
→ when processing text: get_next_episode_step
  (step=None → wait, finish parsing, or clarify conditions)
→ target Program and its contract
→ ready arguments or arguments_formatter
  ├─ ArgumentsNotReady → clarify / get data / wait / change method
  └─ Arguments → caller launches Program → ProgramResult(result, feedback)
→ caller updates state and chooses continuation, waiting, or completion
```

These are dependencies between operations, not a requirement for separate LLM calls. If the target program is already known, its contract is considered when [[#^next-episode-step|selecting a step]]; otherwise, [[#^def-ArgumentPreparation|argument preparation]] checks whether the step is suitable. An unclear process stage can first be clarified through analysis or a model call. Child calls do not require returning to consciousness at every step.

For an LLM step, the program selects [[Core data structures#^def-Prompt|Prompt]], model, settings, and data for placeholders, then parses and checks the response. Its arguments, available material, and actual LLM request may differ; assembling a request locally does not require a separate ProgramRun. An exact algorithm may need no LLM. A `ProcessModel` uses passed data, reads allowed by `read_contract`, and permitted model calls; the calling `exec` or consciousness organizes new observations, actions, and `exec` calls.

Results are available from local variables and [[Memory|memory]]; later calls access them directly or through `sources` and `known_arguments`. A new input or changed conditions may require rebuilding `PreparedContext`; another computation does not. No separate mandatory process-state object is introduced. Missing data preserves uncertainty, and recognizing a process stage does not move Python execution to an arbitrary line.

Evaluation is performed when outcome data are sufficient; selected evaluated experience is passed to [[Learning system#LearningCoordinator|LearningCoordinator]] for credit assignment and permitted parameter learning. Assessing observations as epistemic evidence is separate. The caller uses feedback for further preparation or reanalysis under the [[#^program-feedback|shared rules]]; persistent contract changes go through [[Program Lifecycle and Evolution|revision]].

A program's return passes control to its parent; Task completion and sending a user response are determined by [[Cognition and Attention#^actions-and-user-response|task logic and actions]]. Rereading a source within a Task does not require [[Memory#^def-MemoryReplay|Replay]]; a separate task that returns to experience uses the same cycle with original provenance.

#### Requirements and Feedback: Perception Example
^perception-requirements-feedback

#topic_details

An `exec` program analyzes an engine test log and selects a model to determine the current operating stage; initial processing and routing may happen before this choice.

- **Before the call**, `exec` prepares data under the model contract: events, known temporal relationships, source fragments, and test conditions. Types and roles are semantic; accuracy and order are expressed as constraints. `requirements` retains a nuance in the author's language: “For the ambiguous phrase ‘almost started,’ keep the neighboring records.” Unknown values remain explicit. Reading requirements does not require running a model.
- **After the call**, the model returns the correct stage in `.result` and a recommendation in `.feedback`: “When analyzing a temperature rise, add the test heading: ‘idle’ or ‘under load’.” `exec` passes it through the designated context argument. If the need is persistent, the heading's role is formalized through an existing Concept.

Feedback thus improves successful processing. Model selection, its call, and applying feedback belong to `exec`; new observations arrive through perception.

#### Receiving the Next Observation
^next-observation

#topic_core

```python
observation: OperatorOutput = await next_observation()
```

`next_observation()` returns the next [[Memory#^def-Observation|domain output delivered to this execution in the role of an observation]]. Delivered inputs are retained until processed. If an input is already available, the method returns it without waiting for more; otherwise, execution waits for one. Delivery and recovery of the receive operation use the [[Cognition and Attention#^durable-program-execution|shared durable execution mechanism]].

This is an input-receive function, not a `Program`. If an observation was obtained by a perception program, the value delivered is its `.result` under the corresponding [[Memory#^def-Observation|Observation contract]], with the original identity and provenance; the `ProgramResult` wrapper and feedback do not become part of the observation.

The method does not filter for only an expected type: waiting for temperature must not hide a message about smoke. Source end and expiration of a specified waiting period differ from a temporary absence of input; neither alone means the process has ended in the world.

Already delivered history is processed sequentially without waiting for intervals between described events. A later message about the past is treated as past information; the task program specifies whether history is being reconstructed or a current process is being managed, so historical analysis does not repeat real actions.

#### Data Processing Granularity
^observation-granularity

#topic_core

**Processing granularity** is the size of one unit in a parsing, computation, or checking step: a character, paragraph, process state, or transition. Small units make it possible to check detail and intermediate results but may increase cost; large units often reduce overhead but can hide important distinctions and increase LLM hallucinations. Selection depends on the task, learning value, latency, and budget. EverTree retains available [[#^preparation-source|source material]], so the processing method can be reconsidered.

##### From Incoming Data to a Processing Unit

#topic_details

An **input block** is a portion of data identified during receipt or initial processing: a message, document fragment, sensor reading, or part of command output. Its boundaries define neither program arguments nor its internal steps:

```text
two messages containing parts of a word
    → one argument with the meaning of the whole word
    → read characters inside one call to a counting program
```

The relationship among fragments and permitted transformations are determined by the task and [[#^program-semantic-interface|interface]], not by adjacency. In sequential parsing, `get_next_episode_step` selects a fragment for a call; the program itself specifies the internal detail of reading it. An `EpisodeStep` boundary does not require a learning update.

##### Operation Context and Batching Computation

#topic_core

Two separate decisions are related to granularity:

- **Operation context** is additional information needed to interpret a unit: a heading, neighboring events, or task condition. A single character may require the entire task for context; adding context does not change the unit's size.
- **Computation batch** is the number of units in one call. One LLM call may identify the topic of several paragraphs; code may process all characters in a word. Fine granularity does not require one LLM call per unit.

Joint selection of these parameters must preserve [[#^granularity-learning-sequence|information-access boundaries]] when checking predictions.

##### Reading and Preparing Source Data
^source-access-preparation

#topic_details

The internal API for working with [[#^preparation-source|source material]] supports:

- reading exact ranges or characters, reading words, and traversing content sequentially;
- selecting fragments and time windows, and assembling related parts into an argument;
- obtaining context such as headings, neighboring fragments, related objects, and permitted history;
- extracting information while retaining its provenance.

Shared subprograms are grouped around these operations; the preparer selects them under the target program's contract, without exceptions based on its name. Concepts specify the meaning of units; interfaces specify permitted transformations. Structural paragraph selection may run as code; semantic segmentation may use an LLM when needed. Conscious character-by-character reading and a code loop may use the same operation; standalone Programs return `ProgramResult`, while technical functions return ordinary values.

When regrouping data, preparation retains references to source ranges, information about original order, and known temporal relationships; text order is not treated as event chronology. Overlapping windows, rereading, and new splitting retain [[Memory#^def-ResultProvenance|provenance]] without creating independent evidence or requiring a persistent node for every fragment.

Operations use data already received: a measurement window may be selected again, while increasing the frequency of future measurements requires an action. Splitting cannot restore precision lost through deletion or aggregation; data retention is governed by [[Memory|memory obligations]].

##### Choosing and Changing a Processing Method
^granularity-adaptation

#topic_details

The [[Cognition and Attention#^def-TaskExecution|`exec` program managing the task]] or consciousness chooses a method based on the task and contract. Initial options include a complete message, a document by section or paragraph, and measurements by sample or window. The method can then be adjusted:

- recover missing relationships by combining fragments or adding context;
- inspect missed transitions separately;
- combine reliable computations to reduce cost.

Adjustments may follow from feedback, experience, or a stage change even when processing succeeded. Increased sensitivity to features such as danger is not the same as switching [[Cognition and Attention#Attention (`Attention`)|Attention]] between tasks and must not hide unexpected significant inputs.

Existing programs implement the decisions: [[#^next-episode-step|`get_next_episode_step`]] selects a text step, a domain program selects a measurement window, [[Cognition and Attention#^context-preparation|`prepare_context`]] selects context, and `arguments_formatter` prepares arguments. Selection may be learned from the task, contract, data, stage, experience, and budget; verified strategies can be reused without another selection. The process program defines internal reading and prediction order. Current-run clarifications are passed under the [[#^program-requirement-representation|rules for structure and text]] and do not rewrite the persistent contract.

Criteria include accuracy, completeness, retention of important information, latency, and total cost of preparation, processing, checks, and retries; for learning tasks, they also include experience value for the model and shared agent mechanisms. New, important, or rarely checked work may justify more detail, though a dependency may only become visible in a larger fragment. Expensive semantic segmentation is justified when its benefit to the result or learning covers its cost. Inability to meet required accuracy and response time within the budget remains explicit.

The trace retains significant preparation decisions, data, and their links to the result; [[Learning system#Credit Assignment|credit assignment]] assesses contributions from preparation, routing, and the model when there are sufficient grounds. The task sets the criteria; there is no universal aggregate score. Counts of facts or steps, or a smaller block size, do not by themselves prove improvement. If segmentation, context, and Prompt change together, the benefit belongs to the combination until individual contributions are established. Run configuration, permitted parameter learning, and structural revision are separate operations.

##### Why Control Granularity When Learning a Process Model
^granularity-learning-sequence

#topic_details

When learning a process model, the agent may check forecasts of states and transitions. For this check, the model records a prediction before the outcome is shown. For example, after a description of rising temperature, predict that an engine will stop before reading that its protection system activated:

```text
information available before transition → saved prediction
→ observed outcome → Evaluation
→ credit assignment and permitted update when grounds are sufficient
→ next prediction
```

A large step may reveal both premises and outcome at once; overly small steps may create many useless checks. Therefore, select significant states and transitions; predicting every token or changing the base LLM's training objective is not required.

During [[Program Evaluation and Testing#^prediction-quality-protocol|checking a prediction before its outcome]], `arguments_formatter` prepares the selected step and information available before the predicted transition for the model. The full material is available to the task program and splitting program. Reviewing the full history is allowed for retrospective explanation or training on a known case, but is not treated as a prediction made before the outcome.

Evaluation and learning use the [[Learning system|shared Learning mechanism]] and the [[Learning system#Selecting Learnable Components and Learning Mode|authorized mode]]. A prediction may be checked across several `EpisodeStep` instances; one outcome may check several earlier predictions. If there are insufficient grounds for credit assignment, no update is made.

To prevent future-information leakage and overfitting, enforce information boundaries and check transfer to new cases; fragment size alone does not ensure this. Re-splitting one source does not create independent training and evaluation cases.

##### Applying Granularity to Different Tasks
^input-pipeline-scenarios

#topic_details

| Task | Processing organization |
| --- | --- |
| Count letters in a word across two messages | Join the word according to the established fragment relationship, then count characters in code in one call. |
| Analyze a book's structure | Process it as a whole or compare analyses of sections using completeness, accuracy, and cost criteria. |
| Check a process model against a book | Select significant transitions and keep the prediction separate from the observed outcome. |
| Monitor sensor readings | Select samples or windows; reconsider them after feedback or a stage change. Averaging must not hide a brief significant spike. |
| Account for a delayed observation | Retain event time and receipt time; reconsider history, check the earlier prediction using information then available, and do not repeat actions. |
| Analyze command output | Select all output or diagnostic records together with the command and launch conditions; retain available stdout/stderr, status, and provenance. Reassemble transport fragments into records; distinguish completion, timeout, and no output. |

[[Cognition and Attention#^dialogue-word-count|The letter-counting scenario]] shows how the first example fits the overall Task cycle.

#### Types, Conditions, and Subprograms

#topic_core

An output type specifies available fields, while its semantic relations define what an observation means. Before accessing `observation.temperature`, a program must establish that a temperature measurement exists, its unit, and its applicability to the required object and time. “The engine is hot” does not become an exact numeric measurement. An open set of domain types and concepts does not require a separate Python class for every possible event in the world.

`OperatorOutput` is a shared input interface; the specific schema is preserved when passed. For example, if `TemperatureReading` is a measurement schema in °C, the numeric branch after checking object and time is:

#topic_details

```python
if isinstance(observation, TemperatureReading):
    if observation.temperature > limit_celsius:
        await handle_overheating(observation)
```

#topic_core

Control flow remains ordinary Python code. `if`, loops, and calls to [[#OperatorConcept, Code Anchors, and AnchorResolver|semantic operators]] may use the graph and select every applicable condition. An exclusive `match` is appropriate when alternatives truly exclude one another; compound observations are handled with all significant aspects in mind before choosing actions. For an unknown type, unclear meaning, or unresolved condition, the program provides clarification or passes the question to Attention. An unknown condition value is not treated as false.

In delegated execution, the shared input goes to a specific parent `exec`; subprograms for stages receive observations from it and do not compete to read that input. Short calls return control to it. Runtime continues to receive and save inputs during long child work, but queuing alone does not ensure a timely response. The `exec` program must provide a handler and a way to pass it control, or request a handoff at the [[Cognition and Attention#Attention (`Attention`)|nearest permitted runtime boundary]]. Simply blocking while waiting for child work does not provide this.

Shared reactions are checked when each new observation is processed, regardless of the current stage. An urgent reaction does not wait for Evaluation or training. For example:

```text
information indicates the engine is on fire
→ call the fire response program;
  pause incompatible ordinary control;

conditions for ordinary control are established
→ continue the subprogram for the current stage;

data are insufficient
→ perform a specified clarification or pass the question to Attention.
```

The parent `exec` determines compatibility, priority, and order among applicable branches. Multiple matching conditions do not automatically run in parallel. One working composition may include heating, cooling, and emergency response as subprograms; it does not launch and train every alternative process model at once. If a conscious decision is needed, the Task requests Attention resources; this does not create an intermediate `ProgramResult.feedback` channel for an unfinished program.

This design retains sequential Python code, allows unexpected and compound observations, and makes it possible to refine behavior through graph semantics. A separate expectation language and branch scheduler are not needed.

For checking, the process program calls the shared [[Learning system#^def-PredictionEvaluator|`PredictionEvaluator`]] with observations, process context, and metrics. Its `match_predictions` function finds predictions and gathers related observations; `evaluate_prediction` checks each prediction; `handle_unmatched_observations` handles unmatched experience. A missing prediction for a known, selected `PredictionTarget` is recorded through [[Learning system#LearningCredit and UnresolvedCredit|UnresolvedCredit]] and passed for review under the evaluator's shared rules. The task program organizes assigned learning through [[Learning system#LearningCoordinator|`LearningCoordinator`]]. Evaluation by itself does not authorize training. Credit concerns a semantic target; `UpdatePlanner` selects the state to update, including router parameters when there are grounds to evaluate its choice.

---

## Specialization Strategy

### Generalization and Model Compression

#topic_core

Generalization and compression are persistent strategic priorities for the agent. While preserving required quality and justified cost, it aims to reduce the number of independent models, estimators, and independently trained parameters, as well as duplicated code. The goal is to combine compatible experience, improve transfer to new cases, and reduce training, execution, and maintenance costs.

Programs for specialized processes may use a shared model as is or extend it with conditions, local parameters, and adjustments. Significant differences justify separate models or estimators. Reusing code with independent parameters does not by itself ensure [[Structural Dynamics and Topology#Parameter Tying|joint training]].

Discovered commonality is represented by a [[Core data structures#^def-Claim|Claim]] that a shared model applies within a specified scope. A refactoring candidate changes the Programs that use it; for learnable components, it explicitly defines shared and local state and the experience that updates them. [[Program Evaluation and Testing|Evaluation]] or practical checks compare quality across affected processes, transfer, and costs against the former models; further use follows the ordinary [[Program Lifecycle and Evolution#EvaluationChoice|EvaluationChoice]].

### 1. Enriching the Semantics of the Current Model

#topic_details

The agent may add specialized semantic relations to concepts, operators, or process programs.

Examples:

```text
CAUSAL_TRANSITION(factor, effect)
TRIGGERS(trigger, process_or_transition)
CONTROL_CONFLICT(subject, constraint, scope, expected_signals?)
```

This is the preferred default: rather than create a new kind of model, refine the meaning and relations of an existing model.

---

### 2. Creating a Specialized Model Program

#topic_details

If an ordinary process model is insufficient, the agent may create a separate `Program` with a more specialized representation, such as a causal model.

```text
PROGRAM_FOR_PROCESS(program, process)
PROGRAM_MODEL_FORM(program, CausalModel)
```

[[Process Ontology and Semantic Interface#^semantic-program-organization|`PROGRAM_FOR_PROCESS`]] specifies **which process is modeled**, while `PROGRAM_MODEL_FORM` specifies **which specialized model form is used**. Model forms themselves are organized through ordinary [[Semantics Plane#^spec-SUBTYPE_OF|`SUBTYPE_OF`]].

A specialized `Program` has its own contracts, semantic links, lifecycle, and Evaluation.

---

## Program Implementation Interface

### Python-Backed Core

#### Introduction

#topic_core

Python code is used to:

- describe complex processes without artificial YAML/JSON duplication;
- execute models, simulations, and the agent's internal programs;
- check conditions, branches, loops, and transitions;
- debug through the ordinary Python runtime;
- generate and edit code with an LLM agent;
- link operators to graph concepts for Reflection, memory, and credit assignment.

Code remains the source of truth for control flow within a ProcessModel: it is the **executable process logic**. The graph remains the source of truth for semantic relations, program composition, and calls to ProcessModels themselves.

A program's Python interface may call libraries and native backends. Semantic contracts and Code Anchors describe significant boundaries of those calls; each internal computation does not need separate markup. For narrow tasks, a [[Learning system#Specialized Learning|specialized learning path]] managed by a specific subprogram is permitted.

### Actions

#topic_core

```text
ACTION(agent, target, expected_outcome)
```

Meaning:

```text
Action — a process step intentionally initiated by the agent.
```

Example:

```text
AgentIgnitesWood triggers FireBurnsWood
```

Distinguish:

```text
Action — an agent action (not a concept). Allowed only in Executable Programs.
ActionConcept — a concept representing an agent action in process models. A basis for Reflection.
```

At runtime, a [[Action Selection and Planning|policy]] returns a distribution over `ActionCandidate` instances, which may reference an `ActionConcept`, `ProgramCall`, or branch transition. The shared sampling function returns a specific candidate to the calling `exec`.

```text
`ActionConcept` is for semantics, Reflection, memory retrieval, and `CONTROL_CONFLICT`.
`ActionCandidate` is for a specific choice in the current execution context.
```

If options come from the external environment, their shared contract and two call methods are described in [[Discrete Action Interface]].

### Outcome

#topic_core

An expected result. A process does not have to produce one deterministic outcome.

```text
OutcomeProfile:
  Process → OutcomeA = 0.7
  Process → OutcomeB = 0.3
```

### “Training” Operators and Transitions

#topic_details

Each anchored use of an operator has `BeliefData`; an operator or function that returns a semantic value also returns separate result `BeliefData`.

An anchor's own `BeliefData` does not require a separate assessor or LLM call: [[Uncertainty and Belief Tracking in the World Model#Assessment Lifecycle|EvidenceAssessmentProgram processes related assignments in batches]] and reuses prepared models.

For an operator, this belief concerns not an abstract action in general but **its use at a specific point in control flow**:

```text
OperatorConcept.belief_data
→ how strongly evidence supports that
  this transition / operator is suitable and reliable here.
```

Therefore, the same action, such as `Jump`, may have different operator beliefs in different program branches.

Distinguish:

```text
Program.belief_data
→ belief in the active revision of the Program as a whole;

OperatorConcept.belief_data
→ belief in an anchored use of a transition / operator
  at a specific control-flow point and revision;

result BeliefData
→ confidence in the semantic result obtained.
```

For an anchored policy call, operator belief concerns applying the selection mechanism at this point; confidence in estimates of consequences belongs to the results of the corresponding models. A policy does not need to calculate utility estimates for every candidate. A separate selection wrapper is not required for storing belief.

Operator beliefs are updated through the shared evidence / learning lifecycle.

### OperatorConcept, Code Anchors, and AnchorResolver

#### Operator Concept

#topic_core

If an operator matters for reasoning, it has a concept in `GraphStore` (linked through a Code Anchor):

```python
OperatorConcept: Concept(1.0) {
    id: "op:EngineStartCode:start_gate"
    prototype: "PythonIfOperator" # Automatically filled from relations up the abstraction hierarchy
    description: "Guard deciding whether engine start transition can execute."
    belief_data: BeliefData(...) # belief in the operator itself as part of the model
}
```

Operator relations are stored separately in `RelationStore`, as for any concept.

Example:

```python
Relation(
  type="IDENTITY_TYPE",
  args={
    "instance": "op:EngineStartCode:start_gate",
    "type": "PythonIfOperator"
  }
)
```

#### Code Anchors

#topic_core

Code Anchors link Python code elements to their corresponding `Concept` and `OperatorConcept` in the graph. This binding defines the program's **semantic surface**: which computations, states, conditions, choices, and actions have independent meaning for reasoning, memory, learning, generalization, and debugging.

Anchored elements are part of the agent's observable experience. Technical implementation details without anchors are not materialized as independent memory items.

The runtime value of an anchored operator is interpreted according to its semantic contract, not only as a technical Python value.

The tracer automatically creates a trace-local `Facet` for a domain object's state when specified by the [[Memory#Semantic Interpretation of `OperatorOutput`|`OperatorOutput` projection contract]]. The reliability of claims about the state is expressed through `Belief_data`.

This separation protects memory from technical noise while allowing retention of everything needed to explain results and improve the program later. The agent defines and gradually refines the set of anchors during the `Program` lifecycle.

Execution of an anchored element creates a `TraceEvent`. If an anchored operator returns a result, its specific `OperatorOutput` defines the semantic type of the result and the roles of its named parts. The tracer does not infer meaning from a variable name or raw Python value.

**Code Anchors define the boundary between technical execution and semantic experience that is retained.**

Code Anchor format:

#topic_details

```python
# et:op=<op_id>
```

Example:

```python
def engine_start(ctx):  # et:op=engine_start_program
    start_conditions = ctx.fuel_present and ctx.battery_works

    if start_conditions:  # et:op=start_gate
        outcome = start_engine(ctx.engine)  # et:op=start_engine_transition
        return ProgramResult(result=outcome)

    outcome = engine_not_running(ctx.engine)  # et:op=engine_not_running_outcome
    return ProgramResult(result=outcome)
```

Notes:

- A subexpression with independent semantic meaning is moved to its own line with a separate variable and Code Anchor.
- Objects such as `ctx.fuel_present` are not strings. They are runtime objects containing all fields (such as `belief_data`) of the corresponding concepts from which they were created. At runtime, the agent can use these fields and navigate concept relations through standard LLM tool-calling.

`op_id` is the local ID of an operator within a `CodeNode`.

The full `concept_id` is constructed under the hood:

```text
op:<code_node_id>:<op_id>
```

Example:

```text
op:EngineStartCode:start_gate
```

#### AnchorResolver

#topic_details

`AnchorResolver` returns the operator concept.

```python
resolve_operator(
    code_node_id: str,
    op_id: str,
) -> Concept
```

For operators themselves, the returned Concept is an `OperatorConcept`.

Relations are queried separately if needed:

```python
get_relations(...) -> list[Relation] # TODO: detail the arguments
```

---
