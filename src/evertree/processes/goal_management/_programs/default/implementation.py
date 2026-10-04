"""Bootstrap goal management: returns a proposal with source provenance."""

import json

from evertree.common.structured import ask

SCHEMA = json.loads(
    '{"type":"object","additionalProperties":false,"properties":{"goals":{"type":"array","items":{"type":"object","additionalProperties":false,"properties":{"objective":{"type":"string"},"reason":{"type":"string"},"existing_goal_id":{"type":["string","null"]},"priority":{"type":"number"}},"required":["objective","reason","existing_goal_id","priority"]}}},"required":["goals"]}'
)
INSTRUCTIONS = "Propose goals and priorities from supplied explicit requests, current obligations, states and fixed Values EpistemicQuality and AgentCapability. Preserve user commitments and hard constraints. A new goal need not create an executing Task immediately. Do not duplicate existing goals, spend resources, change Values or treat an assumption as a constraint."


async def run(ctx, context: dict):
    return await ask(ctx, instructions=INSTRUCTIONS, data=context, schema=SCHEMA)
