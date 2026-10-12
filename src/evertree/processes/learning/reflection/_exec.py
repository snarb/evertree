"""Produce scoped hypotheses and an analytical Note for the owner's integration step."""

import json

from evertree.common.analytical import analytical_schema, validate_analytical_output
from evertree.common.structured import ask

SCHEMA = json.loads(
    '{"type":"object","additionalProperties":false,"properties":{"incidents":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"description":{"type":"string"},"source_ids":{"type":"array","items":{"type":"string"}},"causal_scope":{"type":"string","enum":["self","environment","interaction","unresolved"]}},"required":["description","source_ids","causal_scope"]}},"hypotheses":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"statement":{"type":"string"},"source_ids":{"type":"array","items":{"type":"string"}},"independent_check":{"type":"string"}},"required":["statement","source_ids","independent_check"]}},"proposed_changes":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"description":{"type":"string"},"target":{"type":"string"},"expected_benefit":{"type":"string"},"verification":{"type":"string"}},"required":["description","target","expected_benefit","verification"]}}},"required":["incidents","hypotheses","proposed_changes"]}'
)
INSTRUCTIONS = "Analyze supplied actual experience. Distinguish incident, possible persistent problem/opportunity, proposed change, and implementation. Use similar, contrasting and boundary cases; classify causal scope self/environment/interaction/unresolved. One incident can create a hypothesis but not prove a general rule. Propose independent checks and cost-justified improvements, preserve evidence dependencies. Do not activate a candidate or modify fixed acceptance/L4."
SCHEMA = analytical_schema(SCHEMA)
INSTRUCTIONS += (
    " Return a readable analytical Note describing the current understanding, grounds, "
    "limits and next useful checks; a partial result is valid. Cite only supplied "
    "experience_refs or their fragments in source_refs; without trace references leave "
    "source_refs empty. Optional findings can identify individual claims or hypotheses. "
    "Use significance with a reason for important results; preserve=true explicitly "
    "requires the owner's KnowledgeIntegration step to retain that result. These "
    "annotations do not establish truth. The owner integrates this output with its "
    "original experience at the next step boundary; do not rewrite memory directly."
)


async def run(ctx, context: dict):
    output = await ask(ctx, instructions=INSTRUCTIONS, data=context, schema=SCHEMA)
    return validate_analytical_output(output, context)
