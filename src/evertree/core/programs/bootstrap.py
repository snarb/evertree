"""One-time installation descriptions for seed Programs.

After installation the semantic graph owns Program identity, paths and active
slots. This function is not consulted to route subsequent Program calls.
"""

from __future__ import annotations

PROCESS_GROUPS = {
    "task_management": (
        "TaskManagement",
        (
            "task_framing",
            "context_preparation",
            "argument_preparation",
            "episode_step_selection",
            "planning",
            "verification",
            "commitment_control",
            "goal_management",
        ),
    ),
    "cognitive_control": (
        "CognitiveControl",
        ("attention_control", "cognition_control", "resource_control"),
    ),
    "memory_processing": (
        "MemoryProcessing",
        (
            "memory_retrieval",
            "memory_ranking",
            "experience_compaction",
            "experience_consolidation",
            "experience_validation",
            "replay_selection",
        ),
    ),
    "learning": (
        "Learning",
        (
            "reflection",
            "skill_development",
            "prediction_evaluator",
            "evidence_assessment",
            "credit_assignment",
            "update_planning",
            "learning_coordinator",
        ),
    ),
}


def bootstrap_catalog() -> tuple[dict, ...]:
    entries = (
        (
            "TaskFraming",
            "task_framing",
            "exec",
            "Structure the request and select its finite task-specific budget.",
        ),
        (
            "ContextPreparation",
            "context_preparation",
            "exec",
            "Assemble complete current input, structured task state and selected memory.",
        ),
        (
            "ArgumentPreparation",
            "argument_preparation",
            "exec",
            "Prepare typed arguments and expose unresolved requirements.",
        ),
        (
            "EpisodeStepSelection",
            "episode_step_selection",
            "exec",
            "Choose available source spans and granularity for the next step.",
        ),
        (
            "Planning",
            "planning",
            "exec",
            "Compose task-local steps from reusable Programs and justified new mechanisms.",
        ),
        (
            "Verification",
            "verification",
            "exec",
            "Check mandatory obligations without accepting or performing a candidate effect.",
        ),
        (
            "CommitmentControl",
            "commitment_control",
            "exec",
            "Propose automatic execution or conscious selection on the verified scope.",
        ),
        (
            "AttentionControl",
            "attention_control",
            "exec",
            "Propose the next focus; protected runtime enforces single-Task execution.",
        ),
        (
            "CognitionControl",
            "cognition_control",
            "exec",
            "Use the configured Luna/high profile within available task resources.",
        ),
        (
            "ResourceControl",
            "resource_control",
            "exec",
            "Reassess total resource allocation without resetting usage or changing deadlines.",
        ),
        (
            "GoalManagement",
            "goal_management",
            "exec",
            "Propose goals grounded in requests, obligations and fixed Values.",
        ),
        (
            "Reflection",
            "reflection",
            "exec",
            "Generate scoped problem/change hypotheses from real experience and contrasts.",
        ),
        (
            "SkillDevelopment",
            "skill_development",
            "exec",
            "Plan reusable skill acquisition, independent evaluation and standard learning.",
        ),
        (
            "MemoryRetrieval",
            "memory_retrieval",
            "exec",
            "Retrieve related source groups through protected semantic memory.",
        ),
        (
            "MemoryRanking",
            "memory_ranking",
            "exec",
            "Rerank actual candidate groups by relevance, preserving shared provenance.",
        ),
        (
            "ExperienceCompaction",
            "experience_compaction",
            "exec",
            "Propose summaries and retained events without erasing sources or counts.",
        ),
        (
            "ExperienceConsolidation",
            "experience_consolidation",
            "exec",
            "Propose scoped knowledge from experience without automatic truth promotion.",
        ),
        (
            "ExperienceValidation",
            "experience_validation",
            "exec",
            "Check interpretations against source coverage and dependencies.",
        ),
        (
            "ReplaySelection",
            "replay_selection",
            "exec",
            "Choose bounded existing experience without repeating effects or evidence.",
        ),
        (
            "PredictionEvaluator",
            "prediction_evaluator",
            "exec",
            "Match saved predictions, score outcomes, and route missing predictions through credit and attention.",
        ),
        (
            "EvidenceAssessment",
            "evidence_assessment",
            "exec",
            "Submit explicit source likelihoods to dependency-aware protected belief storage.",
        ),
        (
            "CreditAssignment",
            "credit_assignment",
            "exec",
            "Assign resolved or unresolved semantic learning credit without changing parameters.",
        ),
        (
            "UpdatePlanning",
            "update_planning",
            "exec",
            "Prepare an explicitly bound update without applying it.",
        ),
        (
            "LearningCoordinator",
            "learning_coordinator",
            "exec",
            "Apply selected evaluated experience through the atomic standard learning pipeline.",
        ),
    )
    parents = {slug: group for group, (_, slugs) in PROCESS_GROUPS.items() for slug in slugs}
    meta = {
        "planning",
        "cognition_control",
        "reflection",
        "skill_development",
        "credit_assignment",
        "update_planning",
        "learning_coordinator",
    }
    return tuple(
        {
            "name": name,
            "slug": slug,
            "role": role,
            "roles": (role, "meta") if slug in meta else (role,),
            "git_path": f"src/evertree/processes/{parents[slug]}/{slug}/_{role}.py",
            "entrypoint": "run",
            "description": description,
        }
        for name, slug, role, description in entries
    )


def seed_process_delta(graph, *, self_id: int, revision: str):
    """Describe Self's own process taxonomy and its initial role bindings."""
    import dataclasses

    from evertree.core.graph.types import GraphDelta, Node, Prototype

    root = Prototype(graph.reserve_id(), "SelfProcess", properties={"process": True})
    creates = [
        root,
        graph.new_fact("SUBTYPE_OF", {"type": root.id, "supertype": graph.find("Process").id}),
        graph.new_fact("PART_WHOLE", {"part": root.id, "whole": self_id}),
    ]
    groups = {}
    for slug, (name, _) in PROCESS_GROUPS.items():
        group = Prototype(graph.reserve_id(), name, properties={"process": True})
        groups[slug] = group.id
        creates.extend(
            (group, graph.new_fact("SUBTYPE_OF", {"type": group.id, "supertype": root.id}))
        )
    for descriptor in bootstrap_catalog():
        name, role = descriptor["name"], descriptor["role"]
        process = Prototype(graph.reserve_id(), name, properties={"process": True})
        program = Node(
            graph.reserve_id(),
            name + "." + role,
            kind="program",
            properties={
                "git_path": descriptor["git_path"],
                "role": role,
                "roles": descriptor["roles"],
                "revision": revision,
                "process": process.id,
                "slug": descriptor["slug"],
                "entrypoint": descriptor["entrypoint"],
                "active": True,
            },
        )
        process = dataclasses.replace(
            process, properties={"process": True, "active_" + role: program.id}
        )
        group = descriptor["git_path"].split("/")[3]
        creates.extend(
            (
                process,
                program,
                graph.new_fact("SUBTYPE_OF", {"type": process.id, "supertype": groups[group]}),
                graph.new_fact(
                    "PROGRAM_FOR_PROCESS", {"program": program.id, "process": process.id}
                ),
            )
        )
    return GraphDelta(creates=tuple(creates))


INITIAL_PRINCIPLES = {
    "PreserveRequirements": "Keep requirements and scoped constraints in structured state and check them before significant effects.",
    "MinimalSufficientStructure": "Add structure only to solve a concrete present requirement.",
    "VerifySemanticBlocks": "Verify meaningful conditions, transitions and results against their contracts.",
    "SeekIndependentVerification": "Use checks independent of the candidate's generation when the decision matters.",
    "ExternalizeExactState": "Keep exact values, dependencies and invariants in structured state or deterministic computation.",
    "EscalateOnUncertainty": "Direct attention and verification to novelty, uncertainty, contradiction and consequential errors.",
}
