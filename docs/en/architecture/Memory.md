---
status: draft
target_version: next
---

## Status: Draft

## Introduction

#concept #topic_intro

(def_id:: et.Memory)
> [!definition]
> **Memory** — the system for recording, compressing, linking, retrieving, and reusing an EverTree agent's experience. Memory stores not only facts about the world, but traces of how the agent acted, made mistakes, reasoned, changed programs, updated beliefs, and became what it is.
> ^def-Memory

EverTree memory is not an archive of the past. Its purpose is to make past experience available for future action, learning, explanation, evaluation, and self-improvement.

Core principle:

```text
Preserve generously.
Consolidate intelligently.
Retrieve selectively.
Delete cautiously.
```

EverTree should not try to determine perfectly, at the time of writing, what will be important. Early importance criteria may be inaccurate. Therefore, initial recording aims for high recall: it is better to temporarily save more than to lose something important.

Preservation does not mean putting everything into the working context. Memory may retain a great deal, while runtime retrieval should surface only what is useful to the current process.

---

## Purpose of Memory

Memory serves five functions:

1. It stores experience: events, [[#^def-Episode|episodes]], [[#^def-ProgramRun|`ProgramRun`s]], RunTrace, action results, [[Core data structures#^def-Note|notes]] containing reasoning and conclusions, errors, supervisor feedback, graph and program changes.
2. It provides [[Uncertainty and Belief Tracking in the World Model#^def-Evidence|evidence]] for `Strength/Support`. A new observation is not just text; it becomes a basis for updating [[Uncertainty and Belief Tracking in the World Model#^def-Belief|belief]], transition weights, hypotheses, and process models.
3. It provides provenance for saved results — the ability to recover which computation and inputs produced them; see [[#^def-ResultProvenance|Result Provenance]].
4. It serves as a source for [[#^def-MemoryReplay|replay]] and [[Datasets#^def-Dataset|datasets]] for training and evaluation. Saved experience is also used for analysis and insights.
5. It provides the basis for retrieval routes: links among concepts, processes, programs, outcomes, traces, and memories, allowing the agent to quickly find relevant past experience.

---

## The Key Distinction: Storage and Access

Memory addresses two different questions:

```text
what to store
≠
what to retrieve now
```

At input, memory should be broad. At runtime output, it should be selective.

```text
storage policy
→ preserve a potentially valuable trace

retrieval policy
→ find roughly relevant traces

context policy
→ use only a small part of what was found
```

If a memory was not returned by the current retrieval, that does not necessarily mean it was forgotten. It simply lost the local competition for access.

---

## Granularity and Memory Organization
#topic_core

Execution experience in EverTree is organized at three levels:

```text
ProgramRun
└── SemanticTrace
    └── TraceEvent
```

- **[[#^def-TraceEvent|`TraceEvent`]]** — an atomic execution fact for a semantically labeled program element.
- **[[#^def-SemanticTrace|`SemanticTrace`]]** — the current saved, ordered set of `TraceEvent`s for one `ProgramRun`. Initially it may contain the full trace and later be compressed to its most significant parts.
- **[[#^def-ProgramRun|`ProgramRun`]]** — one specific program execution and the natural boundary of a trace.

Semantic results of execution — [[Core data structures#^def-Facet|`Facet`s]], relations, and other semantic objects — are not elements of `SemanticTrace`. They are created by outputs of the corresponding `TraceEvent` and retain a link to the event that produced them through provenance.

When a program calls another program, a child `ProgramRun` is created. It is linked to the exact `TraceEvent` in the parent run through `caller_event`. The `caller_event` links make it possible to reconstruct the full hierarchy of nested `ProgramRun`s.

---

## ProgramRun
^ProgramRun
#topic_core

(def_id:: entity.ProgramRun)
> [!definition]
> **`ProgramRun`** — one execution of one specific `Program` version, from invocation until completion or interruption. It records execution context: the stable `Program` identity, source Git revision, revision changes applied during execution, arguments, mode, time, and status. Semantically significant execution events are recorded as linked [[#^def-TraceEvent|`TraceEvent`s]], and the currently saved portion of this experience is represented by [[#^def-SemanticTrace|`SemanticTrace`]].
> ^def-ProgramRun

This is a logical run: [[Cognition and Attention#^durable-program-execution|recovery through DBOS]] continues the same `ProgramRun`. Running a changed program instead of the previous one creates a new `ProgramRun`. Technical recovery does not change `run_mode` and is not [[#Replay|Memory Replay]], which is separate work on saved experience.

Every root or child `ProgramRun` belongs to a `Task`. A root run is linked to the task; child runs inherit that association through `caller_event`. One run is not the same as the entire [[Cognition and Attention#^def-TaskExecution|`TaskExecution`]]: one task may continue across multiple runs and conscious steps.

#topic_details

```python
ProgramRun {
  program: <Program>
    "The program that was called."

  base_commit_sha: <string>
    "Exact Git revision of the Program at the start of execution."

  revision_changes: <ProgramRevisionChange[]> = []
    "Ordered revision changes in optional interactive mode; normally empty."

  caller_event?: <TraceEvent>
    "TraceEvent in the parent program that called this ProgramRun.
     Absent only for a root ProgramRun."

  arguments: <BoundArguments>
    "Arguments for this specific call, automatically bound
     to the program interface parameters."

  run_mode: "live" | "replay" | "simulation" | "evaluation" | "test"

  started_at: <time>
  finished_at?: <time>

  status: "running" | "completed" | "failed" | "interrupted"
}
```

---

### Automatic Recording of Program Arguments
#topic_details

### Program Interface

Program arguments and return values are always part of the semantic surface and are recorded automatically.

When a [[#^def-ProgramRun|`ProgramRun`]] is created, the tracer automatically records the actual program-call arguments and binds them to the interface parameters (using Pydantic models). Program return values are recorded too.

A successful `Program` return always has the form [[Process Plane/Program Layer#^def-ProgramResult|`ProgramResult[T]`]]: the tracer saves the primary result together with optional textual feedback. Their semantic roles differ; feedback is not included in a domain prediction or observation.

If an argument is an object or graph state, save a reference to the corresponding [[Core data structures#^def-Facet|`Facet`]] (usually), or to a [[Core data structures#^def-Concept|`Concept`]], [[Core data structures#^def-Instance|`Instance`]], or relation instance.

A small value, including an LLM response, may be stored directly in the arguments or output. Large content may be stored in an [[Core data structures#^def-Artifact|`Artifact`]] with a reference to the exact version used. The storage method does not change the semantic meaning of the value and does not require materializing every payload as a `Facet` in the persistent graph.

---
## Nested Program Calls

#topic_details

Every semantically significant `Program` call creates a separate child [[#^def-ProgramRun|`ProgramRun`]]. `caller_event` links the child run to the exact [[#^def-TraceEvent|TraceEvent]] of the anchored call operator.

Example:

```text
TreatmentPlanningRun
  ↓ EvaluateAlternative(Igor, NoTreatment)
DiseaseProgressionModelRun
  ↓ classify_mortality(...)
MortalityClassifierRun
```

The full hierarchy of nested runs can be reconstructed from `caller_event`:

```text
TreatmentPlanningRun
└── DiseaseProgressionModelRun
    └── MortalityClassifierRun
```

For any result, follow the tree upward:

```text
result
→ producer TraceEvent
→ ProgramRun
→ caller TraceEvent
→ parent ProgramRun
→ ...
```

This defines the result's semantic call context.

### Scenario Branches

#topic_details

When a program models several independent possible scenarios, each scenario that materializes its own states runs as a separate child [[#^def-ProgramRun|`ProgramRun`]].

---
## TraceEvent

#topic_core

(def_id:: entity.TraceEvent)
> [!definition]
> **TraceEvent** — an immutable record of one semantically significant step in a `Program` execution within a specific [[#^def-ProgramRun|`ProgramRun`]].
> ^def-TraceEvent

It records the executed `OperatorConcept`, actual arguments, result, execution order, and status.

Each `TraceEvent` belongs to exactly one `ProgramRun`.

The `ProgramRun`'s [[#^def-SemanticTrace|`SemanticTrace`]] stores ordered references to the `TraceEvent`s retained as meaningful experience in the current state of memory. Immediately after execution it may include all events from the run; later, compaction may remove some of them.

```python
TraceEvent {
  program_run: <ProgramRun>
    "The ProgramRun in which the event occurred."

  seq: <int>
    "Monotonic order of TraceEvents within the ProgramRun."

  occurred_at: <time>
    "Physical execution time in the agent system."

  operator: <OperatorConcept>
    "Semantically labeled Program operator recorded by this event."

  arguments: <BoundArguments>
    "Actual arguments bound to the operator's interface parameters."

  output?: <OperatorOutput>
    "Immutable, typed result of the operator."

  status: "completed" | "failed" | "interrupted"
}
```

`seq` establishes execution order within a `ProgramRun`; by itself, it does not imply a causal link between events.

A `TraceEvent` is never rewritten after creation. Memory compaction changes the contents of `SemanticTrace`; the original `TraceEvent` may be physically deleted later only if it is no longer needed for retained experience or provenance.

---
### Automatic Recording of Results

#topic_details

The result of each anchored operator is automatically recorded in [[#^def-TraceEvent|`TraceEvent.output`]] as a typed [[#^def-OperatorOutput|`OperatorOutput`]].

The tracer builds its semantic projection and provenance according to the result type's contract.

A local Python variable name does not affect the result's meaning or identity, though it should preferably describe the result clearly.

Assigning a result to another variable does not create a new semantic object. Intermediate computations may remain ordinary Python variables; requirements for resuming them are defined by the [[Cognition and Attention#^durable-program-execution|DBOS execution contract]].

---
### `OperatorOutput`

#topic_details

(def_id:: entity.OperatorOutput)
> [!definition]
> **`OperatorOutput`** — an immutable, typed result of an anchored operator. It represents one semantically coherent whole and defines the roles of its named parts. It is stored in [[#^def-TraceEvent|`TraceEvent.output`]].
> ^def-OperatorOutput

```python
from pydantic import BaseModel, ConfigDict

class OperatorOutput(BaseModel):
    model_config = ConfigDict(frozen=True)
```

[[Process Plane/Program Layer#^def-ProgramResult|`ProgramResult[T]`]] is a special case of `OperatorOutput` at the `Program` call boundary. The coherent whole is the result of that call; `result` is projected according to its domain contract, while `feedback` separately represents feedback on execution.

If a result type has its own reusable domain meaning, it has an ordinary domain [[Core data structures#^def-Concept|`Concept`]]. Create the Concept once; each operator execution creates a new result instance.

---
### Semantic Interpretation of `OperatorOutput`
#topic_details

The [[#^def-OperatorOutput|`OperatorOutput`]] type defines the semantic contract: how the whole output and its named parts are projected into trace-local semantic objects and facts.

For example, for an anchored operator that is not itself a separate `Program`:

```python
health: HealthState = diagnose(igor)  # et:op=diagnose_health
```

```python
HealthState {
  instance = Igor
  valid_from = "2026-07-17T12:00"

  health_status = {
    belief_data = Profile {
      strengths = {Healthy: 0.05, Sick: 0.90, Recovering: 0.05}
      support = ...
      prior_support = ...
    }
  }

  temperature = {
    value_U = 39.1 Celsius
    belief_data = BeliefData(...)
  }
}

TraceEvent_E19.output = health
```

The semantic contract for `HealthState` defines its projection onto a [[Core data structures#^def-Facet|`Facet`]]; epistemic fields use [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`BeliefData`]] or [[Uncertainty and Belief Tracking in the World Model#^def-Profile|`Profile`]]:

```text
output
→ Facet F;

output.instance
→ STATE_IDENTITY(F, Igor);

output.health_status
→ CompetitionScope {
     alternatives = [
       CLASSIFIED_AS(F, Healthy),
       CLASSIFIED_AS(F, Sick),
       CLASSIFIED_AS(F, Recovering)
     ]
   };

output.temperature
→ HAS_NUMERIC_VALUE(
     F,
     Temperature,
     39.1,
     Celsius
   ).
```

The `health_status` and `temperature` fields do not contain a manual reference to `F`. Under the `HealthState` contract, they describe the same `Facet` represented by the whole output, so they cannot be accidentally assigned to another state.

The tracer does not infer this meaning from a local variable name or string value. It uses the result type and the semantic roles of its fields.

After an operator runs, the tracer automatically:

```text
1. creates a TraceEvent;
2. saves the OperatorOutput;
3. builds its trace-local semantic projection;
4. assigns provenance to each semantic result.
```

All fields here describe parts of one `HealthState` result; domain code does not manually link them to `Facet F`. The tracer uses the result type and the semantic roles of its fields.

---
### Composite Result

A single [[#^def-OperatorOutput|`OperatorOutput`]] may contain several semantic objects when together they form one coherent whole. In that case, represent the result as an instance of the corresponding domain [[Core data structures#^def-Concept|`Concept`]].

That `Concept` may already exist in the graph, or the agent may deliberately create it if the identified result type has its own reusable meaning.

For example:

```text
TransferOutcome#42
├── sender_state: Facet
└── receiver_state: Facet
```

```text
TransferOutcome
→ stable Concept for the result type;

TransferOutcome#42
→ result instance for one execution.
```

If several results do not form one coherent whole, compute them using separate anchored operators.

Created semantic results remain trace-local by default. If a result must become part of the persistent world model, the program explicitly applies `GraphDelta`.

The link from results to the creating `TraceEvent.output` is described in [[#^def-ResultProvenance|Result Provenance]].

### Observation

(def_id:: entity.Observation)
> [!definition]
> **Observation** — a typed domain [[#^def-OperatorOutput|`OperatorOutput`]] in the role of an observation: a result of [[Cognition and Attention#^def-Perception|perception]], source reading, or a tool that describes information received about the world or agent.
> ^def-Observation

This is a result role, not a required `Observation(data=...)` wrapper. For example, `EngineState` may be the result of either a forecast or an observation; specific instances and their provenance distinguish them.

If the producer is a `Program`, its [[Process Plane/Program Layer#^def-ProgramResult|`ProgramResult.result`]] must have a domain `OperatorOutput` schema with this semantic role to be delivered as an observation. The wrapper with feedback is not itself the observation. An arbitrary `str` or `float` returned by another program does not automatically enter the observation channel. Delivery retains the domain result's type, identity, and provenance.

The schema defines available fields and their meaning, such as a temperature value and unit. Semantic references link the result to objects, properties, and graph concepts. A new concept does not require a separate Python class if an existing schema can express it. Interpretation retains the source, the time of the observed event, and the receipt time; unknown values and ambiguity remain explicit. Typing does not make a source's message a reliable fact.

Memory retains both the agent's own experience and information about others' experience from accounts, documents, and other external sources. For external experience, it retains provenance, grounds for source-reliability assessment, and known dependencies among messages. Simulation results and synthetic examples remain distinguishable from observations of real events.

An observation may contain several features of one state or an original block with multiple related details, including details about different times. It does not have to be fully split into individual assertions before the process is selected. Retain the original content, order, known temporal relationships, and provenance for later analysis. Choose [[Process Plane/Program Layer#^observation-granularity|granularity]] when preparing data for specific processing.

Observations are stored in the trace by default. If an observed state is needed in the persistent world model, materialize it through [[Core data structures#Updating the Persistent Graph|`GraphDelta`]]. A persistent `Facet` for each incoming value is not required.

[[Cognition and Attention#^input-reception|Input reception]] links the input to an existing or minimally created `Task`. Runtime delivers a result directly to a known waiting call. If the recipient must be identified by meaning, consciousness or the task's executing `exec` program uses [[Process Plane/Process Ontology and Semantic Interface#^def-ProcessRouter|`ProcessRouter`]] and asks runtime to deliver it to the selected execution. Reading, typing, and branching rules are described in the [[Process Plane/Program Layer#^process-observation-input|shared observation input contract]]. Delivery and rereading during recovery preserve the original observation identity and producer provenance; events that use it do not turn it into new experience.

---
## `SemanticTrace`
^SemanticTrace

#topic_core

(def_id:: entity.SemanticTrace)
> [!definition]
> **`SemanticTrace`** — the retained, ordered subset of [[#^def-TraceEvent|`TraceEvent`s]] from one specific [[#^def-ProgramRun|`ProgramRun`]]. It represents the part of program execution considered worth preserving in the current state of memory.
> ^def-SemanticTrace

`SemanticTrace` does not copy event contents; it stores references to them:

```python
SemanticTrace {
  run: <ProgramRun>
  events: ordered List[TraceEvent]
}
```

All events belong to that same `ProgramRun` and retain their original order by `TraceEvent.seq`.

Immediately after execution, `SemanticTrace` usually contains all `TraceEvent`s from the `ProgramRun`. Later, [[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]] may retain only the subset useful or necessary to keep.

The detailed lifecycle is described in [[#Compacting SemanticTrace]].

---
### Full Trace of Nested Execution

Each [[#^def-ProgramRun|`ProgramRun`]], including a child run, has its own [[#^def-SemanticTrace|`SemanticTrace`]].

```text
Root ProgramRun
├── SemanticTrace(root)
├── Child ProgramRun A
│   └── SemanticTrace(A)
└── Child ProgramRun B
    └── SemanticTrace(B)
```

`caller_event` links between parent and child `ProgramRun`s form a call tree. Recover the complete retained experience of a root run by traversing this tree and reading the `SemanticTrace` of each `ProgramRun`.

The global [[#^def-TraceEvent|`TraceEvent.seq`]] can be used, when needed, to represent all retained events in the tree as one timeline.

---
### Episode

(def_id:: entity.Episode)
> [!definition]
> **Episode** — a domain unit of experience with defined boundaries, such as one poker hand, engine run, conversation, or experiment.
> ^def-Episode

An Episode is represented by an ordinary [[Core data structures#^def-Instance|Instance]] of the corresponding process or event. Its current lifecycle state is expressed through a [[Core data structures#^def-Facet|Facet]].

An Episode is not a technical trace container. Its related [[#^def-ProgramRun|`ProgramRun`s]], [[#^def-TraceEvent|`TraceEvent`s]], and semantic results are found through semantic links and provenance.

Each piece of experience belongs to one most-specific `primary Episode`. Links to broader Episodes, Tasks, Goals, and Processes are defined separately and do not change its primary episode.

One `Task` may work with several episodes, and one episode may be used by several tasks. The list of episodes in a task representation contains references and does not establish exclusive ownership. Time helps find a suitable episode, but a later input may belong to an earlier episode; selection uses meaning and known links, not only arrival proximity.

### Tasks, Goals, and Other Organizing Concepts

Tasks, goals, intentions, observations, and [[Core data structures#^def-Note|`Note`s]] are ordinary semantic objects in the graph. Reconstruct a link to the originating task through the chain of parent [[#^def-ProgramRun|`ProgramRun`s]] and their `caller_event` links.

Subtasks and larger tasks may be linked by ordinary semantic relations:

```text
PART_WHOLE(subtask, task)
```

A `Program` may be linked to a semantic organizing concept, but a separate `Program` is not required for every `Task`: a one-off task may be handled through a task-local `Plan`. [[Cognition and Attention#^def-TaskExecution|`TaskExecution`]] denotes the entire task execution process, which may include many `ProgramRun`s and conscious steps. Conditions for creating a reusable mechanism are defined in [[Cognition and Attention#Planning|`Planning`]], and each actual `Program` execution is saved as a [[#^def-ProgramRun|`ProgramRun`]].

The foundation of the semantic graph responsible for the taxonomy of planning and control of agent activity is defined in a separate subsection: ...

### Cache of Active Tasks and Episodes
^active-state

`active_state` is part of Memory: an operational cache of references to recently active `Task`s and related episodes for fast access. The objects are stored in memory; the cache contains recoverable references to them. The memory policy limits its size to an allocated budget and reviews its contents based on last use and task state. The initial eviction method removes references that have not been used for a long time; the retention strategy may be refined through experience. Removing a reference from the cache leaves the object accessible through ordinary memory retrieval; the object's retention period follows the [[#Retention, Compression, and Forgetting|general memory lifecycle]].

Selecting the current episode, the current version of an object being assembled, and the condition being awaited are material execution state. This state is stored in [[Cognition and Attention#^working-context|`TaskState`]], [[#^def-ProgramRun|`ProgramRun`]], or recovered from the trace; it does not exist only in the cache. Memory manages storage and record lifetime; a program defines substantive changes that runtime applies through existing interfaces.

---
## Result Provenance

#topic_core

(def_id:: et.ResultProvenance)
> [!definition]
> **Result Provenance** — a computed subgraph of a result's origin and use: which [[#^def-TraceEvent|`TraceEvent`]] created it, in which [[#^def-ProgramRun|`ProgramRun`]] and `Program` version, which inputs and material intermediate results produced it, and where it was later used.
> ^def-ResultProvenance

Provenance is needed for:

- explaining results and system changes;
- audit and debugging;
- replay and Evaluation;
- recomputing and retracting beliefs;
- safe memory compaction.

Provenance is not stored as a separate textual history or duplicate semantic graph. It is reconstructed from `TraceOutputRef`, retained `TraceEvent`s, their input/output dependencies, and the corresponding `ProgramRun`s.

### Recording Provenance

#topic_details

Every executed anchored operator creates a [[#^def-TraceEvent|`TraceEvent`]]. Address an individual semantic result within its output with an immutable reference:

```python
TraceOutputRef {
  event_ref: <TraceEvent identity>
    "Stable address of the TraceEvent that created the result."

  output_path: <OutputPath>
    "Stable named path to the result inside TraceEvent.output."
}
```

`output_path` may point to the whole output or one of its named semantic parts. `TraceOutputRef` is a persisted address under the [[Core data structures#Objects and References|general object and reference rule]].

For a `Program` return, paths distinguish `result`, its named parts, and `feedback`. Reading `.result` does not create a new semantic object or independent evidence. If the program returns an existing result, its original identity and producer provenance are retained; a new wrapper records that the value was returned, not that new experience was obtained.

A semantic result materialized from output receives:

```text
created_by: <TraceOutputRef>
```

The tracer assigns `created_by` automatically.

`TraceEvent` arguments retain references to the semantic results they use. Arguments and return values of a `Program` are always part of its semantic surface and are automatically recorded by the tracer, so provenance does not stop at program-call boundaries.

Reconstruct provenance by tracing backward:

```text
result
→ created_by
→ producer TraceEvent
→ its inputs
→ producers of those inputs
→ material control-flow events
→ ProgramRun
→ Program and its version
```

For nested program execution:

```text
child ProgramRun.caller_event
→ TraceEvent in the parent ProgramRun
```

links their provenance.

Therefore, provenance is usually a dependency subgraph, not one linear chain.

---
### Trace-Local and Persistent Results

A semantic result may exist in two states.

(def_id:: entity.TraceLocalResult)
> [!definition]
> **Trace-local result** — the result of a specific computation, belonging to the experience of that [[#^def-ProgramRun|`ProgramRun`]]. It is available to later operators in the run and is retained with the trace, but **is not part of the agent's persistent semantic graph**.
> ^def-TraceLocalResult

(def_id:: entity.PersistentResult)
> [!definition]
> **Persistent result** — a semantic object or relation that the agent explicitly saved in its long-term model of the world or itself. It is available to other `ProgramRun`s, ordinary graph reasoning, and long-term retrieval independently of the original run.
> ^def-PersistentResult

By default, **all results of anchored operators are trace-local**.

This allows the agent to freely compute:

```text
hypotheses;
intermediate states;
simulation results;
temporary inferences;
and so on.
```

without turning every intermediate result into a long-term fact.

If a program or consciousness decides to save a result as part of the persistent model, it does so explicitly through `GraphDelta`:

```text
trace-local result
→ GraphDelta
→ persistent semantic graph
```

Thus, `GraphDelta` is the explicit boundary:

```text
compute
≠
save as long-term knowledge
```

#### Provenance

#topic_details

A trace-local result gets `created_by`, pointing to the [[#^def-TraceEvent|`TraceEvent`]] that computed it.

When writing to the persistent graph, the graph-writing `TraceEvent` records `GraphDelta` and the source semantic results on which the change is based.

Therefore, provenance of a persistent result remains traceable:

```text
persistent result
→ graph-writing TraceEvent
→ source trace-local result
→ producer TraceEvent
→ ...
```

`GraphDelta` does not make a result true or more certain. It only records the decision to place the result in the persistent semantic graph. Truth and confidence are still determined by `Belief_data`.

#### Lifecycle

Trace-local results usually live with their [[#^def-SemanticTrace|`SemanticTrace`]] and may be compacted or deleted during memory compaction when no longer required for provenance, evidence, replay, or other retention obligations.

Assigning a new value to a local variable or exiting a Python function does not delete saved results still needed to resume a task, recover, or evaluate it; they are protected by the shared [[#Retention Obligations|memory obligations]].

Persistent results have a lifecycle independent of the original trace and remain in the semantic graph until updated, generalized, retracted, or deleted under the persistent-graph lifecycle.

### `SemanticTrace` and Provenance Retention
#topic_details

[[#^def-SemanticTrace|`SemanticTrace`]] contains the ordered retained subset of [[#^def-TraceEvent|`TraceEvent`s]] from its [[#^def-ProgramRun|`ProgramRun`]].

It does not define provenance dependencies: those are determined by `TraceOutputRef`, event inputs/outputs, and links between `ProgramRun`s.

However, `SemanticTrace` participates in provenance lifecycle because it determines which part of the trace survives compaction; required dependencies form the [[#^def-RetentionClosure|`Retention closure`]]:

```text
TraceOutputRef + event dependencies
→ define provenance

retention closure
→ defines the minimum trace data
  that must be retained

SemanticTrace
→ stores the retained experience for a ProgramRun
```

Immediately after execution, the full trace may be retained. Later, [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]] retains only events and data needed for future use.

If the full raw form of a retained `TraceEvent` is compacted, its identity and data needed to resolve `TraceOutputRef` and promised provenance must remain available. This does not create a new event type: logically, it is still the same `TraceEvent`.

### Provenance Retention

#topic_details

While a result is protected and its provenance must be recoverable:

```text
created_by
→ protects the producer TraceEvent;

retention closure
→ protects required upstream events,
   inputs, and control-flow dependencies;

ProgramRun
→ is retained as needed for
   program/version and call provenance.
```

Do not physically destroy a [[#^def-TraceEvent|`TraceEvent`]] referenced by an active `created_by` while leaving a dangling `TraceOutputRef`.

Other events may be removed from retained [[#^def-SemanticTrace|`SemanticTrace`]], moved to cold storage, and later physically deleted when no longer required for:

```text
provenance of protected results;
evidence and belief recomputation;
replay or Evaluation;
retained decisions or Program changes;
other retention obligations.
```

After verified compaction or generalization, the depth of retained provenance may be reduced if the corresponding old dependencies no longer belong to the [[#^def-RetentionClosure|`Retention closure`]].

---
### Main Views

#topic_details

```text
producer_of(value)
→ TraceOutputRef that created the value

consumers_of(value)
→ retained TraceEvents and input slots
  where the value was used

provenance_of(value, max_depth?)
→ upstream provenance subgraph for the value

dependents_of(value, max_depth?)
→ retained downstream dependencies of the value
```

These views are computed over trace storage and do not create duplicate semantic relations.

For a protected result, `provenance_of(...)` must remain recoverable within its saved `retention closure`.

`consumers_of(...)` and `dependents_of(...)` describe retained history and are not required to represent every downstream use that ever existed after permissible deletion of old traces.

`dependents_of` shows computational dependency; by itself, it does not assert a causal effect.

## Semantic Relations and Memory

#topic_core

`RelationInstance` follows the shared lifecycle for semantic results: by default, it is trace-local; when it has long-term value, it is materialized through a `GraphDelta`.

Persistent semantic relations are used as:

```text
facts and generalizations in the world model;
knowledge cache of reasoning results;
retrieval routes between related concepts and experience.
```

Consolidating several cases may produce a generalized relation:

```text
scenario results
+ observations
+ evaluations
→ ConsolidationProgram
→ generalized relation
```

For example:

```text
CAUSES_UNDER(
  cause = Infection,
  effect = Death,
  condition = NoTreatment
)
```

## Memory Retrieval

#topic_details

Memory is retrieved from two related stores:

```text
persistent semantic graph
→ long-term Facets, facts, relations, and generalizations;

trace storage
→ program execution experience:
   ProgramRun,
   SemanticTrace,
   retained TraceEvents,
   their arguments and OperatorOutput.
```

Original user messages, responses actually sent, tool calls, and their results are retained as sources and corresponding experience in the trace. To restore context, the system retains the author or role, ordering, known times, and links to the task, episode, or call. A record of an attempted send or an unknown outcome is not presented as confirmed delivery; an internal LLM response is not itself a message to the user.

[[Cognition and Attention#^context-preparation|`ContextPreparation`]] retrieves relevant recent and earlier sources and results for the task, episode, and current work. It can access the exact saved content or a compressed representation with known loss of detail. Compressing a representation for a specific call does not delete the source: its retention period is determined by the [[#Retention, Compression, and Forgetting|shared memory lifecycle]].

[[#^def-SemanticTrace|`SemanticTrace`]] determines which [[#^def-TraceEvent|`TraceEvent`]] instances from a particular [[#^def-ProgramRun|`ProgramRun`]] are retained as accessible experience.

An event's meaning is specified by:

```text
operator;
typed arguments;
the TraceEvent.output contract.
```

The [[#^def-OperatorOutput|`OperatorOutput`]] contract provides a trace-local semantic projection of the result. Its elements are addressed through `TraceOutputRef`, but are not separate memory sources.

If a result should become part of the long-term world model, the program materializes the corresponding semantic objects or facts through `GraphDelta`:

```text
TraceEvent.output
→ GraphDelta
→ persistent semantic object / fact
```

The persistent object retains provenance to the original `TraceEvent.output`.

Main retrieval paths:

```text
persistent semantic object
→ created_by / TraceOutputRef
→ TraceEvent
→ ProgramRun
→ SemanticTrace;

Program / Task / time range
→ ProgramRun
→ SemanticTrace
→ retained TraceEvent
→ arguments and output;

semantic query
→ persistent semantic graph
   and semantic indexes over retained TraceEvent.output
→ corresponding semantic objects or TraceEvents.
```

A search may start, for example, from [[Core data structures#^def-Instance|Instance]], [[Core data structures#^def-Facet|Facet]], [[Core data structures#^def-Concept|Concept]], or [[Semantics Plane#^def-RelationType|RelationType]]:

```text
Instance;
Facet;
Concept;
RelationType;
Program;
ProgramRun;
Task;
Note;
Claim;
Prompt;
SignalSample;
time range.
```

## Retention, Compression, and Forgetting

### Motivation and Basic Model

(def_id:: concept.Forgetting)
> [!definition]
> **Forgetting in EverTree** is the managed reduction of memory volume while preserving what is still needed for action, learning, knowledge revision, explanation, and generalization.
> ^def-Forgetting

The value of experience often becomes clear only later. A routine [[#^def-ProgramRun|`ProgramRun`]] today may become important after a new dependency, model error, or source reassessment is discovered. Therefore, experience is initially retained in enough detail, and irreversible deletion occurs only after review.

Memory and the `ProcessModel` applicable to the experience develop together: new experience refines process models, while sufficiently confirmed models allow recurring experience they explain to be represented more compactly. **What is compressed is not simply whatever a model explains, but whatever has been justified as redundant in detail.**

Memory does not have to provide exact recovery of the entire past or support learning for every future model. It retains enough information for current obligations and expected useful future learning, including the ability to reconsider today's understanding of experience.

There are two basic operations:

```text
compact
→ reduce the retained detail of experience,
  creating a compact replacement when needed;

delete
→ queue data that is no longer needed for deletion.
```

The ordinary lifecycle is:

```text
full registered representation of experience
for the initial_full_retention_period
        ↓
review
        ↓
keep / compact / delete
        ↓
for data marked for deletion:
recoverable during the deleted_protection_period
        ↓
review retention obligations again
        ↓
physical deletion
```

Each memory object is periodically reviewed by [[#^def-ExpirienceCompactionJob|`expirience_compaction_job`]] according to the [[#Memory Review Schedule|review schedule]]. **Completeness applies to the semantic surface of experience**, not to every technical detail of execution.

The agent may also deliberately start compaction.

#### Memory Review Schedule

**`memory_compaction_ladder`** is a developer-defined mandatory sequence of reviews in runtime configuration: a non-empty Python tuple of positive, strictly increasing durations **measured from object creation**. Example with fixed intervals in days:

```python
from datetime import timedelta

memory_compaction_ladder: tuple[timedelta, ...] = (
    timedelta(days=7),
    timedelta(days=30),
    timedelta(days=365),
    timedelta(days=3650),
)

initial_full_retention_period = memory_compaction_ladder[0]
```

`initial_full_retention_period` is the name used below for the first rung, derived from the ladder; it is not a separate configuration parameter. After the last rung, reviews repeat at intervals of `memory_compaction_ladder[-1]`: in the example, the next review dates are 7300 and 10950 days from creation.

`CompactExpirienceProgram` or consciousness may schedule an earlier review with a reason, but may not postpone a required date or change the ladder. An early review does not shift later dates or cancel a required review. It can count in place of the nearest required review only within a small configured allowance before that date.

A material change to an object through `GraphDelta`, completion of a related task, a change to [[#Retention Obligations|retention obligations]], a discovered error, or a better generalization also schedules affected records for early review. Changes already accounted for during a review do not create duplicate requests. The ladder limits how long a regular review can wait, but does not replace responses to new circumstances.

A review date means the object must be included in the review batch of the next job run. Processing follows the [[Cognition and Attention#^sequential-tasks|shared sequential execution order]]; an overdue review remains pending until it is actually performed. Queuing or a failed attempt does not count as a completed review.

Runtime retains completed and pending reviews. A `keep` decision, a change to an existing object, or its compaction does not reset its age or schedule; when it is replaced by a compact representation, review obligations transfer to that representation.

At each review, choose `keep / compact / delete` under the [[#Compaction Review and Accountability|shared rules]]. An early review does not shorten `initial_full_retention_period` or cancel retention obligations. `delete` follows the [[#Delete and deleted_protection_period|deletion lifecycle]] without waiting for the next rung; canceling `delete` returns the object to its previous schedule, including pending reviews.

#### Adaptive Storage Detail

#topic_details

`CompactExpirienceProgram` selects the level of detail based on age, [[#^def-MemorySignificance|significance]], and reproducibility of experience; applicability of models and their `BeliefData`; unfinished tasks; and the overall memory budget.

**Recent experience is kept in greater detail regardless of model confidence.** It is needed to check forecasts, detect unaccounted dependencies, and detect process changes. Decisions about further compression also consider the number of suitable observations, outcome delays, and the process timescale; age alone is not enough.

**Confidence and `BeliefData` affect how much information may be lost.** Other things equal, a confirmed regularity permits stronger compression of its recurring instances. Weak grounds, uncertain applicability, contradictions, or competing explanations require retaining more detail that distinguishes them.

**Process variability is not the same as ignorance of its regularities.** A confirmed distribution can compactly represent random outcomes without retaining every case. Reversible compression is also possible without an explanatory model; for example, “50 zeros over `[t0,t1]`, then 50 ones over `[t1,t2]`” preserves the important temporal structure exactly.

#### What a Compact Representation Preserves

#topic_details

Consolidation preserves not only exceptions, but also **the overall shape of observed experience at the necessary precision**: characteristic values, frequencies, spread, and significant dependencies, including temporal ones.

Models, rules, aggregates, quantiles, and selected representative cases are used for this. A model alone is not always enough: for example, `y ≈ 2x` does not describe the distribution of `x` or the deviations in `y`, so required characteristics are retained separately in compact form.

Within the budget, representatives are kept for typical groups and rare, significant cases. Detail is allocated based on frequency, within-group diversity, and the importance of retention: common groups need representations of important variation and noise, while rare groups must not be lost just because they are infrequent. When necessary, representatives retain more context than the current model uses. Selection does not depend only on model error: an unaccounted dependency may also exist among apparently ordinary cases.

Recurring exceptions may also be generalized when their characteristics, frequencies, and required context are retained. Unusualness alone does not require keeping every case indefinitely.

This representation is a shared foundation for [[Datasets#^def-Dataset|datasets]] used for training and evaluation. A future model may need features or dependencies the generalization no longer retains; the required detail is protected according to the [[Datasets#Lifecycle|dataset's purpose]].

If a representation depends on a specific model version, retain the required revision so future training does not change the meaning of the past.

#### Frequencies of Retained Experience
#topic_core
^experience-frequency

If a group, representative, or [[Core data structures#^def-Prototype|Prototype]] replaces many observations, retain their original count. Otherwise, after compression, one rare case and a representative of a thousand ordinary cases would appear equally frequent. Interpretation requires:

- **Unit of count:** events, episodes, outcomes, or messages.
- **Count and denominator:** how many cases are represented and which experience is used to calculate their share.
- **Observation scope:** inclusion conditions, period, sources, and known selection rules.
- **Precision:** an exact count or an estimate with method and uncertainty; unknown values are not replaced by guesses.

#topic_details

Statistics may be stored in shared aggregates. Observations are counted before representatives are selected; compression carries forward their counts, ratios, and achieved precision. Re-selection or removal of redundant records does not reduce the volume represented. New observations, corrections, or changes to the window or counting conditions change the statistics.

When groups are merged, source experience is not counted twice. Information about overlaps is retained as needed for merging and correction; an unknown overlap prevents treating the sum as exact. Several accounts of one event may be several messages but still one event. Retrieval, replay, and repeated training do not add source events.

Frequency in collected experience does not guarantee the same frequency in the world; that depends on sources and selection. It also does not determine the number of independent confirmations, `Strength/Support`, or learning weight; those follow the [[Uncertainty and Belief Tracking in the World Model#^def-Evidence|evidence]] and [[Learning system#Data and Automatic Updates|learning]] rules.

### Compaction Review and Accountability

`CompactExpirienceProgram` chooses the storage form and, when needed, calls `MemoryConsolidationProgram` to create a generalization and `CompactionValidationProgram` to check whether information loss is acceptable.

The review checks not only fit to the current model but also retention of required properties of experience: frequencies, spread, significant dependencies, temporal distinctions, evidence, and provenance. Repeated compaction accounts for precision already lost.

Good model fit does not cancel retention obligations. A case may still be needed by another model, for evaluation, explanation, or an unfinished task.

```text
detail is still needed
→ keep;

needed information is preserved
in a verified compact representation
→ compact;

data no longer has enough expected value,
is not protected by retention obligations,
and has passed deletion checks
→ delete.
```

### Storage and Access

Storage lifecycle and retrieval answer different questions:

```text
storage lifecycle
→ which data continue to exist
  and in what form;

retrieval policy
→ which existing data are found
  and in what order during ordinary search.
```

Low usage frequency may affect the estimate of future experience value, but by itself does not prove redundancy or authorize deletion.

### Trace-Local and Persistent Results

TODO: partial duplicate of the Trace-Local and Persistent Results section above.

**[[#^def-TraceLocalResult|Trace-local result]]** is the result of an anchored operator, saved in [[#^def-TraceEvent|`TraceEvent.output`]] and addressable through `TraceOutputRef`.

It belongs to a specific execution:

```text
TraceOutputRef
→ TraceEvent
→ ProgramRun
```

By default, semantic objects and relations built from such a result remain local to the trace.

**[[#^def-PersistentResult|Persistent result]]** is a semantic object or relation that a program explicitly placed in the persistent graph through `GraphDelta`.

A persistent result can be used independently of its original run, but retains provenance to the trace from which it was derived.

Moving a result into the persistent graph does not mean that the entire source trace must be retained indefinitely. After consolidation, only its `retention closure` may remain.

A trace-local result is usually compacted sooner if it:

```text
was not materialized through GraphDelta;
was not used downstream;
did not become evidence;
did not affect a decision, belief, or Program;
is not needed for replay, Evaluation, or debugging.
```

A persistent result is retained longer because it participates in long-term reasoning and retrieval, but it too may later be compacted, replaced, or queued for deletion under the shared memory rules.

### Memory Lifecycle Components

The compaction and deletion lifecycle is distributed across several components with non-overlapping responsibilities.

All components of type `Program` are learnable and evolve through EverTree's shared program lifecycle. Jobs and system invariants are infrastructure and are not trained.

#### ProgramRunRecorder

`ProgramRunRecorder` automatically records executions:

```text
ProgramRun;
TraceEvent;
SemanticTrace;
arguments and outputs;
links between nested ProgramRun instances.
```

It does not assess the value of experience or decide how it should be retained later.

#### Experience Evaluation

[[Learning system#^def-PredictionEvaluator|`PredictionEvaluator`]] uses memory to find predictions and related observations through `match_predictions`, then checks them through `evaluate_prediction`. `handle_unmatched_observations` handles unmatched experience: it records a missing prediction for a known selected target through [[Learning system#LearningCredit and UnresolvedCredit|UnresolvedCredit]] and passes cases requiring analysis to consciousness. Results are saved in the trace.

Experience evaluation is separate from memory compaction.

#### expirience_compaction_job

(def_id:: entity.ExpirienceCompactionJob)
> [!definition]
> **`expirience_compaction_job`** is a periodic infrastructure job that creates a `review batch`: a set of accumulated memory and persistent semantic results whose review date has arrived.
> ^def-ExpirienceCompactionJob

The batch includes trace experience and persistent semantic objects or facts due for first, recurring, or early [[#Memory Review Schedule|review]]. Previously retained or compacted objects and overdue reviews are included as well. Each object appears once; a request already pending is not duplicated.

The job does not decide what to do with the objects. It schedules an internal [[Cognition and Attention#Goal, Task, and Task Specification|Task]] for the review batch through [[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]] in the [[Cognition and Attention#^sequential-tasks|shared sequential execution order]].

### CompactExpirienceProgram

(def_id:: entity.CompactExpirienceProgram)
> [!definition]
> **CompactExpirienceProgram** is the main learnable program that receives a `review batch` and chooses how its items should be retained, maximizing expected long-term value within memory and processing costs.
> ^def-CompactExpirienceProgram

Compaction is connected to generalization: if several cases are more useful as a shared structure, the program may pass them to [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]], save the resulting generalization, and reduce the detail of the source experience.

```text
review batch
        ↓
CompactExpirienceProgram
        ↓
keep / delete
or
related experiences
        ↓
MemoryConsolidationProgram
        ↓
generalized / aggregated representation
        ↓
validation
        ↓
final keep / compact / delete
```

The program chooses:

```text
keep
→ the original representation retains independent future value;

compact
→ useful information is preserved in a more compact
  or generalized representation;

delete
→ data no longer provide enough expected value
  and are not protected by retention obligations.
```

To find possible shared structure, the program may group review-batch items by semantic structure, [[#^def-Episode|Episode]] or Process, objects, relation types, [[Uncertainty and Belief Tracking in the World Model#^def-BeliefTarget|`BeliefTarget`]], provenance, and other relevant features.

One or more related cases are passed to `MemoryConsolidationProgram`. When needed, it uses retrieval to find similar, contrasting, or excluding cases in earlier memory. Retrieval is conditioned on the experience already passed in; consolidation does not begin with an arbitrary search across all memory.

After successful generalization, retain required evidence, provenance, representatives, exceptions, and details not yet replaced by the generalization.

The final `keep / compact / delete` decision belongs to `CompactExpirienceProgram`. `MemoryConsolidationProgram` constructs a proposed generalization, and [[#^def-CompactionValidationProgram|`CompactionValidationProgram`]] checks whether the loss of original detail is acceptable.

```text
CompactExpirienceProgram
├── MemoryConsolidationProgram?
└── CompactionValidationProgram?
```

#### Retention Obligations

#topic_details

**Retention obligations** specify which experience or result must not currently be lost, and why.

```text
operational
→ experience is needed by an active result, belief, claim,
  Program, TrainingDataset, EvaluationDataset, EvaluationCase,
  analysis, insight, decision, or action;

epistemic
→ experience or its compact representation is needed for correct
  BeliefData / EvidenceStats, revise/retract,
  source reassessment, or preserving a significant contradiction;

→ relevant non-distinguishing checks
  (`Δ = 0`, `evidence_mass = 0`) are also retained
  when needed for correct EvidenceStats;

audit
→ experience is needed to recover the grounds for
  a significant agent change;

coverage
→ experience is needed as an edge case, counterexample,
  representative of a regime, poorly explained case,
  or control routine example.
```

Explicit requirements from a user, supervisor, safety system, or retention policy also prohibit losing the corresponding experience.

An obligation requires retaining the necessary information, but not necessarily the original experience: after correct consolidation, a compact representation preserving the required invariants is sufficient.

[[Datasets#Lifecycle|Requirements of an active dataset]] protect the required level of detail while data collection continues. When that need ends, the protection is removed unless another task or obligation requires it. Retaining a training or evaluation result does not by itself require indefinite retention of the entire dataset; retain dependencies required for the stated future use of the result.

For a recoverable run, also retain the required code versions, inputs, results, and [[Cognition and Attention#^durable-program-execution|DBOS journal]]. Compressing a `SemanticTrace` does not allow deleting data still needed to continue the run; the technical execution journal has its own retention period.

Data needed for [[Cognition and Attention#^program-restart-continuation|continuing a Task without repeats]] are retained while the Task needs them, including after a replaced `ProgramRun` ends.

In the MVP, experience retention after a failure is limited to the [[Cognition and Attention#^agent-backup|last shared backup]]: later experience may be lost. Dependencies of retained backups are also protected from deletion.

#### Retention Closure

(def_id:: entity.RetentionClosure)
> [!definition]
> **Retention closure** is the minimal set of dependencies that must be preserved **together with an already protected object** to retain its provenance, significant evidence, and context of creation or use.
> ^def-RetentionClosure

It may include:

```text
producer TraceEvent;
significant inputs and their producers;
branch conditions and key alternatives;
comparison / decision events;
significant evidence;
ProgramRun;
graph-writing event;
required portion of the caller chain.
```

In other words:

```text
retention obligations
→ determine what must not be lost;

Retention closure
→ propagates that protection
  only to necessary dependencies.
```

The mere presence of an event in upstream provenance does not create a retention obligation. It belongs to the `retention closure` only if the protected object cannot be correctly used, recomputed, explained, or reproduced without it.

After verified compaction or generalization, `retention closure` is recalculated and may be reduced if some former dependencies are no longer needed.

`Retention closure` is a computed view, not a separate entity or program.

#### Compaction

##### Compacting SemanticTrace

After `initial_full_retention_period`, [[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]] may shorten `SemanticTrace`, retaining events that must or are expected to remain useful:

```text
[E1, E2, E3, E4, E5]
→ compact
[E1, E3, E5]
```

#topic_details

All [[#^def-TraceEvent|`TraceEvent`]] instances required by the current `retention closure` must remain in their corresponding [[#^def-SemanticTrace|`SemanticTrace`]]. The relative order of retained events does not change; immutable `TraceEvent` instances themselves are not rewritten.

Each nested [[#^def-ProgramRun|`ProgramRun`]] is compacted independently. Its `SemanticTrace` may be shortened to empty, while the `ProgramRun` itself is retained if its metadata, call context, or provenance is still needed.

Excluding a `TraceEvent` from `SemanticTrace` does not mean `delete`: deletion is decided separately under the shared lifecycle rules.

---

##### Compressing the Persistent Graph

A persistent result may also be compacted or marked for `delete` under the general memory rules; for example, if it is duplicated, replaced by a more current representation, or better expressed by a generalization.

#topic_details

A state becoming historical, incorrect, or later retracted does not by itself make it unnecessary. It may be retained if it affected an action, a `Program` change or belief, became significant evidence, represents an important rare case, or is needed to reconstruct history.

The lifecycle of a persistent result and its source trace are independent:

```text
persistent result retained
≠ entire source trace must be retained;

persistent result marked for delete
≠ source trace is automatically deleted.
```

It is enough to retain the portion of the source trace required by its own retention obligations and `retention closure`.

---

##### Compacting a Child ProgramRun

Each nested [[#^def-ProgramRun|`ProgramRun`]] is compacted independently; the same rules apply recursively to the entire tree of nested runs.

---

### Compressing Evidence

[[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`BeliefData`]] is a derived view and does not replace evidence needed for later belief `revise`, `retract`, or reassessment.

Repeated compatible [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|`EvidenceAssignment`]] instances may be consolidated by [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]]:

```text
EvidenceAssignment[]
        ↓
MemoryConsolidationProgram
        ↓
consolidated EvidenceAssignment
```

Consolidation must preserve evidence equivalence for supported ways of reading belief, including `Support` and [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceStats|`EvidenceStats`]]:

```text
belief before consolidation
≈
belief after consolidation
```

Retain the minimum information needed for temporal or dependency adjustments, idempotency, and required `revise/retract` granularity, as well as significant distinctions: important dependency branches, different sources or regimes, confirmations and refutations, exceptions, and at least one representative experience for each collapsed group.

After successful consolidation, redundant source `EvidenceAssignment` instances, routine observations, and provenance details may be marked for `delete` if the consolidated representation preserves required information and they are no longer part of the current `retention closure`.

---

##### Compacting the Content of Individual Objects

[[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]] may reduce the size of one large experience object without merging it with other cases or creating a more general model.

For example:

```text
long Note or other text
→ summary;

large external document
→ shortened content;

long numeric series
→ aggregate statistics / quantiles / sketch;

large structured result
→ more compact representation.
```

This differs from [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]]:

```text
compaction of one object
→ reduces its detail;

consolidation of several cases
→ identifies shared recurring structure
  and creates generalized knowledge.
```

`ContentCompactionProgram` creates a compact representation of the content of one object. If the source details are then to be deleted, `CompactExpirienceProgram` checks whether the new representation is sufficient for future use of the experience.

### MemoryConsolidationProgram

#topic_core

(def_id:: entity.MemoryConsolidationProgram)
> [!definition]
> **MemoryConsolidationProgram** is a learnable memory-generalization program. It receives one or more specific, related cases of experience from [[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]] and checks whether they can be represented together with relevant past experience as more general, reusable knowledge.
> ^def-MemoryConsolidationProgram

When needed, the program uses retrieval to find similar, contrasting, and excluding past cases. Its query is based on the passed experience and its semantic structure/provenance; consolidation does not begin with an arbitrary topic search.

Each run considers significant changes, successes, and difficulties in the supplied experience. When needed and within budget, it compares them with [[Evaluative-Control System#^aggregate-queries|aggregates]] and initiates [[Learning system#^outcome-credit|credit assignment for a Task or process outcome]].

```text
related experience
        ↓
MemoryConsolidationProgram
        ↓
optional retrieval of related history
        ↓
generalized representation / aggregate
```

#topic_details

Common forms of generalization:

```text
repeated Facets of one Instance
→ more stable model / generalization of the Instance;

similar Instances
→ Prototype;

repeated observations, Claims, relations, or ProgramRun instances
→ aggregate / generalized semantic representation;

compatible recurring evidence
→ consolidated EvidenceAssignment.
```

Consolidation therefore performs compaction and generalization at once: recurring structure becomes available for prediction, reasoning, and further learning without analyzing every source case each time.

If a result should become persistent knowledge:

```text
consolidation result
→ GraphDelta
→ persistent semantic graph
```

If a discovered regularity requires a `Program` change, it is passed to structural revision / Program Lifecycle; `MemoryConsolidationProgram` does not change programs itself.

For a specific consolidation, the program must:

```text
identify shared structure;
create a generalized representation;
define its applicability boundaries;
identify which source cases it covers;
select required representatives and exceptions;
record significant distinctions and loss of detail.
```

A generalization must not reduce experience to an average case alone. When needed, retain:

```text
significant evidence and provenance;
representative cases;
different regimes;
edge cases and counterexamples;
rare or contradictory outcomes;
unresolved contradictions;
a small control sample of routine experience.
```

Otherwise, successive consolidation may destroy evidence against the model itself.

For example:

```text
1000 similar successful ProgramRun instances
        ↓
MemoryConsolidationProgram
        ↓
generalized model / aggregate
+ representatives
+ exceptions
+ necessary provenance
        ↓
CompactExpirienceProgram
        ↓
redundant source traces may be marked compact / delete
```

Frequency alone does not justify generalization or deletion. Consolidation is useful if the more general representation preserves or improves the agent's ability to:

```text
predict;
transfer knowledge;
distinguish significant cases;
detect deviations;
continue learning.
```

`MemoryConsolidationProgram` does not make the final decision about retaining source data. It returns the generalization and information about which source cases it covers and which details must be retained.

```text
MemoryConsolidationProgram
→ ConsolidationResult
        ↓
CompactExpirienceProgram
→ CompactionValidationProgram, if needed
→ keep / compact / delete
```

The final decision is constrained by retention obligations, `retention closure`, and memory system invariants. Protected source experience remains retained regardless of how well a generalization covers it.

#### Example: Experience → Instance Generalization

#topic_details

Across separate poker hands, the agent obtains beliefs about Igor's specific actions:

```text
BLUFFS(Igor, Bet#17)
BLUFFS(Igor, Bet#83)
BLUFFS(Igor, Bet#124)
```

During review, similar cases become source material for [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]], which may retrieve additional past experience and generalize it:

```text
specific bluff / non-bluff cases
        ↓
MemoryConsolidationProgram
        ↓
BluffTendency(Igor)
        ↓
CLASSIFIED_AS(Igor, BluffProne)
```

Thus, experience from individual actions becomes learned knowledge about the [[Core data structures#^def-Instance|Instance]] itself.

#### Provenance and Referential Integrity

The following are prohibited:

```text
references to a physically missing TraceEvent;
TraceOutputRef to a missing output;
caller_event referring to a missing event;
a protected result without required provenance.
```

These are system invariants. A learnable program cannot override them.

#### CompactionValidationProgram

#topic_details

(def_id:: entity.CompactionValidationProgram)
> [!definition]
> **CompactionValidationProgram** is a program that validates proposed compaction.
> ^def-CompactionValidationProgram

It is called when compaction would lose source details. It checks whether hard referential integrity, required `retention closure`, reasoning and retrieval abilities, and `revise` / `retract` capabilities are preserved. It is not responsible for semantics; it validates references and structure and checks the [[#^def-ResultProvenance|result provenance]] and [[#^def-Memory|Memory]] referential integrity invariants.

#### DeletionFinalizationJob

#topic_details

`delete` does not physically destroy data.

Afterward, data remain recoverable for the duration of:

```text
deleted_protection_period
```

When the period ends, `DeletionFinalizationJob` checks required retention conditions again.

If no new dependencies have appeared:

```text
→ physical deletion
```

If they have:

```text
→ cancel delete
→ return data to the ordinary lifecycle.
```

`DeletionFinalizationJob` does not make a new semantic decision about the value of memory. It only completes or cancels an existing `delete` decision.

---

### Delete and deleted_protection_period

`delete` means a decision to stop retaining data long term, not to destroy it physically at once.

```text
delete
→ deleted_protection_period
→ final recheck
→ physical deletion
```

During `deleted_protection_period`, data remain recoverable.

If any of the following is discovered:

```text
new dependency;
retrieval failure;
regression;
generalization error;
need to revise;
need for replay;
another lost capability,
```

cancel `delete`.

For a [[#^def-TraceEvent|`TraceEvent`]], this means its reference can be returned to its original position in [[#^def-SemanticTrace|`SemanticTrace`]] by `seq`.

Such a case becomes new evidence for training [[#^def-CompactExpirienceProgram|`CompactExpirienceProgram`]], [[#^def-MemoryConsolidationProgram|`MemoryConsolidationProgram`]], or [[#^def-CompactionValidationProgram|`CompactionValidationProgram`]], depending on which decision was wrong.

After `deleted_protection_period` ends, `DeletionFinalizationJob` checks required retention conditions again and either physically deletes the data or cancels `delete`.

---

## Memory Signals

Memory uses EverTree's existing signals. They serve these roles:

```text
when recording
→ mark potentially important experience;

when learning
→ assign credit based on selected LearningTargets and experience context;

when consolidating
→ decide what to compact, link, retain, or delete;

when replaying
→ select which past experience to replay;

when retrieving
→ help rank candidates when there are too many.
```

---

### Memory Significance

(def_id:: concept.MemorySignificance)
> [!definition]
> **Memory significance (`significance`)** is a revisable estimate of the expected long-term value of retaining and making a memory or graph item accessible for future tasks, understanding, and agent development.
> ^def-MemorySignificance

```text
significance: "baseline" | "elevated" | "exceptional" | null = null
```

| Level | Meaning |
| --- | --- |
| `baseline` | The object has been assessed; no grounds for elevated significance have been established. Combines ordinary and low significance. |
| `elevated` | Noticeable added value for future work is expected, but there are no grounds for exceptional significance. |
| `exceptional` | Expected value is especially high, either globally for the agent's long-term self-improvement and generalization or within a particular domain, such as substantially extending understanding or capabilities. |

`null` means there is no assessment: the object has not been considered or the assessment cannot yet be justified. It is outside the scale and is not treated as `baseline`.

Choose the highest level justified by the assessment. The scale is [[Attribution Plane#2. Ordinal Axis|ordinal]]: boundaries are evaluative and no numeric distances between levels are defined. Exceptional significance does not require that the agent cannot replace the item; a breakthrough mathematical method may be significant within its field.

Assess selectively during substantive review by [[#^def-CompactExpirienceProgram|compaction]], [[#^def-MemoryConsolidationProgram|consolidation]], [[Self#From Experience to a Confirmed Problem|Reflection]], or [[Cognition and Attention#^def-Consciousness|consciousness]]. Retain a brief rationale and scope in the review result with ordinary [[#^def-ResultProvenance|provenance]]. Significance may be raised or lowered; it need not be assessed when every object is created. For immutable trace objects, store it separately with a reference to the object.

`significance` is an additional feature for [[#^def-RankMemories|RankMemories]] and for selecting storage detail in [[#^def-CompactExpirienceProgram|CompactExpirienceProgram]]. It is an assessment for memory management; the final retrieval score depends on the current query.

#### Cautions

- Novelty, retrieval frequency, use, or repeated review of the same experience do not by themselves justify increasing significance; it does not propagate automatically through relations or to a generalization.
- Significance does not increase reliability or define [[Learning system#LearningCredit and UnresolvedCredit|learning credit]] or training-example weight.
- Highlighting significant cases must not displace typical experience and counterexamples; storage detail accounts for [[#Retention Obligations|retention obligations]] and the value of information not yet retained by a compact representation.

### ExplanatoryTension and [[Evaluative-Control System#^def-TensionReduction|tension_reduction]]

[[Evaluative-Control System#^def-ExplanatoryTension|`ExplanatoryTension`]] is relative tension across selected processes, not a property of an individual memory. It aggregates `prediction_unexpectedness` already obtained during ordinary work.

A reduction in `ExplanatoryTension`, expressed as positive `tension_reduction`, may prompt review of traces for related updates and consideration of their usefulness. Provenance establishes a dependency path; it does not prove usefulness. Learning System assigns credit.

---

## Projection to Process and Program

For [[Datasets#^def-Dataset|training and evaluation]], EverTree projects saved experience onto a specific process and program using:

```text
process lens
→ what is relevant to the process's meaning;

program lens
→ what a particular program reads, predicts, or changes.
```

For `EvaluationCase`, see [[Process Plane/Program Evaluation and Testing#Contract-Based Evaluation|Contract-based Evaluation]].

Facts that do not pass through the projection are not included in the prepared example. They remain in memory and may become relevant later.

---

## Retrieval

#topic_core

Retrieval finds and orders saved experience for a specific query. Results are grouped into [[#^def-MemoryCandidateGroup|`MemoryCandidateGroup`]] instances and ranked by [[#^def-RankMemories|`RankMemories`]].

One public program:

```text
RetrieveMemories(query, limit)
→ ordered MemoryCandidateGroup[]
```

`MemoryQuery` describes the experience a consumer needs. In addition to semantic anchors, it may include explicit constraints on process, Program, objects, time, signals, or provenance/dependencies. The precise `MemoryQuery` structure will be refined as concrete use cases appear.

Retrieval uses two related memory sources:

```text
persistent semantic graph
→ Facets, facts, relations, generalizations, and other persistent results;

trace storage
→ ProgramRun, SemanticTrace, retained TraceEvent,
  and their arguments / outputs.
```

They are linked by provenance, so search can move between semantic knowledge and the experience that produced it:

```text
persistent result
↔ TraceOutputRef / provenance
↔ TraceEvent
↔ ProgramRun / SemanticTrace
```

### Pipeline

```text
MemoryQuery
  ↓
recall through available retrieval routes
  ↓
explicit constraints
  ↓
deduplication and grouping
  ↓
RankMemories(query, candidate groups)
  ↓
first limit groups
```

Retrieval routes are independent paths to memory:

```text
direct references;
semantic graph and provenance dependencies;
process / Program / operator / task links;
semantic indexes over persistent and trace memory;
signal and time indexes;
fallback semantic search.
```

`Explicit constraints` exclude only candidates that are clearly incompatible with the query. Uncertain relevance is not grounds for exclusion and is considered during ranking.

### Deduplication and Grouping

Before ranking, results from different retrieval routes are consolidated into groups.

Deduplication combines multiple references to the same memory. Grouping combines closely related, redundant experience so many nearly identical cases do not crowd out other results.

Cases must not be combined if their differences may matter to the query.

(def_id:: entity.MemoryCandidateGroup)
> [!definition]
> **MemoryCandidateGroup** is a local view for the current retrieval call, not a new persistent memory entity.
> ^def-MemoryCandidateGroup

### RankMemories

(def_id:: entity.RankMemories)
> [!definition]
> **RankMemories** is a learnable child Program of `RetrieveMemories` that orders already found candidate groups for the same `MemoryQuery`.
> ^def-RankMemories

```text
RankMemories(query, candidate groups)
→ ordered candidate groups
```

It does not search for new memories, apply explicit constraints, or change the memory lifecycle.

The main ranking criterion is:

```text
expected usefulness of a candidate group
for the current query.
```

Depending on the query, ranking may consider:

```text
semantic relevance;
Strength / Support and evidence applicability;
temporal applicability;
signal samples;
provenance and downstream dependencies;
history of use;
cost of access and processing.
```

These features are not universal multipliers. For example, high `Support` is useful when seeking reliable evidence and low `Support` when seeking doubtful cases; recency matters for a time-sensitive query but not necessarily an audit; provenance shows dependencies but is not a universal scalar score.

Therefore, memory has no permanent global `retrieval score`. Any score is specific to a particular `RankMemories` call.

In the MVP, one shared `RankMemories` program interprets `MemoryQuery`. Specialized rankers are added only if Evaluation reveals a systematic problem with the shared mechanism.

### Learning

`RetrieveMemories` and [[#^def-RankMemories|`RankMemories`]] are trained through the ordinary [[Learning system#^def-LearningSystem|Learning System]] using downstream outcomes from the use of retrieved memory.

Distinguish these error types:

```text
needed memory was not in the candidate groups
→ retrieval / recall error;

needed memory was found,
but ranked too low
→ ranking error.
```

Similarly, evidence about systematic incorrect filtering or grouping is assigned to the corresponding retrieval decisions.

[[#^def-ResultProvenance|Provenance]] shows which decisions contributed to the result. `CreditAssignmentProgram` links [[Learning system#LearningCredit and UnresolvedCredit|learning credit]] to the selected [[Learning system#^def-LearningTarget|LearningTarget]] and its use in the context of an evaluated outcome; `UpdatePlanner` selects the parameters to update.

## Replay

### Definition

#topic_core

(def_id:: entity.MemoryReplay)
> [!definition]
> **Memory replay** is a mechanism for returning selected saved experience to a separate processing pass as a [[Cognition and Attention#Goal, Task, and Task Specification|Task]], to continue its unfinished integration, reinterpret it, or use it for learning against a question or goal.
> ^def-MemoryReplay

```text
current experience
→ cognition / analysis;

completed experience analyzed afterward
within the same processing pass
→ Reflection (replay is not needed);

selected past experience is returned from memory to a separate pass
→ replay (may include Reflection).
```

`ReplayTask` may be selected immediately after an [[#^def-Episode|Episode]] ends or much later. What matters is a separate processing pass, not the physical length of the pause. Replay is created only when justified.

`ReplayTask` may cover one or several episodes related by a shared question or goal. For a conscious step, [[Cognition and Attention#^context-preparation|`ContextPreparation`]] loads the necessary parts of selected experience while retaining the context needed to interpret them. Using memory within the current `Task` is not by itself Replay.

> **Replay has no separate learning pipeline. It creates new internal processing experience that passes through the same [[#^def-ProgramRun|`ProgramRun`]], [[#^def-TraceEvent|`TraceEvent`]], Evaluation, credit assignment, and episode integration as live experience.**

### When Replay Is Needed

#topic_core

Replay is needed when reprocessing past experience has expected learning value: it may help explain what happened, assign credit more accurately, refine a model, improve a policy, or extract a transferable conclusion.

Common reasons:

```text
unexpected poor outcome
+ cause is unclear;

unexpected success
+ unclear what made it work;

ambiguous credit assignment;

strong supervisor_feedback_signal
+ unclear which decision or action caused it;

high prediction_unexpectedness
+ ordinary belief / parameter update
   does not explain the mismatch;

rare or unusual case;

possible regime change;

contradiction between episodes
or within one episode;

new Claim or model
that allows past experience to be interpreted differently;

regression or Evaluation gap
that may be understood through past experience.
```

High [[Evaluative-Control System#^def-PredictionUnexpectedness|`prediction_unexpectedness`]] or a strong/unusual outcome does not by itself require replay.

```text
strong outcome
+ cause is understood
+ required learning is done
→ replay is usually unnecessary;

significant outcome
+ cause, credit, or applicability boundaries are unclear
→ good replay candidate.
```

Replay may be planned immediately after an episode or much later, when new knowledge, a hypothesis, or a problem makes old experience informative again.

Another reason may be improving an already working strategy using accumulated experience if the expected benefit justifies the cost. An error or unfinished integration is not required.

### Replay and Signals

#topic_details

Signals help detect experience that may need reanalysis, but do not by themselves determine whether replay is needed.

`ReplaySelectionProgram` considers signals together with:

```text
BeliefData and EvidenceStats; provenance;
current model;
rarity;
contradictions;
previous replay attempts;
cost;
similar and contrasting episodes.
```

### ReplaySelectionProgram

#topic_core

Simplified interface:

```python
ReplaySelectionProgram(
  source_episode? = None,
  reason: str? = None,  # e.g. "why did I receive negative supervisor_feedback?"
)
→ ReplayTask[]
```

`reason` is the question or goal for Replay. Optional `source_episode` gives the selection process a starting point but does not restrict Replay to one episode. When needed, `ReplaySelectionProgram` uses [[#Retrieval|shared retrieval]] to select and supplement episodes based on `reason` and relevant signals.

---

### Scheduling Replay

#topic_core

`ReplayTask` uses the ordinary [[Cognition and Attention#^def-TaskExecution|task execution cycle]] and runtime without a separate scheduler. A ready, authorized `exec` program may run Replay automatically; a task needing a conscious step is added to the shared `AttentionPriorityQueue`.

“Sleep” time—time allocated for internal processing of experience—may be used for these tasks with a shared budget and the same conscious-processing queue. Reflection may initiate a `ReplayTask` or perform analysis and simulation within the current `Task` if a separate return to experience is not needed.

For a task waiting for conscious processing, `attention_priority` is calculated dynamically by:

```text
EstimateAttentionPriority(task)
```

---

### Executing Replay

#topic_details

The substantive work of a `ReplayTask` is:

```text
ReplayTask
  ↓
restore relevant observations,
predictions, decisions, actions,
outcomes, and signal samples
  ↓
add similar and contrasting episodes
  ↓
analyze using a delegated program
or consciousness after obtaining Focus,
using simulation and policy optimization when needed
  ↓
obtain integration results.
```

Replay creates a new [[#^def-Episode|Episode]] for internal processing, linked to the source episode(s).

It creates ordinary [[#^def-ProgramRun|ProgramRun]] instances, including:

```python
ProgramRun(run_mode="replay")
```

Replay may call ordinary Programs for [[Process Plane/Program Evaluation and Testing#3. Simulation Tests and Optimization|simulation and policy optimization]]. Child simulation runs have `run_mode="simulation"`; the calling replay run retains `run_mode="replay"`.

Source Episodes and [[#^def-TraceEvent|`TraceEvent`]] instances are not changed. New [[Core data structures#^def-Note|notes]] with reasoning, conclusions, decisions, and updates belong to the new Episode and retain [[#^def-ResultProvenance|provenance]] to the past experience used.

Possible outcomes include [[Uncertainty and Belief Tracking in the World Model#^def-EvidenceAssignment|`EvidenceAssignment`]], [[Learning system#LearningCredit and UnresolvedCredit|`LearningCredit`]], and [[Core data structures#^def-Claim|`Claim`]]:

```text
EvidenceAssignment
→ belief update;

LearningCredit
→ UpdatePlanner → parameter update;

Claim
→ further checking;

structural revision request
→ ProgramBranch / new Program / semantic change;

generalized relation or prototype
→ transferable knowledge;

EvaluationCase
→ check a specific hypothesis or Program;

experiment / action proposal
→ ordinary planning and action selection task;

no justified update
→ available evidence is insufficient.
```

[[#^def-MemoryReplay|Replay]] never automatically repeats an external action. It may only create an experiment proposal or action task, which then follows the ordinary planning, commitment, and safety mechanisms.

#### Example: Improving Play Against a Specific Opponent

`ReplaySelectionProgram(reason="How can I improve my play against Igor?")` may create a task with this plan:

1. **Gather experience.** Use [[#Retrieval|retrieval]] to select hands involving Igor and existing [[#Example: Experience → Instance Generalization|generalizations about him]]. Record the current policy for comparison. Recover decision situations: cards available at the time, bets, pot and remaining chip sizes, observed actions, and outcomes. Include different outcomes, not only losses.
2. **Refine the opponent model.** From actual actions, estimate probabilities of folding, calling, and raising based on the situation and the agent's actions. Hidden cards remain unknown; possible opponent hands are represented by a distribution consistent with the available history. Experience already accounted for is reused under the [[Learning system#PreparedUpdate, UpdateTransactionManager, and UpdateDispatcher|rules for duplicate accounting and parameter updates]].
3. **Simulate alternatives.** From selected situations, run continuations with different agent actions. An ordinary Program enumerates or samples legal cards, models Igor's responses, and computes results under poker rules. For specified cards and actions, the result is computed exactly; expected strategy winnings also depend on the model of hidden cards and opponent behavior. The policy sees only the player's information, even if the simulator knows all cards. Analysis defines options and budget, while many numeric simulations run without an LLM call for each hand.
4. **Improve the policy.** Compare the current strategy and candidates by expected net chip winnings under specified risk constraints. Check advantage under plausible variants of the uncertain Igor model. Selected simulation results are used for [[Process Plane/Program Evaluation and Testing#3. Simulation Tests and Optimization|policy optimization]] through the shared learning pipeline; analysis, runs, and updates may repeat within the task budget.
5. **Check and retain the result.** Held-out real hands test the predictions of Igor's model; separate simulation runs check policy winnings inside the model. Retain the improvement with its scope (“against Igor under these conditions”) and provenance to source experience, the model, and runs. Permitted parameter updates go through Learning System; code or contract changes go through [[Process Plane/Program Lifecycle and Evolution#General Program Lifecycle|Program Lifecycle]]. Later real games check transfer and provide experience for another cycle.

---

### Replay and Memory Lifecycle

An unfinished `ReplayTask` creates a retention obligation for the parts of source experience it needs.

---

## Overall High-Level Lifecycle for Processing and Integrating Experience

#topic_core

This diagram is for convenience and is not the source of truth; the sections above are.

It presents the [[Cognition and Attention#^agent-processing-cycle|overall agent cycle]] from the perspective of memory: conscious and automated processing belong to a `Task`, including observation, waiting, and Reflection. Observation delivery follows the [[Process Plane/Program Layer#^process-observation-input|execution input rules]]; semantic routing is needed only when the recipient is unknown or subject to review.

```text
new experience
        ↓
Memory → Episode
        ↓
TaskExecution: delegated Program work
and, when needed, Attention → Consciousness
        ↓
new observations / notes / decisions / actions / outcomes
        ↓
Memory + online Learning
        ↓
Episode continues
        │
        └── Episode completion
                    ↓
            episode-level integration
                    ↓
        ┌───────────────────────────────┐
        │ sufficiently integrated      │
        │ → no additional work now     │
        │                              │
        │ needs further analysis       │
        │ → Cognition / Reflection     │
        │                              │
        │ structural revision needed   │
        │ → Program Lifecycle          │
        │                              │
        │ useful as separate reprocess │
        │ → ReplayTask                 │
        └───────────────────────────────┘
```

Learning happens as evaluable evidence becomes available and does not wait for the `Episode` to end.

After the `Episode` ends, episode-level integration accounts for evidence that requires the entire episode context. Its outcomes are not mutually exclusive: for example, Reflection may produce a structural revision or a `ReplayTask`.

Replay returns saved experience to the same shared processing cycle:

```text
ReplayTask
→ TaskExecution: delegated Programs; Attention → Consciousness when needed
→ new internal Episode
→ Memory + Learning
→ episode-level integration
```
