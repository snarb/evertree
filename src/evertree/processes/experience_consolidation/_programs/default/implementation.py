"""Bootstrap experience consolidation: returns a proposal with source provenance."""

import json

from evertree.common.structured import ask

SCHEMA = json.loads(
    '{"type":"object","additionalProperties":false,"properties":{"claims":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"statement":{"type":"string"},"scope":{"type":"string"},"source_ids":{"type":"array","items":{"type":"string"}},"needs_review":{"type":"boolean"}},"required":["statement","scope","source_ids","needs_review"]}},"reusable_principles":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"rule":{"type":"string"},"applicability":{"type":"string"},"independent_source_ids":{"type":"array","items":{"type":"string"}}},"required":["rule","applicability","independent_source_ids"]}}},"required":["claims","reusable_principles"]}'
)
INSTRUCTIONS = "Propose persistent knowledge from supplied experience. Preserve source identities and shared dependencies; compressed or replayed material is not independent evidence. Keep hypotheses scoped; propose a general principle only when its transfer has independent support. Never treat successful completion as proof of every explanation. Return proposals; core separately verifies and materializes them."


async def run(ctx, context: dict):
    return await ask(ctx, instructions=INSTRUCTIONS, data=context, schema=SCHEMA)
