"""Propose source-grounded knowledge for the owner's common integration boundary."""

import json

from evertree.common.analytical import analytical_schema, validate_analytical_output
from evertree.common.structured import ask

SCHEMA = json.loads(
    '{"type":"object","additionalProperties":false,"properties":{"claims":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"statement":{"type":"string"},"scope":{"type":"string"},"source_ids":{"type":"array","items":{"type":"string"}},"needs_review":{"type":"boolean"}},"required":["statement","scope","source_ids","needs_review"]}},"reusable_principles":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"rule":{"type":"string"},"applicability":{"type":"string"},"independent_source_ids":{"type":"array","items":{"type":"string"}}},"required":["rule","applicability","independent_source_ids"]}}},"required":["claims","reusable_principles"]}'
)
INSTRUCTIONS = "Propose persistent knowledge from supplied experience. Preserve source identities and shared dependencies; compressed or replayed material is not independent evidence. Keep hypotheses scoped; propose a general principle only when its transfer has independent support. Never treat successful completion as proof of every explanation."
SCHEMA = analytical_schema(SCHEMA)
INSTRUCTIONS += (
    " Return an analytical Note preserving the relationships between sources, conditions, "
    "counterexamples and the proposed knowledge. Partial synthesis is valid. Cite only "
    "supplied experience_refs or their fragments in source_refs; without trace references "
    "leave source_refs empty. Optional findings isolate useful claims without losing their "
    "conditions. Use significance with a reason for important results; preserve=true "
    "requires preservation through KnowledgeIntegration, without raising belief. The "
    "owner integrates this output together with original experience at its step boundary. "
    "Do not turn repetition into independent evidence or write the graph directly."
)


async def run(ctx, context: dict):
    output = await ask(ctx, instructions=INSTRUCTIONS, data=context, schema=SCHEMA)
    return validate_analytical_output(output, context)
