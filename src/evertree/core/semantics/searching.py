"""Shared validation for the batch search boundary."""

from ..graph.types import normalize_name
from ..values import ContractError

SEARCH_KINDS = frozenset(
    {
        "concept",
        "prototype",
        "instance",
        "facet",
        "relation_type",
        "relation_instance",
        "property",
        "claim",
        "note",
        "process",
        "program",
        "operator",
    }
)


def query_key(query):
    """Normalize an identity or text query consistently with graph name lookup."""
    return normalize_name(str(query))


def search_queries(queries):
    """Validate and deduplicate a nonempty batch, preserving the first query's spelling."""
    if not isinstance(queries, list) or not queries:
        raise ContractError("queries must be a nonempty array of text or integer IDs")
    unique = {}
    for query in queries:
        if not ((isinstance(query, str) and query.strip()) or (type(query) is int and query > 0)):
            raise ContractError("Each search query must be nonempty text or a positive integer ID")
        # An integer ID and a numeric name have different lookup meanings.
        unique.setdefault((type(query), query_key(query)), query)
    return list(unique.values())


def search_limit(limit):
    """Require a per-query ceiling of at most ten candidates."""
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ContractError("limit must be between 1 and 10 per query")
    return limit


def search_kinds(kinds):
    """Normalize an optional union of graph kinds without treating an empty filter as broad."""
    if kinds is None:
        return None
    if (
        not isinstance(kinds, list)
        or not kinds
        or any(not isinstance(kind, str) or not kind.strip() for kind in kinds)
    ):
        raise ContractError("kinds must be a nonempty array of graph kind names or null")
    normalized = sorted({kind.strip().casefold() for kind in kinds})
    if set(normalized) - SEARCH_KINDS:
        raise ContractError("Unknown search kind; choose from " + ", ".join(sorted(SEARCH_KINDS)))
    return normalized
