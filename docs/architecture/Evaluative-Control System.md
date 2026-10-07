---
status: draft
target_version: next
---

## Introduction

The Evaluative-Control System defines evaluation signals for analysis, learning, and self-regulation. There is no single mandatory reward function; programs that use the signals make decisions about attention, actions, and learning.

## Signal Type Taxonomy

(def_id:: entity.EvaluativeSignal)
> [!definition]
> **Evaluative signal** — an assessment, on a specified scale, of a property of a state, outcome, process, or metaprocess. It is available to other subsystems for analysis, learning, and self-regulation.
^def-EvaluativeSignal

(def_id:: entity.SignalChannel)
> [!definition]
> **SignalChannel** — the semantic kind of an evaluation. Its contract defines the property being evaluated, the criterion or norm, the scale, and the meaning of its values.
^def-SignalChannel

One channel can evaluate different processes. A metric defines how measurement is performed, a channel defines what the evaluation means to its consumers, and the evaluation subject identifies what it applies to.

### Shared Contract and Scales

The result contract defines the channel and scale. In [[Process Plane/Program Evaluation and Testing#EvaluationResult|`MetricSample`]], the channel is specified in `channel`, the calculation method in `metric`, and the value in `value`. The subject, conditions, and evaluated period are recovered from the contract, arguments, and associated experience; source, basis, and calculation version are recovered through [[Memory#^def-ResultProvenance|provenance]]. Calculation time does not replace the time of the evaluated event.

The result contract specifies when an evaluation is absent; absence is not replaced with zero. The reliability of an evaluation is described separately from its magnitude by applicable [[Uncertainty and Belief Tracking in the World Model|Belief contracts]].

No common scale is introduced: a level and a directional change have different meanings. A consumer contract defines normalization when needed; the original value is preserved. Matching ranges do not make channels interchangeable or define weights for combining them. Whether “higher is better” depends on the channel's meaning.

### Concept Boundaries

- [[Memory#^def-Observation|Observation / Outcome]] — experience from which an evaluation can be obtained or learning can occur. An observed outcome can be useful for learning even if it was expected.
- [[Learning system#^def-LearningSignal|LearningSignal]] — selected experience, metrics, and a learning objective; it may use evaluation signals.
- [[Cognition and Attention#^def-AttentionPriority|`attention_priority`]] and other control parameters — results of interpreting evaluations, tasks, and constraints. A parameter's availability to other programs does not make it a separate evaluation channel.

Predictions of signal values use the shared [[Process Plane/Program Layer#PredictionTarget and Forecast Contract|prediction contract]]. Predictions saved before an outcome are available to consciousness and reflection through [[Memory#^def-TraceEvent|`TraceEvent.output`]] and provenance. They may be included in analysis and learning when appropriate.

## Version 1 Signals (MVP)

### Outcome Evaluations

#### supervisor_feedback_signal

(def_id:: signal.supervisor_feedback_signal)
> [!definition]
> **supervisor_feedback_signal**  
> An external evaluation of the agent's behavior by a person or control system: numerical approval or disapproval, with an optional text explanation of the reason.  
> Used by: behavior analysis, selection of subsequent actions, and learning.
^def-SupervisorFeedbackSignal

```python
SupervisorFeedback {
  value: <float in [-5, +5]>
  comment?: <string>
}
```

`value` is the channel value: negative means disapproval, positive means approval, and zero means neutral evaluation. A consumer may normalize to `[-1, 1]` with `value / 5`. `comment` explains the reason or desired correction and is available for analysis and credit assignment. An unclear connection between an evaluation and behavior requires investigation under the [[Learning system#Credit Assignment|Learning rules]].

A numerical prediction for this channel concerns `value`. When the evaluation is used in `MetricSample`, its `value` contains only the number; `comment` remains in the original observation and is available through provenance. Explicit instructions and prohibitions are handled under their own contracts, independently of the evaluation value.

### Prediction Assessment Signals

[[Process Plane/Program Evaluation and Testing#^def-PredictionError|`prediction_error`]] denotes error under a selected metric. The `prediction_unexpectedness` defined below measures how unusual the discrepancy is; its absence does not prevent applicable error metrics from being calculated.

(def_id:: signal.prediction_unexpectedness)
> [!definition]
> **prediction_unexpectedness ∈ [0, 1]** measures how unusual a discrepancy from a saved prediction is relative to an explicitly selected norm: a distribution of expected discrepancies. The norm is derived from the prediction model or estimated from comparable past cases. The calculation accounts for conditions, observation volume, and expected variability; the meaning of the calibration is defined below. A value close to `1` means that the selected norm rarely allows a discrepancy this large or larger.
> Controls / Influences: Attention, model checking, decisions about learning and structural revision. The signal does not specify a parameter update.
^def-PredictionUnexpectedness

The subject is a specific prediction for a selected [[Process Plane/Program Layer#^def-PredictionTarget|PredictionTarget]] and its evaluation conditions. The target may be a domain quantity or an evaluative signal; the diagnostic channel is `prediction_unexpectedness` in either case. For example, predictions of `supervisor_feedback_signal` and `tension_reduction` can be checked.

#### Choosing a Method and Its Cost

Calibrated `prediction_unexpectedness` is not required for every process. Choose the simplest sufficient method whose expected diagnostic and decision value justifies its development, data collection, maintenance, and computational costs. Process simplicity alone does not determine the required accuracy: the consequences of error and the decisions supported by the signal matter. A separate calculation of calibration value before each observation is not required.

Prefer a ready-made calculation from a prediction model or a simple empirical norm when its assumptions hold. An analytical calculation may directly produce the required rarity scale without a separately trained calibrator. Reuse rules in compatible conditions; the signal may be calculated over windows or episodes. A rough, conservative calculation is acceptable if it preserves the [[#Calibration and Interpretation|meaning of the scale]]. Complex simulations, separate calibrators, and increased accuracy are introduced only when their expected value justifies them within the task budget.

If no supported method is available or its cost is not justified, omit the signal. Outcomes, directional errors, and other available metrics remain usable for analysis and learning under their own contracts; an uncalibrated score must not be presented as `prediction_unexpectedness`.

#### Purpose and Calculation

The loss function of a particular estimator belongs to its learning algorithm; it is not a general control signal. The directional difference `observed − predicted` and [[Process Plane/Program Evaluation and Testing#^prediction-quality-metrics|surprisal / log loss]] may be calculated separately when needed; they are not values of `prediction_unexpectedness`.

Calibration is chosen to distinguish unusual discrepancies from expected variation and to give high values the same meaning of rarity across different checks. Raw distances and loss functions do not provide that meaning on their own.

The unit of evaluation is an event, observation window, or episode. For a learned stochastic process, statistics can be accumulated and expected frequencies, dispersion, or dependencies checked over a window; the signal need not be calculated after every outcome. Checking only overall frequency is insufficient if the model also claims that events are independent or depend on conditions.

For a live check, use the prediction saved before the outcome; when running a model on material from memory, keep evaluation outcomes hidden from it. Before viewing the outcomes, fix the conditions being checked, the window-selection rule, and the discrepancy measure `T`. If the check was selected after an anomaly was noticed, calibration must account for that selection; otherwise, evaluate the conclusion on new data. This does not prohibit retrospective analysis of experience.

For a model-based method, `Q` is the saved predictive distribution for the entire evaluation unit. It accounts for material dependencies among outcomes and uncertainty in estimated parameters. Individual predictions do not imply independence. For example, coin tosses may be independent conditional on a shared probability of heads, while that probability is itself unknown and described by a Beta posterior. The predicted number of heads is then obtained by averaging the binomial distribution over that posterior (beta-binomial); substituting the mean parameter loses its uncertainty. The saved prediction, its conditions, and its state must be sufficient to reproduce the check.

A larger `T` means a stronger discrepancy under evaluation. For example, `T = abs(K - n*p)`, where `K` is the observed number of heads, `n` is the number of tosses, and `p` is the predicted probability of heads. Calculation using the predictive model:

```text
T_observed = T(observations, Q)
p_tail = P_{Y ~ Q}(T(Y, Q) >= T_observed)
prediction_unexpectedness = 1 - p_tail
```

`Y` is a possible outcome, window, or episode under `Q`; `p_tail` is the probability of a discrepancy at least as strong, not the probability of one particular sequence. For example, with independent tosses and `p = 0.5`, any particular sequence of 1,000 tosses has probability `0.5^1000`; unusualness of the number of heads is checked against its distribution. The expected number is 500 with a standard deviation of about 15.8: 520 heads is ordinary variation, while 600 is a strong mismatch.

`p_tail` can be calculated analytically or estimated by simulation. Another valid approach is to calibrate the discrepancy measure against comparable past discrepancies, calculated without fitting the corresponding predictions to the outcomes they evaluate. In that case, rarity is defined by this empirical norm, not automatically by distribution `Q`. The rule must state its assumptions and how it handles finite samples. For example, standard rank calibration requires exchangeability of `T` values across calibration cases and the evaluated case — their joint distribution must be unchanged by permutation. A change in model, mode, or observation selection may violate the assumptions; a simple percentile of past calibration errors provides no guarantee.

For a resolved question about which alternative is true, a prediction may use an epistemic [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]]. For a process with variable outcomes, it may use an [[Uncertainty and Belief Tracking in the World Model#Probabilistic Process Outcomes|`OutcomeProfile`]]. Parameter uncertainty is not conflated with variability in the process itself. For a point-valued numerical prediction, the distribution of deviations is specified separately. An explicit deterministic contract is a special case with zero dispersion; an unspecified dispersion does not by itself imply determinism.

#### Calibration and Interpretation

When calculation uses a correct predictive distribution `Q` and a check fixed in advance, the following holds:

```text
P_{Y ~ Q}(prediction_unexpectedness >= 1 - alpha) <= alpha,  0 < alpha < 1
```

Under these conditions, the probability of a value at least `0.99` in one check is no greater than 1%; the observed proportion in a finite series may differ. If `T` has a continuous distribution, the scale is uniform; for a discrete distribution, the probability may be lower than the bound. Ordinary observations need not produce values near zero: an individual value of `0.5` does not indicate a model problem. For empirical calibration, a similar bound requires the method's assumptions to hold; it does not by itself confirm that `Q` is correct.

Approximate calculations must also respect the stated bound. Seeing no stronger discrepancies in a finite simulation does not prove `p_tail = 0`; simply clipping the result to `[0, 1]` does not ensure calibration.

The signal does not express the probability that the model is wrong, the practical cost of harm, or the direction of error. A high value is a reason to investigate the discrepancy, but does not itself prove a regime change. The scale supports comparing the rarity of discrepancies across checks; its mean is not the agent's overall accuracy. When inspecting multiple checks, account for the possibility of chance high values. If a control program makes automatic threshold decisions with a stated false-alarm rate, that guarantee must apply to the entire series of simultaneous or sequential checks.

Reducing the signal is not an independent learning objective: widening the allowed dispersion may hide a problem. Recalculating an empirical norm may hide either improvement or deterioration in the model: after rescaling, the largest 10% of errors are still the largest 10%. Therefore, evaluate changes to the model and changes to the norm separately, using independent experience and predefined [[Process Plane/Program Evaluation and Testing#^prediction-quality-metrics|prediction quality criteria]]; do not use evaluation material to fit the prediction being evaluated. `prediction_unexpectedness` is not the model's [[Process Plane/Program Evaluation and Testing#^prediction-excess-risk|excess expected loss]].

[[Learning system#^def-PredictionEvaluator|`PredictionEvaluator`]] saves the signal in [[Process Plane/Program Evaluation and Testing#EvaluationResult|`EvaluationResult`]] with provenance for the prediction, observations, and evaluation-rule version. Provenance also records whether calculation was model-based or empirical and the norm used before its update; saved data or state must be sufficient to reproduce the result. A method or norm must not be changed when comparing results without explicitly accounting for that change. The absence of an applicable prediction, data, or supported calibration rule, and a decision to omit calculation because of cost, are not replaced with artificial `0` or `1` values. Reasons for omission, available metrics, and status are governed by the general `EvaluationResult` contract.

> [!example]
> ```text
> predicted_supervisor_feedback_value = +0.6
> observed_supervisor_feedback_value = -0.2
> residual = -0.8
> ```
> This is `prediction_error` under the directional-deviation metric. Calculating `prediction_unexpectedness` for this prediction requires a discrepancy norm and evaluation rule; it cannot be determined from the two numbers above.

### Aggregates of Discrepancy Unusualness

`ExplanatoryTension` and `tension_reduction` give [[Cognition and Attention#^def-Consciousness|consciousness]] compact “before and after” diagnostics: how the unusualness of prediction discrepancies changed in a selected group of processes. This helps identify overall trends and possible effects of changes that appear across several processes or after a delay. A material increase or decrease is a reason to inspect the components, specific experience, and conditions of the change. Consciousness may use an LLM for this analysis. Aggregates are neither an overall evaluation of the agent nor a learning objective; a mean may hide changes in individual processes.

^tension-diagnostics

(def_id:: signal.ExplanatoryTension)
> [!definition]
> **ExplanatoryTension** — the mean level of unusualness of prediction discrepancies during ordinary work on selected processes.  
> Used by: Consciousness, `tension_reduction`, reflection, replay, and graph revision.
^def-ExplanatoryTension

The MVP includes only evaluations with an applicable [[#Calibration and Interpretation|rarity calculation rule]] and sufficient data for it. This does not require proving in advance that the prediction model is correct: its discrepancies are the subject of the diagnosis. A high error alone does not exclude a process from the aggregate. Partial coverage is allowed; reasons for omissions are retained, and results apply only to the covered part of the group.

For each included process `p`, take its already calculated [[#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] values over the selected observation window or episodes — `unexpectedness[p]`. First average the scores within each process, then average across the included processes in `included_processes` with equal weights:

```text
ExplanatoryTension = mean(mean(unexpectedness[p]) for p in included_processes)
```

In the MVP, observation frequency, number of examples, and confidence in the predictive model do not determine process weights. A lower weight does not make an uncalibrated evaluation comparable; such an evaluation remains available to consciousness as a local metric.

The result is a `float` in `[0, 1]` or `None` when data are insufficient. Separate datasets, evaluation runs, or calibration of other processes are not required just to complete the aggregate. Period comparisons follow the [[#^tension-comparison|rules below]].

A simultaneous reduction in tension across several related processes may indicate a breakthrough; the component values show this. The metric does not measure information gain or [[Process Plane/Program Evaluation and Testing#^prediction-quality-metrics|prediction quality]] and is not an independent optimization objective: vague predictions may also reduce unusualness. For a correct prediction, a continuous discrepancy measure, and an exact tail-probability calculation, the expected `prediction_unexpectedness` is `0.5`, not zero; for discrete checks it may be lower.

(def_id:: signal.tension_reduction)
> [!definition]
> **tension_reduction** — an approximate aggregate indicator of change in [[#^def-ExplanatoryTension|`ExplanatoryTension`]] for a selected process group between two periods. A positive value means observed tension decreased; a negative value means it increased.  
> Controls / Influences: priority of conscious analysis, reflection, experience selection for replay, and research directions.
^def-TensionReduction

#### Interface and Calculation of tension_reduction

```python
get_tension_reduction(
    period,
    processes: list[ProcessConcept],
    baseline_period=None,
) -> TensionReductionResult
```

`period` is the interval being evaluated, `[start, end)` (`after`). `baseline_period` defines the comparison interval (`before`); by default, it is the immediately preceding interval of equal duration. A fixed baseline period supports tracking accumulated and delayed changes. The evaluation period is determined by the end time of the event, window, or episode being checked, not by the method-call time.

`processes` follows the [[#^aggregate-queries|shared process selection rule]]; subtrees are expanded once for both periods.

Source evaluations are grouped by the process of the prediction being checked, from its context and provenance. A parent's own predictions are included, but aggregates of its descendants are not added again as parent data.

```text
delta[p] = mean(unexpectedness[p, before]) - mean(unexpectedness[p, after])
tension_reduction = mean(delta[p] for p in comparable_processes)
                  = ExplanatoryTension_before - ExplanatoryTension_after
```

`comparable_processes` are processes from the expanded set with applicable evaluations and sufficient data in both periods. Sufficiency is defined for the check being used; there is no universal minimum sample size for every process. Both `ExplanatoryTension` values are calculated over this same set with the same equal weights.

No additional normalization is needed in the MVP: `prediction_unexpectedness` already has scale `[0, 1]`, so `tension_reduction` lies in `[-1, 1]`. This scale represents a change in discrepancy unusualness; it is not a percentage improvement in the model.

**`TensionReductionResult`** contains:

- `value` — overall `tension_reduction`; `None` if there are no comparable processes.
- `by_process` — for each included process, its mean `before`, mean `after`, their difference `delta`, and the number of source values in each period.
- `skipped` — selected processes, after subtree expansion, that were omitted, with reasons such as no supported calibration method, unjustified calculation cost, insufficient data, or incomparable periods.
- `period`, `baseline_period` — the intervals actually used.

Rules for comparison over time:
^tension-comparison

- **New data.** Window and data-sufficiency rules are set in advance. Without new outcomes, measured tension does not decrease; a new idea or revision alone is not a measured improvement.
- **Comparability.** Keep the process set, selected [[Process Plane/Program Layer#^def-PredictionTarget|PredictionTargets]], evaluation conditions, calculation rules, and observation selection rules consistent. A change in them starts a separate series or requires recalculating aggregates on a common basis; historical predictions are retained and source evaluations are not rewritten. Models and their predictions may change through learning. A change in calibration method or a recalculated empirical norm is recorded separately, as it can also change the indicator.
- **Missing data.** Missing values are not replaced with zero; a process disappearing or coverage changing is not treated as improvement. Partial aggregates with different compositions are not compared directly.
- **Components.** `by_process` helps distinguish an overall shift from a large contribution by one process and reveals increases in tension within individual processes.

The limitations of `ExplanatoryTension` still apply. Its dynamics may reflect resolution of difficulties, changing conditions, prediction spread, or random variation. A flat trend does not mean there was no learning; a prediction can improve while unusualness rises, resulting in negative `tension_reduction`. Check quality and its change under the [[Process Plane/Program Evaluation and Testing#^prediction-quality-protocol|Evaluation protocol]].

## On-Demand Metrics
^aggregate-queries

Aggregates are calculated on demand from saved experience so that analysis costs depend on its expected value. The [[#^tension-diagnostics|diagnostic overview]] does not require continuous recalculation after every event or a separate statistical alert system.

[[Cognition and Attention#^def-Consciousness|Consciousness]], [[Self#From Experience to a Confirmed Problem|reflection]], and [[Memory#^def-MemoryConsolidationProgram|consolidation]] can use `get_tension_reduction` and `get_task_outcome_stats`. Consciousness and Reflection select experience to investigate; consolidation already works with supplied cases and uses aggregates to compare them with history. The consciousness receives `by_process` and `skipped` along with the result so it can account for group composition, data volume, and coverage gaps. Analysis determines whether [[Learning system#^outcome-credit|credit assignment]], replay, or targeted Evaluation is needed. An observed trend alone does not prove overall agent improvement or a causal effect of a metastrategy; such hypotheses are checked under the [[Self#From a Problem to a Change Hypothesis|Self rules]].

`processes: list[ProcessConcept]` contains selected [[Process Plane/Process Ontology and Semantic Interface#ProcessConcept|process concepts]]. For each, include the concept itself and all descendants under [[Semantics Plane#^spec-SUBTYPE_OF|`SUBTYPE_OF`]], combining results without duplicates. `[Process]` selects the entire tree from the [[Process Plane/Process Ontology and Semantic Interface#^def-ProcessRoot|general process root]]. The aggregate covers all available, suitable cases in the declared scope or a saved summary with known coverage, not only retrieval examples found. Memory compression preserves [[Memory#^experience-frequency|observation counts and proportions]].

### Task Outcome Statistics

```python
get_task_outcome_stats(period, processes: list[ProcessConcept])
```

`period` is an interval `[start, end)`. Success is defined by the [[Cognition and Attention#Goal, Task, and Task Specification|Task specification]] and the saved outcome evaluation. A completed `ProgramRun` does not imply Task success; a timeout of one execution does not determine the Task's final outcome. The result deadline comes from Task conditions, if specified, and is distinct from the runtime execution limit.

| Metric | Calculation and time selection |
|---|---|
| `success_rate` | Successful / (successful + unsuccessful) among Tasks with a known final outcome in `period`. |
| `on_time_rate` | Tasks with confirmed success by their deadline / all included Tasks whose deadline falls in `period`, including open, overdue Tasks. Tasks without a deadline are excluded from this rate. |

The result contains rates in `[0, 1]`, the numerator and denominator for each, a `by_process` breakdown, the `period` used, and omissions with reasons. A zero denominator yields `None`. Cancellations during the period, open Tasks at its end, and cases with insufficient data are reported separately. If the needed outcome or its state by the deadline cannot be recovered, the Task is excluded from both parts of the corresponding rate and marked as omitted.

Abandoning a persistent commitment counts as failure; removing a commitment under a saved decision counts as cancellation. Commitments removed before their deadline are excluded from `on_time_rate`; a late cancellation does not erase a previously recorded missed deadline.

A Task is assigned to the process doing the evaluated work, based on its context and provenance; calls to helper programs do not add it to other groups. A Task is counted once in the overall result. The accounting level is fixed: the same outcome is not counted again through both a parent Task and its subtasks. Overall rates are calculated from summed numerators and denominators.

Period comparisons preserve selection and evaluation rules, the accounting level, and comparability of Tasks across processes and conditions. Changes in Task composition and coverage are accounted for separately. Calculation uses the selected revisions of the specifications. Cancellations, deadline changes, and revised criteria retain prior conditions and the reasons for changes in provenance; they cannot silently rewrite a past-period result.

## V1 Scheme

```text
Observation / Outcome
├─ external evaluation
│  → supervisor_feedback_signal
├─ saved prediction + applicable check
│  → EvaluationResult / MetricSample
│    → prediction_unexpectedness, when calibration is available
│      → on demand: ExplanatoryTension → tension_reduction
├─ saved Task outcomes and deadlines
│  → on demand: success and on-time statistics
└─ selected experience → Learning / Belief under their contracts

Evaluative signals + tasks + context + constraints
→ control programs
→ attention priorities, action selection, experience selection, and learning objectives
```

Learning from observations does not require high unusualness. Obtaining an evaluation does not itself trigger an update: evidence, credit, and parameter changes go through [[Learning system|Learning]] and [[Uncertainty and Belief Tracking in the World Model|the Belief System]], while structural changes go through the [[Process Plane/Program Lifecycle and Evolution|Program Lifecycle]].
