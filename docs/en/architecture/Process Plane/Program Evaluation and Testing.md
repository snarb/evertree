## Program Evaluation and Testing
^Evaluation and Testing

This section describes quantitative evaluation of programs and qualitative checks that they meet requirements. New real-world events are not Evaluation tests by themselves; checking predictions against them uses the shared [[#EvaluationResult|`EvaluationResult`]]. Saved experience becomes an evaluation case after a scenario and scoring rule have been prepared.

## Types of Testing

### Program Tests (Qualitative)

The agent writes tests for a given program (unit, behavioral, adversarial, property-based, smoke, and other suitable test types), runs them immediately, and revises the program and tests as needed, debugging or rewriting them. This is the standard developer workflow.

`ProgramTestManager` is the module responsible for testing Programs. By default, it is the Codex agent with its internal decision-making; it is gradually improved and expanded like other modules. These tests are not used to compare programs or select candidates. They are tools for creating candidate hypotheses and preventing regressions as programs change.

### Evaluation (Quantitative)

**Evaluation** is a system for quantitatively checking models, programs, policies, and process hypotheses.

Evaluation tests return metrics, including metrics for the evaluative channels in [[Evaluative-Control System]], and are used to compare, select, reject, or continue checking candidates.

Candidates are compared using quality metrics declared in advance. [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] measures how unusual a discrepancy is relative to a saved prediction, but it is not an independent measure of model quality: reducing it, including by widening predicted dispersion, is not by itself an improvement.

#### Prediction Quality Metrics
^prediction-quality-metrics

(def_id:: metric.PredictionError)
> [!definition] **prediction_error** — the error of a particular prediction under a selected metric, such as directional deviation, absolute or squared error, or probabilistic prediction loss. The metric defines its formula, meaning of values, scale, units, and aggregation rules. No common scale or mandatory calibration is assumed.
^def-PredictionError

This is a general concept, not a separate required field or channel: [[#EvaluationResult|`MetricSample`]] specifies the particular `metric` and its `value`. Calibrated unusualness of a discrepancy is evaluated separately as [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]].

Let `q(y | c)` be the model prediction, `y` the outcome being checked, and `c` the features, necessary history, and prediction horizon available before the outcome. A **loss function** `S(q, y)` defines how to evaluate the prediction: lower values are better. Choose it based on the output's meaning and the decisions it supports; [[Learning system|Learning System]] defines the corresponding learning method.

For probabilistic predictions, use a **proper scoring rule**: for any true distribution `p` in the rule's domain, expected loss is minimized at `q = p`. **Strictly proper** means that this is the unique optimum as a distribution, though not necessarily as a parameter set. If the entire claimed distribution must be checked, use a strictly proper rule for the corresponding class of distributions. [Definitions and applicability](https://arxiv.org/html/2504.01781v4).

Common options:

- **Log loss:** `S(q, y) = −ln q(y | c)`. For categories, `q(y | c)` is the probability of the outcome; its negative logarithm is also called the outcome's **surprisal**. The mean loss is the mean negative log-likelihood (**NLL**), or cross-entropy for categorical labels.
- For a continuous outcome, log loss uses a **density with respect to a measure shared by the models being compared**, not the probability of an individual point. Its value may be negative and depends on units; it does not define a universal unusualness scale across processes. Zero probability or density for the observed outcome gives infinite loss.
- **Brier:** for a binary outcome `y ∈ {0, 1}` and event probability `r`, the score is `(r − y)²`. For categories it is `Σₖ(qₖ − 1{y=k})²`, where `qₖ` is the probability of category `k`, and the indicator is 1 for a matching category and 0 otherwise. Fix normalization before comparison.
- **CRPS** for a one-dimensional numerical distribution with a finite first absolute moment: `E|X − y| − ½E|X − X′|`, where `X, X′` are independent draws from predictive distribution `q`. The score has the same units as the outcome. [Formula and conditions](https://arxiv.org/html/2504.01781v4#S2.SS1).

A proper loss points in the right direction **in expectation**, but does not guarantee that a trained model is calibrated. The true distribution may not be expressible within the chosen parameterized class; in that case, choose the best available approximation. Limited data and optimization errors remain; minimizing training cross-entropy may still produce overconfidence on new data. Different proper losses may rank imperfect models differently. [Neural network calibration](https://proceedings.mlr.press/v70/guo17a.html).

A high surprisal for one outcome does not prove a model defect: an event with a correctly predicted 1% probability is still surprising. Mean NLL evaluates predictions over a series of outcomes but includes the process's inherent randomness. Neither raw surprisal nor mean NLL is the same as [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]].

**Check point-prediction error and the outcome of using a prediction separately** when they matter to the task. For a point prediction `a`, squared loss `(y − a)²` targets the mean, absolute loss `|y − a|` targets the median. Quantile loss `u(τ − 1{u < 0})`, where `u = y − a` and `0 < τ < 1`, targets the quantile at level `τ`. Finite expected squared loss requires a finite second moment of the outcome; absolute and quantile loss require a finite first absolute moment. The best available distribution under one score need not give the best result under every application metric. Choosing a representation and deriving point estimates from a distribution are described in [[Learning system#Forecast Representation and Learning Objective]]. [Evaluating point predictions](https://arxiv.org/abs/0912.0902).

#### Calibration, Sharpness, and Distinguishing Contexts
^prediction-calibration-sharpness

[[Uncertainty and Belief Tracking in the World Model#^def-Calibration|Calibration]] is checked for probabilistic claims that matter. For prediction intervals, check coverage — the proportion of outcomes inside the interval — relative to the stated level, accounting for discreteness and intended conservatism. A sample estimates agreement with uncertainty; it does not prove exact calibration.

**Sharpness** is the concentration of a predictive distribution. Prefer a more specific prediction while retaining justified calibration. Specificity is improved by using helpful information, accounting for regimes, and correcting systematic errors. A properly broad distribution for a genuinely noisy process is not a defect. [Calibration and sharpness](https://arxiv.org/abs/1106.1638).

**Resolution** is the ability to distinguish situations with different outcome distributions. It is not the same as concentration: a model that always predicts 50% may be calibrated to the overall frequency but fail to distinguish two equally common contexts with probabilities of 20% and 80%. Therefore, check contexts material to use, not only overall calibration. [Score diagnostics and decomposition](https://arxiv.org/abs/2008.03033).

An improved proper score does not guarantee separate improvement in calibration, sharpness, or every application metric. Diagnose them in proportion to the task and data. Do not add arbitrary rewards for confidence, low entropy, or narrow intervals: this encourages unjustified narrowing. Nor should widening a distribution count as improvement solely because it reduced an unusualness signal.

Introduce a separate calibrator — a learnable transformation of predictions used to correct calibration — only when need is confirmed and sufficient data are available. Fit it and perform its final check on different data; evaluate its gains together with other material prediction properties.

#### Prediction Evaluation Protocol
^prediction-quality-protocol

The following rules apply to both saved tests and evaluation of new real-world outcomes. A real-world outcome does not thereby become an Evaluation test.

- **Define the task in advance:** outcomes to check, information available at prediction time, horizon, metrics, application contexts, and rules for selecting and weighting cases. For related variables or sequences, check material dependencies; correct marginal frequencies do not establish a correct joint distribution.
- **Preserve the meaning of evaluated probabilities:** the sample and weights must represent the target process or correct a known selection bias. Arbitrarily increasing the weight of certain outcomes usually changes optimal probabilities even under proper loss; declaring weights in advance is not enough. Evaluate the practical cost of such outcomes separately or explicitly define a different prediction task.
- **Save the prediction first, then evaluate the outcome, then update the model.** In prequential evaluation, an evaluated observation may be used for later predictions. This applies to real experience and isolated [[#^evaluation-modes|evaluation of learning ability]]; learning is disabled when evaluating a ready-made model.
- **Check the required transfer:** to future observations, new objects, or new groups, depending on how the model will be used. For a temporal process, random shuffling does not replace testing on future data; for new objects, dependent examples of one object must not leak between training and final evaluation. [Data-splitting protocols](https://scikit-learn.org/stable/modules/cross_validation.html).
- **Compare with a simple baseline or previous version on the same new cases**, unavailable when the corresponding predictions were fitted. When checking adaptation, fix each candidate's data access and update rules in advance. Evaluate the size and uncertainty of the gain, accounting for dependencies between observations.
- **Separate tuning from final evaluation:** do not use final outcomes to choose the model, hyperparameters, or calibrator. Repeated tuning on one evaluation set turns it into tuning data; a final conclusion requires new evidence.
- **Report data volume and freshness, covered contexts, assumptions, and evaluation uncertainty.** An old result does not establish quality in a new regime. No errors found with little experience does not mean the model is good; equal results for candidates do not mean either is correct.

**Generalization is a property checked by this protocol, not an additional universal loss function.** Quality, calibration, unusualness, data coverage, and task importance metrics are not combined into an arbitrary overall score.

Quality and changes in the process are evaluated separately from adaptation of the unusualness norm. Recalculating the norm may hide deterioration; even when the model improves, error percentiles need not fall: the largest 10% remain the largest 10%. Correcting the norm does not correct the prediction. One rare outcome cannot distinguish with certainty between anticipated randomness and a process change.

#### Irreducible Loss and Process Description Error
^prediction-excess-risk

Let `p(y | c)` be the true outcome distribution given information `c`, `q(y | c)` the prediction, and the distribution of evaluated contexts `c` be fixed. For a proper loss and finite corresponding expectations:

$$
R(q)=\mathbb E_c\mathbb E_{Y\sim p(\cdot\mid c)}[S(q(\cdot\mid c),Y)]
=R(p)+D(p,q),\qquad D(p,q)\ge0.
$$

**`R(p)`** is the irreducible loss level given this information; **`D(p,q)`** is excess expected loss (*excess risk*), the error in describing the process under the selected loss. For a strictly proper rule, `D = 0` only when distributions match, except in contexts with zero probability. A correct model of a random process has `D = 0`, although individual outcomes may still be surprising.

**Learning can use the full loss:** for a fixed task, `R(p)` does not depend on the model. It is not necessary to subtract noise before updating parameters. When models are compared on the same task, this component cancels in the difference of expected losses; relative quality can therefore be evaluated without recovering `p`.

For log loss:

$$
D(p,q)=\mathbb E_c\!\left[\mathrm{KL}\bigl(p(\cdot\mid c)\Vert q(\cdot\mid c)\bigr)\right],
\qquad \mathrm{KL}(p\Vert q)=\mathbb E_{Y\sim p}\!\left[\ln\frac{p(Y)}{q(Y)}\right].
$$

Here, the irreducible component is the entropy of the **true** distribution averaged over contexts (differential entropy for continuous outcomes): `R(p) = E_c H(p(· | c))`, where `H(p) = E_{Y~p}[−ln p(Y)]`. **Subtracting model entropy `H(q)` from NLL does not give `D`.** For example, a constant outcome predicted as 50/50 has NLL = `H(q) = ln 2`; their difference is zero, even though the process is fully predictable and the prediction is wrong. [Proper-score decomposition](https://arxiv.org/html/2504.01781v4#S2.SS2).

Irreducibility depends on the chosen information. Candidates are compared for one target process, a shared set of available information `c`, and a common distribution of evaluated cases; knowing the true `p(y | c)` is not required. A candidate may ignore part of `c` to save resources, but variation explained by that information remains in its `D`, rather than becoming part of the shared irreducible component. Evaluation relative to a reduced information set is allowed if that limitation is explicit; `D` values based on different information are not directly comparable.

Absolute `D` cannot be obtained from one observation because `p` is unknown. For simple, stable processes, frequencies or parameters and their discrepancy from the prediction may be estimated while accounting for uncertainty in those estimates. When the basis is weak, report relative quality and diagnostics. “No discrepancy detected” does not mean “`D = 0` has been proved.”

Comparing or aggregating `D` across processes requires a common scoring rule and normalization, prediction unit, horizon, context distribution, and weights. KL does not change under a one-to-one change of units: density multipliers cancel in the ratio. This does not make the error for one scalar step comparable to the error for a multidimensional trajectory.

If an interface needs a bounded scale, it may define `Q = e^(−D/s)` in advance, where `s > 0` is a fixed scale in units of `D`; for log loss with the natural logarithm, `s = 1` is possible. This scale is not a required field. Under a strictly proper rule, a value of 1 corresponds to the correct distribution, but an estimated `Q = 0.9` does not mean a 90% probability of correctness. Equal `Q` values do not imply equal harm, and the transformation does not remove uncertainty in the estimate of `D`.

#### EvaluationTestManager

**`EvaluationTestManager`** runs a [[Program Layer#Program|`Program`]] in an evaluation environment and scores it against an [[#EvaluationCase|`EvaluationCase`]]; for predictions, it uses [[Learning system#^def-PredictionEvaluator|`PredictionEvaluator`]].

```python
EvaluationTestManager.evaluate_case(
    program: Program,
    program_state: S,
    case: EvaluationCase,
) -> EvaluationResult

EvaluationTestManager.evaluate_dataset(
    program: Program,
    program_state: S,
    dataset: EvaluationDataset,
) -> DatasetEvaluationResult
```

`S` is the concrete type of the program state; pass `None` if there is no state. For candidate comparison, fix the code, initial states, read context, metrics, and budget.

Before each independent candidate run, create a separate copy of the declared initial state or a sandbox. Isolation covers all mutable state available to the program: memory, graph, files, learnable components, updater state, and accounting for applied updates. Route candidate and child Program reads and writes to this environment; `GraphDelta` and parameter updates change only its state. Data access follows evaluation rules.

`evaluate_dataset` runs cases sequentially in dataset order, preserving the candidate environment and state between cases until the run ends. A separate `evaluate_case` call runs one example.

Evaluation does not add its own transactions for run isolation or rollback; the standard [[Learning system#PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher|update mechanism]] operates inside the copy or sandbox. Remove the temporary environment after the run ends or fails. Save results through ordinary [[Memory#^def-TraceLocalResult|trace-local]] storage; before deletion, preserve their traces and required dependencies under the [[Memory#^def-RetentionClosure|provenance retention rules]]. Changes in the evaluation environment are not automatically transferred to the agent's working state.

The manager's methods are infrastructure APIs, not separate `Program`s. When the tested `Program` is called, the manager receives [[Program Layer#^def-ProgramResult|`ProgramResult[T]`]] and evaluates its `result`; provenance points to the corresponding part of the saved output.

`DatasetEvaluationResult` contains results for all cases and aggregate metrics under the [[#EvaluationDataset|dataset rules]]; untested cases retain their statuses. The result is linked to the dataset version used. The manager performs evaluation; datasets are managed by [[Datasets#Lifecycle|separate Tasks]].

`EvaluationTestManager` uses `EvaluationTestCacheManager` (in the same directory) for [[#^3162cf|caching]].

##### Evaluation Modes
^evaluation-modes

The evaluation rule specifies the mode; the default is to evaluate a ready-made model.

| Mode | What is evaluated | What may change |
|---|---|---|
| Ready-made model | Quality of the current model or policy. | Working execution state; learnable parameters are fixed. |
| Ability to learn | Adaptation quality on new experience and training cost. | Isolated candidate state under a learning algorithm fixed in advance. |

In the second mode, define data access, update rules, and update times before the run. Candidates receive the same evaluation conditions.

During a dataset run, the manager performs this cycle: save prediction or decision → obtain the outcome and evaluate the result → perform permitted learning → move to the next case. Updates follow the [[Learning system|candidate learning contract]] in its isolated state. Evaluation outcomes remain hidden from the program, including through inputs and retrieval, until the corresponding prediction or decision has been saved; after evaluation they are available for future updates only under the stated rules. Compare later results and costs; learning does not change predictions and evaluations already saved.

Candidate code, learning algorithm, and evaluation rules remain fixed for the entire run. Tuning them on the dataset's results follows the [[Datasets#Training and Evaluation Boundaries|shared evaluation independence constraints]]. The mode, initial states, and update sequence are saved in the evaluation rule and result provenance.

#### Contract-Based Evaluation

A Task selects the purpose, scope, and evaluation requirements under the [[Datasets#Versions and Usage Rules|dataset contract]]. When a case is built from experience, its semantic scope is aligned with process semantics and program contracts.

Memory, `ProgramRun`, or a dataset row contains many facts. To evaluate a specific program, EverTree builds a **projection of this experience onto the task being checked and the program interface**.

The projection uses two lenses:

1. **Process lens** — shows which experience concerns the meaning of the `ProcessConcept` linked to the program through [[Process Ontology and Semantic Interface#^semantic-program-organization|`PROGRAM_FOR_PROCESS`]]: `PART_WHOLE`, `PROCESS_VARIABLE`, `TRAJECTOR`, semantic links, and description.
2. **Program lens** — shows what a specific program actually reads and returns: `read_contract`, `output_contract`, shared runtime trace / `ProgramRun`, and operator anchors.

As a result:

```text
read_contract
→ supplies input facts / context

output_contract
→ shows what the program actually predicts or changes

PROCESS_VARIABLE
→ helps define EvaluationCase semantic scope and reveal uncovered parts of the model

TRAJECTOR
→ defines perspective and helps retrieval, but does not define a metric
```

Source facts outside this projection do not participate in this `EvaluationCase`. They may remain in memory, belong to another process, or become important later after structural alignment.

When programs are compared, keep the evaluated outcomes, available information, and evaluation rules shared. Projections account for candidate interfaces but do not let each candidate choose only a convenient part of the common task. Uncovered requirements remain explicit.

Missing output/prediction required by the [[Program Layer#Output Contract|program contract]] is a contract violation and a reason for structural revision. A [[Process Ontology and Semantic Interface#PROCESS_VARIABLE|`PROCESS_VARIABLE`]] link alone does not make a prediction mandatory for every process model. The absence of an optional prediction is not itself a model error. In either case, do not create `prediction_unexpectedness` for a missing prediction. If a prediction is missing for a known selected `PredictionTarget`, record it as [[Learning system#LearningCredit and UnresolvedCredit|`UnresolvedCredit`]] under [[Learning system#^def-PredictionEvaluator|`PredictionEvaluator` rules]].

Calculate applicable metrics from the saved prediction and observations; calculate [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] when there is a basis for calibration. The evaluation applies to a specific prediction, its [[Program Layer#^def-PredictionTarget|`PredictionTarget`]], and its evaluation conditions. A check may cover an event, a set of observations, or an episode; it does not need to evaluate every event separately.

If a contradiction is found among `ProcessConcept`, semantic links, and program contracts, or a coverage gap is confirmed under the [[Process Ontology and Semantic Interface#Semantic Scope and Implementation Contracts|process coverage rules]], then:

```text
structural revision
```

The managing program raises `attention_priority` for the discrepancy and passes it to consciousness for resolution and alignment of the `ProcessConcept` definition/description, its semantic content (semantic links / `PART_WHOLE` / responsibility structure), and/or the specific program (including its read/output contracts). The graph is not repaired automatically.

Experience is not a test by itself. To make a case from memory, add to the experience projection an outcome or a way to obtain one, and an evaluation rule, under the [[#EvaluationCase|`EvaluationCase` contract]].

#### EvaluationDataset

(def_id:: entity.EvaluationDataset)
> [!definition] **`EvaluationDataset`** — a version of [[Datasets#^def-Dataset|`Dataset`]] with a fixed sequence of evaluation [[#EvaluationCase|cases]], metrics, and aggregation rules for a specified evaluation. ^def-EvaluationDataset

A dataset lets programs be compared under the same conditions. Its composition depends on the question: quality on typical experience, in a particular mode, or on difficult cases. Versions and data splitting follow the [[Datasets|shared dataset rules]].

```python
EvaluationDataset {
  name: <string>
  description?: <string>
  cases: <EvaluationCase[]>
  target_channels?: <SignalChannel[]>
  belief_data?: <BeliefData>
  aggregation_policy?: <string>
  target_metrics?: <MetricDefinition[]>
}
```

#### EvaluationCase

**`EvaluationCase`** is one evaluation example (sample), evaluated on its own or included in a dataset. It defines inputs, evaluation outcomes or how to obtain them, and the evaluation rule.

```python
EvaluationCase {
  id: <string>
  name?: <string>
  inputs?: <Node[]>
  outcomes?: <(Observation | Outcome)[]> # known evaluation outcomes with provenance
  evaluation_rule: <string> # criterion, how to obtain an outcome, and supported check
  target_metrics?: <MetricDefinition[]>
  weight?: <float> = 1.0 # weight under the declared aggregation rule
  belief_data?: <BeliefData> # case reliability
}
```

The evaluator can access `outcomes` and the evaluation rule. The program receives only permitted inputs and context and, in [[#^evaluation-modes|learning-ability mode]], previously evaluated outcomes under the rules for exposing them. The rule unambiguously specifies the requirement, mode, metrics, how to obtain the outcome, and the version of the evaluation implementation to use. The outcome comes from saved data, a run, or a simulation; a goal or expectation does not substitute for it.

Source, preparation, and information available to the program are traceable through [[Memory#^def-ResultProvenance|provenance]]. Inapplicability, insufficient data, and partial metric calculations are represented by [[#EvaluationResult|result statuses]].

Inputs, outcomes, and rules are [[Datasets#Versions and Usage Rules|fixed in the case version]]. One case may belong to multiple datasets. Excluding it from a dataset does not delete the case or its source; the [[Datasets#Deletion|general deletion rules]] apply.

A metric defines how something is measured; a channel defines what a signal means. `weight` is set by [[Datasets#Versions and Usage Rules|weighting rules]] and does not automatically represent case frequency or importance.

#### EvaluationResult

**`EvaluationResult`** is the shared result of evaluating one case or prediction, whether evaluation was run on a saved `EvaluationCase` or after a real-time observation arrived. Fields contain objects under the [[Core data structures#Objects and References|shared object and reference rule]]. The schema describes a payload; when returned from a `Program`, it is in `result` of the shared [[Program Layer#^def-ProgramResult|`ProgramResult`]].

```python
EvaluationResult =
  EvaluatedResult {
    status: "evaluated"
    basis: <EvaluationBasis>
    metric_samples: <NonEmpty[MetricSample]>
  }

| NotApplicableResult {
    status: "not_applicable"
    reason: <string>
  }

| UnresolvedEvaluationResult {
    status: "unresolved"
    reason: <string>
    missing_requirements?: <string[]>
  }
```

Status determines which data are guaranteed to be available:

```text
evaluated
→ an outcome exists;
→ the trace being checked is recoverable;
→ at least one metric has been calculated;

not_applicable
→ evaluation conditions did not occur;
→ this result does not start learning;

unresolved
→ no selected metric was calculated: data or rule support was insufficient,
  or calculation was skipped because of cost;
→ a retry is possible if the reason for omission changes, but is not required;
→ this result does not start learning.
```

`not_applicable` and `unresolved` are not replaced with zero `prediction_unexpectedness` and are not counted as a successful evaluation.

If at least one selected metric was calculated, `evaluated` contains the available `MetricSample`s; reasons for omitting others are recorded in the trace. A consumer checks for the metrics it needs: `evaluated` does not mean the entire requested set was calculated. If no metric was calculated, return `not_applicable` when conditions did not apply or `unresolved` for the reasons above.

`EvaluationBasis` is the immutable factual basis of an evaluation:

```python
EvaluationBasis {
  evaluation_run: <EvaluationRun>
  outcomes: <NonEmpty[Observation | Outcome]>
}
```

The tested Program, case or prediction, runtime trace, and context are recovered through `EvaluationRun` and its provenance. `outcomes` makes the required basis of an evaluated result explicit and available to the next stage.

`MetricSample` stores one measurement obtained during evaluation:

```python
MetricSample {
  metric: <MetricDefinition>
  value: <number | structured value>
  channel?: <SignalChannel>
}
```

`MetricSample` is an immutable part of the evaluation output, so Learning System can refer to selected samples without copying their values.

`MetricSample.channel` and `EvaluationDataset.target_channels` denote [[Evaluative-Control System#^def-SignalChannel|the channels of the resulting evaluations]]. For example, `prediction_unexpectedness` uses the identically named channel when evaluating a supervisor feedback prediction. The prediction being checked, its `PredictionTarget`, and its conditions are recovered through `EvaluationRun` and provenance.

`EvaluationResult` describes an evaluation result but is not itself a learning command. Learning System separately selects outcomes, metrics, and an objective from which it may create a `LearningSignal`.

### Creating Tests

A case may come from experience or an evaluation requirement. Adding it to a set is described by the [[Datasets#Lifecycle|Dataset lifecycle]].

#### Memories

An `EvaluationCase` may come from detailed or compact [[Memory#Observation|first-hand or external experience]] under the [[Datasets#Purpose and Relationship to Memory|shared Dataset rules]].

A memory is not a test by itself. For Evaluation, project the relevant experience onto the specific process and Program under `Contract-Based Evaluation`:

```text
memory / episode
→ projection to process + Program
→ EvaluationCase
→ Evaluation
```

For example, a past episode in which an engine stalled after water entered it may become an `EvaluationCase` for a new version of an engine model.

Case reliability is determined by the quality and applicability of its source evidence through `Belief_data`.

Replay is not required. Replay may independently analyze the same episode and produce a new `EvaluationCase` if a useful evaluation scenario is formulated during analysis.

#### Goal / Expectation / Reasoning / Imagination Tests

The agent's goals and expectations define criteria for evaluation scenarios. An LLM may also propose edge cases and imagined situations based on general knowledge; save them as generated scenarios with their own provenance.

Examples:

```text
goal: income grows
check: new_income > previous_income
```

```text
expected: stick is broken
check: check_relation(stick_facet, Broken)
```

The desired increase in income or broken stick defines the requirement here. Evaluation values come from data or a run result with a specified source. Conclusions from simulation are limited by the environment model's conditions.

A desired result does not substitute for an observation when training a model. Matching a generated expectation alone does not confirm the quality of a prediction about an external process.

Additional checks may cover imagined situations and edge cases, alignment with the goal vector (`goal_progess_delta`), LLM unit tests, simulation, and related approaches.

#### 3. Simulation Tests and Optimization

A program may run in simulation mode. The mode of a specific run is stored in the existing [[Memory#^def-ProgramRun|`ProgramRun.run_mode`]] and does not change [[Program Layer#Program Roles|`Program.roles`]].

In simulation mode:

```text
- there are many runs;
- some operators and parts of the environment may be mocked;
- self-play may be used;
- parameters or a policy may be optimized;
- a strict time / compute budget applies.
```

Simulation may combine two ways of obtaining outcomes:

- **Reuse history.** Use saved outcomes without repeating the original actions when policy changes preserve the conditions under which those outcomes were obtained. For example, change the selection, ordering, or stopping time of independent search branches while respecting dependencies within each branch. If evaluation uses only history, a request for an unrecorded continuation means data are insufficient.
- **Generate from a model.** Memory provides initial situations and data for refining a process model; a simulator creates new continuations, including consequences of alternative actions absent from history. Evaluate these outcomes under the model used. This can combine known environment rules with a learnable model of a particular participant's behavior.

In the standard path, [[Action Selection and Planning#Process Management and Skill Development|`TaskManagingProgram`]] selects simulation evaluation results to train a policy and passes them to the [[Learning system#LearningCoordinator|shared learning pipeline]]. Updates alternate with new runs within the budget. The separate path for a specialized trainer is described in [[Learning system#Specialized Learning]]. [[#EvaluationTestManager|Isolated Evaluation]] compares the current policy and candidates using a fixed environment model and evaluation conditions; whether training is allowed depends on the selected [[#^evaluation-modes|evaluation mode]].

The policy being evaluated receives only information available at the corresponding step in the scenario, including restrictions on hidden simulation state. The shared rules for [[Learning system#Data and Automatic Updates|using training data]] apply. Transfer to new cases requires a [[Learning system#Budget and Review|separate evaluation]].

How much a conclusion from simulation is justified depends on the checked [[Uncertainty and Belief Tracking in the World Model#Belief and BeliefTarget|`BeliefTarget`]] and on the applicability of the data and model used. Simulated outcomes are not by themselves new observations of the corresponding external process; reusing historical outcomes does not create independent new evidence. Their accounting follows the shared [[Uncertainty and Belief Tracking in the World Model#Evidence Sources|Evidence source rules]].

An end-to-end example combining memory, an opponent model, and simulation: [[Memory#Example: Improving Play Against a Specific Opponent|improving play against a specific opponent]].

### Caching Mechanics
^3162cf

`EvaluationTestCacheManager` saves a prepared case when reuse reduces generation costs. A Task selects what to cache. A memory object, JSON, and code are possible forms of the same scenario, retaining its source, version, and evaluation rules.

The cache, including standalone cases, follows the [[Datasets#Deletion|shared deletion rules]]. Deleting a source record after compression does not automatically delete a case if the information it needs has been retained. A case with lost supporting evidence cannot continue to be used for evaluation.

### Debugging

Debugging is handled by `ProgramDebugger`. By default, it uses the standard Codex-agent strategy, with gradual improvement.
