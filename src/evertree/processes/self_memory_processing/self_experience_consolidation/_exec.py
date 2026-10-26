"""Propose source-grounded knowledge for the owner's common integration boundary."""

from evertree.common.analytical import (
    ANALYTICAL_INSTRUCTIONS,
    analytical_schema,
    validate_analytical_output,
)
from evertree.common.structured import ask

SCHEMA = analytical_schema(
    {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "statement": {"type": "string"},
                        "scope": {"type": "string"},
                        "source_ids": {"type": "array", "items": {"type": "string"}},
                        "needs_review": {"type": "boolean"},
                    },
                    "required": ["statement", "scope", "source_ids", "needs_review"],
                },
            },
            "reusable_principles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "rule": {"type": "string"},
                        "applicability": {"type": "string"},
                        "independent_source_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["rule", "applicability", "independent_source_ids"],
                },
            },
        },
        "required": ["claims", "reusable_principles"],
    }
)
INSTRUCTIONS = (
    """Synthesize useful knowledge from the experience supplied by the caller.
The input contains source material, the question being examined and any source labels or
trace references. Preserve the conditions under which each proposed conclusion holds.

Work in this order
1. Identify supported observations, hypotheses, disagreements and relevant counterexamples.
2. Propose claims useful beyond this immediate analysis. Keep uncertain explanations tentative.
3. Propose a reusable principle only if independent cases support its application beyond the
   original case. Replays, summaries and repeated statements of the same source are not
   independent evidence. Successful task completion does not prove every explanation of it.

Output categories
- claims: statement, scope of applicability, supporting source_ids and needs_review.
  Set needs_review=true for unresolved uncertainty, contradictory sources or missing checks.
- reusable_principles: rule, applicability conditions and independent_source_ids.
  Use [] when the supplied sources do not establish independent support for generalization.
Explain shared evidence and important counterexamples in analysis; do not erase them during
synthesis. Unsupported but useful hypotheses may remain scoped claims requiring review.

"""
    + ANALYTICAL_INSTRUCTIONS
)


async def run(ctx, context: dict):
    """Propose source-backed generalizations across experience without applying graph changes."""
    output = await ask(ctx, instructions=INSTRUCTIONS, data=context, schema=SCHEMA)
    return validate_analytical_output(output, context)
