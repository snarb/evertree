"""Bounded, observable read tools for one adaptive retrieval evaluation."""

from evertree.common.semantic_search import search
from evertree.core.graph import api as graph
from evertree.core.semantics.searching import search_queries


class SearchSession:
    """Expose real search/describe reads; budgets never depend on hidden relevance labels."""

    def __init__(self, ctx, *, searches=3, queries=6, reads=4):
        self.ctx = ctx
        self.searches, self.queries, self.reads = searches, queries, reads
        self.trace = []
        self.visible = {}

    def _remember(self, value):
        if isinstance(value, dict):
            if {"id", "name", "kind"} <= value.keys() and type(value["id"]) is int:
                self.visible[value["id"]] = value
            for child in value.values():
                self._remember(child)
        elif isinstance(value, list):
            for child in value:
                self._remember(child)

    async def call(self, name, arguments):
        """Serve one sequential native read and retain the actual presented cards."""
        if name == "graph.search":
            queries = search_queries(arguments["queries"])
            if self.searches <= 0 or self.queries <= 0:
                result = {"error": "Search budget exhausted; finish with any unresolved parts."}
            elif len(queries) > self.queries:
                result = {
                    "error": f"Only {self.queries} query entries remain; submit a smaller batch."
                }
            else:
                self.searches -= 1
                self.queries -= len(queries)
                result = (
                    await search(
                        self.ctx,
                        queries,
                        kinds=arguments.get("kinds"),
                        limit=arguments.get("limit", 10),
                    )
                )["result"]
        elif name == "graph.describe":
            if self.reads <= 0:
                result = {"error": "Read budget exhausted; finish with any unresolved parts."}
            else:
                self.reads -= 1
                result = await graph.read(self.ctx, "describe", arguments)
        else:
            raise ValueError("Unsupported evaluation tool: " + name)
        self._remember(result)
        self.trace.append({"name": name, "arguments": arguments, "result": result})
        return result

    def check_evidence(self, evidence):
        """Reject citations that were never exposed through a read tool."""
        ids = {entry["object_id"] for entry in evidence}
        if not ids <= self.visible.keys():
            raise ValueError("Answer cites objects that were never read")
        return ids


def adaptive_tools():
    """Use the application's actual native graph-read definitions."""
    from evertree._application.prompts import semantic_tools

    return tuple(
        tool for tool in semantic_tools() if tool.name in {"graph.search", "graph.describe"}
    )


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"object_id": {"type": "integer"}, "supports": {"type": "string"}},
                "required": ["object_id", "supports"],
                "additionalProperties": False,
            },
        },
        "unresolved": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "evidence", "unresolved"],
    "additionalProperties": False,
}
