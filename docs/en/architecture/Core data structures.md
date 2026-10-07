---
status: stable
target_version: next
---

## Introduction and Graph Data Structure
#topic_core

(def_id:: evertree.CoreStructure)
> [!definition]
> **EverTree's core data structure** — a directed, dynamic, cyclic hyper-multigraph that combines symbolic structure (knowledge) with neural dynamics (learning, actions, prediction, rewards, reflection, and self-regulation).
^def-CoreStructure

One of the key innovations is the active use of a graph to:

- structure knowledge about the world with clear, verifiable information sources and eliminate hallucinations;
- structure and preserve internal programs (algorithms) for actions in different circumstances and tasks;
- enable graph analysis, opening the way to meta-learning;
- modify the graph quickly during execution (test time);
- structure an individual's experience as part of memory, retaining important information and significant situations while removing redundant or irrelevant data;
- use weighted influence similar to the way different neurons contribute to a final decision. This is especially useful for tasks and learning stages where precise verbal rules are difficult to create but outcome probabilities are available for different situations. _For example, an “unfair” coin with probabilities different from 50/50._
- integrate feed-forward neural-network decision trees or linear regression as custom components to manage policies in specific processes;
- support a kind of alternative to Monte Carlo Learning.

The graph as a structure, combined with an LLM that produces updates, can be viewed as a meta-mechanism for learned gradient descent: only weights that need to change are updated based on the agent's experience and objectives. This approach enables rapid, efficient, and flexible learning at test time.

---

## Nodes
#topic_core

### Basic Node Types

The EverTree graph consists of the following node types: [[#^def-Concept|concepts]], [[#^def-Input|information inputs]], outcomes (containing predictions of world states), reward nodes, and actions (external and internal).

### Node Specification Format
#policy

> [!INFO]
> Obsidian-friendly, Python-first:

#### General Node Definition Template

(formal_id:: schema.NodeTemplate)
```python
<NodeName>: <Base1(Strength1)>, <Base2(Strength2)> {
  field: <Type> "description"                    # required
  field?: <Type> "description"                   # optional
  field: <Type>=value "description"              # default
  field: <Type[]> "description"                  # list
}
```
^spec-NodeTemplate

`"description"` is the minimum necessary (under Occam's razor) **semantic contract** defining interpretation boundaries: **what the field means and what it does not mean**. It should be short and clear, yet precise enough. Add the field's purpose/role when needed.

Example:

(formal_id:: schema.SimpleCodeNode)
```python
SimpleCodeNode: FakeTextNode(0.95), {
}
```
^spec-SimpleCodeNode

#### Naming Conventions

| Element | Style | Example | Note |
|---|---|---|---|
| **NodeName** | `PascalCase` | [[#^def-Node|`Node`]], [[#^def-Concept|`Concept`]], [[#^def-Instance|`Instance`]] | Entity name |
| **Fields** | `snake_case` | `belief_state`, `t_from` | Data fields |

#### Data Typing

Types follow Python typing style, but use angle brackets `<...>` as metanotation.

Default values are specified with an equals sign `=`.

Basic types:

- Scalars: `<int>`, `<float>`, `<bool>`, `<string>`
- Time: `<time>`
- Objects: `<X>` — an object of type `X`
- Lists: `<T[]>` (equivalent to `list[T]`)
- Dictionaries: `<dict[K,V]>`

#### Objects and References

Application interfaces and fields pass objects (`value: X`). Passing an argument within a Python process does not copy the object. Use `Ref` / `_ref` when a value denotes an address where an object can be found, for example [[Memory#Recording Provenance|`TraceOutputRef`]]. A separate `XRef` for every type `X` is unnecessary.

The runtime is responsible for identifying, transferring between processes, saving, and loading objects. When persisted, links to already addressable objects are encoded using their stable identity (the same object on subsequent lookup); results inside an output use [[Memory#^def-ResultProvenance|provenance]]. Their contents are not recursively copied every time they are included in another object; new values are saved with the data needed to resolve addresses under [[Memory#^def-RetentionClosure|retention closure]].

A Python reference is not a persistent address by itself. After loading or transferring between [[Cognition and Attention#2. Isolation of the Protected Core and Executable Programs|core and worker processes]], the runtime preserves logical identity, although Python instances may differ. This is a runtime responsibility, not an automatic guarantee of the serializer.

#### Required Fields

The following technical fields always exist on every node and never change:

- `id: <int>` — a unique node ID slot (monotonic counter/generator); a technical field hidden from System 1 and System 2, used for addressing and references.
- `activations: <dict[Axis, float]>` — the node's current activation levels along different axes/relationship types. It indicates “how relevant/active” the node is in each channel (causality, mereology, association, temporal proximity, and so on).
- `name: <string>` — a short, clear node name (a few words), without ambiguity or synonyms; it must distinguish the node from similar entities.
- `description?: <string>` — an optional explanation used when `name` is insufficient; it defines semantic boundaries (“what this is / is not”) and prevents misinterpretation.

_These fields are not specified when concepts are declared._

### Inheritance and Semantics
#topic_core

> [!WARNING] Important: node type ≠ inheritance
>
> Inheritance is defined by the **Abstraction Ladder** and applies to **[[#^def-Concept|Concept]]** (including axes and [[Semantics Plane#^def-RelationType|`RelationType`]]). Node types on the abstraction ladder ([[#^def-Prototype|`Prototype`]] / [[#^def-Instance|`Instance`]] / [[#^def-Facet|`Facet`]]) are simply concept symbols used for thinking and reflection.

Taxonomic inheritance is expressed by the relation:

```text
SUBTYPE_OF(type, supertype)
```

[[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`Belief_data`]] for this relation has its ordinary epistemic meaning:

```text
Strength
→ how confident the agent is that type is actually a subtype of supertype;

Support
→ how much effective evidence underlies this estimate.
```

For example:

```text
SUBTYPE_OF(Dog, Animal)
BeliefData:
  Strength = 0.99
  Support = ...
```

means that the agent is highly confident in the taxonomic relation itself, not that “Dog inherits 99% of Animal's properties.”

#### Inheriting Members

When a node is created and used, its field list is created/refined for that specific node. This takes into account the node's parents, their `Strength` and `Support`, experience (memory), and reasoning (System 1). It may happen in the moment, during reflection, or during sleep.

#### Field Principles

1. **Necessary minimalism:** use the minimum number of fields, with brief and maximally clear content.
2. Prefer **precise, specialized names and descriptions** over generic ones inherited from a parent when appropriate. For example, rename a `Content` field to `Code` and tailor its description to Code nodes.

### Materialization Instead of “Storing Properties”

Nodes are **not treated as static containers for all their properties**.

Much of what is known about an entity exists as **uncertainty** distributed across relationships and programs/rules, and is **materialized during perception/analysis** through operations that create relationships, measure, infer, and intervene.

### Node

(def_id:: entity.Node)
> [!definition]
> **Node** — the basic abstract node type of the EverTree multigraph. It defines the basic set of parameters. All direct descendants are, in effect, specialized base node classes.
^def-Node

### Concept

(def_id:: entity.Concept)
> [!definition]
> **Concept** — a stable unit of meaning, or an “identity node” in experience, which may be activated repeatedly in different episodes as _the same thing_ and has a set of _useful_ links to other concepts. A Concept is a symbol, not the world object itself.
^def-Concept

- **Typology:** Any object, process, relation ([[Semantics Plane#^def-RelationType|`RelationType`]]), state, or abstraction (linguistically, a word or phrase) is a Concept. The node's role is determined by its link pattern.
- **Parameters:**
  - `Bias` (`b`): prior probability of activation (tendency to fire).
  - `Stability` (`S_tab`): resistance to forgetting (`0..1`).
  - `Alpha` (`α`): activation threshold (Policy Threshold).
  - `Belief_State`: optional [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`Belief_data`]] structure; see “Uncertainty and Belief Tracking in the World Model.”

A concept's field is its local edge structure, their weights, and shared activation-propagation rules.

A concept does not merely _exist_ as a region; it also **deforms the field of possible transitions**. A concept is approximately **an operator that changes the metric and curvature around itself**:

- which steps seem closer;
- which links become “thicker,” and which nearly disappear.

As a metaphor:

- there is a map of lakes (all concepts) = regions;
- and there are **riverbeds** — how “thought usually flows” on the map = a vector field (which transitions concepts tend to initiate: which other concepts they are “drawn” toward).

A Concept is not the same as a word. It may correspond to a phrase, such as “hit a person,” or be a model, dynamic, or field that is difficult to describe precisely even with a long text.

A Concept is on the Abstraction Ladder and has lists of parents and children, either of which may be empty.

`ActionConcept` or `ProgramConcept` is a symbol for an action or program. Execution itself belongs to the Process Plane / Program Layer and is defined by an `ActionNode`, `ProgramNode`, or `CodeNode`. A Concept denotes meaning; a Program executes.

### Nodes on the Abstraction Ladder

#### Instance State (Facet)

#### Facet

(def_id:: entity.Facet)
> [!definition]
> **`Facet`** — a semantically coherent aspect of the state of a specific [[#^def-Instance|`Instance`]], applicable over a world-time interval. `Instance` preserves an object's identity through time; `Facet` represents one of its changing states.
> ^def-Facet

```python
Facet {
  valid_from: <time>
    "Start of the interval when the state applies in the world."

  valid_until?: <time>
    "End of the applicability interval.
     Absent if the end time is unknown."
}
```

The interval is interpreted as:

```text
[valid_from, valid_until)
```

The contents of a `Facet` are expressed as property facts and semantic relations attached to it:

```text
CLASSIFIED_AS(IgorHealth@t, Sick)

HAS_NUMERIC_VALUE(
  IgorHealth@t,
  Temperature,
  39.1,
  Celsius
)
```

`Facet` is not a separate property value. One state may be described by several facts and relations.

[[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`Belief_data`]] applies to specific claims about a `Facet`; it is not one confidence value for the entire state.

The origin of a `Facet` and its associated facts is recorded by the shared `created_by` mechanism; see [[Memory#^def-ResultProvenance|Result Provenance]].

##### Closing a Temporal State
#topic_details

If a [[#^def-Facet|`Facet`]] described a state that existed but is no longer current:

```text
close_facet_state(facet, valid_until)
→ GraphDelta
```

sets the end of the state's temporal interval.

Closing a `Facet` does not disprove that it existed in the past or change its `created_by`.

```text
close_facet_state
→ the state existed,
  but ceased to apply after valid_until.
```

#### Instance

(def_id:: entity.Instance)
> [!definition]
> **`Instance`** — a specific instance of a prototype, a unique information node extended through time that serves as an “anchor” for attaching all incoming facts about a particular object. It is what **remains unchanged as properties change over time**.
> ^def-Instance

- **Parameter:**
  - `Memories`: list of `<Memory Entry>` about the object.

#### Prototype

(def_id:: entity.Prototype)
> [!definition]
> **`Prototype`** (schema) — a **statistically generalized model of a class of objects**, formed by compressing many unique **Identities** into their common (invariant) features. It provides predictions (priors) for any object assigned to the group, filling gaps in perception with default values.
^def-Prototype

#### Entity

(formal_id:: entity.Entity.schema)
```python
Entity: Concept(0.95) {
  prototype: <Prototype> "Prototype (abstract) representation of the entity: a general template/class for inheritance and typing; not a concrete object."
  instance: <Instance> "Instance (concrete) representation of the entity: one object/case in the world or memory; not a class or aspect."
  facet?: <Facet> "Semantically coherent aspect of the instance's state; not a separate identity or class."
  description: <string> "Semantic contract of Entity as a class: 'what it is / what it is not.' A domain entity with Prototype/Instance representations and optional Facet; not used for utility/technical nodes (such as CodeNode)."
}
```
^spec-Entity

---

### Node Groups

#### Subgraph

(def_id:: entity.Subgraph)
> [!definition]
> **Subgraph** — an isolated set of nodes describing a model, process, or system.
^def-Subgraph

**Properties:**

- `Name` (`str`): one-to-three-word label (for example, “Poker”).
- `Description` (`str`): short description (optional).
- `Value` (`str`): actual raw text received (for example, “I fold”, `H:[Ad, Ks]`).
- `Nodes`: `List[Node]`, the subgraph's nodes ([[#^def-Node|Node]]).

### Input and Output

#### Artifact
#topic_core

(def_id:: entity.Artifact)
> [!definition]
> **Artifact** — a file on disk containing data and versioned through Git.
> ^def-Artifact

Artifacts are used, for example, for large texts, datasets, and other values whose contents would be unreasonable to store directly in the graph. An artifact defines the storage method; the semantic type of its contents — such as a word, essay, or dataset — is defined separately.

Artifacts are stored in `artifacts/` relative to the root of the agent's [[Process Plane/Program Lifecycle and Evolution#Repository Organization|Git repository]]. An artifact ID is a relative path, such as `artifacts/essays/draft.md`; its exact version is the pair `(path, git revision)` in that repository, where revision points to a specific commit. The graph or trace stores necessary metadata and this reference: a mutable path by itself does not identify previous contents. Usually `.md` and `.csv` are used; other suitable formats, including compressed and binary formats, are allowed for large data.

Large files may use [Git LFS](https://git-lfs.com/); the version reference must make the contents themselves available, including the corresponding LFS object.

If a computation uses contents that are not yet committed, save an exact snapshot or create a Git revision before recording a reference to them. Writing a new version of the file does not overwrite the contents referenced by an earlier result. This does not require a commit for every character: working accumulation and committing the version used have different boundaries. Required files and versions follow the shared [[Memory#Retention Obligations|retention obligations]] and [[Memory#^def-ResultProvenance|provenance]] rules.

#### Input (Observable State)

(def_id:: entity.Input)
> [!definition]
> **Input** — a node representing an external signal received by the system as text. It is a graph entry point (“sensor”). Unlike Hidden State, this node is **not computed**; it is supplied from outside.
> ^def-Input

**Properties:**

- `Name` (`str`): short label (for example, “User Input Message”, “Poker Hand Data”).
- `Value` (`str`): actual raw text received (for example, “I fold”, `H:[Ad, Ks]`).
- `Source` (`string`): identifier of the input channel (for example, `USER`, `WORLD`, `SYSTEM LOG`, `GAME API`). It is used to select a message-parsing method and source-reliability model.
- [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`Belief_data`]] (`BeliefData`): confidence in the Input contents for an explicitly specified target. Source reliability, the initial presumption of cooperation, and error models are defined in [[Uncertainty and Belief Tracking in the World Model#Source Reliability Estimation|`SourceReliability`]]. Receiving a message alone does not confirm that its contents are true.

#### TextOuput

(def_id:: entity.TextOuput)
> [!definition]
> **`TextOuput`** — a message to the user displayed in chat.
> ^def-TextOuput

**Properties:**

- `Message` (`str`): message contents.
- [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`Belief_data`]] (`Belief_data`): confidence in the response contents.

---

#### ShellCall

(def_id:: entity.ShellCall)
> [!definition]
> **`ShellCall`** — a shell command invocation.
> ^def-ShellCall

**Properties:**

- `Command` (`str`): shell command to invoke.
- [[Uncertainty and Belief Tracking in the World Model#^def-BeliefData|`Belief_data`]] (`Belief_data`): confidence in the call.

---

#### Other Input/Output Commands

**`ReadFile(path: string) -> Content(string)`** reads a local file and returns its contents.

**`WriteFile(path: string, content: str) -> Status(string)`** overwrites a local file and returns the status.

**`ReadWebLink(url: string) -> Content(string)`** reads a web page, simplifies it (using an LLM), and returns its contents.

---

#### Note
#topic_core

(def_id:: entity.Note)
> [!definition]
> **`Note`** — a free-text record of observations, experience, reasoning, conclusions, or instructions for later use.
> ^def-Note

A Note may preserve coherent content as a whole: for example, an experience description, a possible explanation, and a proposed next action. It does not have to be broken into a separate claim for every sentence before it can be stored, retrieved, used, or evaluated. This allows relationships and reasoning that are not yet formalized to be retained.

A Note is linked to relevant concepts, processes, programs, and experience through ordinary semantic relations. [[Memory#^def-ResultProvenance|Provenance]] records which inputs and computations produced it; related memories may explain its origin, confirm its contents, or show their limits. Originating from an experience does not mean that the experience supports the entire Note.

A Note may remain a result in a trace. If it is needed in the long-term world model, a program explicitly materializes it in the persistent graph through [[#Updating the Persistent Graph|`GraphDelta`]]. Both cases follow the shared [[Memory#^def-Memory|Memory lifecycle]]. Content evaluation is defined in the [[#^note-claim-prompt-evaluation|shared rules below]].

---

#### Claim
#topic_core

(def_id:: entity.Claim)
> [!definition]
> **`Claim`** — an individual, checkable assertion about a state, relation, transition, or regularity in the world, the agent, or a model. It may be true or false under a specified meaning and may therefore be a [[Uncertainty and Belief Tracking in the World Model#^def-BeliefTarget|`BeliefTarget`]].
> ^def-Claim

Claim atomicity is determined by whether it can be independently checked and updated, not by text length or number of concepts. One claim may describe a causal regularity with conditions. If parts need to be confirmed, refuted, or revised independently, define separate targets for them.

A Claim may be expressed in a [[#^def-Note|Note]] and extracted for independent work; the entire Note may also be evaluated as a whole. A hypothesis remains a Claim even when it has not yet been confirmed.

When meaning is already represented precisely enough by ordinary EverTree properties, relations, or transitions, use that representation instead of a duplicate [[#^def-Claim|Claim]].

A Claim may first arise as the result of reasoning or program execution.

If a claim becomes an independent `BeliefTarget` that must be used or updated separately from the source [[Memory#^def-ProgramRun|`ProgramRun`]], materialize it in the persistent semantic graph through an ordinary `GraphDelta`.

Here, persistent means:

```text
→ has a stable identity and is available to other ProgramRuns;
```

It does **not** mean “stored forever.”

When no longer currently applicable, the Claim follows the ordinary [[Memory#^def-Memory|Memory lifecycle]]. The target itself, its [[Uncertainty and Belief Tracking in the World Model#^def-Evidence|evidence]], and required [[Memory#^def-ResultProvenance|provenance]] all follow that lifecycle.

Use a Claim only while a more precise native semantic representation is unavailable.

For example:

```text
Claim:
"Water ingress increases the probability of engine stall"

        ↓ further formalization

CAUSES_UNDER(
  cause = WaterIngress,
  effect = EngineStop,
  condition = ...
)
```

After successful formalization, the structured representation becomes the canonical target for future learning. The old Claim may be kept as a historical formulation and provenance, but do not maintain two independent beliefs about the same meaning.

---

#### Prompt
#topic_core

(def_id:: entity.Prompt)
> [!definition]
> **`Prompt`** — instructions and a method for presenting data, intended to elicit specific behavior from an LLM; it may be represented as a parameterized message template.
> ^def-Prompt

A Prompt defines how to address a model to perform a particular task: wording, message order, examples, and response requirements. A general rule may be recorded in a [[#^def-Note|Note]], while different Prompts implement ways to communicate it to an LLM. Therefore, a Prompt's wording does not have to match the wording of the general rule.

In a reusable template, substituted parameters are marked as placeholders, for example:

```text
In {source_text}, identify conditions and exceptions
that concern {target_process}.
Preserve the source wording and links to text fragments.
```

Parameters have a technical representation and semantic meaning under the [[Program Layer#^program-semantic-interface|shared program interface]]. For example, `source_text` represents source text, while `target_process` represents a process in the graph. If parameters are already declared by the interface of the calling Program, the template refers to those definitions rather than creating a duplicate signature. A placeholder's link to its declaration is explicit; it is not inferred from matching names. Preparing actual values is separate work.

##### Prompt Fields and Call Settings
^prompt-configuration

The structure describes one immutable Prompt version. Stable identity, provenance, and links use the shared graph mechanisms.

```python
Prompt: Concept {
  revision: <string>
    "Identifier of this immutable Prompt version."

  messages: <list[{role: str, content_template: str}]>
    "Ordered message template: instructions, examples, and data placeholders."

  target_llms: <list[str] | None> = None
    "Models this Prompt variant is intended for."

  llm_settings: {
    temperature?: <float>
    max_output_tokens?: <int>
    reasoning_effort?: <str>
  } = {}
    "Default generation settings; specify only the fields needed."

  output_schema: <schema reference | None> = None
    "Reference to the technical LLM response schema and semantic roles of its parts."
}
```

`messages` preserves message roles and order, not only the concatenated text. In the current text representation, `content_template` is a string containing placeholders; a separate graph type for every message is unnecessary. Placeholders are linked to prepared values through the shared interface described above. Their types are declared once; do not store a separate list of names that duplicates the template. Before the call, check that required values are present, their types match, and substitution is allowed. If images, audio, or other attachments are needed, extend the message-content representation.

`target_llms` contains unambiguous model identifiers, for example `provider/model-id`; semantic relations may point to the corresponding model concepts in the graph. A nonempty list specifies target models for ordinary selection by the calling Program, without a preference order or a requirement to call all of them. `None` means no model specialization is declared; an empty list is invalid. Use outside the declared list is an explicit probe or revision of the applicability scope. Being on the list is not evidence of suitability: evaluate quality for the model actually used and its available version.

Initial `llm_settings`:

| Field | Purpose |
|---|---|
| `temperature` | Generation randomness setting when supported by the selected model and mode. |
| `max_output_tokens` | Upper bound on generation length under the selected API; it is not the input-context size. |
| `reasoning_effort` | Requested reasoning-cost mode; allowed values are determined by the model. |

An absent field means inherit the call setting, not zero. No universal numeric defaults are defined. Other settings, such as `top_p`, are added for a specific need. The selected model adapter checks parameter support, values, and combinations; an explicitly set unsupported parameter is not silently discarded.

`output_schema` is used for a structured response and checking its shape; it refers to an existing schema without copying Python types or semantic definitions. `None` means no additional schema: the response is determined by the call mode, such as ordinary text or a call to a provided tool. The schema describes the response to this LLM call, which may be an intermediate program result. The calling Program parses and checks the response and constructs its own [[Program Layer#^def-ProgramResult|`ProgramResult`]]. Schema validation does not confirm that the content is true.

##### Selecting, Versioning, and Using a Prompt

One task with one semantic interface may have Prompt variants for different LLMs. They may differ in instruction detail, examples, and organization. Select a preferred variant by evaluating quality, cost, and latency; a model's price alone does not establish its quality. Link variants and versions in the graph as solutions to one task; no mandatory type hierarchy for family, template, and completed request is needed.

The calling Program selects a specific LLM and resolves settings in this order: call-method defaults → `Prompt.llm_settings` → explicit overrides for this call. The choice must satisfy task constraints and the resource budget. A one-time override is recorded in the trace and does not change the Prompt; a persistent change to the template, parameter bindings, target models, defaults, or response schema creates a new revision. Replacing a pinned dependency and dynamic selection of variants follow the [[Program Layer#^program-text-dependencies|shared graph-instruction contract]].

```text
prepared arguments + selected Prompt version + required context
  + selected LLM and call settings
→ concrete LLM request
→ result
```

The template is reusable; the concrete request is produced by substituting prepared values from [[Cognition and Attention#^def-PreparedContext|`PreparedContext`]], arguments, or permitted reads by the specific program. A new `PreparedContext` for every Prompt is unnecessary. The actual request contents and dependencies used are recorded under the [[Program Layer#^program-text-dependencies|graph-instruction and Prompt contract]].

Conversation history, retrieved memory, and other current data belong to the call context. The Program/runtime defines available tools, timeout, retries, and call sequence. Instructions in a Prompt about using a tool must match the tools provided by the program.

Rendering a simple template may be an ordinary function. Data retrieval, branching, loops, tool calls, and multiple LLM calls belong to the calling Program's logic. A Prompt does not replace that program with a hidden execution language. [[Process Ontology and Semantic Interface#^semantic-program-organization|Prompt preparation, evaluation, and optimization]] are organized as ordinary EverTree processes.

#### Purpose and Evaluation of Notes, Claims, and Prompts
^note-claim-prompt-evaluation
#topic_core

The distinction between these concepts is based on use: a Note preserves coherent material, a Claim allows an assertion to be evaluated separately, and a Prompt forms, selects, and improves an LLM request. These are ordinary semantic graph concepts, not new base node types or storage subsystems. They need neither mutually exclusive classification nor a mandatory inheritance chain: a Note may contain an assertion and an instruction used in a Prompt. Multiple uses do not require copies of the same text.

Evaluate content through the shared [[Uncertainty and Belief Tracking in the World Model#Belief and BeliefTarget|belief and evidence mechanism]], with respect to a defined meaning and purpose:

- a statement or description of observations — how well it matches reality;
- a process model expressed in text — how accurately it describes and predicts the process;
- a behavior rule or instruction — how reliably applying it achieves specified goals and target signals while meeting constraints.

A composite Note may be evaluated as a whole, as a model or policy, without extracting a Claim for every sentence. The target specifies the content or version being evaluated, its applicability scope, and, for quality or effectiveness evaluation, a [[Attribution Plane#^def-Criterion|`Criterion`]]. For example: “the described model achieves the required accuracy on this class of cases” or “following these rules reliably achieves the goal under these conditions.” Different evaluation questions are not mixed into one vague confidence value.

Parts may receive independent targets when needed. Evaluation of the whole is not automatically the average of evaluations of its parts: the truth of individual claims does not confirm the reasoning that connects them, and successful use of an instruction does not prove every explanation it contains. Shared bases retain [[Uncertainty and Belief Tracking in the World Model#Evidence Dependencies|evidence dependencies]]; extracting parts or restating them does not create independent confirmation from the same experience.

Prompt evaluation applies to its version together with the LLM, material call settings, context preparation, and task class. Compare result quality, cost, and latency under the stated conditions. Success on one request may be evidence under the tested conditions, but does not by itself establish template reliability in general; results on one model do not transfer automatically to another. If the model and Prompt both change, the observed gain applies to the combination; separate attribution requires evidence.

---

### Concept Canonicalization and Semantic Linking

^04821b

Before creating a new [[#^def-Concept|concept]], the agent first searches for an existing concept with the same or sufficiently similar semantics.

Create a new concept only if:

1. no suitable existing concept is found;
2. a separate concept is semantically and functionally justified.

The goal is compression of the graph at the level of meaning: rather than storing a chaotic set of word-signs that mean the same or nearly the same thing, crystallize an ordered field of concepts from them.

The agent compresses the space of possible concepts through two mechanisms:

1. **the Abstraction Ladder** — place a concept at an appropriate level of generalization/specialization;
2. **semantic relations** — explicitly represent the kind of proximity between concepts through the corresponding [[Semantics Plane#^def-RelationType|`RelationType`]] and `TransitionType`.

For example:

```python
SYNONYM_OF
ALIAS_OF
```

The same mechanism and goals apply to `RelationType` and `TransitionType` concepts.

---

## General Definitions and Concepts

### Context
#topic_intro

**Intuition:** object `E` does not “store” ready-made properties. Before it is queried, many facts about `E` are uncertain and **materialized** by reading relations, measuring, intervening, and inferring. **Context** defines _which_ materializations are allowed/likely and _which rules_ to apply.

#### Definition
#topic_core

(def_id:: concept.TaskContext)
> [!definition]
> **Task context (`TaskContext`)** `Q` about object `E` at time `t` is the **minimal set of facts external to `E`** that are used as inputs when materializing an answer to `Q`, change the result (or result distribution), and are **not** the target facts we are trying to obtain about `E`.
^def-TaskContext

Key point: **task context is always relative** (to `E`, `Q`, and `t`).

`TaskContext` describes external conditions of a domain question. [[Cognition and Attention#^def-PreparedContext|`PreparedContext`]] contains working data gathered for the next step and may include these conditions together with inputs and other necessary information; they serve different purposes.

The operation's [[Process Plane/Program Layer#^program-semantic-interface|contract]] defines the full set of inputs: alongside external facts, it may require data about the object itself, a reference frame, evaluation scope, or assumptions. `TaskContext` denotes the role of external facts and does not require a shared container or a `context` parameter in operation interfaces.

#### What Is NOT Task Context
#topic_details

Context does **not** include:

- **The type/hierarchy of the object itself** ([[#^def-Prototype|`prototype(E)`]], `ancestors(prototype(E))`). This is part of `E`'s _internal identity_, not external conditions.
- **Target facts about `E`** that are being materialized (for example, “the current speed of `E`”). These are the result, not the context.
- **The entire environment** or “everything outside the focus.” Context is only the minimum necessary external facts.
- **A default classification `classify(E, ContextX)`.** Do not make “context” a separate class/label unless it is part of an explicit process program. Context is a set of external facts, not an object type.

#### Allowed Task Context Components (External Only)

Context may contain only:

- **Global world conditions**, if they actually participate in the rules/norms for `Q` (time, season, weather, etc.).
- **Facts about other objects** linked to `E` and used by the rules.
- **Relations between `E` and other objects**, if used to materialize the result (for example, `ON_SURFACE(E, Road#17)`).

#### Example

Query `Q`: “Is `E` fast right now?”  
Goal: materialize `CLASSIFIED_AS(E_now, Fast)`.

- **Not context:** `prototype(E)` (for example, `Car`) — this is identity.
- **Context:** `ON_SURFACE(E, Road#17)` (if the Fast rule depends on surface type), `Weather=Rain` (if the rule depends on weather).
- **Not context:** speed itself, `HAS_NUMERIC_VALUE(E_now, SpeedOfMotion, v)` — this is input to the target fact about `E`, not an external condition.

*Informally, in this approach, “context/modes” are primarily process-related (Process Plane), computed/registered, rather than permanent “properties.”*

## GraphStore

(def_id:: entity.GraphStore)
> [!definition]
> **`GraphStore`** — storage for the persistent EverTree semantic graph.
> ^def-GraphStore

It stores:

- semantic objects: [[#^def-Concept|`Concept`]], [[#^def-Instance|`Instance`]], [[#^def-Facet|`Facet`]], [[#^def-Claim|`Claim`]], and others;
- semantic facts: `RelationInstance`s, including property facts and transitions.

Physically, different data types may be stored and indexed separately, but this is an internal implementation of `GraphStore`, not a separate semantic subsystem.

### Updating the Persistent Graph

All semantic changes to the persistent graph are performed through `GraphDelta`:

```text
creation;
semantic update;
deletion
        ↓
GraphDelta
        ↓
GraphStore
```

A write operation is recorded by the corresponding graph-writing [[Memory#^def-TraceEvent|`TraceEvent`]], so the change retains [[Memory#^def-ResultProvenance|provenance]] to the computation and experience on which it was based.

Direct semantic mutation of persistent objects outside `GraphDelta` is prohibited.

Runtime state that is not persistent semantic knowledge, such as current `activations`, may be changed separately.

Initial loading or importing of a graph is also performed through an initial `GraphDelta`, so persistent objects do not appear without a known creation history.

### Change History

From `GraphDelta` history and associated [[Memory#^def-TraceEvent|`TraceEvent`s]], the infrastructure provides views:

```text
created_at(object)
→ when object first appeared in the persistent graph;

last_changed_at(object)
→ time of the last semantic change;

changes_of(object, time_range?)
→ history of changes to object;

provenance_of(object)
→ computational origin of object.
```

`created_at` and `last_changed_at` are not stored as required fields on every semantic object; the change history remains the source of truth.

### GraphChangeIndex

(def_id:: entity.GraphChangeIndex)
> [!definition]
> **`GraphChangeIndex`** — a technical index over `GraphDelta` history and [[Memory#^def-TraceEvent|`TraceEvent`s]] that quickly finds persistent objects by creation or change time.
> ^def-GraphChangeIndex

It is used, among other things, to create a memory `review batch`.

`GraphChangeIndex` is not a semantic entity and does not store a separate version of the truth.

### MVP Implementation

In the MVP, [[#^def-GraphStore|`GraphStore`]] is an ordinary in-memory Python structure.

Graph state is saved together with the rest of core and the DBOS database in the [[Cognition and Attention#^agent-backup|shared periodic backup]]. After a crash, the entire agent is restored from one completed save; later changes may be lost. A separate core change journal is not required in the MVP.

DBOS uses local SQLite; a separate graph database or database server is not required in the MVP.

`GraphStore` defines the graph's logical storage interface; its physical backend may be replaced later without changing the rest of the architecture.
