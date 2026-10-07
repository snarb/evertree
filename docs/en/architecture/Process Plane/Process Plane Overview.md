---
status: draft
target_version: next
---

## Introduction
#concept #topic_intro

(def_id:: et.Process Plane)
> [!definition]
> **Process Plane** — the plane of dynamics, models of change in the world, causality, and the internal programs of an EverTree agent.

It describes:

- which factors trigger, enable, suppress, or interrupt changes, and which consequences follow;
- how objects in the world and relationships among them change over time (at the symbolic level, this projects to “how [[Core data structures#^def-Concept|concepts]] and relationships between concepts change over time”);
- how strongly and with what probability a cause affects an outcome;
- how the agent should respond in a given situation, both externally and internally.

### Purpose

- Effective analysis and prediction
- Agent self-improvement

---

## Process Modeling Principles
#topic_details

1. Build not a “complete description of the process,” but the smallest model that supports prediction, intervention, and rapid learning from errors. The simplest starting model is “if I do X in situation S, outcome Y is likely” — an **affordance/action-outcome model**. The agent identifies dimensions: what changes here, what stays stable, what matters, and what can be ignored. Start by asking: **what states exist → what transitions are possible → what triggers them → what blocks them → what actions change the trajectory → which signals will tell me the model is wrong?** The model is refined gradually, adding several complementary process models when needed.
2. A good model of an important process has four layers:
   - **Attribution:** what the objects and states of the process are like; which properties matter.
   - **Semantics:** what is what, what the system consists of, and which roles its elements play.
   - **Process:** programs.
   - **Associative/contextual:** what tends to appear together, and what strengthens or suppresses something else.
3. Distinguish triggers, conditions, and causes.
4. Check and account for edge cases.
5. Use counterfactuals.
6. Use interventions.
7. After an insight, win, or loss, retain not only the conclusion but also the path that led to it.
8. A good model is often probabilistic.
9. Exploration should be driven by information value, not be chaotic.
10. Break processes into subprocesses. Look for common subprocesses across processes and reuse them.
11. A good model is:
    - predictive;
    - **operational:** shows which actions change the outcome;
    - **hierarchical:** distinguishes an individual case, a class of cases, and a general principle;
    - **compressible:** turns many episodes into a small number of patterns over time.
