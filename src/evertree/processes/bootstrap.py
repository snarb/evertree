"""One-time installation descriptions for seed Programs.

After installation the semantic graph owns Program identity, paths and active
slots. This function is not consulted to route subsequent Program calls.
"""

from __future__ import annotations


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
            "model",
            "Assemble complete current input, structured task state and selected memory.",
        ),
        (
            "ArgumentPreparation",
            "argument_preparation",
            "model",
            "Prepare typed arguments and expose unresolved requirements.",
        ),
        (
            "EpisodeStepSelection",
            "episode_step_selection",
            "model",
            "Choose available source spans and granularity for the next step.",
        ),
        (
            "Planning",
            "planning",
            "model",
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
            "model",
            "Retrieve related source groups through protected semantic memory.",
        ),
        (
            "MemoryRanking",
            "memory_ranking",
            "model",
            "Rerank actual candidate groups by relevance, preserving shared provenance.",
        ),
        (
            "ExperienceCompaction",
            "experience_compaction",
            "model",
            "Propose summaries and retained events without erasing sources or counts.",
        ),
        (
            "ExperienceConsolidation",
            "experience_consolidation",
            "model",
            "Propose scoped knowledge from experience without automatic truth promotion.",
        ),
        (
            "ExperienceValidation",
            "experience_validation",
            "model",
            "Check interpretations against source coverage and dependencies.",
        ),
        (
            "ReplaySelection",
            "replay_selection",
            "model",
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
            "model",
            "Prepare an explicitly bound update without applying it.",
        ),
        (
            "LearningCoordinator",
            "learning_coordinator",
            "exec",
            "Apply selected evaluated experience through the atomic standard learning pipeline.",
        ),
    )
    return tuple(
        {
            "name": name,
            "slug": slug,
            "role": role,
            "roles": (role, "meta") if role == "exec" else (role,),
            "git_path": f"src/evertree/processes/{slug}/_programs/default/implementation.py",
            "entrypoint": "run",
            "description": description,
        }
        for name, slug, role, description in entries
    )


INITIAL_PRINCIPLES = {
    "PreserveRequirements": "Keep requirements and scoped constraints in structured state and check them before significant effects.",
    "MinimalSufficientStructure": "Add structure only to solve a concrete present requirement.",
    "VerifySemanticBlocks": "Verify meaningful conditions, transitions and results against their contracts.",
    "SeekIndependentVerification": "Use checks independent of the candidate's generation when the decision matters.",
    "ExternalizeExactState": "Keep exact values, dependencies and invariants in structured state or deterministic computation.",
    "EscalateOnUncertainty": "Direct attention and verification to novelty, uncertainty, contradiction and consequential errors.",
}
