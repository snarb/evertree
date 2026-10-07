---
status: draft
target_version: next
---

## Introduction
#topic_core

> _“The shape of a connection matters even before it has a name.”_

This section describes emergent properties of the graph. The focus shifts from individual edges to **Geometry** and **Ensembles**. These structures affect real-time decision-making (**Online Inference**) and provide a basis for learning (**Consolidation**).

## Neurogeometry: Topology as a Signal
#topic_core

In EverTree, the geometric shape of a subgraph is a **primary observable signal** (`o`) available to the agent.

## Active Geometry (Topological Perception)
#topic_core

When the agent activates context `S`, its **Reflection Module** can perceive not only a list of nodes, but also topological primitives (**Shapes**) in the Process and Associative Planes:

1. **Cycles (loops):**
   - _Pattern:_ `A → B → C → A`.
   - _Signal:_ a “closed process” or “dead-end recursion.”
   - _Effect:_ the agent can stop execution before resources are exhausted simply by recognizing the “infinite loop” geometry.
2. **Hubs and stars:**
   - _Pattern:_ one node has an unusually large number of incoming or outgoing connections.
   - _Signal:_ a “key point” or “bottleneck.”
3. **Bridges:**
   - _Pattern:_ a single connection joins two large clusters.
   - _Signal:_ a “critical transition” with high structural value.
4. **Conflicts (forks):**
   - _Pattern:_ two incompatible nodes are strongly activated (an inhibitory link).
   - _Signal:_ “cognitive dissonance” → trigger for System 2 (deliberation).

> [!important] Mechanism
> The agent can choose a **response to a pattern** as its next step (for example, “break the cycle”) instead of moving to the next node in a process/program.

#### Metric Deformation

Reified concepts and strong ensembles change “distances” in the graph:

- **Wormholes:** a pattern that has become concept `E` allows a jump from the start to the end of a chain in one step (`Cost(A → Z) ≈ 0`).
- **Gravity wells:** areas with high connection density draw the reasoning process in (attractors). It is difficult for the agent to “leave a topic” when it is topologically dense.

### Ensemble
#topic_core

(def_id:: entity.Ensemble)
> [!definition]
> **Ensemble** — a stable _dynamic regime_ (activity pattern) over a subgraph of concepts. In simple terms, it is a group of nodes that activate in coordination (co-activation in the Resonance Plane plus a sequence in the Process Plane).
^def-Ensemble

**Key characteristics:**

1. **Dynamic nature:** an ensemble is not just a list of nodes, but a _way they work together over time_ (an activation trajectory).
2. **Internal structure:** connections within an ensemble need not only be reinforcing. It may include inhibition, logical conditions, competing branches, and feedback loops.
3. **Stochasticity:** an ensemble often defines not one deterministic outcome, but a _probability distribution_ over future states (predictions, actions, rewards).

**Practical meaning:**

In EverTree, ensembles are not stored as separate entities “for the sake of collecting them.” An ensemble is valuable only as a **candidate for reification** (becoming a new Concept) if it meets at least one of these criteria:

- improves **compression** of experience (replaces several similar dynamic patterns with one symbol in each case);
- improves the accuracy of **predictions**, including reward/outcome distributions;
- improves **control**;
- supports **generalization** (transferring knowledge across contexts) and faster long-term learning and planning (path search): improving generalization through abstraction and/or structural correspondence, and accelerating learning by transferring updates to many similar episodes. Efficient thinking and communication are among the means of generalization; a new concept should make explanation and communication easier.

If at least one of these conditions is met, correlation between the ensemble and reward, directly or indirectly, increases the chance of reification.

### Reification Process
#topic_core

(def_id:: entity.Reification)
> [!definition]
> **Reification** — a fundamental mechanism for learning graph structure. It turns a detected _dynamic ensemble_ or recurring geometry into a new static **Concept Pattern (`E`)**.
^def-Reification

Reification introduces a concept for a recurring structure. Using it to generalize models and apply [[#Parameter Tying|parameter tying]] requires [[Process Plane/Program Layer#Generalization and Model Compression|checking the hypothesis that the cases are generalizable and refactoring programs]].

> [!important]
> Simply “naming” or aliasing a subgraph without integrating its structure may help communication, but **does not provide the full benefit of reification**.

> [!important] On frequency
> Frequency alone is not a criterion. A pattern may be rare but critically important (a hazard, accident, or costly error) and still be worth reifying.

The Analysis Module is responsible for reification. The process may be fully automatic in simple cases, or use an LLM, the Self concept, and reflection in complex cases. See the documentation for the **Analysis Module**.

#### What `E` Is After Reification
#topic_details

After reification, `E` is an ordinary **concept node** in the graph.

`E` differs from an ordinary concept in that it represents a **structural pattern**: a set of relationships among other concepts that is useful to treat as a unit.

- `E` may be:
  - **instance-bound** (tied to a particular instance, object, or situation), or
  - a **generalized type** (raised along the abstraction axis). _Example:_ in one episode, a dog growls and bites; in another, a wolf bares its teeth and attacks. The concrete instances do not match, but at the abstraction level (`Animal` → `Threatening signal` → `Aggression`) a stable skeleton (motif) is visible.

#### Minimal Reification Result (What Actually Changes in the Graph)
#topic_details

The semantic result of reification is `E`, connected to surrounding concepts:

- incoming connections to `E` appear from concepts usually present in the pattern;
- outgoing connections from `E` appear to concepts that usually follow, are explained by, or are associated with the pattern;
- connections have a type (axis) and weights/confidence, like any other connections;
- the concept may optionally have internal content (a set of linked nodes); the Analysis Module selects that content and the incoming/outgoing nodes.

The pattern's semantic interface is defined by its incoming and outgoing connections; no separate entity is needed. Contracts for programs that use it are defined in the [[Process Plane/Program Layer#Program Contracts|Program Layer]].

## Parameter Tying
#topic_core

#### What Is Parameter Tying?

(def_id:: entity.ParameterTying)
> [!definition]
> **Parameter tying** is when multiple similar situations begin to “share” the same parameters instead of learning separately for every combination of features.
^def-ParameterTying

Without `E`, a graph often ends up with:

- dozens of features `X1..Xn` connected directly to outcome `Y`;
- weights that must effectively be “relearned” for each context/instance.

When a common model based on `E` is implemented:

- part of the structure goes through `E`:

`X → E → Y`

Then:

- `E → Y` becomes a **shared** connection used by many episodes;
- `X → E` learns to recognize the regime/pattern.

Parameter tying is achieved only when programs using the model actually read the shared parameters and direct compatible experience toward updating them. A shared node and connections alone do not provide this.

#### Expected Benefits to Check Through Generalization

- Faster learning and less overfitting through compatible experience from different cases.
- Faster transfer to new combinations of `X`.
- Fewer parameters on the “periphery.”
- More stable credit assignment: reward/error is more likely to reach the right cause (through `E`) instead of spreading across noisy features.

## Geometry of Patterns in the Graph
#topic_core

“Geometry” in EverTree is understood as a **derived property** of graph structure, not as a separately stored field.

#### A Concept's Geometry Is the Shape of Its Surrounding Connections

After reification, `E` becomes a “geometric object” in the graph in the sense that it:

- defines local transition topology;
- forms characteristic activation “trajectories” through causal/dynamic connections;
- creates “shortcuts” between concepts that were previously linked by a long chain.

In practice, this appears as:

- shorter reasoning (fewer steps through the graph);
- more stable context retention (activations concentrate around `E`);
- the ability to apply the same explanatory “skeleton” to different instances.

#### A “Geometric Pattern” as a Recurring Subgraph Shape

A pattern may recur even without a good lexical or taxonomic abstraction, simply through the shape of its connections. In that case, `E` is an “object corresponding to the shape.”

### Transferring a Pattern Through Structural Subgraph Correspondence

In addition to the abstraction axis (types), EverTree can transfer patterns by **structural similarity**:

> A pattern is considered applicable if a subgraph is found in a new location that structurally corresponds to the pattern's subgraph, allowing nodes to be replaced with nodes compatible by abstraction.

This can be understood as finding a partial homomorphism/isomorphism:

- the “skeleton” matches:
  - which nodes are connected;
  - the edge types (axes);
  - which directions, cycles, and inhibitions are present;
- the specific nodes may differ, but remain compatible under `SUBTYPE_OF/IDENTITY_TYPE`.

It may be useful to cluster weights in a pattern concept. This creates generalization and abstraction by moving from concrete numbers to clusters; fewer clusters correspond to a higher level of abstraction.

Practical meaning:

- a pattern transfers **by shape**, not by name;
- situations can be recognized even when no suitable taxonomy was defined in advance;
- this strengthens the “geometric” aspect of reasoning: the agent recognizes familiar **connection patterns**.
