"""Select a justified portion of currently available input; never reveal future data."""

from evertree.common.structured import ask

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source_id": {"type": "string"},
                    "start": {"type": "integer", "minimum": 0},
                    "end": {"type": "integer", "minimum": 0},
                },
                "required": ["source_id", "start", "end"],
            },
        },
        "done": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["sources", "done", "reason"],
}


async def run(ctx, objective: str, sources: list[dict], progress: dict | None = None):
    output = await ask(
        ctx,
        instructions=(
            "Select the next semantically useful chunk of the available sources for this task. "
            "Use exact source IDs and Python Unicode character slice offsets [start,end). "
            "Choose granularity according to the process; source message boundaries need not be argument boundaries. "
            "Only use the supplied available sources, preserve continuation progress, and do not inspect unavailable future outcomes."
        ),
        data={"objective": objective, "sources": sources, "progress": progress or {}},
        schema=SCHEMA,
    )
    available = {source["source_id"]: source["content"] for source in sources}
    for part in output["result"]["sources"]:
        content = available.get(part["source_id"])
        if not isinstance(content, str) or not 0 <= part["start"] < part["end"] <= len(content):
            raise ValueError("Episode step selected an unavailable source or invalid span")
    if not output["result"]["done"] and not output["result"]["sources"]:
        raise ValueError("An unfinished step must identify input to process")
    return output
