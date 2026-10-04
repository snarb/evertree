"""Bootstrap skill development: returns a proposal with source provenance."""

import json

from evertree.common.structured import ask

SCHEMA = json.loads(
    '{"type":"object","additionalProperties":false,"properties":{"objective":{"type":"string"},"reuse_program_ids":{"type":"array","items":{"type":"string"}},"implementation_steps":{"type":"array","items":{"type":"string"}},"training_source_ids":{"type":"array","items":{"type":"string"}},"evaluation_source_ids":{"type":"array","items":{"type":"string"}},"target_metrics":{"type":"array","items":{"type":"string"}},"guardrails":{"type":"array","items":{"type":"string"}}},"required":["objective","reuse_program_ids","implementation_steps","training_source_ids","evaluation_source_ids","target_metrics","guardrails"]}'
)
INSTRUCTIONS = "Plan development of a reusable skill within the Task's allocated budget. First assess reusable programs, rules, trained states and available data. Choose the simplest sufficient implementation and explicit prediction targets/learning bindings only when useful. Separate training, refinement and source-independent Evaluation. Specify checks of baseline quality, cost, regressions and transfer. Do not claim a skill learned before actual runs and protected acceptance."


async def run(ctx, context: dict):
    return await ask(ctx, instructions=INSTRUCTIONS, data=context, schema=SCHEMA)
