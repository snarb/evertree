---
status: draft
target_version: next
---

## Consciousness (`Consciousness`)

#topic_core

> [!definition] **Consciousness (`Consciousness`)** — a protected, event-driven, top-level control process that works on the current [[#`Goal`, `Task`, and Task Specification|`Task`]] in [[#Attention (`Attention`)|`Focus`]], observes its state, the [[Process Plane/Program Layer#Program|`Program`s]] it uses, and their execution, and uses this information to choose the next control action.
^def-Consciousness

Consciousness may continue execution, change the solution method, suspend a `Task`, start additional processing, or intervene once in the current [[Memory#^def-ProgramRun|`ProgramRun`]] to test a local hypothesis, fix a detected error, or exit a failed execution path. It may suspend the current `ProgramRun`, change the subsequent solution method, and, through [[#Conscious Program Supervision|`Conscious Program Supervision`]], apply a new committed candidate revision to reloadable code that has not yet run. The revisions actually used and execution results are saved in [[Memory#^def-ResultProvenance|provenance]]. If a discovered change or generated hypothesis should be used in future runs, it is formalized as a candidate `Program` or [[Process Plane/Program Lifecycle and Evolution#ProgramBranch|`ProgramBranch`]] and goes through the [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]].

Consciousness works as a resumable loop:

```text
observe current Task / Program / ProgramRun
        ↓
interpret current situation
        ↓
act / delegate / suspend
        ↓
observe again
```

#topic_details

The object of observation is not only an already executed trace, but also the current plan, code that has not yet run, task specification, beliefs, relevant semantic graph, and past experience. At every significant stage, consciousness can use retrieval, reasoning, planning, verification, debugging, LLMs, tools, child Programs, and other available mechanisms; request more information or create a separate `Task`; suspend current work and resume it later with new context; change the plan or branch; fix a candidate `Program` revision and restart it; run Reflection; save a significant result; or finish processing.

#topic_core

Ready-made processes such as [[Self#SelfRegulation|`SelfRegulation`]] and other Programs are tools and skills of consciousness; they do not replace it. In a familiar and sufficiently reliable situation, most control flow may run automatically. With novelty, insufficient evidence, conflict, high importance, or high cost of error, control returns to consciousness, which flexibly determines what happens next.

For diagnostic “before and after” comparisons, consciousness can request [[Evaluative-Control System#^aggregate-queries|aggregates]] for selected periods and groups of processes. [[Evaluative-Control System#^tension-diagnostics|Changes in tension]] help select processes and experience for investigation; aggregate use is determined by expected value and cost.

Conscious control is applied adaptively:

```text
reliable, familiar process
→ automatic execution;

novelty / insufficient evidence /
high importance or high cost of error
→ conscious supervision;

verified recurring mechanism
→ gradual automation;

anomaly / new context / loss of confidence
→ return to conscious control.
```

---

## Attention (`Attention`)

#topic_core

**Attention** allocates the limited resources of conscious processing among tasks and relevant objects.

```text
AttentionPriorityQueue
→ Tasks waiting for conscious processing;

Focus
→ the current Task receiving conscious resources.
```

`AttentionPriorityQueue` determines which [[#`Goal`, `Task`, and Task Specification|`Task`s]] compete for consciousness.

(def_id:: control.attention_priority)
> [!definition]
> **`attention_priority`** — a dynamic `Task` priority assigned by a control program to allocate conscious attention based on evaluations, goals, and context.
^def-AttentionPriority

Other programs may use this parameter through available state or a saved trace. A high value alone does not explain why the task has priority; analysis uses the source evaluations and task context. A separate evaluation channel or event to represent the priority again is not required.

The following must also be distinguished:

```text
AttentionRuntime (L4)
→ fixed part of the consciousness core:
  stores Focus and queue state,
  safely performs suspend / resume / switch,
  enforces hard execution limits,
  watchdog, and minimal fallback;

AttentionControl
→ ProcessConcept within SelfRegulation;
  its active meta-Program uses attention_priority
  and proposes Focus / suspend / resume / switch decisions.
```

`AttentionControl` does not change runtime state directly: `AttentionRuntime` checks the proposed decision under the L4 contract and applies it, rejects it, or uses a fallback. The active [[Process Plane/Program Layer#Program|`Program`]] for `AttentionControl` may evolve as an L3 meta-Program. `AttentionRuntime` belongs to [[Self#Meta-Improvement|L4]]: the agent may analyze it, but only a developer outside the agent runtime may change it.

There is one primary focus `Task` at a time; all execution follows the [[#^sequential-tasks|sequential Task execution rule]]. Atomicity is a runtime property of the current attention scope, where a `Task` can be processed, suspended, and resumed independently; it is not an ontological type of Task.

At an available control point, `AttentionControl` may retain, suspend, resume, or switch the current focus. Task decomposition belongs to planning; attention only allocates focus among the resulting tasks. A critical signal may request control transfer at the nearest allowed runtime boundary.

The attention queue contains tasks that need a conscious step, not every existing `Task`. Input reception, waiting for data, and permitted automatic execution of the current Task do not require continuous `Focus`. Before handing execution to another Task, the runtime suspends the current one under the [[#Stopping Execution and Releasing Memory|shared contract]]. Selecting features and chunk sizes while preparing data belongs to [[Process Plane/Program Layer#^granularity-adaptation|granularity management]], not `Focus` allocation.

---

## `Goal`, `Task`, and Task Specification

#topic_core

**Goal** — a desired result or state that the agent seeks to achieve.

**Task** — a semantically defined unit of work toward a `Goal`, an external request, an [[Self#Events|`Event`]], [[Memory#Replay|Replay]], or another signal.

`Goal` is not a mandatory gateway for creating a `Task`:

```text
Values + state + signals
        ↓
GoalManagement
        ↓
create / prioritize / revise Goals

Goal / external request / Event / Replay
        ↓
create / continue Task
        ├─ assigned automatic work → exec Program
        └─ conscious step needed → AttentionPriorityQueue
```

Not every `Goal` immediately becomes a `Task`; [[Self#SelfRegulation|`GoalManagement`]] manages goals, while attention manages competition among tasks for conscious processing. The detailed goal lifecycle belongs to [[Self#SelfRegulation|`SelfRegulation`]].

`TaskFraming` is a `SelfRegulation` [[Process Plane/Process Ontology and Semantic Interface#ProcessConcept|`ProcessConcept`]] whose active meta-[[Process Plane/Program Layer#Program|`Program`]] creates and revises a structured task specification from the original request, signal, and available context.

A `Task` already exists for the first call to `TaskFraming`: its initial `objective` may be “interpret the incoming request,” with a reference to the source. A complete subject-matter specification is not required before entry into the attention queue. Initial framing and later refinement are distinguished in [[#^input-reception|input reception]].

A minimal semantic task specification contains:

```text
objective
→ desired result;

success_criteria?
→ how to determine whether the objective was achieved;

constraints?
→ conditions that make the result, actions,
  or process acceptable within a given scope.

preferences?
→ soft preferences among acceptable solutions.
```

`objective` is required; it may specify an outcome to achieve or a state to maintain. Add `success_criteria` when separate conditions are needed to establish success; these may require human evaluation. Without them, assess the result against the objective, original instruction, and constraints. If the evidence is insufficient, success remains undetermined; stopping execution does not itself establish success.

Known mandatory conditions are recorded in `constraints`, including a required method, output format, scope of work, overall spending limit, and deadline when specified. `preferences` express concrete priorities when choosing among solutions, such as preferring simplicity when quality is comparable. Omit these fields when no such additional conditions or preferences are given; the agent's general rules still apply. Choose the execution method within the task requirements.

`Requirement` is a general term for an original requirement. When structured, it is expressed through one or more of `objective`, `success_criteria`, or `constraint`. An `Invariant` is a scoped `constraint` that must remain true throughout its scope, so it is checked again before actions that could violate it and at other defined control points.
^def-Requirement

Textual input requirements of a specific `Program` are defined by [[Process Plane/Program Layer#^program-input-requirements|`Program.requirements`]]. The calling program or conscious step accounts for them when [[Process Plane/Program Layer#^def-ArgumentPreparation|preparing arguments]].

An agent assumption remains knowledge that may be checked; it does not become a `constraint` without a corresponding requirement or policy.

Material parts of the specification are materialized in the semantic graph and retain provenance to the original request or other basis:

```text
source request / signal
        ↓ provenance
structured task specification in semantic graph
```

`Task specification` is a versioned, structured specification of a `Task`, whose material parts are materialized in the semantic graph. A material change to `objective`, `success_criteria`, `constraints`, or `preferences` is made through `GraphDelta`, retains provenance, and creates a new specification revision. The latest accepted revision is current. Mandatory execution-resource decisions are stored separately from the specification in [[#Execution Budgets|`TaskState`]].

#topic_details

Context preparation and Verification use the specification and may consult the source through provenance when needed. For material decisions, Verification may run `SourceToSpecCoverageCheck()`, which compares the original source against the structured specification to find omitted or distorted requirements. This can reveal both requirements forgotten during reasoning and errors in the initial structuring.

---

## Input Reception and Perception
^input-reception

#topic_core

At runtime, the source adapter accepts data and saves the full original content, source, arrival order, known event and receipt times, and link to the call or task in [[Memory|Memory]]. This initial record does not have to be an [[Memory#^def-Observation|`Observation`]] yet: the semantic result receives provenance from work performed in the context of a `Task`.

Handle incoming data in this order:

1. **The recipient is unambiguous:** deliver a tool result, answer to a specific clarification, or continuation of an established flow to the existing `Task` and, if defined, its `ProgramRun`. A conversation identifier alone does not prove that items belong to one task.
2. **There is no unambiguous recipient:** runtime creates a minimal `Task` for interpreting the input according to a fixed rule, with an initial `objective` and provenance to the source. This does not mean that new subject-matter work has begun; after interpretation, the input may turn out to continue an earlier task.
3. **An allowed handler was configured in advance:** a specific `exec` `Program` performs the initial work after the established `Task` is admitted to [[#^sequential-tasks|sequential execution]]. The binding is specified by the source or a verifiable rule; ambiguity does not trigger every possible candidate. Without such a handler, the task requests a conscious step through attention. Runtime does not choose an arbitrary program based on the text's meaning.

The input is also linked to a known [[Memory#^def-Episode|`Episode`]], such as the current conversation or experiment. If no such link exists, an episode is created for the initial interpretation. This link describes the episode in progress, not a separate task container: one Episode may relate to multiple Tasks, and one Task may draw on multiple Episodes. Until the subject-matter process is defined, the conversation or input-interpretation episode grounds the initial link; later refinement preserves provenance.

The original text may be represented as a standard typed observation without LLM interpretation. More complex interpretation and `TaskFraming` are performed by an assigned program or organized by consciousness after it receives `Focus`. On redirection, the source identity and provenance are retained; the initial Task is completed or its specification revised, and reusing the input does not count as independent experience.

Internal [[Self#Events|events]], [[Self#SelfRegulation|Goals]], and [[Memory#^def-MemoryReplay|Replay]] also create or continue a `Task`; there is no need to present an existing internal result again as a new external observation. Every running workflow has an owning task under the [[#Stopping Execution and Releasing Memory|general execution contract]].

### Perception

> [!definition]
> **Perception** — a process that obtains and represents information from a source as a typed result with the role of an [[Memory#^def-Observation|`Observation`]].
> ^def-Perception

This is an ordinary [[Process Plane/Process Ontology and Semantic Interface#ProcessConcept|`ProcessConcept`]], implemented by operations and Programs for the relevant sources. Initial text processing may save the whole message or block; all atomic facts do not need to be extracted before the task is known. Initial boundaries follow the source format and processing cost, but do not automatically define argument, fact, or learning-step boundaries. An already suitable typed observation is reused without extraction again.

Rereading a saved source may produce a different representation or level of detail while preserving the original provenance. `Perception` performs the assigned data work; it does not choose or call a domain process program. The required follow-up processing is determined by [[#^def-TaskExecution|consciousness or the specific executing program]].

When the recipient is known, delivery does not require semantic routing. When a task must identify the process and its execution, consciousness or the executing `exec` program calls [[Process Plane/Process Ontology and Semantic Interface#^def-ProcessRouter|`ProcessRouter`]]. Choosing a process, creating or refining a Task, and allocating conscious focus are separate decisions.

---

## `TaskState`, `Focus`, and `PreparedContext`
^working-context

#topic_core

Distinguish:

```text
Task
→ semantic identity + specification;

TaskState
→ resumable runtime state;

Focus
→ pointer to the Task receiving conscious resources;

PreparedContext
→ data prepared for the next processing of a Task and Episode.
```

`TaskState` stores progress, the current [[#Planning|`Plan`]], [[#Execution Budgets|budgets and recorded spending]], unresolved questions, waits, status, task-specification revision, and references to current objects, related Episodes, material results, and [[Memory#^def-ProgramRun|`ProgramRun`s]]. Execution facts belong to `ProgramRun` and [[Memory#^def-TraceEvent|`TraceEvent`]]. [[Memory#^active-state|`active_state`]] is part of Memory and speeds access to recently active tasks and episodes; Memory controls this cache's size and cleanup.

> [!definition]
> **PreparedContext** (formerly `WorkingContext`) — a typed [[Memory#^def-OperatorOutput|`OperatorOutput`]] that prepares data for work on a Task and its related Episode: current input, selected information from memory, and references to its sources.
> ^def-PreparedContext

`PreparedContext` is assembled for the current processing step and may include the task specification, execution progress, and selected experience. It is not guaranteed to be complete for every later step: sources remain available, and missing information is requested as needed. [[Core data structures#^def-TaskContext|`TaskContext`]] contains facts external to the domain object that affect materialization; these facts are included in `PreparedContext` when needed.

Preparing again creates a new `PreparedContext`. Values computed during execution are passed separately to [[Process Plane/Program Layer#^def-ArgumentPreparation|argument preparation]] as references to selected sources (`sources`) or as ready parameter bindings (`known_arguments`). Rebuild the context when the work needs new inputs, information, or refined conditions.

### Execution Budgets

#topic_core

Before a Task runs, both fields are assigned in its `TaskState`:

| Field | Meaning |
|---|---|
| `execution_budget` | Finite resource allowance before continuation must be reviewed, including resources already spent. Resources and units are explicit. |
| `self_improvement_budget` | A number from `0` to `100`: the approximate permitted share of each `execution_budget` resource for additional self-improvement. |

Consciousness or a control program assigns budgets within [[Self#SelfRegulation|ResourceControl]]; for initial input interpretation, runtime uses its established policy. The full cost of a solution does not have to be estimated in advance. Hard spending limits and deadlines, when specified, remain in `constraints`; extensions follow the [[#Stopping Execution and Releasing Memory|general rules]].

Work time is approximate, without strict minute-by-minute accounting. A small deviation, such as 25 minutes instead of 24, is not by itself a violation or reason for a penalty. Material overspending requires review; explicit hard limits remain binding.

Choose the self-improvement share based on task urgency and the expected value of available improvements. It defines permitted additional spending; it does not reserve resources or require spending them. Self-improvement is performed only when justified by the current task; if there is no useful learning or improvement, the budget need not be spent. A value of `0` is allowed.

Work required by the objective, including research and training, uses the main budget. The self-improvement share applies to additional work for future tasks, such as generalizing a tool. These costs count against both the overall budget and the originating Task's sublimit, including when delegated to a subtask. If self-improvement itself is the objective, the sublimit applies only to improvements beyond that goal. A budget does not replace authorization to learn or change programs.

```python
execution_budget = {"active_time_minutes": 120}
self_improvement_budget = 20  # Approx. up to 24 extra minutes for self-improvement.
```

`active_time_minutes` estimates total active time for all workers, excluding pauses and time waiting for the user. The percentage is based on the assigned budget; early completion does not require spending the remainder. Track both the remaining overall budget and remaining self-improvement share; exhausting the latter does not prevent the main work.

### Context Preparation

> [!definition]
> **ContextPreparation** — a process that selects and assembles `PreparedContext` from input, work state, and relevant experience in Memory.
> ^context-preparation

The Task and Episode define the search scope: preparation retrieves related results and history, and, when useful, similar or other relevant experience. Recent data are available through references in `active_state`; older data are found through retrieval. Use the exact saved content or a compressed representation with known loss of detail and preserved provenance.

Include the latest incoming message in full. Selected earlier messages from the user and agent, tool calls, and tool results may be passed as `messages`, preserving roles, order, and the link between each call and its result.

Minimal interface for a standalone preparation program:

```python
prepare_context(task, episode, incoming) -> ProgramResult[PreparedContext]
```

These arguments and the active task constraints define the work's scope. `incoming` contains the saved current input; the return follows the general [[Process Plane/Program Layer#^def-ProgramResult|`ProgramResult` contract]]. After a Task is admitted for execution, runtime runs the assigned preparation implementation for the new input or resumption; the current work owner may request later preparation. Conscious `Focus` is not required for this.

#topic_details

```text
Task + Episode + incoming
        +
TaskState / active_state / Memory retrieval
        ↓
ContextPreparation / prepare_context(...)
        ↓
PreparedContext
        ↓
TaskManagingProgram or consciousness for the focused Task
        → further steps in the general task cycle
```

#topic_core

The initial preparation method uses a moderate amount of data within budget: the current specification, unfinished state, latest input, and relevant recent information. Retrieve additional experience as needed. The amount, age, and detail of selected experience are learnable: successful work, checks, and feedback help determine what is useful to include for a class of tasks. A fixed number of latest messages does not replace this evaluation.

The preparer and the task execution program may use the full input. A specific process model receives selected data through its interface; its actual LLM request and instruction versions are saved under the [[Process Plane/Program Layer#^program-text-dependencies|general contract]].

Applicable `constraints` remain in the structured specification even when not fully included in the current request, and are available for review again before a material commitment. Include [[Self#SelfModel|`SelfModel`]], [[Self#Self-Regulation Principles|`SelfRegulationPrinciples`]], the semantic graph, and domain `TaskContext` when relevant. For initial input interpretation, the source, initial objective, and explicitly saved unresolved questions are enough; a complete specification is not yet required.

`ContextPreparation` gathers information for the owner of work on a Task/Episode; [[Process Plane/Program Layer#^def-ArgumentPreparation|argument preparation]] binds selected data to parameters of a specific call. After receiving its arguments, a child program assembles its own LLM request from them and permitted reads. The operations may share code, but local request assembly does not restart preparation for the whole task or automatically expose the full `PreparedContext` to the model. The `model` role restrictions and [[Process Plane/Program Evaluation and Testing#^prediction-quality-protocol|forecast-evaluation protocol]] still apply.

Consciousness or the specific calling program may refine preparation for future inputs and context based on [[Process Plane/Program Layer#^program-feedback|feedback]] from completed calls, including suggestions after successful processing. Feedback goes to the immediate caller and is not broadcast automatically to all preparation modules. Conscious reading of symbols or fragments uses [[Process Plane/Program Layer#^source-access-preparation|shared source access]], while [[Process Plane/Program Layer#^granularity-adaptation|granularity selection]] accounts for the task, quality, and resource budget.

Consciousness may observe which data preparation selected and change its future work through existing [[#Conscious Program Supervision|supervision]] and [[#Code Anchor as a Control Point|Code Anchors]]. A one-off refinement does not require a new program; a reusable change follows the ordinary Program Lifecycle. Reducing `PreparedContext` does not itself delete experience from Memory: source retention and compaction follow [[Memory|Memory's separate lifecycle]].

Reaching a time or processing-budget limit is handled by the [[#Stopping Execution and Releasing Memory|stop and extension rules]].

---

## Task Execution (`TaskExecution`)

#topic_core

> [!definition]
> **TaskExecution** — the process of executing and resuming a `Task` through conscious steps and delegated Programs.
> ^def-TaskExecution

Execution state is retained in `TaskState`, [[Memory#^def-ProgramRun|`ProgramRun`]], and the trace. Each control step is performed by consciousness or a specific program:

| Responsibility | Owner |
|---|---|
| Choose a conscious step, change the plan or solution method | `Consciousness` for the focused task. |
| Perform assigned work and organize required calls | A specific `TaskManagingProgram` in its `ProgramRun`. |
| Prepare a call and use its result | The immediate caller: a conscious step or program that respects its role restrictions. |
| Propose allocation of conscious focus | `AttentionControl`; `AttentionRuntime` checks and applies the decision. |
| Deliver input, start, suspend, or resume execution | Runtime under established rules and permitted control requests. |

> [!definition]
> **TaskManagingProgram** — a general class of `exec` programs that perform a certain kind of task, such as essay analysis or playing NL Texas Hold'em.
> ^def-TaskManagingProgram

A specific program defines the solution method: it uses prepared context, maintains work state, calls required subprograms, and handles their results. One essay-analysis program may perform many different Tasks; a game-playing program implements another solution method under the same general interface.

One specialization, [[Process Plane/Action Selection and Planning#^def-SkillDevelopmentProgram|`SkillDevelopmentProgram`]], organizes the development of a solution method for a class of tasks. Examples include `PokerPlayProgram` for playing a game and `PokerSkillDevelopmentProgram` for developing the playing skill.

Sketch of the shared Python interface for executable code:

```python
class TaskManagingProgram:
    async def run(
        self, prepared_context: PreparedContext, task_state: TaskState
    ) -> ProgramResult: ...
```

`prepared_context` contains data for the current work; `task_state` contains its resumable state. Both belong to a specific execution, while the reusable [[Process Plane/Program Layer#Program|Program]] retains its shared identity and code version. An implementation specializes the type of the primary result in `ProgramResult`. Consciousness may perform work directly while the Task is focused or delegate it to a suitable `TaskManagingProgram`.

A related new input may resume work using saved state and updated context under the [[#^sequential-tasks|general Task execution order]]. The current `ProgramRun` may continue; choosing a new input does not itself mean the program has started a new run.

In nested composition, each calling program manages its own calls. Consciousness and programs transfer control across established boundaries, with execution history recorded; each control step has one executor.

Delegation specifies assigned work, applicable constraints, and resource budget. For sequential text processing, the controlling program or consciousness uses [[Process Plane/Program Layer#^next-episode-step|`get_next_episode_step`]]; the selected [[Process Plane/Program Layer#^def-EpisodeStep|`EpisodeStep`]] grounds preparation of the required call. The executing program uses child results and, when needed, requests a conscious step for its Task with a reason and necessary context. Once focused, consciousness may continue, recheck, change the method, or stop the work. Automatic and conscious control may alternate multiple times within one task.

**At any moment, EverTree executes at most one `Task`. Parallel execution of different Tasks is prohibited without exception, including automatic, service, and child tasks.**
^sequential-tasks

Nested `ProgramRun`s, subprocesses, and threads belong to the current Task. Helper computations may run in parallel only within it. Before another Task starts or resumes, runtime suspends all executions for the current Task and confirms they have actually stopped; they do not continue or resume while another Task is executing. This also applies when work is delegated to a separate child Task: the parent waits for its result. Task completion follows the [[#Stopping Execution and Releasing Memory|required stop of remaining executors]].

Runtime continues accepting and saving inputs; input for a waiting Task is handled after that Task is admitted for execution. A [[#Planning|`Plan`]] performed through conscious steps does not continue by itself after attention switches. A new result is handled by the current Task's defined continuation or saved until it resumes. Repeated inputs do not require separate Tasks or duplicate entries for one task in the attention queue.

`AttentionControl` runs within the current Task or in a separate service Task while other tasks are stopped. It does not wait to receive `Focus`; otherwise choosing focus would depend on a focus choice that had already been made. Conscious analysis of such control still requires attention.

---

## Planning

#topic_core

**Planning** — building and revising a task-local method for achieving the `objective`.

**Plan** — the current task-local structure of proposed actions, subtasks, conditions, and branches. It is stored in `TaskState` and does not have to become a separate persistent semantic-graph object.

**PlanningProgram** — a specific mechanism for building or revising a `Plan`.

#topic_details

```text
Task specification + TaskState
        ↓
retrieve relevant:
- Programs and ProcessModels;
- similar, contrasting, and boundary Episodes;
- SelfRegulationPrinciples;
        ↓
construct / revise Plan
```

#topic_core

If existing mechanisms are sufficient, the `Plan` specifies how to compose their calls; consciousness or a delegated `exec` program performs the steps under the [[#^def-TaskExecution|general rules]]. A one-off new `Task` may be handled through a `Plan` and conscious steps without creating a new `Program`.

Create a candidate [[Process Plane/Program Layer#Program|`Program`]] or [[Process Plane/Program Lifecycle and Evolution#ProgramBranch|`ProgramBranch`]] only when the missing or changing mechanism is expected to be reused, is sufficiently complex, or needs formalization for reliability or learning.

#topic_details

[[Process Plane/Action Selection and Planning#Runtime Planning|Runtime planning]] is a local call to `PlanningProgram` from a control program, policy, or conscious step when searching available models is expected to improve the decision enough to justify its cost. The conditions for calling it and the priority of a ready compact policy are defined there; MCTS is one possible algorithm.

---

## Conscious Program Creation and Debugging

#topic_details

If a [[#Planning|`Plan`]] requires creating or changing a reusable mechanism, work goes through the `implementation` stage of the shared [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]].

When working on a new or insufficiently checked candidate [[Process Plane/Program Layer#Program|`Program`]], implementation, local execution, and debugging alternate.

#topic_core

The unit of development is a semantic block—a material condition, transition, action, or result—not a file or number of lines. Local checks of a block do not replace candidate-level internal verification, program tests, and Evaluation.

Changes to an existing active `Program` are made in a [[Process Plane/Program Lifecycle and Evolution#ProgramBranch|`ProgramBranch`]]; a fundamentally new mechanism is created as a candidate `Program`. The active version is not rewritten or replaced before [[Process Plane/Program Lifecycle and Evolution#EvaluationChoice|`EvaluationChoice`]].

---

## `Verification` and `CommitmentControl`

#topic_core

### `Verification`

#topic_core

**Verification** is a learnable meta-[[Process Plane/Program Layer#Program|`Program`]] in [[Self#SelfRegulation|`SelfRegulation`]], analogous to a general skill for checking the agent's own decisions. It is not one specific check; it **manages verification of a candidate**:

```text
what is material to check;
which checks are needed;
whether the results obtained so far are sufficient.
```

```text
candidate + existing check results
        ↓
Verification
        ↓
verified
| failed
| need_checks(...)
```

`Verification` cannot waive an applicable mandatory check or return `verified` while a required verification obligation remains incomplete, unless the corresponding protected lifecycle explicitly permits it.

`Verification` is called by [[#Consciousness (`Consciousness`)|`Consciousness`]] or by the process making the current decision—for example, [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|`ProgramLifecycleManagement`]] when changing a `Program`. When needed, `Verification` calls checking Programs as ordinary child programs. Mandatory acceptance checks for a candidate `Program` run through the protected `ProgramLifecycleRuntime`.

After Verification completes, the original calling process separately calls [[#CommitmentControl|`CommitmentControl`]]. `Verification` and `CommitmentControl` do not call one another.

Checking Programs only perform a specific check and return its result. They do not accept a candidate, call `CommitmentControl`, or manage the rest of the lifecycle.

#topic_details

The initial architecture uses one general `Verification`. As experience grows, it may be refined and use specialized Programs for different classes of decision, such as:

```text
Program / ProgramBranch
→ code review, tests, Evaluation;

Plan / material branch
→ check assumptions, requirements, and expected result;

GraphDelta
→ check the semantic change and its grounds;

external action
→ check conditions and expected consequences;

final answer / Task completion
→ source-to-spec coverage when needed
+ check objective, success_criteria,
  and material constraints.
```

#topic_core

Specialized Programs are created only when a separate, reusable verification mechanism is genuinely useful. `Verification` remains one shared skill that decides which checks to use and whether their results are sufficient.

Verification does not make the decision being checked and does not perform effects.

---
### `CommitmentControl`

#topic_core

**`CommitmentControl`** is a learnable meta-[[Process Plane/Program Layer#Program|`Program`]] in [[Self#SelfRegulation|`SelfRegulation`]], analogous to a skill for deciding **when a decision may be made automatically and when it should be referred to [[#Consciousness (`Consciousness`)|`Consciousness`]]**.

```text
caller
  ↓
Verification, if required
  ↓
VerificationResult
  ↓
caller
  ↓
CommitmentControl(
    candidate,
    VerificationResult?
)
  ↓
automatic
or
consciousness_selection
```

#topic_details

Initially, use one general `CommitmentControl`. As it learns, it may use specialized policies for different classes of decision: `Program` changes, `GraphDelta`, Plan branches, external actions, final answers, and other recurring cases.

#topic_core

```python
CommitmentDecision {
  mode: "automatic" | "consciousness_selection"

  reason?: <string>
    "Material reason for or against referring the decision to consciousness."

  belief_data?: <BeliefData>
    "Confidence in this decision."
}
```

---

## Modes of Conscious Processing

#topic_core

^1101e5

`cognition_mode` defines the resource intensity of current conscious processing: available models and tools, reasoning effort, and time and cost limits.

#topic_details

Modes are set through configuration, for example:

- **low** — minimum cost for simple tasks;
- **medium** — standard processing;
- **high** — increased reasoning budget for complex tasks;
- **max** — the highest permitted budget for critical cases.

#topic_core

[[Self#CognitionControl|`CognitionControl`]] selects and, when needed, changes `cognition_mode` within the `ResourceControl` budget and L4 hard limits.

`cognition_mode` does not determine whether a decision is automatic or conscious:

```text
CognitionControl
→ how many resources to use;

CommitmentControl
→ automatic or consciousness_selection.
```

Therefore, expensive processing may run automatically, while a simple decision may be referred to [[#Consciousness (`Consciousness`)|`Consciousness`]] when required by [[#CommitmentControl|`CommitmentControl`]].

---

## Conscious Program Development and Execution Control

#topic_core

Consciousness must be able to create and refine a [[Process Plane/Program Layer#Program|`Program`]] directly while solving a [[#`Goal`, `Task`, and Task Specification|`Task`]], observe its actual execution, check local alternatives against the current process state, and turn successful discoveries into persistent candidate changes. This mode can be viewed as **`test-time programming`**: the agent may build and refine its solution method while applying it to the current task.

The degree of conscious involvement depends on the reliability and maturity of the `Program` in use, novelty of the current situation, uncertainty, importance of the result, and cost of error. A reliable, familiar `Program` usually runs automatically; a rough, new, or insufficiently verified one may run under closer conscious supervision. During supervision, [[#Consciousness (`Consciousness`)|`Consciousness`]] may recheck assumptions and the current trajectory, use [[#Verification|`Verification`]], change the subsequent solution method, and refine the `Program` itself when needed. [[#CommitmentControl|`CommitmentControl`]] determines whether specific decisions are referred to consciousness at the relevant control boundaries.

EverTree does not duplicate the capabilities of Git, coding agents, and standard Python development/debugging tools. Its own runtime is added only where EverTree-specific responsibility is required: [[Memory#^def-ProgramRun|`ProgramRun`]], [[Memory#SemanticTrace|semantic trace]], [[Memory#^def-ResultProvenance|provenance]], [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]], management of live execution, and safe application of changes.

### Principles

#topic_core

#### 1. Native Tools First

> Do not create an EverTree API for operations that a coding agent, such as Codex, already performs reliably with standard tools. Add only operations that carry EverTree-specific semantics or enforce its invariants.

#topic_details

Therefore, a coding agent directly uses its ordinary tools for:

```text
reading, searching, and editing code;
Git operations;
shell;
tests, linters, and type checks;
logs and run results.
```

#topic_core

EverTree does not introduce its own equivalents.

---
#### 2. Isolation of the Protected Core and Executable Programs

`Consciousness` and EverTree's authoritative state reside in a protected core process. Learnable Python `Program` code runs in managed worker processes; [[Core data structures#GraphStore|`GraphStore`]] remains in the protected core.

```text
Core process
├── Consciousness
├── AttentionRuntime
├── authoritative GraphStore / Memory state
├── ProgramLifecycleRuntime
└── execution controllers
          ↕
         IPC
          ↕
Worker process
└── Program execution
    ├── Python runtime state
    ├── ProgramRun
    └── nested ProgramRun
```

This allows the system to independently:

```text
pause / resume / terminate ProgramRun;
retain live runtime state while Consciousness works;
isolate faulty or candidate code from the protected core.
```

#### 3. Reuse of the Worker Process

Related nested `ProgramRun` instances execute in the same worker process. A new worker is created only when parallel, isolated processing within the current Task is clearly necessary. A worker with unfinished executions for one Task is not reused for another.

#### 4. A `Program` Does Not Directly Change Authoritative Core State

A worker has no direct write access to the authoritative GraphStore, Memory, or protected lifecycle state.

```text
Program
→ result / proposed GraphDelta / effect request

Core
→ validate
→ apply.
```

#### 5. Unambiguous Identification of the Code Actually Executed

A coding agent may freely change the candidate workspace, but a code version is applied to execution only after a Git commit.

```text
edit
↓
commit
↓
execute / apply revision
```

Git therefore remains the single mechanism for identifying executable code, including intermediate experimental revisions.

### Durable Execution and Recovery Through DBOS

^durable-program-execution

#topic_core

In the MVP, **every run of a registered [[Process Plane/Program Layer#Program|`Program`]] executes as a DBOS workflow**. This is one runtime rule for every role and execution duration. The runtime registers the program with DBOS and manages its launch; program code does not need a separate choice of whether to make a run durable.

A **workflow** is a Python function with an execution journal that DBOS can use to recover its work. Each [[Memory#^def-ProgramRun|`ProgramRun`]] corresponds to a separate workflow execution. Calling a child `Program` creates a child workflow; ordinary helper functions remain part of the calling program.

Each `Program` returns [[Process Plane/Program Layer#^def-ProgramResult|`ProgramResult[T]`]]; this contract does not change the return shape of ordinary Python helper functions.

One rule lets the runtime recover and replace any `Program` through the same protocol. The cost is journal storage and additional time for every run, including short models. The MVP accepts this cost to simplify execution management.

In the local MVP, DBOS stores the journal in SQLite. A runtime adapter links its entries to `ProgramRun`, [[Memory#^def-TraceEvent|`TraceEvent`]], and results. The DBOS journal is for continuing execution; the semantic trace stores the meaning and provenance of experience. [DBOS integration](https://docs.dbos.dev/python/integrating-dbos)

#### How Execution Is Recovered

A **step** is a call within a workflow whose result DBOS saves. During recovery:

1. The code versions and inputs from the previous run are loaded.
2. The workflow code runs from the beginning. For completed steps and child workflows, DBOS returns their saved results. Ordinary local computations run again.
3. Execution continues from operations whose results have not yet been saved.

This also restores local variables. DBOS does not save the entire Python stack or resume from an arbitrary line of code. Recovery continues the same `ProgramRun`; reading a previous result does not create a new observation or learning credit.

> Everything required to continue must be recoverable from saved code versions, inputs, and operation results.

For this to work, the same inputs and saved results must lead to the same order of calls. This is a requirement on program code; integrating DBOS does not ensure it by itself. [Workflow execution](https://docs.dbos.dev/python/tutorials/workflow-tutorial)

#### Which Operations Become Steps

- LLM calls, reads of mutable graph state, external requests, actions, and reads of time or random values run through steps or DBOS operations that already save their results.
- Computations that repeat with the same inputs may remain ordinary functions. An expensive calculation may be made a step so its result is saved.
- Calls to other `Program` instances run in workflow code. They cannot be placed inside a step: DBOS does not allow a workflow to be called from a step.

A `Code Anchor` marks a semantically significant region of a program; a step marks the boundary at which a result is saved. Their boundaries may differ. A nested step call inside another step is saved only with the outer step; the semantic trace may still describe its internal operations. [Step rules](https://docs.dbos.dev/python/tutorials/step-tutorial)

Inputs and results must be serializable. Semantic results are saved as immutable [[Memory#^def-OperatorOutput|`OperatorOutput`]]. A reference may be saved instead of a value if it returns the same saved content after failure, including the required object version.

Code, inputs, results, and the journal are retained while a run may need recovery. Semantic trace compression must not delete data required for this.

#### Receiving Observations

[[Process Plane/Program Layer#^next-observation|`next_observation()`]] reads the shared observation channel for this execution through `DBOS.recv_async`. It is an ordinary async function in workflow context and needs no additional step because DBOS already saves the receive result.

The sender passes a typed result or reference through `send`. The adapter validates the schema and detects redelivery by observation ID. On recovery, previous inputs are returned first, then new messages are read in delivery order. The process program accounts for the times of the events being described. [Workflow communication](https://docs.dbos.dev/python/tutorials/workflow-communication)

#### Regular Agent Backup and Recovery
^agent-backup

For the MVP, it is enough to save the entire agent regularly. **After a failure, core and the DBOS journal are restored from one completed backup.** Work after that backup may be lost. A separate core change journal and immediate persistence of every update are not required.

The runtime performs a shared backup at a configurable interval:

1. It pauses new runs, subsequent workflow operations, input handling, and other changes to saved state. It lets already-started steps finish and write their results to DBOS. The pause is reached between operations, when core state and the journal are consistent; waiting for a future observation does not require waiting for that observation to arrive.
2. It saves core state—the graph, memory, trained parameters, and tasks—and the DBOS database as one set. The set includes bindings to program versions; required code versions and result files are saved with it or remain available as immutable dependencies.
3. Only after the full write succeeds does it mark the new backup complete and resume work. The previous completed backup remains available while the new one is being created. If a consistent pause cannot be reached, backup creation is deferred.

The [SQLite Backup API](https://www.sqlite.org/backup.html) is used to copy the database. It ensures consistency of the SQLite copy; the runtime pause described above ensures consistency of the full set.

During recovery, the entire selected set is loaded before workflows are allowed to resume and new inputs are accepted. A newer working DBOS journal is not combined with older core state. Internal updates after the backup are lost along with their records and may be recomputed from the restored state.

External actions are not undone by this rollback. After a failure, they may be repeated, as may individual operations whose results DBOS did not save in time. The MVP accepts these repeats and does not require universal protection for every command or automatic determination of every action's outcome. Existing repeat checks in specific operations remain in place.

#### Stopping Execution and Releasing Memory

Each workflow belongs to a `Task` and is linked to a parent run, if one exists. The runtime tracks the entire tree of executions it creates, including subprocesses and threads created directly or through child executions. The task program ends work that is no longer needed. `AttentionControl` proposes continuing, deferring, or canceling; `AttentionRuntime` applies those decisions and limits the number of live executions and worker resources.

**When a Task ends with any final outcome, including cancellation, the runtime forcibly ends all its remaining workflows, subprocesses, and threads that the task did not end itself.** Workers that own them are terminated if necessary. A Task is considered complete only after its entire tree has actually stopped; another Task does not start before then. Runs belonging to a completed Task cannot be started or recovered, including through automatic DBOS recovery.

When estimated [[#Execution Budgets|`execution_budget`]] is exhausted, consciousness reviews whether to continue. It analyzes `TaskState` and the specific trace: whether there is progress, what is blocking it, how close the result is, and whether more cost is justified by the importance of the goal. Consciousness may extend work with a new limit, allow it to wait, change the solution method, defer the task, or stop execution, requesting a forced stop (`force-kill`) if needed. Execution pauses at a permitted runtime boundary until continuation is authorized. Intermediate results, Task state, the decision, and its grounds are retained for review and possible resumption.

An extension is allowed within `ResourceControl` and L4 hard limits. The runtime enforces these hard limits and its watchdog regardless of whether consciousness is available. Extending the execution budget does not automatically change the result deadline in the task specification. Stopping execution does not delete the Task or its history; its subsequent status and obligations are determined separately.

Limits are checked at launch, resumption, and automatic DBOS recovery. Usage by child calls, delegated subtasks, parallel work within a Task, and retries counts toward applicable shared budgets, with each budget charged once. An extension preserves the Task and its accumulated usage. Restarting, using a new revision, or recreating a continuation of the same work does not reset accounting or remove limits. A separate workflow does not require a separate worker.

Exhausting a revisable budget is not itself a violation. [[Learning system#^outcome-credit|Evaluation and learning from the Task outcome]] may consider whether resources were allocated reasonably and whether the budget was reviewed in time; hard-limit violations are assessed separately. A violation alone does not identify the responsible mechanism.

Pausing before a `Code Anchor` and waiting through `await` leave execution state in memory. To release memory, the runtime cancels the workflow through DBOS, retaining the deferral reason and return condition in `TaskState`. Cancellation usually takes effect before the next step; interruptible async steps use `preemptible`. Resources are counted as released only after execution has actually stopped, not immediately after the status changes. If execution hangs or does not stop within the allowed time, the runtime forcibly terminates the worker under established limits. This may affect other executions on that worker. Continuation uses [[#^program-restart-continuation|saved operation information]]; permitted repeats after lost records follow the [[#^agent-backup|MVP recovery rules]]. [Workflow management](https://docs.dbos.dev/python/tutorials/workflow-management)

When canceling all workflows for a Task, the runtime explicitly sets `cancel_children=True`; processes and threads it created are stopped under the shared rule above. To continue an unfinished Task after it is admitted for execution, the runtime resumes the required workflows with `resume_workflow`: resuming a parent does not itself resume canceled children. Inactive database records do not count against the number of live executions. Their history is deleted when it is no longer needed for recovery or agent memory. [Managing an execution tree](https://docs.dbos.dev/python/reference/contexts#cancel_workflow)

#### Code Changes and Restart
^program-restart-continuation

**In the MVP, a newly committed version starts from the beginning of the function in a new `ProgramRun` / workflow and continues the same Task.** The old run may finish on its previous version; for immediate replacement, the runtime first confirms that it and any unnecessary child executions have stopped. The trace retains both runs, the reason for replacement, and continuation state.

The calling program or consciousness prepares continuation from `TaskState` and the trace: completed operations and results, remaining work, unprocessed observations, and unknown outcomes. The new version receives these through its interface. Results compatible in inputs, dependencies, and meaning are reused with their original provenance, without a new observation or learning credit; recomputation requires grounds. The Task, memory, and completed effects remain. Correcting an effect is a separate action.

For an external action, the runtime atomically checks and records the operation identity within the Task, its parameters, and status; the result is saved when received. The identity persists across run replacement. A repeated request returns the previous result or waits for the in-progress operation without executing it again; different parameters with the same identity are rejected. An intentional new action gets a different identity, even if the command is the same. Existing accounting is used for [[Learning system#PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher|parameter updates]].

A command accepted by an external system is not sent again; its effects are checked separately. If the outcome is unknown, the runtime must reconcile with the source or use supported idempotency with the original key. Dependent continuation waits until the outcome is resolved.

If the new version does not accept the continuation state or cannot map the operations, automatic restart is prohibited: consciousness prepares a compatible continuation or defers the replacement. When replacing a child, the parent explicitly calls the new version; if it cannot do so, the parent is stopped and replaced under the same rules.

The Python stack and DBOS journal are not automatically carried into a new run. Required continuation data is included in the [[#^agent-backup|shared backup]], with its limitations. After a failure, recovery continues the old `ProgramRun` using its saved code and journal. Changing code within a live run remains an [[#Interactive Revision Change Within the Current `ProgramRun`|optional interactive capability]].

### Persistent Changes to a `Program`

#topic_core

Persistent changes to a `Program` follow the ordinary Program Lifecycle. `ProgramLifecycleRuntime` owns [[Process Plane/Program Lifecycle and Evolution#ProgramBranch|`ProgramBranch`]], lifecycle state, and merge/activation through [[Process Plane/Program Lifecycle and Evolution#EvaluationChoice|`EvaluationChoice`]].

### Main Development Loop

#topic_details

Default path:

```text
write / edit candidate
        ↓
commit
        ↓
run
        ↓
SemanticTrace + logs + tests + outcome
        ↓
Consciousness / coding agent analysis
        ↓
edit
        ↺
```

This is preferable to step-by-step Python debugging: `SemanticTrace` directly shows significant [[Process Plane/Program Layer#OperatorConcept, Code Anchors, and AnchorResolver|`OperatorConcept`]] instances, their arguments, outputs, nested `ProgramRun` instances, and provenance.

A new version launches under the [[#Code Changes and Restart|shared restart rules]].

### Conscious Program Supervision

#topic_core

For a new, rough, or insufficiently automated `Program`, consciousness may directly supervise its execution.

#topic_details

```text
ProgramRun
↓
execute semantic blocks
↓
Code Anchor
↓
when needed:
pause worker
↓
request a conscious step for the Task
→ Attention, if the Task is not already in Focus
↓
Consciousness for this Task in Focus
→ inspect trace / current state
→ retrieval / reasoning / Verification
→ continue
  or change the candidate
```

#topic_core

`Conscious Program Supervision` is not a separate `run_mode`.

If a suitable `Program` does not yet exist, `Consciousness` solves the `Task` through a `Plan`, existing Programs, and direct cognitive steps. A candidate `Program` is created when the discovered mechanism is expected to be worth formalizing and reusing.

#### `Code Anchor` as a Control Point

[[Process Plane/Program Layer#Code Anchors|`Code Anchor`]] provides semantic observability and a boundary available for conscious control.

#topic_details

Source code:

```python
state = prepare_state(ctx)       # et:op=prepare_state
decision = choose(state)         # et:op=choose
result = execute(decision)        # et:op=execute
```

When a `Program` is loaded, the runtime instruments it so that a control hook exists before every anchored block:

```text
before anchor
↓
continue immediately
or
pause worker → request a conscious step for the Task
→ obtain Focus through Attention, if required
→ Consciousness decides what happens next
→ resume, if continuation is chosen
↓
execute anchored block
↓
TraceEvent
```

#topic_core

During ordinary execution, hooks pass without stopping. Pausing a background `ProgramRun` does not itself take `Focus`: a request for a conscious step goes through the shared attention mechanism. If the Task is already in Focus, control continues in its current conscious cycle.

Consciousness may also request:

```text
pause current ProgramRun
→ stop it before the nearest Code Anchor.
```

If a semantic block contains another Code Anchor, it provides an additional available control point.

Thus, the granularity of conscious control is determined by the `Program`'s semantic surface, not by arbitrary Python lines.

#### Interactive Revision Change Within the Current `ProgramRun`

This is an optional extension to interactive mode and is not required for the MVP. If the runtime supports it and preserving the current execution state matters, consciousness may change an unexecuted reloadable operator and continue the same `ProgramRun`.

#topic_details

```text
ProgramRun executes
↓
pause before Code Anchor
↓
Task in Focus; Consciousness chooses a change
↓
coding agent changes a future operator
↓
commit new revision
↓
runtime loads the new implementation
↓
ProgramRun continues with saved state
```

For example:

```python
x = operator_a(ctx)       # already executed
y = operator_b(x)         # paused before anchor
z = operator_c(y)
```

#topic_core

After changing and committing `operator_b`, the current `ProgramRun` may continue by calling the new implementation with the already computed `x`.

This is possible only for code not yet executed that the runtime can independently reload or rebind. An already active Python frame does not switch to a new code object.

The runtime retains exact Git revisions and compatibility with the DBOS application version. If the order of durable operations changes, use DBOS versioning or `patch` as provided; a `ProgramRevisionChange` record alone is not sufficient. If a change affects the active frame or breaks history replay, the new version starts in a new `ProgramRun` under the [[#^program-restart-continuation|rules for continuing completed work]]. [Upgrading workflow code](https://docs.dbos.dev/python/tutorials/upgrading-workflows)

##### Recording Revisions Within a `ProgramRun`

A `ProgramRun` starts from one exact Git revision:

```text
ProgramRun.base_commit_sha
→ revision on which execution began.
```

If another committed revision is applied to code not yet executed during `Conscious Program Supervision`, the runtime creates an immutable record:

```python
ProgramRevisionChange {
  commit_sha: <string>
    "Revision from which new implementations were loaded."

  applied_before_anchor_id: <string>
    "Full anchor ID op:<code_node_id>:<op_id>, before whose next execution
     the revision was applied."

  after_trace_seq?: <int>
    "Sequence of the last already executed TraceEvent in this ProgramRun.
     Absent if the revision was applied before the first TraceEvent."

  applied_anchor_ids: <string[]>
    "Anchors whose implementations were reloaded from this revision for
     further execution in the current ProgramRun."
}
```

`after_trace_seq` identifies the dynamic application point. Therefore, repeated execution of one anchor in a loop or recursion remains unambiguous.

`ProgramRun` begins with `base_commit_sha` and accumulates ordered `ProgramRevisionChange` records when live revisions are applied.

Already created [[Memory#^def-TraceEvent|`TraceEvent`]] instances are never rewritten.

A revision may be applied within the current `ProgramRun` only to code sites the runtime can independently reload or rebind. Code in an already active Python frame does not switch to the new revision.

### Minimal EverTree Runtime Interface

#topic_core

Standard coding operations remain with the coding agent. EverTree adds only `ProgramRun` control; `run_ref` addresses a specific run, resolved by core runtime under the [[Core data structures#Objects and References|shared object and reference rule]]:

```python
request_pause(run_ref)
resume_program(run_ref)
terminate_program(run_ref)
```

`request_pause` stops the worker before the nearest `Code Anchor`.

Only when the [[#Interactive Revision Change Within the Current `ProgramRun`|optional interactive revision change]] is supported, add:

```python
apply_program_revision(
    run_ref,
    commit_sha,
) -> ApplyRevisionResult
```

`apply_program_revision` applies a committed revision to reloadable code in the current run that has not yet executed, and returns:

```text
applied
→ revision applied;

requires_new_run
→ the change affects an active frame or is incompatible
  with workflow recovery and requires a new ProgramRun.
```

Retrieval, reasoning, Verification, tests, and Evaluation use existing Programs and coding tools; separate runtime APIs are not needed for them.

### Low-Level Debugger

A full Python debugger is not part of the MVP.

#topic_details

By default, use:

```text
SemanticTrace + logs + tests
+ exception traceback
+ Code Anchor supervision.
```

#topic_core

Add `debugpy` / DAP only if practice shows a persistent need to inspect the internal state of an executing Python frame below the semantic surface.

---

## High-Level Conscious Processing Cycle
^agent-processing-cycle

#topic_core

The shared cycle connects incoming data to a task and episode, retrieves relevant experience from Memory, and uses it to choose the next work. [[#^def-PreparedContext|PreparedContext]] gives the work owner shared context; [[Process Plane/Program Layer#^def-EpisodeStep|EpisodeStep]] selects the next portion to process, and argument preparation turns it into a specific call. The owner is consciousness for a Task in Focus or a suitable [[#^def-TaskManagingProgram|TaskManagingProgram]]. Control handoffs preserve the task and its state and may recur at different stages.

Preparation selects useful experience, while [[Process Plane/Program Layer#^granularity-adaptation|granularity control]] selects an appropriate level of detail within the budget. When learning a process model, this allows significant transitions to be forecast and checked separately; for familiar tasks, it can reduce processing costs.

### Overall Flow

#topic_details

```text
external request / data / tool result
    → save to Memory; link to Task and Episode
Goal / internal Event / Replay → create or continue a Task
                                  ↓
             Task + Episode + incoming input + saved experience
                                  ↓
                 ContextPreparation → PreparedContext
                                  ↓
    ├─ TaskManagingProgram → program-managed task execution
    └─ conscious step needed → AttentionPriorityQueue
           → AttentionControl → AttentionRuntime → Focus → Consciousness
                                  ↓
                 program or consciousness selects the next work
                 → if a text fragment is needed: get_next_episode_step
                 → target Program and its contract
                 → ready arguments or arguments_formatter
                 → call ProcessModel or exec-Program
                 → ProgramResult → continue / wait / check
                                  ↺

for an action selected by either control path:
    applicable Verification and CommitmentControl
    → execute action / GraphDelta / send response
    → observed outcome → Memory and related Task / Episode
```

#topic_core

The flow describes [[#^def-TaskExecution|TaskExecution]]. Receiving data does not require Focus; preparing context and automated work outside Focus are allowed only for the [[#^sequential-tasks|currently executing Task]]. If a program needs a conscious choice, the Task requests attention; consciousness may then hand further work back to it. Child calls continue the same task. `Perception`, `TaskFraming`, `Planning`, and checks are used as needed: for example, perception represents a new source as an Observation, while TaskFraming clarifies a request that is not yet clear.

The latest input is retained in `PreparedContext` in full. The work owner and the mechanism selecting the next EpisodeStep may use it; the target model receives the selected step and the data it needs through its contract. The full `PreparedContext` is not forwarded automatically.

### Selecting the Next Step and Nested Calls

#topic_details

```text
Task / Episode + PreparedContext + values and remaining input
    ↓
TaskManagingProgram or Consciousness for the Task in Focus
    → clarify the task / obtain information / revise the Plan if needed
    ↓
select next work:
    ├─ process input or text assembled by a program
    │      → assemble TextInput and set complete
    │      → get_next_episode_step(...)
    │      ├─ step returned → retain step and remaining text
    │      └─ step=None → wait for continuation, finish parsing,
    │                     or clarify the method based on the input state
    ├─ another call using available data
    └─ action / handoff / wait / stop / finish

for a call: target Program and its contract
    ready arguments or arguments_formatter(program, prepared_context, ...)
    ├─ ArgumentsNotReady → clarify / obtain data / wait
    └─ Arguments → runtime calls Program → ProgramResult to caller
    ↓
result / feedback / updated state and remaining input
    ↓
continue processing / rebuild PreparedContext / select action /
hand off / wait / finish Task under its conditions
```

#topic_core

[[Process Plane/Program Layer#^next-episode-step|`get_next_episode_step`]] receives [[Process Plane/Program Layer#^def-TextInput|`TextInput`]] and returns a selected fragment with the remainder. Before calling it, `TaskManagingProgram` or consciousness sets `complete`: whether transmission of this specific input is complete under task conditions or a source signal. Planning, checks, and other calls on ready data do not require splitting. A target program may already be known from the plan, in which case its contract informs fragment selection; otherwise, it is determined from the selected work and data. An empty remainder means the available text is exhausted; the Task's conditions determine whether its goal is achieved.

To prepare arguments, the calling program or consciousness uses [[Process Plane/Program Layer#^def-ArgumentPreparation|`arguments_formatter`]]: it passes the target Program, `PreparedContext`, and, when needed, selected sources, known bindings, and clarifying instructions. The preparer returns arguments or [[Process Plane/Program Layer#^def-ArgumentsNotReady|`ArgumentsNotReady`]]; the current EpisodeStep is retained for continuation. The immediate caller runs the ready call. If all arguments are already known and conditions are met, no separate preparation is needed.

[[Process Plane/Program Layer#^input-preparation-pipeline|Nested calls]] follow the same principle with their specific caller. For a conscious step, [[Self#CognitionControl|`CognitionControl`]] chooses `cognition_mode` within budget; consciousness may inspect the trace, select or create programs, check results, and change the solution method. Preparation may be adjusted for the selected mode. Another conscious step is possible while the Task remains in Focus; automated work continues only while the Task is admitted for execution, otherwise it waits.

A normal call returns to the execution that awaited it. Long-running delegated work may continue without holding conscious Focus. During [[#Conscious Program Supervision|`Conscious Program Supervision`]], a request for a conscious step occurs at an available boundary, such as before a [[#`Code Anchor` as a Control Point|`Code Anchor`]]; it does not bypass `Attention`. Such boundaries do not cause pauses during ordinary automated execution.

### Actions, User Responses, and Task Completion
^actions-and-user-response

#topic_core

A proposed effect may arise during either a conscious step or an automated `exec` program. When required, the decision owner calls [[#Verification|`Verification`]], receives its result, and then separately calls [[#CommitmentControl|`CommitmentControl`]] at the applicable boundary. In `automatic` mode, the owner accepts, rejects, or revises the candidate itself; the effect is initiated only after acceptance and satisfaction of required conditions. In `consciousness_selection` mode, it retains the candidate and context for a conscious step in its Task; if the Task is already in `Focus`, the decision is considered in the current cycle without queuing it again. Neither Verification nor CommitmentControl executes the effect being checked.

The accepted action is carried out by the appropriate execution mechanism through the runtime, which checks protected constraints and [[#^program-restart-continuation|prevents the same operation from executing twice]]. The runtime applies an admissible request but does not invent an action or select it based on the task's meaning. The execution result or error is saved and returned to the related call or task.

The text of a composed response is an internal result. **Sending a response to a user is a separate external action** with a specific recipient, channel, and content, subject to the same applicable rules. Returning `ProgramResult`, sending a message, and completing a Task are different events. A clarifying question usually leaves the task waiting for a reply; an intermediate message leaves it in progress; a final response completes it only when the objective, success criteria, and required conditions are satisfied. A send error is not treated as successful delivery.

Therefore, preparation that detects missing data returns that information to the caller. The caller decides whether to request information from the user, read another source, wait for continuation, or change the solution method. Feedback by itself does not authorize sending a message or taking an external action.

### Checking the Overall Flow Against Scenarios

| Scenario | Execution path |
| --- | --- |
| New complex request | Runtime saves the input in Memory and links it to a minimal Task and Episode. ContextPreparation builds a PreparedContext with the complete input; after Attention selects it, consciousness clarifies the specification and Plan, determines the EpisodeStep, calls Programs through argument preparation, and separately arranges to send the result. |
| Count letters in a word spread across messages | The task begins when the instruction arrives; preparation gathers arguments from the specified sources, a program counts the letters, and the caller arranges delivery of the answer. [[#^dialogue-word-count|Example below]]. |
| Required argument is missing | Preparation returns an unresolved condition; the step owner chooses a clarifying question, sends it, and waits. The related user reply continues the same Task. |
| Result of a long-running command | Input is saved and delivered through the call link independently of Focus. Once the Task is admitted for execution, its managing program uses the result and Task/Episode context to continue; if no automated step follows, the Task waits for conscious processing. |
| Urgent observation during a long calculation | Input reception saves it. The current Task's handler takes an allowed response or requests a conscious step; switching to another Task first follows the shared rule. A queued item alone does not ensure a timely response; [[Process Plane/Program Layer#Types, Conditions, and Subprograms|input processing]] must not depend on a long child calculation finishing. |
| Replay | A separate Task returns to saved experience and uses the same cycle for conscious or delegated automated steps. Sources retain provenance; previous external actions are not automatically repeated. |

### Example: Counting Letters in a Word Across Messages
^dialogue-word-count

#topic_details

The user sends `straw`, then `berry`, then: “Join the previous two messages without a space and count the letter r in the resulting word.” The counting task begins with the third message; the first two are source data from the related dialogue Episode. ContextPreparation includes the full latest request and retrieves the two needed sources from Memory.

Consciousness or TaskManagingProgram uses PreparedContext and selects the next EpisodeStep: process the specified word as a whole. The selected function is `count_letter_in_word(word: str, letter: str)`; its interface links the parameters to the semantic concepts “word” and “character.” The `arguments_formatter` program prepares `word="strawberry"` and `letter="r"` from the request and source fragments, retaining provenance. Ready values may be passed directly without a separate preparation call.

The caller launches the program: ordinary code counts the characters and returns `ProgramResult(result=3, feedback=None)`. The caller then arranges [[#^actions-and-user-response|sending the response]] to the user. Thus, source blocks are messages, the argument is the complete word, and the unit counted is a character; no LLM call is needed for each letter.

The instruction, not message adjacency, justifies joining the fragments. If their relationship is ambiguous, preparation returns an unresolved condition for clarification. If the user instructed the agent in advance to wait for parts of a word and then count its letters, the task exists before those parts arrive, and the messages continue it.

#topic_details

Experience recording accompanies both execution paths. Returning `ProgramResult.result` means a call has produced a result, but not necessarily an [[Process Plane/Program Layer#Outcome|evaluated process outcome]]. For example, a forecast may be returned now while the observation needed to check it arrives later. If the result already contains enough outcome data, evaluation may happen immediately; otherwise, the task retains the expected link to future observations.

```text
Program execution
→ ProgramRunRecorder
→ TraceEvent / Memory;

result + enough data about the evaluated outcome
→ applicable Evaluation
→ learning credit and permitted updates / Learning;

Task / Episode completion
→ integration
→ optional Reflection / Replay /
  Program improvement.
```

#topic_core

Reflection may also occur within an unfinished [[#`Goal`, `Task`, and Task Specification|`Task`]]. [[Learning system|Learning from evaluated outcomes]] happens as sufficient data arrives and does not wait for the entire `Task` or [[Memory#^def-Episode|`Episode`]] to finish. A program returning or moving to the next EpisodeStep does not replace Evaluation or create learning credit. Assessing observations as epistemic evidence follows a separate [[Learning system#LearningCoordinator|LearningCoordinator]] path and does not require turning every observation into a forecast check. [[Memory#ProgramRunRecorder|`ProgramRunRecorder`]] records experience and episode-level integration is described in [[Memory]]; Reflection and Program improvement are described in [[Self]], and Program lifecycle in [[Process Plane/Program Lifecycle and Evolution]].
