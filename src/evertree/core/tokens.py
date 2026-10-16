"""Local token accounting and provider context carried across tool callbacks."""

import json
from contextvars import ContextVar
from functools import lru_cache

from .values import ContractError

current_read_context = ContextVar("read_context", default=None)


def tool_text(value):
    """Serialize a tool result using the JSON representation counted against model context."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@lru_cache(maxsize=16)
def encoding(model, fallback="o200k_base"):
    """Select the model's tokenizer or the configured estimate for an unregistered model name."""
    import tiktoken

    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        # Private model names are absent from tiktoken's public registry. The
        # configured encoding is a local estimate, never a server-exact count.
        return tiktoken.get_encoding(fallback)


def count_tokens(value, model, fallback="o200k_base"):
    """Estimate the token cost of a serialized tool result with the selected model tokenizer."""
    return len(encoding(model, fallback).encode_ordinary(tool_text(value)))


def read_budget(context, fraction):
    """Limit graph-result tokens to a context fraction and any known remaining capacity."""
    if (
        not context
        or type(context.get("context_window")) is not int
        or context["context_window"] <= 0
    ):
        raise ContractError("Model context window is unavailable; cannot budget graph results")
    maximum = int(context["context_window"] * fraction)
    remaining = context.get("remaining_tokens")
    if remaining is not None:
        if type(remaining) is not int:
            raise ContractError("Invalid remaining model context")
        maximum = min(maximum, max(0, remaining))
    return maximum
