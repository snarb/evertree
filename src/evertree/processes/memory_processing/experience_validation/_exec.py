"""Bootstrap experience validation: returns a proposal with source provenance."""

import json

from evertree.common.structured import ask

SCHEMA = json.loads(
    '{"type":"object","additionalProperties":false,"properties":{"valid":{"type":"boolean"},"issues":{"type":"array","items":{"type":"string"}},"source_ids":{"type":"array","items":{"type":"string"}}},"required":["valid","issues","source_ids"]}'
)
INSTRUCTIONS = "Check supplied experience and its retained sources against the claimed interpretation. Identify missing source coverage, unsupported conclusions, stale assumptions, duplicated dependencies and lost requirements. A summary is not an independent observation. Set valid false if a required source or outcome is missing. Do not change beliefs or delete history."


async def run(ctx, context: dict):
    return await ask(ctx, instructions=INSTRUCTIONS, data=context, schema=SCHEMA)
