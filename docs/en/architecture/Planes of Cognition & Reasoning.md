---
status: stable
target_version: next
---

## Introduction

#concept #topic_core

We group all types of cognition into functional **Planes**.

(def_id:: plane.PlaneOfCognition)
> [!definition]
> **Plane of Cognition** — a distinct layer of the world model that highlights one useful aspect of its organization and defines its own structures, relationships, and operations for that aspect.
^def-PlaneOfCognition

In EverTree, the same knowledge graph supports different modes of thinking and cognition:

| **Plane** | **Key question** | **Mode of thinking** |
| --- | --- | --- |
| **Attribution Plane** | “What is the object like?” | Properties and characteristics. Describes an entity through its properties. |
| **Semantics Plane** | “What is it, essentially?”<br>“What is it made of?” / “What is it part of?” | Describes the world through semantic relationships among entities, levels of abstraction, and mereology (decomposing into parts and assembling them). |
| **Process Plane** | “What will happen?” | Dynamics; simulation of causes and effects. |
| **Associative Plane** | “What is it connected to?” | Context (what tends to activate or suppress together). |

Each Plane defines its own dimension of knowledge organization: which facts are native to it, which structures and operations it uses, and which runtime result it returns.

A fact can be stored in one Plane and projected into another. For example, a structural relation fact may be native to the Semantics / Structural Plane, yet have an attribution projection when used to answer the question “what is a property of the object?”

At runtime, a Plane returns a result under its own contract: a value, signal, or relation reading together with `Belief_data` / support, from [[Uncertainty and Belief Tracking in the World Model]].
