"""Bootstrap argument preparation: returns a proposal with source provenance."""

import json

from evertree.common.structured import ask

SCHEMA = json.loads(
    '{"type":"object","additionalProperties":false,"properties":{"arguments":{"type":"object","additionalProperties":true},"missing_requirements":{"type":"array","items":{"type":"string"}},"source_ids":{"type":"array","items":{"type":"string"}}},"required":["arguments","missing_requirements","source_ids"]}'
)
INSTRUCTIONS = "Prepare arguments for the supplied semantic Program interface using the provided source material and known arguments. Preserve provenance. Never invent a missing fact; record unresolved conditions in missing_requirements. The output arguments must satisfy the described input contract and task constraints. Do not execute the Program."


async def run(ctx, context: dict):
    return await ask(ctx, instructions=INSTRUCTIONS, data=context, schema=SCHEMA)
