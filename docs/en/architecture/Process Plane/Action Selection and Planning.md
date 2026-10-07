## Action Selection and Planning

### Process Management and Skill Development

#topic_core

Selection and execution are handled by ordinary [[Program Layer#Executable Programs|`exec` programs]] with different purposes.

**[[Cognition and Attention#^def-TaskManagingProgram|`TaskManagingProgram`]]** manages task execution. For example, `PokerPlayProgram` runs a game, calls a policy, and organizes execution and any planned learning.

> [!definition]
> **`PolicyProgram`** — an `exec` program that returns a distribution for selecting the next action.
> ^def-PolicyProgram

It is useful to separate this program when a distinct selection contract is needed; it may contain conditions, models, search, and calls to other policies.

**Prefer a verified, compact policy expressed through conditions, concepts, and rules.** Use it when applicable and when it provides the required quality and reliability. This preserves process knowledge in a form that can be analyzed, supports transfer of both regularities and the methods used to obtain them, and reduces the cost of repeated decisions. For example, groups of similar poker situations (buckets) and hand-strength rules can replace some search; grouping methods and probabilistic calculations are useful in other tasks too. Compression should capture meaningful regularities; applicability and transfer are checked through Evaluation.

> [!definition]
> **`SkillDevelopmentProgram`** — a specialization of `TaskManagingProgram` with `exec` and `meta` roles that performs a task to develop or adapt a reusable way to solve a class of problems.
> ^def-SkillDevelopmentProgram

For example, `PokerSkillDevelopmentProgram` improves poker knowledge, models, and programs through exploration, learning, and comparison of alternatives under the shared [[Self#Self-Improvement Loop|self-improvement rules]].

Planned adaptation to changes in the environment, mode, opponent, or opponent style is performed by a `TaskManagingProgram` with subprograms. Independent exploration or revision of a solution method can become a [[Cognition and Attention#Goal, Task, and Task Specification|task]] for `SkillDevelopmentProgram`. Execution and development can be combined; a separate development run is not needed for every change or update. Their relationship is described by [[Program Layer#ProgramDesign|`ProgramDesign`]].

These are purposes of ordinary Programs; they do not add values to `Program.roles` or introduce a `Skill` entity. A skill may span multiple programs and models. The MVP prioritizes reusable programs, process models, and knowledge with transfer checks; [[Learning system#Specialized Learning|training a dedicated backend]] is an additional path for narrow tasks.

### Policy Program and ActionDistribution

#topic_core

A policy returns `ProgramResult[ActionDistribution]` under the [[Program Layer#^def-ProgramResult|shared contract]]; the calling program executes the selected action. This common output allows shared validation and sampling across different algorithms. Other `exec` programs retain their own `ProgramResult[T]`.

```python
from dataclasses import dataclass

@dataclass
class ActionDistribution:
    choices: list[tuple[ActionCandidate, float]]

ActionDistribution(choices=[(fold, 0.3), (call, 0.7)])
# Deterministic decision:
ActionDistribution(choices=[(fold, 1.0)])
```

[[Program Layer#Actions|`ActionCandidate`]] describes an action, program call, or transition. Each pair associates a candidate with a probability, independently of any external list. Zero-probability choices may be omitted.

#topic_details

Contract conditions:

- The distribution is nonempty and candidates are unique.
- Probabilities are finite, nonnegative, and sum to `1` within numerical tolerance.
- If an allowed candidate set is supplied, the result is limited to that set; otherwise, candidates created by the policy are checked against the task and action contracts.
- The calling program handles violations; there is no implicit random fallback.

Inputs are defined by the [[Program Layer#^def-ArgumentPreparation|contract of the particular policy]], not by a universal opaque `ctx`:

```python
poker_policy(
    view: PokerView, legal_actions: list[ActionCandidate]
) -> ProgramResult[ActionDistribution]

negotiation_policy(
    task: NegotiationTask,
    conversation: Conversation,
    constraints: NegotiationConstraints,
) -> ProgramResult[ActionDistribution]
```

In poker, commands are provided by the [[Discrete Action Interface]], and the policy input contains only information available to the player. In negotiation, the policy may prepare proposals itself. Consciousness or the managing program chooses how candidates are constructed.

### Composition and Sampling

#topic_details

A program may call several policies or continue without an action. Its code leaves are not collected into one set of alternatives:

```python
def poker_policy(view, legal_actions) -> ProgramResult[ActionDistribution]:
    if view.stage == "preflop":
        return preflop_policy(view, legal_actions)
    return postflop_policy(view, legal_actions)
```

Branches before the policy call also determine behavior. A shared helper validates the distribution and samples once:

```python
sample_action(distribution: ActionDistribution) -> ActionCandidate
```

The distribution and selected action are recorded in the trace through a [[Program Layer#Code Anchors|Code Anchor]]. `ProgramResult.feedback` is saved and available to the caller separately from the probabilities.

```text
TaskManagingProgram
→ observations and input preparation
→ PolicyProgram → ProgramResult[ActionDistribution]
→ sample_action → proposed ActionCandidate
→ applicable Verification and CommitmentControl
→ execution of the accepted action
→ observed consequences and trace
→ when sufficient data are available: Evaluation
→ selected experience and learning objective → LearningCoordinator
→ update learnable components and continue
```

The calling program organizes [[Cognition and Attention#^actions-and-user-response|validation, acceptance, and execution]], including handing selection to consciousness when needed. Checks may be required before the policy call; sampling alone does not authorize an external effect.

If waiting is an available decision, `wait` may be a candidate. An empty distribution does not mean waiting, missing data, or an error.

#### Internal Randomness

#topic_details

Returned probabilities are conditional: they apply to sampling **after the current call's computations**. For example, Thompson sampling first selects a model randomly and may then return one action with probability `1`. If learning needs the full behavior probability including internal randomness, the algorithm contract defines how to obtain it and which trace data are needed; a returned `1` is not a substitute.

### Selection Mechanisms

#topic_core

| Basis for selection | Example |
|---|---|
| Use what is known | Maximize a utility score. |
| Obtain useful knowledge | Experiment or check a poorly explored option. |
| Follow a mixed strategy | Use specified action probabilities even for a well-studied process. |

A policy may combine these bases. Universal scores and temperature are not required.

#### Utility Scores and Greedy Selection

#topic_core

`score_actions` is the name of an optional operation for scoring candidate utility, not a model class. Higher values are preferred; scores combined together must be consistent in meaning and scale. The contract defines the selection criterion and, when needed, accounts for horizon, cost, risk, and the value of future knowledge.

Sources may include a model, simulation, experience, rules, or an LLM. A `ProcessModel` predicts a specific [[Program Layer#^def-PredictionTarget|PredictionTarget]]; a predicted score or other value serves as a selection score only if it matches the selection criterion. [[Program Layer#Expected Signals|Expected signals]] are added only through justified channels and program locations under the [[Learning system#Selecting Learnable Components and Learning Mode|learning rules]].

#topic_details

If the evaluator is a separate `Program`:

```python
score_actions(inputs, candidates) -> ProgramResult[list[SelectionScore]]

@dataclass
class SelectionScore:
    score: float
    expected_signals: dict[SignalChannel, ExpectedOutcomeSignal] | None = None
    belief_data: BeliefData | None = None
```

Scores are finite and correspond to candidate order. **Greedy selection** is `argmax(values)`: it may be myopic when scoring immediate reward, or encourage exploration if the score accounts for future information value.

#### Mixed Strategy

Apply the strategy distribution directly: action probabilities are not utility estimates. For example, classical Counterfactual Regret Minimization (CFR) uses an average strategy. Using `argmax` instead of sampling, or arbitrarily changing probabilities, changes the strategy; filtering or replacing candidates requires a specified adaptation method.

### Exploration

The method and intensity of exploration are determined [[Self#Exploration|for each process and its parts]] to benefit future decisions, accounting for risk, tasks, values, and budget. Information about uncertainty and the freshness of experience is needed: equal immediate utility does not imply equal exploration value.

| Mechanism | Selection | Requirements |
|---|---|---|
| Targeted experiment | Test a material hypothesis while accounting for value, cost, and risk. | A way to distinguish hypotheses through observations. |
| [UCB](https://doi.org/10.1023/A:1013689704352) | Maximize utility with an uncertainty bonus. | A statistical model that justifies the bonus. |
| [Thompson sampling](https://arxiv.org/abs/1707.02038) | Sample a model or parameters from an uncertainty distribution, then choose the best action for that sample. | A model uncertainty distribution updated from data. |

[[Program Layer#ProgramDesign|`ProgramDesign`]] records the local mechanism, delegation, or justified decision that exploration does not apply; the executable contract defines parameters and assumptions. When conditions change, the program rechecks model freshness under the [[Learning system#Data and Automatic Updates|learning rules]]. A general mode monitor is unnecessary; increasing temperature does not fix an outdated model.

### Ready-Made Functions and Classes

Extract recurring mechanisms when there is a real need:

```python
certain(action) -> ActionDistribution
greedy_distribution(candidates, values, tie_rule) -> ActionDistribution
softmax_distribution(candidates, values, temperature) -> ActionDistribution
sample_action(distribution) -> ActionCandidate
```

`argmax` returns an index and softmax returns probabilities; helpers associate them with candidates. Ordinary functions return values, while standalone Programs return `ProgramResult`.

Introduce methods and class templates when they represent a recurring structure. For example, an optional `ValuePolicy` may combine an evaluator with distribution construction.

### TemperaturePolicy

Temperature `T` for `softmax(values / T)` is a local setting, chosen together with the score scale based on experience or comparison of alternatives. A constant is sufficient for the MVP; a recurring rule may be extracted as `TemperaturePolicy`:

```python
temperature_policy(inputs, candidates, scores) -> ProgramResult[float]
# Finite T > 0.
```

Temperature controls how concentrated the selection is, but does not replace exploration, a mixed strategy, or validity checks. Use `greedy_distribution` for strictly greedy selection, not `T = 0`.

### Belief and Selection History

Policy probabilities describe behavior; [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]] is an epistemic belief over alternatives in one [[Uncertainty and Belief Tracking in the World Model#^def-CompetitionScope|`CompetitionScope`]] and may be a policy input.

Confidence in a program and its application is represented by shared [[Program Layer#“Training” Operators and Transitions|program and operator beliefs]]; confidence in predicted consequences comes from model results. An ordinary `Program` is sufficient for contracts, anchors, traces, and learnable components; a separate selection wrapper is unnecessary.

### Runtime Planning

#topic_core

The code of a managing `exec` or `PolicyProgram` determines whether to apply a ready-made rule, make a direct prediction, or invoke a planner at a particular decision point. Planning is not a mandatory step before an action; it searches for a decision using models within an allocated budget.

**`PlanningProgram`** is an ordinary `exec` search program, called through program composition. A separate Python class is optional; below, `estimate_actions` is the entry point of a particular planner.

Search is justified when the expected improvement in the decision is worth the additional cost, for example:

- a verified policy has not yet been developed for current conditions;
- combinations of options cannot yet be covered by sufficiently accurate rules and generalizations;
- the previous policy is no longer applicable, for example after a regime change;
- consequences are significant, and the current policy is not sufficiently reliable, while search over available models is expected to improve the decision.

Applicable models and a budget are required. Lack of process knowledge or a regime change alone does not make a planner more reliable: an incorrect model may require new experience. Invocation conditions are defined in code; their rationale and revision are described in [[Program Layer#ProgramDesign|`ProgramDesign`]].

#### Invocation at a Specific Program Point

An example policy fragment combining a ready-made rule with local search:

```python
def poker_policy(view, legal_actions) -> ProgramResult[ActionDistribution]:
    if fold in legal_actions and verified_fold_rule_applies(view):
        return ProgramResult(result=certain(fold))

    if planning_needed(view):
        scores = estimate_actions(
            view, legal_actions, process_models=models,
            continuation_policy=baseline_policy, budget=planning_budget,
        ).result
        return ProgramResult(result=softmax_distribution(
            legal_actions, [s.score for s in scores], temperature
        ))

    return prepared_policy(view, legal_actions)
```

Conditions and `prepared_policy` are defined by the particular program; this example illustrates the structure, not poker advice. If no justified automatic decision is available, use the ordinary [[Cognition and Attention#^actions-and-user-response|handoff of selection to consciousness]].

#### Evaluating Continuations

A planner that scores candidates may return the same `SelectionScore` as `score_actions`. A shared output does not require inheritance or identical input interfaces:

```python
estimate_actions(
    position, candidates, *, process_models, continuation_policy, budget
) -> ProgramResult[list[SelectionScore]]
```

It conditionally fixes each first candidate and predicts consequences through `ProcessModels`. `continuation_policy` defines baseline behavior afterward; if the search revises subsequent decisions, scores apply to the continuation it found. Random events and participant responses use their corresponding models. To estimate the expected continuation outcome, weight continuations by the probabilities in those models and policy, or sample from them. Do not multiply a candidate's score by its current selection probability. The contract defines the score meaning, horizon, and continuation assumptions; the calling policy builds an `ActionDistribution` from the resulting scores.

[[Program Layer#Direct Outcome Forecast|Direct outcome prediction]] can score an action without search or evaluate a remaining outcome to complete a search. Do not add intermediate results again if they are already included. A planner composes model and policy calls; a `ProcessModel` does not call `exec`. A continuation policy is usually simpler than the caller; another planner call is allowed only with a limit on total budget and depth.

Exact enumeration suits a small number of continuations; Monte Carlo trajectory sampling suits a large number. MCTS allocates search across branches, while best-first or beam search uses a heuristic. Choose an algorithm for the process. Exploration within search allocates computation; the policy selects external exploratory actions. Simulations follow the [[Program Evaluation and Testing#3. Simulation Tests and Optimization|limits on available information and on conclusions drawn from a model]].

This interface concerns candidate evaluation. Other `PlanningProgram`s may return a plan or ready-made strategy; a single action is represented as `certain(action)` when returned through the policy interface.

### Policy Optimization

`TaskManagingProgram` or `SkillDevelopmentProgram` selects experience, an objective, and a time for learning. [[Learning system#LearningCoordinator|`LearningCoordinator`]] organizes [[Learning system#LearningCredit and UnresolvedCredit|credit for the selected `LearningTarget`]] and updates estimator state or program parameters, including the policy. `UpdatePlanner` selects the state to update; the corresponding updater calculates its new value.

Learning may use one observation, a batch, a window, or an episode and does not have to block the next step. A policy call uses the current state; learning is started explicitly. One poor outcome does not automatically update all components involved.

Learnable components are selected under the [[Learning system#Selecting Learnable Components and Learning Mode|shared rules]]; a fixed rule or ready-made strategy may suffice for the MVP. [[Program Evaluation and Testing|Evaluation]] checks decision consequences over the required horizon, including exploration value, cost, and constraints. An immediate score or an increase in [[Evaluative-Control System#^def-TensionReduction|`tension_reduction`]] alone does not confirm improvement. Check prediction quality for a model and decision quality for a policy.

Changes to code, contracts, or component composition go through the [[Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]].

Repeated search provides material for hypotheses about compact rules, concepts, and models. `SkillDevelopmentProgram` tests such generalizations and the transfer of methods used to obtain them under the [[Self#Self-Improvement Loop|self-improvement rules]]. A verified policy reduces the scope of repeated planning; simulation results alone do not establish that the external process model is true.
