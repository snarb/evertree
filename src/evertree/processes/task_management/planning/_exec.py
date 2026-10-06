"""Bootstrap planning: returns a proposal with source provenance."""

import json

from evertree.common.structured import ask

SCHEMA = json.loads(
    '{"type":"object","additionalProperties":false,"properties":{"steps":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"objective":{"type":"string"},"program_id":{"type":["string","null"]},"arguments":{"type":"object","additionalProperties":true}},"required":["objective","program_id","arguments"]}},"open_questions":{"type":"array","items":{"type":"string"}}},"required":["steps","open_questions"]}'
)
INSTRUCTIONS = "Construct a task-local plan for the supplied objective, constraints, state and available Programs. Reuse adequate Programs; do not create a reusable Program for every one-off task. Each step should advance the objective and declare the Program to call if known. Preserve unresolved requirements and do not execute effects or declare success."


async def run(ctx, context: dict):
    return await ask(ctx, instructions=INSTRUCTIONS, data=context, schema=SCHEMA)
