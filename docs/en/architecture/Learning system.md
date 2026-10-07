---
status: draft
target_version: next
---

## Introduction

#concept #topic_intro

(def_id:: et.LearningSystem)

> [!definition]
> **Learning System** — a system that orchestrates the processing of evaluated experience, owns learning credit assignment and parameter-update routing, and calls the Belief System when epistemic evidence needs to be assessed.
> ^def-LearningSystem

---

## Core

#topic_core

EverTree programs can predict states, transitions, and signals through separate channels. New [[Memory#^def-Observation|observations]] arrive through the [[Process Plane/Program Layer#^process-observation-input|program for the selected process]]. [[Process Plane/Action Selection and Planning#Process Management and Skill Development|`TaskManagingProgram`]], including specializations such as `SkillDevelopmentProgram`, organizes the required Evaluations and selects experience, an objective, and a time for learning within the current `Task`; this work may be delegated to a subprogram. Learning may be triggered by an observation, batch, episode, or evaluated outcome of a Task or process, separately from the policy call that selects an action.

[[#^def-PredictionEvaluator|`PredictionEvaluator`]] finds predictions for selected [[Process Plane/Program Layer#^def-PredictionTarget|PredictionTargets]] and evaluates them against observations. For a known target with no assigned prediction, record [[#LearningCredit and UnresolvedCredit|`UnresolvedCredit`]]. `LearningCoordinator` organizes the processing of experience selected for learning: assessing epistemic evidence, assigning credit to selected [[#^def-LearningTarget|`LearningTarget`s]], and preparing updates. An observation may support beliefs without a verifiable prediction; performing an Evaluation does not itself mean training.

Observations may be accumulated and evaluated over a window or episode. It is not necessary to calculate [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] for every individual outcome.

Main experience-based learning flow:

```text
Within a Task context:
ProgramRun → prediction / epistemic Profile / OutcomeProfile / expected signals
Observations + process context + metrics → PredictionEvaluator
├─ matches found → evaluate_prediction → EvaluationResult for each prediction
└─ observations without predictions → handle_unmatched_observations
   → PredictionTargets → CreditAssignmentProgram
     → UnresolvedCredit(target, missing_prediction) → save → Attention
   → other unmatched cases → account for prior decisions / investigate

Selected observations / Evaluation of predictions, Task outcomes, or process outcomes
→ LearningCoordinator
├─ Belief System
│  → EvidenceAssessmentProgram
│  → EvidenceAssignment[]
│  → Evidence lifecycle / belief recomputation
│
└─ LearningSignal, only for EvaluatedResult
   → CreditAssignmentProgram: assign credit to LearningTarget in experience context
   → CreditAssignmentResult[]
      ├─ LearningCredit(target, signal)
      │  → UpdatePlanner: select a specific estimator or Program parameters
      │  → PreparedUpdate
      │  → UpdateTransactionManager.apply
      │  → UpdateDispatcher
      │  → estimator / optimizer under the state contract
      │  → atomic commit: updated parametric state + UpdateReceipt
      │
      └─ UnresolvedCredit(target, ambiguous_attribution)
         → save for analysis
         → do not update parameters
```

Learning System owns `LearningCoordinator`, `CreditAssignmentProgram`, `UpdatePlanner`, [[#^def-UpdateTransactionManager|`UpdateTransactionManager`]], and `UpdateDispatcher`. The Belief System owns [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]], [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|`EvidenceAssignment`]], and its lifecycle. Signal definitions are in `Evaluative-Control System`; the Belief System contract is in [[Uncertainty and Belief Tracking in the World Model]].

Flow diagrams show the payload from `ProgramResult.result` under the [[Process Plane/Program Layer#^def-ProgramResult|shared Program contract]]. The [[Process Plane/Program Layer#^program-feedback|`feedback`]] field does not create a `LearningSignal` by itself.

### Types of Updates (During Learning)

[[#^def-LearningSystem|Learning System]] distinguishes:

```text
belief update
→ Strength, Support, and Profile;

parameter update
→ parameters of an existing predictor or policy;

structural revision
→ changes to semantics, contracts, or Program structure.
```

Within a parameter update, the mechanism is defined by the learnable component's contract:

```text
frequency / categorical process value
→ FrequencyEstimator with counts / Beta / Dirichlet state;

numeric / distribution model value
→ model-specific estimator with sufficient statistics;

policy parameters
→ policy-specific optimizer.
```

Belief updates and planned parameter updates, including policy parameters, may run automatically. For competing alternatives, a belief update computes [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]]. Structural revision is passed to the shared lifecycle for programs and hypotheses.

A policy may have learnable strategy parameters, a utility evaluator, or other explicitly declared components. [[#LearningCredit and UnresolvedCredit|`LearningCredit`]] applies to the selected [[#^def-LearningTarget|`LearningTarget`]]; `UpdatePlanner` selects parameters to update based on context and learning objective, while the optimizer contract defines the update method. A policy call for action selection does not implicitly start learning; each policy does not need its own `learn()` method.

### Selecting Learnable Components and Learning Mode

When creating or revising a program, [[Cognition and Attention#^def-Consciousness|consciousness]] selects, within a `Task` context, which parts are [[Process Plane/Program Layer#Learnable and Fixed Components|learnable and which remain fixed]]. These decisions may be delegated to a program within bounds set by consciousness.

The main rule is to choose the simplest model sufficient for the required decisions, following the [[Process Plane/Program Layer#Generalization and Model Compression|generalization and compression strategy]]. Simplicity accounts for the number of parameters and the cost of input data, prediction, training, evaluation, and storage. An existing shared model, fixed rule, or evaluation may cost less than a new learnable component. Suitability is mandatory: a model must account for valid outcomes and dependencies material to the task. There is no need to consider simple models known to be unsuitable.

#### Selection Questions for Consciousness

Consciousness answers the following questions as needed, starting with the minimum required for the current task. It does not have to decide every detail in advance: suitable ready-made mechanisms and defaults may be used and refined from experience within the task budget.

- **Purpose:** which [[Process Plane/Program Layer#^def-PredictionTarget|PredictionTarget]] is predicted, at which point in the program, and for which decision; the observed outcome, conditions of use, available features and history, horizon, and units of measurement.
- **Representation and training:** what the output means, which estimator or optimizer updates it, the algorithm's assumptions, initial state, and metrics aligned with the objective. Consider reusing an existing model, general knowledge, or a suitable [[#^def-TrainingDataset|`TrainingDataset`]].
- **Experience:** which observations are allowed and how their dependencies and selection are handled; which outcomes are actually observable, and how corrections and [[#PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher|duplicate accounting]] are handled.
- **Mode:** learning from an observation, batch, or episode; trigger conditions and batch size; accumulation of statistics or an explicitly selected rule for adapting to process changes.
- **Evaluation:** a baseline model, the required type of transfer to new cases, sufficiency criteria, and revision conditions under the [[Program Evaluation and Testing#^prediction-quality-protocol|quality evaluation protocol]].
- **Resources and memory:** cost limits for obtaining data, prediction, updates, and evaluation; sufficient statistics, selected examples, or history in an artifact. Saved data and provenance must be sufficient for the algorithm, checks, and supported state recomputation.

For a specific prediction, define the output meaning and conditions; for an update, define a compatible algorithm, data, and state. Mode, batch size, budget, and checks may be selected and changed during operation, including automatically within delegated limits. Code, semantic, or contract changes go through the [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]]; changing settings within the active program's capabilities does not.

[[Process Plane/Program Layer#^granularity-adaptation|Learnable selection of preparation and granularity]] follows the same rules. Boundaries of source chunks do not automatically define prediction and update points; their relationships and limits on access to future data are described in [[Process Plane/Program Layer#^granularity-learning-sequence|preparing sequential experience]].

#### Forecast Representation and Learning Objective

When its decision value justifies the cost, prefer learning a distribution of possible outcomes under specified conditions and deriving the needed forecast from it. This is especially useful for assessing risk and obtaining several characteristics of one process. Reuse an existing suitable distribution. If one characteristic is enough for the task and modeling the full distribution offers no justified gain, directly forecasting that characteristic is acceptable. Choose the [[Process Plane/Program Evaluation and Testing#^prediction-quality-metrics|loss function]] according to the meaning of the output:

| Required forecast | Simple starting mechanism | Predictive quality criterion |
|---|---|---|
| Event or category probability | Smoothed counts, Beta / Dirichlet estimator | Brier or log loss |
| Conditional mean | Running mean, table, or regression | Squared error |
| Median or specified quantile | Suitable estimator or regression | Absolute or quantile loss |
| Numeric distribution | Suitable simple distribution family | Log loss or CRPS, when applicable |
| Related outcomes or trajectory | Model of material dependencies | Joint forecast metric and required horizons |

When a suitable distribution already exists, derive the mean, median, quantiles, and event probabilities from it; training each characteristic separately needs justification. For example, if outcomes are `10` with probability `0.9` and `30` with probability `0.1`, the mean is `12` and the median is `10`: these are different answers from one model. Check the practical accuracy of the forecast used by the application separately from the quality of the distribution.

Featureless statistics, estimates, and regression use the shared [[Process Plane/Program Layer#Estimator|estimator interface]]. Updating its sufficient statistics is parameter learning; a separate learning algorithm for each program point is unnecessary. A summary of historical values is not itself a forecast: the selected statistic, horizon, and applicability conditions are also needed.

Probabilistic forecasts use an appropriate strictly proper loss, whose meaning and limits are defined in [[Process Plane/Program Evaluation and Testing#^prediction-quality-metrics|quality metrics]]. Updates do not have to use gradients: accumulating sufficient statistics and Bayesian updates are also valid. If an optimizer uses a different internal objective, its contract explains how that objective relates to the learnable output; results are checked against the declared metrics. The objective of a policy optimizer is defined by decision consequences in the task context, not automatically by a predictive-model loss.

#### Data and Automatic Updates

Training experience must match the meaning of the forecast: the quantity and characteristic, horizon, information available when the forecast was made, and conditions—including the agent's continuation policy and the behavior of other participants. If these conditions change, check that the experience is still compatible; matching the `PredictionTarget` or anchor is not enough.

Selecting only errors, losses, or surprising cases may distort observed frequencies. If selection changes the target distribution, estimate the original process only with a supported correction whose assumptions hold; if a different distribution is intentional, state that explicitly. The importance of an outcome after it occurs is not by itself a reason to increase its weight when estimating probabilities. An unobserved outcome is not treated as zero or failure, and the consequences of an unchosen action do not become observations about that action.

Check predictive ability using a forecast saved before the outcome, or in an evaluation run on material from memory. In the latter case, the model does not see the outcome, and that outcome was not used to fit the forecast under evaluation. After evaluation, the outcome may be used for training; training on it again is not a new independent quality check. An event's rarity alone does not mean its source is unreliable. Limiting the influence of large deviations must match the target statistic and estimator assumptions; it may be justified even for reliable data with heavy tails. Treating an outcome as unreliable requires separate grounds; a model must not systematically ignore real rare outcomes.

For a stable process, sufficient statistics may be accumulated. For a changing process, choose a window, forgetting mechanism, or dynamics model with suitable assumptions. A process program may itself track changing conditions and adapt the model. Recalibrating a measure of unexpectedness does not replace changing the predictive model. The specific updater algorithm determines update size and permissible rules for forgetting and weighting observations.

In the standard path, designated parameter updates are performed automatically through [[#LearningCoordinator|`LearningCoordinator`]], without consciously choosing an algorithm for every example. It organizes permitted updates to existing components; it does not change the set of predictors through this path. A reusable estimator may keep separate learned state for different processes. Shared state is used only for the same dependency under compatible conditions. A specialized trainer has a separate path, described [[#Specialized Learning|below]].

#### Estimator Initial State

Built-in estimators start from a declared initial forecast—a prior estimate—or reuse suitable trained state. A new bucket uses a declared prior or shared estimator. A prior is not an observation and does not increase the number of real examples. The initial forecast may be evaluated against the first actual outcome and the component updated through the ordinary learning pipeline; its suitability for action is checked separately from whether it can be trained.

Preparation and reuse of initial models follow the [[Process Plane/Program Lifecycle and Evolution#Preparing Initial Models|general Program Lifecycle]]. The lack of training examples does not require an LLM call for every forecast.

If a meaningful initial forecast for the selected target is unavailable, create [[#LearningCredit and UnresolvedCredit|`UnresolvedCredit(target, missing_prediction)`]]; retain the experience for model selection or revision. Do not replace a missing forecast with a fictitious metric or create a `LearningSignal`. Training on accumulated data follows the [[#TrainingDataset|general path]], while model changes follow the [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]].

#### Budget and Review

Allocate resources according to the expected benefit of improving future decisions, including transfer to other tasks, and the cost of errors. Usage frequency is one factor, not the definition of importance: a rare, costly decision may justify a careful model, while a frequent, well-understood process may need little further training. Simple rules and available knowledge may be enough for a rare, low-impact task.

Compare expected benefit with the full cost of data acquisition, training, evaluation, future use, and storage within the [[Cognition and Attention#Execution Budgets|Task budgets]]. Estimating this benefit is itself budget-limited; an exact calculation before every update is unnecessary. Importance affects the budget and quality requirements, but does not increase the reliability or statistical weight of an observation.

Accept added complexity when a practically meaningful gain, confirmed on new cases, justifies the added costs. Training may be paused when quality is sufficient or further costs are not justified; the absence of discovered errors with little experience does not establish model quality.

During reflection, conscious analysis, structural revision, material errors, unexpected signals, or a change in process importance, consciousness may review the components, learning mode, and training volume, including whether to resume training. A missing forecast may also trigger this review; no numeric `prediction_unexpectedness` signal is required. A high signal alone does not justify unlimited spending. A separate periodic review of every paused component is not mandatory; choose checks for the specific process.

### `TrainingDataset`

(def_id:: entity.TrainingDataset)

> [!definition]
> **`TrainingDataset`** — a [[Datasets#^def-Dataset|Dataset]] for training; its version fixes the admissible experience and data-preparation rules for a compatible estimator or optimizer.
> ^def-TrainingDataset

The dataset makes it possible to retrain a model or train a new candidate on accumulated experience. A saved dataset is not required for updates from an observation, batch, or episode. Data preparation follows the model contract and the [[Datasets|general dataset rules]].

In the standard path, when a new candidate is trained, its own run is evaluated on selected experience. The resulting trace and [[Process Plane/Program Evaluation and Testing#EvaluationResult|`EvaluatedResult`]] let the [[#LearningCoordinator|shared learning pipeline]] assign credit to the relevant targets and train the candidate. Credit from the previous implementation is not automatically transferred to the new one merely because the target matches; repeated passes follow the [[#PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher|experience-accounting rules]].

For reproducible training, the trace retains links to versions of the data, preparation, and code; initial and resulting state; updater settings; and random seed, if applicable. Transfer to new cases is checked on [[Datasets#Training and Evaluation Boundaries|independent data]].

### `LearningCoordinator`

`LearningCoordinator` is a technical child program in a `Task` context. The calling program passes selected experience and a learning objective related to the task objective; the coordinator does not choose the task, run tests, or decide independently which Evaluations to perform. Required checks are completed before their results are passed to training.

For observations and evaluation results, the coordinator calls [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]] when they may provide epistemic evidence. This path does not require a checkable forecast. For a selected `EvaluatedResult` to train on, with outcome, metrics, and recoverable context, the coordinator creates a [[#^def-LearningSignal|`LearningSignal`]] and calls `CreditAssignmentProgram` for the relevant [[#^def-LearningTarget|`LearningTarget`]]. A forecast or a Task/process outcome may be evaluated. A completed evaluation is not rerun. The [[#PredictionEvaluator|missing-forecast branch]] creates `UnresolvedCredit` separately, without a fictitious evaluation or a `LearningSignal` for that forecast check.

When the mapping from outcome to target and the learning binding to an estimator or program parameters are defined by contract, credit assignment and update preparation are deterministic, including for batches. Thus, the standard pipeline updates means, frequencies, and bucket statistics without an LLM call for each example. Calling `predict(inputs)` and recording the value in the trace do not by themselves authorize an update. Ambiguous credit assignment and inability to prepare an update are distinguished by the rules below.

`EvidenceAssessmentProgram` and `CreditAssignmentProgram` are independent branches and do not call each other. Calling `EvidenceAssessmentProgram` does not transfer ownership of evidence assessment to the Learning System. `LearningCoordinator` does not itself assess evidence, assign learning credit, or change parameters.

Related experience is passed to assessment in a shared batch under the [[Uncertainty and Belief Tracking in the World Model#Assessment Lifecycle|call-grouping and budget rules]]. The evidence model itself and source-error models are trained through ordinary credit and parameter updates on [[Uncertainty and Belief Tracking in the World Model#Training the Evidence Model|independently resolved cases]]; there is no separate self-confirming belief path.

Given a `LearningCredit` and the program's declared bindings, `UpdatePlanner` selects the estimator or parameters to update, and retrieves original inputs and outcomes from evaluation and provenance. [[#^def-UpdateTransactionManager|`UpdateTransactionManager.apply`]] performs the prepared update in a shared transaction; `UpdateDispatcher` selects the updater under the chosen implementation's contract. The updater computes new state; the transaction manager saves it with an `UpdateReceipt`.

### Specialized Learning

For narrow tasks, a `SkillDevelopmentProgram` may call a specialized training subprogram, such as CFR / self-play implemented with NumPy or CUDA through Python. This is an additional path—an exception that requires strong justification—outside the standard `LearningCoordinator` pipeline. The subprogram manages internal iterations of a custom training pipeline, working state, and checkpoints without a separate `LearningCredit` for every step.

EverTree's primary approach is to develop and reuse programs and knowledge and train them through `LearningCoordinator`. Specialized training on a custom backend, such as a neural network, may be expensive and its results difficult to interpret. It may help solve a local task that needs a specialized training method, but is unlikely to improve the agent and will not help it generalize to other processes. Success on a narrow task alone does not establish transfer to other tasks; the gain must justify these limitations.

Checkpoints for resuming training and the exported strategy are saved as versioned [[Core data structures#^def-Artifact|Git Artifacts]], using Git LFS when needed, with provenance for the data, code, and settings. The candidate undergoes a separate [[Process Plane/Program Evaluation and Testing#EvaluationTestManager|Evaluation]] before use. Code changes or changes to a versioned artifact used by the program follow the [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]]; a trainer does not overwrite an active estimator state or Program parameters outside the standard update mechanism.

---
## Observable and Latent Claims

Compute direct [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] for an observable model prediction when observations not derived from that prediction are available and there is an adequate basis for calibration. Observations may depend on one another; account for these dependencies in evaluation.

```text
predicted observable state
+ observed state
→ direct prediction_unexpectedness.
```

Do not assign direct `prediction_unexpectedness` to a latent state. Its [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|evidence assessment]] relies on observable consequences and does not require that signal:

```text
latent state
→ observable prediction
→ observation
→ evidence assessment
→ indirect upstream evidence.
```

If a required public observable prediction is missing, trigger structural revision.

An internal anchored [[Core data structures#^def-Claim|`Claim`]] may be checked directly if an independent observation becomes available for it.

Expected signals are a standard special case of observable claims; their evaluation is described in [[#Expected Signal Updates]].

---
## Fast Learning

Fast learning processes experience selected for training after an evaluable event, a batch has accumulated, or a sub-episode has completed. Parameter updates follow the [[#Selecting Learnable Components and Learning Mode|selected mode]]; pausing parameter training does not prevent beliefs from being updated with new evidence.

It affects:

```text
observable claims with direct evidence;
latent states and operators on which those claims depended;
competing alternatives in the same CompetitionScope;
Program or policy components involved in the outcome.
```

A high [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] is a reason to investigate a surprising discrepancy, not a logical refutation of a model or proof of a regime change. An expected outcome is also evidence and may be used for learning; training data are not restricted to surprising cases.

Beliefs receive [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|`EvidenceAssignment`s]] through [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]]. Based on `LearningCredit` for a [[#^def-LearningTarget|`LearningTarget`]], the pipeline prepares permitted updates to specific implementations. Save `UnresolvedCredit` without a parameter update.

---
## Credit Assignment
#topic_core

The standard learning pipeline answers four distinct questions in sequence:

```text
what happened and how was it evaluated?
→ LearningSignal;

which LearningTarget and its use does the experience's training contribution concern?
→ LearningCredit;

which estimator or Program parameters should be updated, and how should the data be prepared?
→ PreparedUpdate;

how should the command be executed safely?
→ UpdateTransactionManager;
→ UpdateDispatcher selects the updater.
```

If a `PredictionTarget` was selected for forecasting in the current context but no forecast exists, create `UnresolvedCredit` with the known target and case context. This branch does not require a `LearningSignal`. If credit has been assigned to a target but a specific update cannot be prepared, return `UpdateBlocked`.

### `LearningSignal`

Fields and arguments in the learning pipeline contain objects under the [[Core data structures#Objects and References|general object and reference rule]].

(def_id:: entity.LearningSignal)
> [!definition]
> **`LearningSignal`** — a package of evaluated experience for one learning decision: observed outcomes, selected metrics, and an improvement objective. It is a data package, not a separate evaluation channel in [[Evaluative-Control System]].
> ^def-LearningSignal

```python
LearningSignal {
  evaluation: <EvaluatedResult>
  outcomes: <NonEmpty[Observation | Outcome]>
  metric_samples: <NonEmpty[MetricSample]>
  objective: <LearningObjective>
}
```

The fields answer:

```text
evaluation
→ the complete evaluation and its provenance;

outcomes
→ what actually happened;

metric_samples
→ how the result was measured;

objective
→ what should be improved.
```

Create [[#^def-LearningSignal|`LearningSignal`]] only from an `EvaluatedResult`. All of its outcomes and metrics must belong to the same evaluation. `NotApplicableResult` and `UnresolvedEvaluationResult` do not create a learning signal.

`LearningObjective` links the meaning of the objective to its metrics and direction:

```python
LearningObjective {
  source?: <Criterion | Utility>
  metrics: <NonEmpty[MetricDefinition]>
  direction: "minimize" | "maximize"
}
```

For example, an objective may require reducing mean squared error for a binary outcome probability `(p - y)²`, where `y ∈ {0, 1}`, or maximizing the share of successful decisions under the selected Evaluation criteria. [[Attribution Plane#^def-Criterion|`Criterion`]] or `Utility` may explain where the objective came from, but do not replace the learning objective themselves.

[[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] is a diagnostic assessment, not a minimization objective or gradient. The updater uses original inputs and outcomes under the estimator contract; its internal objective is aligned with the [[#Forecast Representation and Learning Objective|meaning of the forecast]]. Improvement is checked under the [[Process Plane/Program Evaluation and Testing#^prediction-quality-protocol|quality protocol]]; reducing unexpectedness alone does not count as improvement.

---
### `LearningCredit` and `UnresolvedCredit`

(def_id:: role.LearningTarget)
> [!definition]
> **`LearningTarget`** — the recipient of learning credit: an evaluated quantity or result, selected action or decision, participating mechanism, or inference used. For forecast training, this role is filled by [[Process Plane/Program Layer#^def-PredictionTarget|`PredictionTarget`]].
> ^def-LearningTarget

An existing Concept, Program, or Claim fills this role; a separate node or runtime class is not required.

`CreditAssignmentProgram` assigns credit to a selected `LearningTarget` in a specific experience context. For an evaluated case it receives a `LearningSignal` and uses related traces to find credit recipients. When a forecast is missing, it receives the known `PredictionTarget`, search context, and available observations without a `LearningSignal`. It returns `ProgramResult[CreditAssignmentResult[]]`.

```python
CreditAssignmentResult =
  LearningCredit {
    target: <LearningTarget>
    signal: <LearningSignal>
    attribution_weight?: <float in (0, 1]> = 1.0
    resolves?: <UnresolvedCredit>
  }

| UnresolvedCredit {
    target: <LearningTarget>
    observations?: <list[Observation | Outcome]>
    reason: "missing_prediction" | "ambiguous_attribution"
    signal?: <LearningSignal>
    missing_requirements?: <string[]>
}
```

**The target is known in both result branches.** `reason="missing_prediction"` applies only to a `PredictionTarget` selected for forecasting in the current context when no forecast was assigned. It records a forecasting gap; it does not create a numeric error assessment, `LearningSignal`, or parameter update for the missing forecast. Having a forecast does not guarantee `LearningCredit`: applicable Evaluation and enough data for a `LearningSignal` are required first. A learning update from an independently evaluated action outcome does not require a forecast of that action.

`context` stores references to the original case and search conditions, so the system can determine exactly where the forecast is missing. For completed `LearningCredit`, context is reconstructed from the `signal` and provenance of the `CreditAssignmentProgram` work: which target, use, or decision received credit and from which evaluated result. The original evaluation retains its own subject; credit assignment does not rewrite it. Matching Concepts does not merge distinct cases or models.

`LearningSignal`, `LearningCredit`, and `UnresolvedCredit` are immutable [[Memory#^def-OperatorOutput|`OperatorOutput`s]]. Their identity and provenance are provided by shared runtime; separate `id` and `created_at` fields are redundant.

`attribution_weight` is a nonnegative share of the learning signal assigned to a target in this context: `1.0` means the full contribution, `0.3` means 30%. It is not an error sign, gradient, parameter delta, probability of selecting an updater, or measure of proven causal influence. The `LearningObjective` defines direction; the updater computes new parameter values. The updater contract defines how to apply the weight.

If soft assignment among several targets is accepted, create separate `LearningCredit`s with explicit weights. If the contribution to a selected target remains ambiguous, create `UnresolvedCredit(reason="ambiguous_attribution")` with the original signal; defer the parameter update for this case. Do not replace uncertainty about the cause with arbitrary weights.

`UnresolvedCredit` retains the history. Once resolved, a new `LearningCredit` may reference it through `resolves`. Evaluate the original forecast, if found, in the ordinary way. If a new model was created instead, check its own run: a later forecast must not be presented as one that existed before the observation, and fitting on that outcome must not be presented as an independent evaluation.

[[#PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher|`UpdatePlanner`]] selects the address of mutable parameters from completed credit. Ambiguity in this technical selection returns `UpdateBlocked`, not `UnresolvedCredit`.

`CreditAssignmentProgram` does not create [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|`EvidenceAssignment`]], select an update formula, or change parameters. Provenance links credit to experience but by itself does not prove that participating mechanisms were responsible.

---
#### Credit for a Task or Process Outcome
^outcome-credit

The basis may be an evaluated intermediate or final outcome of a Task or process: success, constraint satisfaction, cost, or another selected quality. The result is represented by an ordinary `Outcome`; criteria, metrics, and the link to execution are retained in `EvaluatedResult`.

Consciousness, [[Memory#^def-MemoryConsolidationProgram|memory consolidation]], and [[Self#From Experience to a Confirmed Problem|Reflection]] may select experience and a learning objective, organize required checks, and pass their results to `LearningCoordinator`. `CreditAssignmentProgram` assigns credit.

Using traces, the program searches for decisions, actions, inferences, and mechanisms that may have contributed. For example, choosing X instead of the usual Y or inferring a cause of difficulty may have changed how work proceeded. An explanation of influence is represented as a [[Core data structures#^def-Claim|`Claim`]] with its grounds and applicability limits; its reliability and the truth of an inference are assessed separately through the Belief System from the usefulness of applying it. A successful Task does not by itself confirm a causal hypothesis or prove that every inference used was true.

An observed outcome for X is not an outcome for an unchosen Y. A claim that X is better requires comparable experience, a check of the alternative, or an explicitly labeled model counterfactual under the [[Self#From a Problem to a Change Hypothesis|Self rules]]. Ordinary policy learning from a trajectory is still allowed under the optimizer contract without proving the exact causal contribution of every step.

If the credit recipient has not yet been found, retain a question or hypothesis for later analysis. Inferences may be saved as knowledge; a change to code or the solution method goes through [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]]. Reanalysis of experience by consolidation and Reflection follows the [[#PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher|shared experience-accounting rules]].

### PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher

`UpdatePlanner` selects a specific estimator or Program parameters based on the `LearningTarget`, attributed application, source context, and `LearningObjective`. It uses the learning bindings declared by the program and the provenance of the credit and evaluation; a matching target alone does not authorize updating every implementation of that Concept. It then checks the contract of the selected state and prepares an update:

```python
UpdatePlanner.prepare(
  credit: LearningCredit
) -> UpdatePlanningResult

UpdatePlanningResult =
  PreparedUpdate {
    source_credit: <LearningCredit>
    state: <reference to estimator state or Program parameters>
    updater_input: <input for the selected updater>
  }

| UpdateBlocked {
    source_credit: <LearningCredit>
    reason: "no_learning_binding"
          | "ambiguous_learning_binding"
          | "incompatible_updater_contract"
          | "unsupported_signal"
          | "already_accounted"
  }
```

Field meanings:

```text
source_credit
→ why this update is authorized;

state
→ reference to the estimator state or Program parameters being updated;

updater_input
→ experience and update settings in the format expected by a specific estimator or optimizer.
```

For example, credit for `NetChipChange` may train an estimator when the objective is to estimate winnings, or train policy parameters when the objective is to improve action selection. The binding must explicitly specify the corresponding update. A policy does not need its own forecast: an applicable evaluation of its actions is enough. The absence of a required forecast remains a separate `UnresolvedCredit` and does not invalidate that evaluation.

`PreparedUpdate.state` is a stable reference to a specific estimator state instance or to the Program parameters held by their owner. It may address a consistent parameter block for atomic updating; it is not a `PredictionTarget` or process input state. The prepared request fixes the address: a retry does not select a model again from the target. Several anchors may use shared state, and one target may use different estimators; the program defines these relationships and connects them to its semantics through anchors.

The updater computes the new state from the current parameters within a protected runtime operation. The version of the state used for the original prediction is retained in the trace and does not change after learning.

`PreparedUpdate` represents one authorized application of `LearningCredit`; it may include a batch and several internal optimizer steps when the updater contract permits them. A request to cancel or reduce an already accounted contribution is:

```python
CreditRetraction {
  credit: <LearningCredit>
  state: <reference to estimator state or Program parameters>
}
```

`PreparedUpdate` and `CreditRetraction` are immutable [[Memory#^def-OperatorOutput|`OperatorOutput`]]. The runtime provides a stable identity for each request, representing one specific intentional call to the corresponding method.

For `retract`, the state address and accounted contributions are recovered from the updates actually applied, their receipts, and the ledger. A changed binding from the target to a new model does not redirect a correction intended for the old state to the new model.

```text
new intentional call
→ new request object
→ new identity;

retry of the same call after a failure
→ same identity, including after loading the request from memory.
```

A `LearningCredit` is usually applied to a selected state once; multiple updates from it are allowed only under an explicit learning contract. Before preparing an update, `UpdatePlanner` checks the algorithm contract and the provenance of the inputs and outcome to determine whether the same logical contribution has already been accounted for. One outcome may update different addressed states or provide multiple examples required by the algorithm for different inputs to one estimator or Program, for example from decision points in a single hand. Dependencies between such examples are tracked; they do not become independent observations. Re-evaluating or replaying the same example does not create independent experience, even if the evaluation and credit have new identities.

Several internal optimizer steps may form one `PreparedUpdate`. Separate requests are created when the algorithm explicitly requires each step to be applied and saved independently. Reusing credit must be permitted by the contract; it does not increase the number of independent observations or the amount of data supporting the model. A corrected outcome is handled under the [[#Correcting Experience Already Used|experience correction rules]]. Protection against accounting for experience twice complements the transactional protection against retrying one request.

Examples of `updater_input`:

```text
Beta / Bernoulli estimator
→ observed category + attribution weight;

numeric estimator
→ observed value + context + attribution weight;

threshold optimizer
→ features + actual outcome + objective + attribution weight;

policy updater
→ action + realized outcome or advantage + attribution weight.
```

(def_id:: entity.UpdateTransactionManager)
> [!definition]
> **[[#^def-UpdateTransactionManager|UpdateTransactionManager]]** is the shared infrastructure boundary for executing parameter updates in the standard learning pipeline:
> ^def-UpdateTransactionManager

```python
UpdateTransactionManager.apply(
  update: PreparedUpdate
) -> UpdateReceipt

UpdateTransactionManager.retract(
  retraction: CreditRetraction
) -> UpdateReceipt

UpdateReceipt {
  request: <PreparedUpdate | CreditRetraction>
  status: "applied" | "retracted" | "adjusted" | "skipped" | "rejected"
  reason?: <string>
}
```

`retracted` means the contribution was exactly undone within the updater contract; `adjusted` means it was approximately corrected; `skipped` means no change was made, with a reason such as unsupported `retract`. `rejected` means the request was invalid. An empty `retract` implementation is allowed, but its result is recorded as `skipped`.

Both methods use the same transaction pattern. A stable request identity distinguishes a new intentional call from a retry; field equality and Python `id()` are not used for this:

```text
begin transaction
→ check whether an UpdateReceipt exists for the request identity
→ check whether the logical outcome contribution is admissible:
  prevent duplicate accounting; allow optimizer steps specified by the contract
→ read current values through the state reference
→ UpdateDispatcher selects an updater
→ call updater.apply or a supported updater.retract
→ atomically save state (if changed), contribution accounting, and UpdateReceipt[request identity]
→ commit
```

If an exception occurs before `commit`, the transaction rolls back automatically: the new state, accounting changes, and receipt are not saved. If the call has already committed, a retry with the same request identity finds and returns the saved receipt without changing the parameters again.

The runtime serializes operations on one state: the protected region covers reading current parameters, calculating, and applying the result, including preparation that depends on current parameters. A write queue alone is not enough. If calculation happens outside this region, the runtime checks that the state used is still current before applying the result and recalculates when needed. This is an internal runtime guarantee; the shared learning interface does not need a separate revision field. Replacing state with a trained candidate uses the same boundary.

The transaction's check of logical contributions is authoritative: two different requests prepared before the first commit must not account for the same learning contribution twice in one state, including when reached through different anchors. Accounting is saved atomically with the state and reflects the actual correction result. Optimizer steps repeated for one credit are allowed when the algorithm specifies them; a new credit for the same experience does not by itself authorize this.

In the MVP this means atomic changes in core, not immediate persistence to disk. Updatable states, logical contribution accounting, and receipts are included in the [[Cognition and Attention#^agent-backup|shared agent backup]] and roll back together on recovery. Learning lost in a failure can be repeated from the recovered state.

An updater does not persist its own state, implement transaction rollback, or handle retries. Its methods compute a new state from the current state and corresponding request, and report the operation result. `UpdateDispatcher` likewise does not assign credit or change state; it only selects an updater according to the addressed state's contract. `apply` is required; support for `retract` follows the [[#Correcting Experience Already Used|rules below]].

Ordinary parameter updaters must not have external, non-transactional side effects. If state cannot be stored and changed through shared transaction-capable storage, it needs a special lifecycle with compensation instead of an ordinary automatic parameter update.

If a learning binding is absent or ambiguous, the contract is incompatible, the updater cannot accept the signal, or the contribution was already accounted for without permission to repeat an optimizer step, `UpdatePlanner` returns `UpdateBlocked` with the corresponding reason. Parameters do not change; semantic credit remains assigned. If an inadmissible repeat is detected only inside the transaction, it returns an `UpdateReceipt` with status `rejected` and reason `already_accounted`. A retry of that same request still returns its previously saved receipt.

```text
UnresolvedCredit
→ retain / analyze / resolve again later;
→ never pass to UpdatePlanner or UpdateTransactionManager;

LearningCredit
→ UpdatePlanner;
→ PreparedUpdate;
→ UpdateTransactionManager.apply;
→ UpdateDispatcher;
→ updater;
→ atomic parameter update + UpdateReceipt.
```

#### Correcting Experience Already Used

`retract` is optional. Its contract specifies precision, scope, and required data:

- **Exact reversal**, when it is straightforward to implement; for example, removing a contribution from an accumulator's sum and count.
- **Approximate correction**, when exact reversal is difficult but there is a justified way to reduce the erroneous influence. Full removal is not guaranteed; the effect is checked in proportion to the importance of the correction.
- **Unsupported**, when implementation, storage, or execution costs exceed the expected benefit. The method may be absent or may return without changing state.

Even an exact reversal applies only to the specified state and declared algorithm. It does not undo actions already taken, observations received afterward, or learning by other programs. Subtracting an old gradient after subsequent updates usually does not restore the state that would have resulted without the erroneous example: later gradients may have depended on it.

Accounting distinguishes recognizing an outcome as wrong from removing its effect on parameters. The original credit, its applications, and correction results are retained; approximate correction or skipping does not mark the contribution as fully removed. A corrected outcome does not become a new independent example. Additional learning from it is allowed as an explicit correction that accounts for the previous contribution; the original erroneous example is no longer used as correct.

The program managing learning chooses the correction method based on the error's influence, future use of the model, and cost. Rare or expensive experience makes correction more valuable because one example may strongly affect the model. It is acceptable to leave a small residual influence with a recorded limitation; lack of `retract` does not require structural revision.

When the benefit justifies the cost, a learning subprogram may recompute statistics or retrain a candidate on corrected [[#TrainingDataset|experience]] through the standard learning pipeline, then verify the result before replacing the state. No separate universal type or rebuild method is needed. Exact recomputation is possible only if the necessary data, initial state, ordering, and training settings have been retained.

---
---

### Parameter Update Examples

#topic_details

```text
unfair coin outcome
→ LearningSignal: observed side + (p - y)² metric + probability-estimation objective
→ LearningCredit: target = CoinSide, weight = 1.0
→ UpdatePlanner: select the source estimator through the program binding
→ PreparedUpdate: state = estimator state, updater_input = Bernoulli sample
→ UpdateTransactionManager.apply
→ UpdateDispatcher
→ FrequencyEstimator with Beta / Bernoulli state
→ updated α, β, and process probability p;

ProgramRun with branch x > threshold + evaluated outcome
→ LearningSignal: actual outcome + metric + objective
→ LearningCredit: target = evaluated process result, weight = 1.0
→ UpdatePlanner: select threshold through its declared learning binding
→ PreparedUpdate: state = threshold for a specific Program, updater_input = features + actual outcome
→ UpdateTransactionManager.apply
→ UpdateDispatcher
→ ThresholdOptimizer
→ updated threshold;

known PredictionTarget, but no prediction was assigned to it
→ UnresolvedCredit(target, context, reason="missing_prediction")
→ retain and pass to Attention; no LearningSignal;

LearningCredit assigned to a target, but no unambiguous update binding:
threshold or upstream estimator
→ UpdateBlocked(reason="ambiguous_learning_binding")
→ leave parameters unchanged.
```

In the first case, `p` is a model value parameter, not epistemic `Strength`. In the second, the threshold is an optimized parameter, not an unknown truth about the world. If no threshold removes a persistent mismatch, `LearningCoordinator` passes the case to slow structural learning.

The same evaluated outcome may independently provide an [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|`EvidenceAssignment`]] about model correctness through [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]]; this does not replace `LearningCredit` for its parameters.

---

## Sub-Episodes

A long [[Memory#^def-ProgramRun|`ProgramRun`]] is divided into local sub-episodes when it contains independently predictable outcomes:

```text
significant intermediate state;
change in a signal channel;
process transition that occurs or does not occur;
local decision;
and so on.
```

```text
local prediction
+ local outcome
→ local evaluation
→ local credit assignment
→ local updates.
```

This shortens the dependency path and helps connect credit to the right target and a specific decision within a long process.

## Slow Structural Learning

If local updates do not explain a persistent mismatch, slow structural analysis is started and may lead to structural revision. Conscious review may also happen during Reflection or after significant new experience, without a prior series of parameter updates; [[#Selecting Learnable Components and Learning Mode|component selection and learning mode]] are reconsidered together with the program. When investigating a cause, check local mechanisms first; the same error in several independent applications provides grounds to check a shared upstream mechanism if local explanations are insufficient.

Main triggers:

One trigger is [[Evaluative-Control System#^def-ExplanatoryTension|`ExplanatoryTension`]] remaining elevated on new observations after parameter updates, compared with a comparable history.

```text
high prediction_unexpectedness occurs more often than the sequential-check rule allows;
a new process regime;
reliable evidence against a model with high Support;
ExplanatoryTension remains elevated on new comparable observations;
regression in Evaluation.
```

Slow analysis may identify:

```text
missing factor or CONDITION;
incorrect context scope;
a new process regime;
incomplete output contract;
unsuitable predictor structure;
an incorrect Program.
```

The result is passed to `Program Lifecycle and Evolution`; the initial form of a structural hypothesis may be a [[Core data structures#^def-Note|Note]] or [[Core data structures#^def-Claim|Claim]]:

```text
Note / Claim
→ reasoning / elaboration
→ semantic change / parameter update / Prompt revision / ProgramBranch / new Program / EvaluationCase
→ Evaluation
→ EvaluationChoice.
```

Reasoning may set an initial prior, but not `Support`; activating a new Claim or making a structural change requires subsequent evidence.

---

## Expected Signal Updates

Forecasts of evaluative signals are checked at the level of a specific [[Memory#^def-ProgramRun|`ProgramRun`]], only for channels the program actually predicted. Their composition and how they are obtained are determined during [[#Selecting Learnable Components and Learning Mode|component selection]], not added for every signal on every run. The original forecast and final assessment are compared under the shared [[#PredictionEvaluator|`PredictionEvaluator`]] rules; matching the channel alone is not sufficient:

```text
saved forecast of a channel value or distribution
+ received assessment for the same channel
→ EvaluationResult with applicable metrics,
  including prediction_unexpectedness when there are grounds for calibration.
```

[[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssessmentProgram|`EvidenceAssessmentProgram`]] creates evidence about belief in the correctness of a signal model. `CreditAssignmentProgram` assigns credit to the corresponding PredictionTarget; `UpdatePlanner` then selects an estimator or policy parameters based on context and learning objective.

The way expected signals are computed is internal to the program. Examples include:

```text
domain model or simulation;
a fixed value or learnable scalar V;
linear Ax+b;
categorical OutcomeProfile;
another model-specific estimator.
```

A universal `PredictorState` is not created for every signal. Only a learnable component designated for training in this case receives a parameter update; divergence from a fixed forecast may instead be grounds for revising the program.

For [[Evaluative-Control System#^def-SupervisorFeedbackSignal|`supervisor_feedback_signal`]], the numeric forecast and its check concern `value`. An optional `comment` retains the explanation for the feedback and may help with analysis and credit assignment; its text is not substituted for the numeric outcome.

Point models `V` and `Ax+b` can be evaluated and trained using suitable [[Process Plane/Program Evaluation and Testing#^def-PredictionError|`prediction_error`]] metrics without `prediction_unexpectedness`; that signal also requires a distribution of expected deviations under the [[Evaluative-Control System#^def-PredictionUnexpectedness|shared contract]].

The target, learning objective, and update binding are distinct:

```text
incorrect forecast of a domain outcome
→ credit for that outcome's target
→ train the world/process-model estimator;

correct forecast of the domain outcome,
but incorrect expected signal
→ credit for the signal's target
→ train the signal estimator;

correct predictions,
but a poor choice
→ credit for the evaluated action outcome
→ train the policy or its utility estimator under the relevant objective.
```

---

## Prediction and Observation

#topic_details

Predictions and observations are different kinds of experience and are retained separately.

A model `Program` returns a prediction in `result` of the shared [[Process Plane/Program Layer#^def-ProgramResult|`ProgramResult[T]`]]: a numeric estimate, predicted state, `Profile`, or `OutcomeProfile`. Runtime saves `ProgramResult` in `TraceEvent.output`; a prediction reference addresses `result` or the relevant semantic part. An anchored operator that is not a `Program` saves its own typed [[Memory#^def-OperatorOutput|`OperatorOutput`]]. [[Memory#^def-SemanticTrace|`SemanticTrace`]] references the source event and is part of memory. A Python variable may reference the same prediction; no separate working-state object is needed to store it.

A predicted state may be represented by a local [[Core data structures#^def-Facet|`Facet`]] inside [[Memory#^def-SemanticTrace|`SemanticTrace`]], but does not become an ordinary object state in the persistent graph.

To find a prediction during a later check, materialize a fact about the prediction in the graph:

```text
PREDICTS(
  model_run,
  subject,
  prediction_target,
  predicted_value_or_profile,
  valid_at,
  conditions?
)
```

`prediction_target` references the [[Process Plane/Program Layer#^def-PredictionTarget|Concept being predicted]]: a property, state, event, or signal. `subject` specifies the object the prediction concerns.

`PREDICTS` remains an immutable record of what the model expected at prediction time. Its [[Memory#^def-ResultProvenance|provenance]] leads to the source result in the trace. It is not recomputed after the model is trained. Memory retains the prediction and required context while they are needed for checking or learning.

[[#^def-PredictionEvaluator|`PredictionEvaluator`]] performs shared prediction search and assembly of related observations through memory and the graph; the DBOS journal is used to restore execution.

[[Memory#^def-Observation|An observation]] is saved as a typed perception result. To include an observed state in the persistent world model, use the ordinary materialization path when needed:

```text
Source → PerceptionOperator → observation in trace
→ when needed: GraphDelta
→ persistent Facet
```

An observed state is not treated as absolutely true. Its reliability is expressed through `Strength` and `Support`.

### PredictionEvaluator

(def_id:: entity.PredictionEvaluator)
> [!definition]
> **PredictionEvaluator** is a shared [[Process Plane/Program Layer#Program|Program]] that finds saved predictions, gathers related observations, and checks each prediction using selected metrics. It returns `ProgramResult[EvaluationResult[]]`, with one [[Process Plane/Program Evaluation and Testing#EvaluationResult|EvaluationResult]] per checked prediction in `result`. For a selected PredictionTarget with no assigned prediction, it calls `CreditAssignmentProgram` to retain `UnresolvedCredit`. It processes unmatched experience according to prior decisions about whether a prediction is needed and passes cases requiring analysis to consciousness.
> ^def-PredictionEvaluator

The task or process program passes it new observations, the evaluation context (selected process, object, and episode), and metrics. Three functions run inside `PredictionEvaluator`:

1. **`match_predictions(observations, context)`** finds source predictions in memory through `PREDICTS` and provenance. For each prediction, it gathers new and previously saved observations related by object, PredictionTarget, episode, time, and conditions. It returns prediction-observation sets and observations with no match. One prediction may require multiple observations; one observation may relate to several predictions. If a compound observation is only partially matched, the unmatched portion is identified and a reference to the complete source observation is retained.
2. **`evaluate_prediction(prediction, observations, metrics)`** checks whether the prediction applies and the observations are sufficient, computes metrics, and returns `EvaluationResult`.
3. **`handle_unmatched_observations(observations, context)`** prepares source observations, the selected process program, current episode, and prediction-search results from memory and trace. If a target was selected for prediction in this context but no prediction was assigned or found, it calls `CreditAssignmentProgram` with the known target and context, retaining `UnresolvedCredit(reason="missing_prediction")` without a `LearningSignal`. If no target has been selected or prediction was deemed unnecessary in this context, it accounts for the corresponding saved decision. Unresolved credits, new cases, and grounds for reconsidering prior decisions are passed through [[Cognition and Attention|Attention]] for review within a `Task`.

`PredictionEvaluator` calls `evaluate_prediction` for matched predictions and `handle_unmatched_observations` for remaining observations or unmatched parts. A missing prediction does not create a numeric `prediction_unexpectedness`, a fictitious Evaluation, or a `LearningSignal`; `UnresolvedCredit` records an unfinished case for a selected target. Not every observed Concept needs a prediction. If the calling program already has the prediction and related observations, it can call `evaluate_prediction` directly without searching.

The decision not to model a particular signal in a context is retained with its reason and scope. If the same case recurs without new grounds, reuse that decision without another conscious review. A case outside that scope or a material change in process usage frequency, importance, or feedback requires reconsideration. Declining to predict does not remove the need to respond to the observation itself. A decision cannot excuse the absence of a prediction required by contract.

Every case passed to Attention requires conscious review. Review may be deferred; related cases may be considered together. In interactive mode, consciousness may review the prepared context immediately.

Failure to find a prediction does not by itself prove that the model is incomplete. [[Cognition and Attention#^def-Consciousness|Consciousness]] investigates the cause: the program does not account for important behavior; an intended prediction was not produced or found; the observation was assigned to the wrong process; or no prediction was required. When a gap is confirmed, consciousness starts structural revision through [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]].

For example, supervisor feedback may reveal a useful missing prediction. Consciousness determines which decision the feedback concerns and where a prediction would help: task selection, action selection, or a specific branch. It may then connect an existing model or add a local predictor with a selected learning mode. Feedback by itself does not require a new regressor: dissatisfaction that the agent is playing poker instead of completing a task may concern activity selection, not the poker-action model.

If the need for a new component is discovered during credit assignment, it is also passed for program review. The evaluator and credit assignment do not add predictors themselves. The change goes through Program Lifecycle; after activation, further learning follows the currently selected mode. Saved observations may be used for initial candidate training, but a prediction made afterward is not treated as one that existed before those observations.

`match_predictions`, `evaluate_prediction`, and `handle_unmatched_observations` are functions of one program, not separate `Program` instances. Matching data and passing unmatched experience for review belong to `PredictionEvaluator`, so process programs do not each implement these steps.

```python
PredictionEvaluator.evaluate_prediction(
    prediction: T,
    observations: tuple[OperatorOutput, ...],
    metrics: tuple[MetricDefinition, ...],
) -> EvaluationResult
```

`prediction` is the domain payload of the saved source prediction; `T` is specified by the model contract. For a `Program` result, it is the value from `ProgramResult.result` with provenance to the corresponding part of the original output; for an ordinary anchored operator, it is that operator's typed result. Typed observations and their semantic projections are matched to the prediction by object, time, and conditions, accounting for source independence and reliability. The specific check accepts suitable domain schemas. `evaluate_prediction` does not run or change the model; training, credit assignment, and error explanation are separate.

For [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]], the evaluator uses the saved prediction and a checking rule under the shared signal contract. If there is no supported way to specify a distribution of expected deviations, or the calculation is not worth its cost, the signal is not computed. This does not invalidate other available metrics: skip reasons and status follow the [[Process Plane/Program Evaluation and Testing#EvaluationResult|shared `EvaluationResult` contract]].

`PredictionEvaluator` returns check results to the caller in `ProgramResult.result` and saves them in the trace with references to predictions and observations used. `UnresolvedCredit` is saved separately as a typed result from a child `CreditAssignmentProgram` and is not included in `EvaluationResult[]`. The calling program decides which check results to pass to [[#LearningCoordinator|`LearningCoordinator`]] for learning within the task.

(def_id:: entity.PredictionEvaluationRun)
> [!definition]
> **PredictionEvaluationRun** is a run of [[#^def-PredictionEvaluator|PredictionEvaluator]] that checks saved predictions against observations and handles unmatched experience. Its `ProgramResult.result` contains a separate [[Process Plane/Program Evaluation and Testing#EvaluationResult|EvaluationResult]] for every prediction checked.
> ^def-PredictionEvaluationRun

Statuses and metric skip reasons follow the [[Process Plane/Program Evaluation and Testing#EvaluationResult|shared `EvaluationResult` contract]]. With `evaluated`, at least one selected metric has been calculated; `prediction_unexpectedness` is included only if it was calculated:

```text
PredictionEvaluationRun
→ EvaluationResult for each prediction
  → NonEmpty[MetricSample]
→ if selected for learning: LearningCoordinator
  → LearningSignal
```

`NotApplicableResult` and `UnresolvedEvaluationResult` are retained as evaluation history but do not create [[#^def-LearningSignal|`LearningSignal`]].

A probabilistic prediction does not receive a binary “confirmed” or “refuted” label. An observation is new evidence, while a metric indicates how well the outcome matched an epistemic [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]] over competing alternatives or an [[Uncertainty and Belief Tracking in the World Model#Probabilistic Process Outcomes|`OutcomeProfile`]] for a stochastic process. These representations are not interchangeable.

If a more complete or corrected observation appears later, create a new [[#^def-PredictionEvaluationRun|`PredictionEvaluationRun`]]. Retain the original prediction and earlier evaluations as history.

### Hypotheses

Record hypotheses through the relation:

```python
HYPOTHESIZES(
  reasoning_run,
  proposed_fact,
  valid_at,
  created_at
)
```

Memory therefore stores these separately:

```text
what the model expected;
the conditions under which the prediction was made;
what was observed;
whether the prediction could be checked;
how well the observation matched the prediction;
how the result affected the model.
```

---

## Runtime Integration, Simplified

The calling program owns the launch of checks and the selection of experience for learning within a `Task`. Observations may enter the coordinator's evidence path without Evaluation.

The diagram below shows the prediction path; [[#^outcome-credit|Evaluation of Task or process outcomes]] also reaches the shared `LearningCoordinator`.

```text
ProgramRun
        ↓
prediction / epistemic Profile / OutcomeProfile / expected signals
        ↓
Observation
        ↓
PredictionEvaluator
        └─ match_predictions
             ├─ matches found → evaluate_prediction → EvaluationResult
             └─ observations without prediction → handle_unmatched_observations
                  ├─ selected PredictionTarget → CreditAssignmentProgram
                  │   → UnresolvedCredit(target, missing_prediction)
                  │   → retain → Attention; no LearningSignal or parameter update
                  └─ other cases → apply prior decision;
                      cases needing review → Attention → consciousness

EvaluationResult selected for learning
        ↓
LearningCoordinator
        ├─→ EvidenceAssessmentProgram
        │   → EvidenceAssignment[]
        │   → Evidence lifecycle
        │
        └─→ LearningSignal, only for EvaluatedResult
            → CreditAssignmentProgram: assign credit to LearningTarget
            → CreditAssignmentResult[]
              ├─→ UnresolvedCredit(target, ambiguous_attribution)
              │   → store / analyze
              │   → no parameter update
              │
              └─→ LearningCredit(target, signal)
                  → UpdatePlanner: select estimator or Program parameters
                  → PreparedUpdate
                  → UpdateTransactionManager.apply
                  → UpdateDispatcher
                  → updater under the state's contract
                  → atomic commit: updated parameter state + UpdateReceipt

if mismatch remains unexplained:
        ↓
slow structural analysis
        ↓
Program Lifecycle and Evaluation
```

---
