"""Produce scoped hypotheses and an analytical Note for the owner's integration step."""

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
            "incidents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "description": {"type": "string"},
                        "source_ids": {"type": "array", "items": {"type": "string"}},
                        "causal_scope": {
                            "type": "string",
                            "enum": ["self", "environment", "interaction", "unresolved"],
                        },
                    },
                    "required": ["description", "source_ids", "causal_scope"],
                },
            },
            "hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "statement": {"type": "string"},
                        "source_ids": {"type": "array", "items": {"type": "string"}},
                        "independent_check": {"type": "string"},
                    },
                    "required": ["statement", "source_ids", "independent_check"],
                },
            },
            "proposed_changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "description": {"type": "string"},
                        "target": {"type": "string"},
                        "expected_benefit": {"type": "string"},
                        "verification": {"type": "string"},
                    },
                    "required": ["description", "target", "expected_benefit", "verification"],
                },
            },
        },
        "required": ["incidents", "hypotheses", "proposed_changes"],
    }
)
INSTRUCTIONS = (
    """Review supplied experience to identify possible improvements to an agent.
The input contains the caller's question or problem, source material and any source labels
or trace references. Use only the material actually supplied.

Work in this order
1. Identify incidents: what was observed, including successes, failures and ordinary results.
2. Compare available similar, contrasting and boundary cases. Separate an observed result
   from a possible explanation. One incident can suggest a hypothesis, not prove a general rule.
3. Propose changes only where the expected benefit justifies the cost. State how an independent
   check could disprove the explanation or reveal harm from the change.

Output categories
- incidents: description, supporting source_ids and causal_scope. Use self when the proposed
  cause is within the agent; environment when external; interaction when both contribute;
  unresolved when the cause cannot yet be assigned. This classification can be tentative.
- hypotheses: statement of the possible recurring problem or opportunity, source_ids and
  independent_check using new evidence or a comparison that could distinguish alternatives.
- proposed_changes: description, target component, expected_benefit and verification method.
Distinguish a proposal from work actually implemented or checked. Do not propose bypassing
mandatory acceptance checks or changing protected execution limits.

"""
    + ANALYTICAL_INSTRUCTIONS
)


async def run(ctx, context: dict):
    """Propose source-backed lessons and revisions from the supplied experience without applying them."""
    output = await ask(ctx, instructions=INSTRUCTIONS, data=context, schema=SCHEMA)
    return validate_analytical_output(output, context)
