"""Per-invocation tool catalogs; loading never increases caller authority."""

from dataclasses import dataclass

from .provider import ToolDefinition


@dataclass(frozen=True)
class ToolSet:
    name: str
    description: str
    tools: tuple[ToolDefinition, ...]

    def for_mode(self, mode):
        """Restrict a loadable tool set to capabilities permitted by the invocation mode."""
        return ToolSet(
            self.name,
            self.description,
            tuple(t for t in self.tools if mode == "exec" or t.read_only),
        )


def loader_definition(sets):
    """Describe the native tool for loading one of the available capability sets."""
    return ToolDefinition(
        "load_tool_set",
        "Load tool definitions for this invocation. "
        + " ".join(s.name + ": " + s.description for s in sets),
        {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": [s.name for s in sets]}},
            "required": ["name"],
            "additionalProperties": False,
        },
        read_only=True,
    )
