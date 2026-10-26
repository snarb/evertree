"""One-time installation descriptions for seed Programs.

After installation the semantic graph owns Program identity, paths and active
slots. This function is not consulted to route subsequent Program calls.
"""

from __future__ import annotations

PROCESS_GROUPS = {
    "semantic_processing": ("SelfSemanticProcessing", ("semantic_search", "knowledge_integration")),
    "task_management": (
        "SelfTaskManagement",
        (
            "task_framing",
            "task_outcome",
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
        "SelfCognitiveControl",
        ("attention_control", "cognition_control", "resource_control"),
    ),
    "memory_processing": (
        "SelfMemoryProcessing",
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
        "SelfLearning",
        (
            "reflection",
            "skill_development",
            "prediction_evaluator",
            "evidence_assessment",
            "credit_assignment",
            "update_planning",
            "learning_coordinator",
            "program_improvement",
        ),
    ),
}

GROUP_DESCRIPTIONS = {
    "semantic_processing": "An agent-owned process that retrieves or integrates semantic representations, including their sources and unresolved distinctions.",
    "task_management": "An agent-owned process that frames, prepares, plans, forecasts, verifies or manages task-directed activity; it need not itself execute the task.",
    "cognitive_control": "An agent-owned process that regulates attention, cognition or resource use within the agent's execution boundaries.",
    "memory_processing": "An agent-owned process that retrieves, ranks, validates, compacts, consolidates or selects retained experience.",
    "learning": "An agent-owned process that prepares, reflects on, assesses, coordinates or applies learning and Program improvement; an occurrence need not itself change knowledge or parameters.",
}

# Subprocesses are SUBTYPE_OF their parent process and live in its directory.
SUBPROCESSES = {
    "graph_evidence_assessment": "evidence_assessment",
    "program_evidence_assessment": "evidence_assessment",
}


def bootstrap_catalog() -> tuple[dict, ...]:
    """Describe the seed Program names, roles and source paths used by agent bootstrap."""
    entries = (
        (
            "SemanticSearch",
            "semantic_search",
            "model",
            "Find semantic objects through exact, lexical, vector and graph retrieval.",
        ),
        (
            "KnowledgeIntegration",
            "knowledge_integration",
            "exec",
            "Integrate experience and analytical Notes, preserving explicit memory intentions.",
        ),
        (
            "TaskFraming",
            "task_framing",
            "exec",
            "Structure the request and select its finite task-specific budget.",
        ),
        (
            "TaskOutcome",
            "task_outcome",
            "model",
            "Forecast whether a newly framed task will pass independent completion verification.",
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
            "Produce scoped analytical Notes and findings for the owning step integration.",
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
            "Produce sourced consolidation Notes for the owning step integration without truth promotion.",
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
            "Assess new experience as evidence for graph elements, then for Programs, in sequence.",
        ),
        (
            "GraphEvidenceAssessment",
            "graph_evidence_assessment",
            "exec",
            "Turn experience behind changed or related graph elements into capped binary evidence.",
        ),
        (
            "ProgramEvidenceAssessment",
            "program_evidence_assessment",
            "exec",
            "Assess run results as evidence for Program revisions and anchored operators.",
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
        (
            "ProgramImprovement",
            "program_improvement",
            "exec",
            "Program lifecycle management. Arguments: program (target Program ID), objective (the improvement to achieve), optional max_candidates (default 2). Plans candidates, develops and evaluates them, and records EvaluationChoices.",
        ),
    )
    parents = {slug: group for group, (_, slugs) in PROCESS_GROUPS.items() for slug in slugs}
    directories = {slug: f"self_{group}/self_{slug}" for slug, group in parents.items()}
    for slug, parent in SUBPROCESSES.items():
        directories[slug] = f"{directories[parent]}/self_{slug}"
    # Meta Programs build, train or manage other learnable mechanisms.
    meta = {
        "reflection",
        "skill_development",
        "credit_assignment",
        "update_planning",
        "learning_coordinator",
        "program_improvement",
    }
    return tuple(
        {
            "name": "Self" + name,
            "slug": slug,
            "role": role,
            "roles": (role, "meta") if slug in meta else (role,),
            "git_path": f"src/evertree/processes/{directories[slug]}/_{role}.py",
            "entrypoint": "run",
            "description": description,
        }
        for name, slug, role, description in entries
    )


def seed_process_delta(graph, *, self_id: int, revision: str):
    """Describe Self's own process taxonomy and its initial role bindings."""
    import dataclasses

    from evertree.core.graph.types import GraphDelta, Node, Prototype

    root = Prototype(
        graph.reserve_id(),
        "SelfProcess",
        description="A process performed within this agent's own implementation and control scope, distinct from a general world process or one particular execution.",
        properties={"process": True},
    )
    creates = [
        root,
        graph.new_fact("SUBTYPE_OF", {"type": root.id, "supertype": graph.find("Process").id}),
        graph.new_fact("PART_WHOLE", {"part": root.id, "whole": self_id}),
    ]
    groups = {}
    for slug, (name, _) in PROCESS_GROUPS.items():
        group = Prototype(
            graph.reserve_id(),
            name,
            description=GROUP_DESCRIPTIONS[slug],
            properties={"process": True},
        )
        groups[slug] = group.id
        creates.extend(
            (group, graph.new_fact("SUBTYPE_OF", {"type": group.id, "supertype": root.id}))
        )
    processes = {}
    group_for_process = {
        slug: group for group, (_, slugs) in PROCESS_GROUPS.items() for slug in slugs
    }
    for descriptor in bootstrap_catalog():
        name, role = descriptor["name"], descriptor["role"]
        process = Prototype(
            graph.reserve_id(),
            name,
            description="Agent-owned process with this contract: " + descriptor["description"],
            properties={"process": True},
        )
        program = Node(
            graph.reserve_id(),
            name + "." + role,
            kind="program",
            description=descriptor["description"],
            properties={
                "git_path": descriptor["git_path"],
                "role": role,
                "roles": descriptor["roles"],
                "revision": revision,
                "process": process.id,
                "slug": descriptor["slug"],
                "entrypoint": descriptor["entrypoint"],
                "lifecycle_status": "active",
            },
        )
        process = dataclasses.replace(
            process, properties={"process": True, "active_" + role: program.id}
        )
        processes[descriptor["slug"]] = process.id
        parent = SUBPROCESSES.get(descriptor["slug"])
        supertype = processes[parent] if parent else groups[group_for_process[descriptor["slug"]]]
        creates.extend(
            (
                process,
                program,
                graph.new_fact("SUBTYPE_OF", {"type": process.id, "supertype": supertype}),
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
