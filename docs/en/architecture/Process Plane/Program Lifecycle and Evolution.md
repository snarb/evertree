## Program Evolution, Selection, and Improvement

EverTree programs evolve as testable hypotheses.

`Program` is a stable identity for a mechanism that models or executes a process.

`ProgramBranch` is a temporary change line for an existing `Program`.

Create a new `Program` when the solution principle itself changes. Create a `ProgramBranch` when the main mechanism remains, but its details, parameters, edge cases, contracts, local structure, or implementation are refined.

Every new program or branch must have an explicit hypothesis:

```text
what change is proposed
→ why it should help
→ which signals or metrics should improve
→ how it will be evaluated
```

A program does not become active just because an idea seems reasonable.

Reasoning, LLMs, literature, memory, analogies, and external sources produce candidates and priors. A program becomes active only after verification, Evaluation, and `EvaluationChoice`.

Evaluation does not have to end immediately in acceptance or rejection. If evidence is insufficient, a candidate may remain under consideration while the agent gathers more data through replay, simulation, new `ProgramRun`s, real observations, or specially created `EvaluationCase`s.

This is not a separate lifecycle or a separate `LiveValidation` entity. It is the ordinary state of an unfinished choice: multiple alternatives remain live while support is insufficient.

---

### General Program Lifecycle

All Programs go through the same lifecycle, regardless of their [[Program Layer#Program Roles|roles]].

```text
trigger
→ gather_relevant_info
→ reasoning_and_synthesis
→ candidate change
→ implementation / semantic update
→ verification
→ program tests
→ training on TrainingDataset if needed
→ Evaluation
→ evidence accumulation if needed
→ EvaluationChoice
→ merge / activate / continue / reject / archive / keep alternatives
```

A candidate may first be trained on a [[Learning system#^def-TrainingDataset|`TrainingDataset`]]. For comparison on an [[Program Evaluation and Testing#EvaluationDataset|`EvaluationDataset`]], the baseline model and candidate use the same dataset version, respecting [[Datasets#Training and Evaluation Boundaries|evaluation independence]]. Dataset management follows the [[Datasets#Lifecycle|shared dataset lifecycle]].

Programs differ not in their lifecycle, but in the requirements checked for their primary roles and modifiers.

When creating or revising a program, select and complete a [[Program Layer#ProgramDesign|`ProgramDesign`]] profile. Verification compares declared design decisions with the implementation, including branches before action selection, adaptation, exploration, and the learning path. Behavioral requirements are checked through tests and Evaluation.

#### Preparing Initial Models
#topic_core

First reuse suitable programs, rules, tables, and trained state. If they are insufficient, a bounded consciousness session using an LLM and external research prepares the missing implementation and defines its scope of applicability.

This is the shared preparation path for different kinds of initial assumptions:

| What is prepared | Meaning of the result |
|---|---|
| Initial policy | Action-selection rule, action preferences, or initial strategy parameters |
| Epistemic prior | Probability of a target before the agent's own evidence |
| Observation model | Probability of an observation result under each target state |

Preparation, storage, evaluation, and later learning are shared. These outputs retain their own types; they are not combined into a universal `Prior` entity. An initial policy preference is not a probability that a belief is true and does not create epistemic `Support`.

The result is saved as code, settings, or a model artifact for an existing Program with a typed interface. An approximate model may run as code from day one; the quality of its supporting basis is checked separately. Evaluation may justify using a limited fallback before precise calibration is available, provided the contract, scope of applicability, and influence limits are respected. This decision goes through the ordinary `EvaluationChoice`.

A new instance of a process, target, or state under known conditions does not require preparation again. New data update planned parameters; material differences in conditions may require separate state or a new version. Replacing an LLM-based path with code is decided by quality and total cost, including maintenance and evaluation. The specific belief preparation path is described in the [[Uncertainty and Belief Tracking in the World Model#Assessment Lifecycle|assessment lifecycle]].

#### Primary Role: `model`

A `Program` with `model ∈ Program.roles` answers:

```text
how does the process work, and what does it predict?
```

Its initial version must be sufficient to:

```text
- make the key transition predictions for this process;
```

Starting example:

```text
in situation S
if transition/action X occurs
then outcome/profile Y is likely
```

Typical initial sources:

```text
memory
similar ProcessConcept and TransitionType
LLM/general priors
simulation / dataset
```

This `Program` does not select an action directly. It returns predictions, profiles, or expected signals that may be used by an `exec`-role `Program`, a [[Action Selection and Planning|local selection policy]], planning, or consciousness selection.

#### Primary Role: `exec`

A `Program` with `exec ∈ Program.roles` answers:

```text
what does the agent do in this process?
```

Its minimal initial version is a working structure for the agent's actions in this process.

Typical initial sources:

```text
similar executable programs
expert strategies/imitation
LLM/general priors
dual model program
```

A `Program` with primary role `exec` may use a `Program` with primary role `model`:

```text
model ∈ Program.roles
→ predictions / expected signals / process understanding

exec ∈ Program.roles
→ candidates / control flow / policy programs / actions
```

A declarative model does not select an action directly. An executable program selects actions through ordinary control flow, a policy program, planning, or consciousness selection.

#### Candidate Change

The result of `reasoning_and_synthesis` does not have to be code immediately.

It may produce different kinds of changes:

```text
semantic change
→ refine ProcessConcept, relation, PROCESS_VARIABLE, contract, or scoped semantic link

parametric update
→ change weights, priors, values, probabilities, or other parameters without changing structure

ProgramBranch
→ change an existing Program while preserving the main mechanism

new Program
→ an alternative approach with a different solution principle

EvaluationCase
→ a new evaluation scenario, when the problem is better expressed as a test for now
```

If a change requires code edits, it proceeds through a `ProgramBranch` or a new `Program`.

If it affects only the graph, semantic links, or contracts, it must still be testable through replay, `EvaluationCase`, `ProgramRun`, simulation, or subsequent observations.

#### Verification and Program Tests

A candidate `Program` or `ProgramBranch` undergoes general `Verification` after implementation. `Verification` determines which additional checks are needed and whether the results are sufficient.

`Program tests` are ordinary qualitative development tests: unit, behavioral, adversarial, property-based, smoke, and other suitable checks.

For an `exec` program with effects, verify the [[Cognition and Attention#^program-restart-continuation|continuation-without-duplication contract]] when replacement during a `Task` is supported, including replacement of a parent program.

Program tests are not the primary way to choose between competing programs. They are used to:

```text
- find implementation defects;
- prevent regressions;
- refine a candidate;
- bring a branch to a state suitable for Evaluation.
```

Candidates are compared through `Evaluation`.

#### Evaluation

`Evaluation` is a quantitative check of a program, branch, or hypothesis on an `EvaluationCase` or `EvaluationDataset` built from memory, simulation, offline data, generated scenarios, and other evidence sources.

Evaluation returns outcome metrics, including signals from [[Evaluative-Control System]]:

```text
prediction_unexpectedness
supervisor_feedback_signal
tension_reduction
and other target metrics
```

[[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] helps detect discrepancies for analysis; minimizing it is not a model-selection criterion. Candidates' predictive quality is compared on independent data using the same criteria fixed in advance, accounting for both outcome fit and forecast informativeness.

Evaluation is not the same as new real-world experience. Real events can provide evidence, but they enter the choice only after projection onto the process, program, and measurable criteria.

#### Evidence Accumulation

If the data are insufficient, the agent does not have to accept or reject a candidate immediately. It can keep one or more alternatives in candidate status while continuing to gather evidence.

A candidate remains under consideration while:

```text
- several alternatives are still viable;
- no active version has been selected;
- evidence/support is insufficient for EvaluationChoice.
```

If there is one program and it has already been accepted for use, a separate evidence-accumulation status is unnecessary. New observations simply update beliefs, parameters, or contracts, or create the next improvement trigger.

#### EvaluationChoice

`EvaluationChoice` is a conscious decision about a candidate's fate after Evaluation and evidence accumulation.

Evaluation provides metrics. EvaluationChoice makes the decision.

Possible outcomes:

```text
merge_branch
→ accept the change to an existing Program and merge the branch into main

continue_branch
→ evidence is insufficient or the candidate needs more work; keep the branch active

reject_branch
→ the branch hypothesis lacks sufficient support; archive or delete the branch

create_new_program
→ the change is no longer a branch and needs a separate Program

activate_program
→ the Program linked through PROGRAM_FOR_PROCESS becomes
  ProcessConcept.active_model or ProcessConcept.active_exec

reject_program
→ the alternative loses and receives lifecycle_status="rejected"

keep_alternatives
→ several programs remain candidates because evidence is insufficient

archive_program
→ the program is no longer needed as an active candidate but is kept
  for history, replay, or future analogy
```

Active process slots (`ProcessConcept.active_model` and `ProcessConcept.active_exec`) are updated only through `EvaluationChoice`.

#### Operational Flows

Improving the current program:

```text
active code is in main
→ create ProgramBranch
→ write / edit code
→ update program tests
→ commit changes
→ run EvaluationDataset
→ EvaluationRun → EvaluationResult[]
→ create EvaluationChoice
→ merge / continue / reject / archive
```

Evaluating an alternative program:

```text
create new Program
→ create PROGRAM_FOR_PROCESS(new_program, process)
→ Program.alternative_to = current active Program
→ write code in its own git_path
→ run comparable Evaluation
→ compare EvaluationRuns
→ activate if better
→ reject or keep as candidate if support is insufficient
```

The current active Program remains active until `EvaluationChoice`. A candidate Program or ProgramBranch does not replace the active slot automatically.

#### Meta-Program Lifecycle Safety

The stronger requirements in this section apply only when `meta ∈ Program.roles`. `ProgramLifecycleManagement` manages program lifecycles and has `roles = {exec, meta}`.

Meta-programs affect many future decisions and may change the mechanisms used for their own learning. Within the [[Self#^meta-improvement-mvp|MVP limit on changing the improvement-acceptance procedure]], they use the same lifecycle but are improved more conservatively than ordinary programs:

```text
- run self-improvement less often;
- require more support/evidence;
- run broader Evaluation, including old and new versions
  on histories of successful and unsuccessful program improvements;
- strengthen regression checks;
- account for a higher cost of errors than for ordinary domain programs;
- apply updates more cautiously;
- require a higher evidence threshold before activation;
- use simplified tests for expensive meta-evaluation when a full check costs too much.
```

For permitted changes to meta mechanisms, strong evidence is first required that the new version improves lifecycle quality, cost, stability, or safety. Accumulating such evidence does not remove the MVP restriction on changing the final review and acceptance of improvements.

Modeling self-improvement does not by itself make a `Program` meta. For example:

```text
ImprovementOutcomeModel.roles = {model}
ProgramLifecycleManagement.roles = {exec, meta}
```

---

### Stage 1: `gather_relevant_info`

`gather_relevant_info(Program | ProcessConcept)` gathers material for building or improving a program.

This is not planning or action selection. This stage does not choose an action or directly change the program.

It answers:

```text
what does the agent already know or could learn to form a better program hypothesis?
```

Sources include:

```text
memory
→ past episodes, failures, wins, ProgramRun, EvaluationRun

semantic graph
→ similar ProcessConcept, TransitionType, ActionConcept,
  OperatorConcept, and relations

existing programs
→ Programs for the related process in all lifecycle statuses,
  plus siblings and prototypes

LLM general knowledge
→ initial priors, edge cases, and possible model structure

external research
→ literature, documentation, articles, domain guides, deep research

simulation / datasets
→ synthetic episodes, offline evidence, self-play, benchmark cases
```

`gather_relevant_info` creates evidence and context for reasoning. It does not create the final program by itself.

Run external research to address a specific gap when the expected benefit justifies the cost—for example, to find a test model, measurement characteristics, or source error statistics. Retain the source, version, and applicability conditions; a publication does not automatically establish that its findings transfer to the current process. Reconsider the research when conditions or the underlying evidence change materially; periodic LLM or web research is not mandatory.

---

### Stage 2: `reasoning_and_synthesis`

`reasoning_and_synthesis` turns gathered information, errors, observations, and goals into checkable explanations and possible ways to improve a model or program.

This stage contains two related processes.

**Analysis** examines the available material for recurring errors, contradictions, missing variables, hidden factors, different process modes, model applicability limits, and useful analogies.

**Synthesis** builds new explanations and approaches by combining memories, similar processes, semantic structure, rejected alternatives, external sources, counterfactuals, and LLM/general-knowledge priors.

The agent therefore does not only find a ready-made hypothesis. It may build a new idea from several partial observations or analogies that would not support a conclusion individually. An initial hypothesis is usually not yet a program and is not the same as a specific implementation.

For example:

```text
"Perhaps the current model does not account for an important factor X."
```

Such an idea may be recorded as a [[Core data structures#^def-Note|`Note`]].

If the statement must be checked and updated independently, the agent records a [[Core data structures#^def-Claim|`Claim`]]:

```text
Claim G:
"X has a material effect on Y."
```

A `Claim` is a checkable assertion and may be an independent `BeliefTarget`; a whole `Note` can also be evaluated without necessarily decomposing it, under the [[Core data structures#^note-claim-prompt-evaluation|shared evaluation contract]].

Here, **hypothesis** is not a separate data type, but a role of a `Claim`: a Claim is a hypothesis when the agent considers it as a possible explanation, prediction, or improvement approach and gathers evidence to check it.

---

### Refining Hypotheses

Reasoning may elaborate a general Claim into several more specific competing explanations:

```text
general Claim
        ↓ reasoning / elaboration
specific Claims
```

For example:

```text
G:
"The current model conflates different process modes."

        ↓

C1:
"High prediction_unexpectedness is caused by conflating modes A and B."

C2:
"There is one mode, and the mismatch is explained by factor X."
```

The general and specific Claims are independent `BeliefTarget`s.

A Claim's level of generality is not defined by a separate type or field. It is expressed through its semantics: a more general Claim uses more general Concepts, `ProcessConcept`, `Prototype`, or conditions; a more specific one refers to narrower objects, mechanisms, or context.

When a persistent Claim is created as a refinement of another Claim, record this explicitly with the semantic relation `REFINES_CLAIM(specific, general)`.

Claims thereby form a navigable structure from general hypotheses to more specific ones. The relation does not imply that the Claims are true or automatically transfer evidence. `EvidenceAssessmentProgram` assigns evidence to a Claim only when the actual check is informative about that Claim.

Therefore:

```text
specific Claim is false
≠
general Claim is automatically false.
```

Several independent results may provide evidence for a more general Claim if together they genuinely check its meaning.

---

### Claims About a Problem and Claims About an Improvement Method

Reasoning may create Claims with different roles:

```text
explanatory Claim
→ what likely explains the observed problem;

change Claim
→ what change is likely to improve the result.
```

These are roles of the same `Claim` type, not separate classes.

For example:

```text
Claim G:
"High prediction_unexpectedness is caused by conflating modes A and B."

        ↓ reasoning

Claim A:
"Explicitly separating modes A and B
through a separate model branch will explain the observed discrepancy
and improve forecast quality over the current model
on an independent evaluation with fixed criteria."
```

`Claim A` describes an **approach**, not its specific implementation.

Reasoning may create several alternative change Claims:

```text
A:
"Use separate branches for modes A and B."

B:
"Use a continuous latent regime variable."

C:
"Keep one model but add factor X."
```

This is the level at which different approaches are explored and compared.

Reasoning itself is not strong evidence. It may create a Claim, set an initial prior, and raise the expected value of checking it, but it does not increase `Support` merely because an explanation seems convincing.

Check Claims through independent observations, Evaluation, simulation, experiments, replay, or live experience.

---

### Implementing the Selected Approach

A single change Claim may be implemented in several ways.

For example:

```text
Claim A:
"A separate branch for mode B will explain the observed discrepancy
and improve forecast quality on an independent evaluation
with fixed criteria."

        ↓ implementation generation

ProgramBranch A1
ProgramBranch A2
ProgramBranch A3
```

`A1`, `A2`, and `A3` may differ by:

```text
different prompts;
different LLMs;
several stochastic runs using one LLM and prompt;
subsequent refinement or debugging.
```

These are **several concrete implementations of the same approach**, not different Claims.

An **implementation candidate** is the role of a specific native artifact that implements a change Claim; a separate `ImplementationCandidate` entity is unnecessary.

Depending on the change, the artifact is:

```text
change to an existing Program (same main mechanism)
→ ProgramBranch;

fundamentally different mechanism
→ candidate Program;

semantic change
→ candidate semantic change;

change to existing parameters
→ candidate parameter update;

change to instruction template or placeholders
→ candidate Prompt revision;

new evaluation scenario
→ EvaluationCase.
```

[[Core data structures#^def-Prompt|`Prompt`]] has its own revisions and [[Core data structures#^note-claim-prompt-evaluation|evaluation contract]]. If a Prompt change also changes the code, semantics, or contract of the `Program` that uses it, it goes through that Program's [[#General Program Lifecycle|lifecycle]] as well.

---

### Checking the Approach and Its Implementation

Distinguish checking an approach from checking one specific implementation. Failure of one implementation does not by itself refute the underlying `Claim`. However, repeated failures across sufficiently different and correct implementations may become evidence against the `Claim` if they are not better explained by implementation defects, insufficient resources, or other external limits.

**Evaluation, evidence assessment, and credit assignment**

Evaluation produces a checkable result. `EvidenceAssessmentProgram` creates evidence for the implementation directly checked and related `Claim`s; `CreditAssignmentProgram` assigns learning credit to the relevant [[Learning system#^def-LearningTarget|`LearningTarget`s]] in the context of experience. `UpdatePlanner` selects the specific state to update. Use Verification and program tests before Evaluation to distinguish implementation defects from weaknesses in the approach.

#### Belief Updates Across Hypothesis Levels

Evaluation updates the level it actually checked, then generalizes gradually from specific implementations toward the underlying idea to record how valid the idea is.

---

### Parametric Update vs. Structural Revision

---

### Parametric Update

A parametric update changes parameters within the existing program structure. Automatic parameter learning applies to [[Program Layer#Learnable and Fixed Components|learnable components]] under the [[Learning system#Selecting Learnable Components and Learning Mode|selected learning mode]]; it does not make fixed components learnable.

Use it when experience can be incorporated into the existing structure by refining weights, priors, values, probabilities, or other parameters. A surprising discrepancy is not required; ordinary expected outcomes also provide training data.

In the standard path, update estimator state or program parameters through the [[Learning system#PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher|parameter-learning pipeline]]. A separate [[Learning system#Specialized Learning|specialized learning path]] is allowed for narrow tasks. Related epistemic beliefs are updated through the [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|evidence lifecycle]]. Changing values embedded in the program's code or versioned artifact goes through a `ProgramBranch`.

Criterion:

```text
if the program can be improved without changing its structure or contracts
→ parametric update
```

---
### Structural Revision

**Structural revision** is a non-parametric change to a model, program, or its semantic boundaries.

Structural revision includes:

```text
adding, removing, or changing a control-flow branch or operator;

changing read_contract or output_contract;

adding, removing, replacing, or moving a learnable component;

and so on.
```

A contract mismatch is a common special case of structural revision.

Criterion:

```text
if the problem cannot be resolved by changing existing parameter values or beliefs
→ structural revision is required.
```

Structural revision proceeds through a `ProgramBranch`, semantic change, or new `Program` and is checked through Evaluation.

During the revision, consciousness selects which program parts should be learnable and how. A new predictor and, if training is intended, its updater are verified and activated together with the program change; parameter updates then follow the selected scheme. Pausing or resuming already-defined training does not itself change program structure.

---

### Dual Development of Declarative and Executable Programs

Declarative and Executable programs often develop together.

```text
Declarative Model improves process understanding
→ better expected signals
→ better ExecutableProgram / policy program

ExecutableProgram acts and explores
→ produces new experience
→ improves Declarative Model

Evaluation finds mismatch
→ update model, exec, or both
```

---
## Program Versioning in Git

### Core Principle

EverTree program code is versioned through Git.

The repository's `main` branch is the **active state of programs**. A program's active version is its code in `main`.

```text
main branch = current active version of all programs
codex/program/<process-graph-path>/<role>/<candidate-name> = candidate change
```

`Program` defines a program's stable identity; Git stores its versions. Epistemic belief applies to a specific revision, not unconditionally to the full history of a stable `Program` identity.

---
### `ProgramBranch`

**`ProgramBranch`** is a metadata record for a Git branch created to change a program.

Use a branch when improving, repairing, or extending an existing `Program` without changing its fundamental mechanism.

Technically, a branch belongs to the whole repository, but `ProgramBranch.program` metadata indicates which program it was created for.

```python
ProgramBranch: Node {
  program: <Program>
  git_ref: <string>  # e.g. codex/program/Self/Process/TaskManagement/Planning/exec/refine-budget

  change_claim: <Claim>
    "Checkable claim explaining why the proposed approach should improve the program."

  source_memory?: <MemoryFact>

  status: "active" | "merged" | "rejected" | "archived"

  created_at: <datetime>
  closed_at?: <datetime>
}
```

Examples of branches:

```text
codex/program/Self/Process/TaskManagement/Planning/exec/refine-budget
fix/enterprise_edge_cases
refactor/negotiation_state_tracking
```

---
### Active Code

The active version of a program is always read from `main`. Once a branch passes verification successfully, merge it into `main`; it then becomes active automatically.

---
### Repository Organization

Program code is stored in one Git repository. Each commit contains one version of every Program; alternative changes to a Program are kept in Git branches at the same path, without variant directories. The managed repository's active/default branch is `main`; alternatives use `codex/program/<process-graph-path>/<role>/<candidate-name>`. A process path begins with `Self/Process`; the role is `exec` or `model`; a descriptive candidate name contains one to three hyphenated words, with a numeric suffix for repeated names. Invalid path-component characters are percent-encoded. Stable internal IDs are kept separately from branch names. A precise version is addressed by commit. The remote active branch `evertree/programs` publishes the `main` tree and retains the alternative history; a commit being in history does not mean it was activated.

- **Placement by taxonomy.** `src/evertree/processes/` matches the agent's own Self/Process branch (`SelfProcess`), which belongs to Self through `PART_WHOLE` and is a subtype of the general `Process`. Nested folders for own processes follow [[Semantics Plane#Taxonomy Axis: Type Taxonomy (Type → SuperType → …)|`SUBTYPE_OF`]] with one parent. Implemented process roles live alongside one another as `_exec.py` and `_model.py`; a multi-module role becomes a `_exec/` or `_model/` package. The roles are separate Programs, and their alternatives live in branches. Nesting depth follows the existing taxonomy; composite steps are linked through `PART_WHOLE`.
- **Direct access.** The currently selected program is available through [[Process Ontology and Semantic Interface#PROGRAM_FOR_PROCESS|`ProcessConcept.active_model` / `active_exec`]]; the `PROGRAM_FOR_PROCESS` relation can find all programs for a process, including candidates and archived programs. Code is addressed by [[Program Layer#Program|`Program.git_path`]], the path to its Python file or module. Repeated access does not require walking directories or reading files to find the program.
- **Consistent moves.** A parent or name change that affects placement is performed as one operation: update the graph, folders, and `git_path`; check consistency against the exact commit before Evaluation and activation. CI separately compares the initial graph for the current code against its source files. Process and Program identities and their learning history are retained; previous paths and code remain available in their Git revisions.
- **Other search paths.** [[Process Ontology and Semantic Interface#Semantic Organization: Concept → ProcessConcept → Program|Semantic links]] can find a process by subject, participants, and other useful properties without adding a second taxonomy parent or copying code into multiple folders.
- **Shared code.** `common/` contains packages and modules not tied to a specific process or domain concept and reused by different programs. Ordinary Python package organization by responsibility is allowed within it. Models for different processes may [[Program Layer#Generalization and Model Compression|reuse a shared algorithm]] with different features, parameters, and weights; process folders retain their bindings and specific code. A change in `common/` requires considering all programs that depend on changed files as affected.

#### Modules and Imports

Related functionality is organized in a Python module; start with one function and add functions and classes as needed. Each program module has a corresponding `ProgramModule` concept for organization, search, and analysis.

- The standard library, external packages, and helper modules for one program are imported normally.
- Shared utilities are imported from `common/`.
- Other independent EverTree `Program`s are called through their declared interfaces and [[Cognition and Attention#Task Execution (`TaskExecution`)|runtime]], without directly importing their internal implementation.

These boundaries keep inter-program calls manageable and allow one implementation to be split across several files.

---
### Branch Management

Rule:

```text
active / paused branches — remain Git branches until a decision (EvaluationChoice);
merged branches — are deleted after merge;
the history remains in main;
rejected branches — are archived and their branch ref is deleted.
```
