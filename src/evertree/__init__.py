"""EverTree's local Python API. Importing the package does not start an agent."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import EverTree, EverTreeEvent
    from .core.codex_provider import CodexProvider
    from .core.evaluation import SupervisorFeedback
    from .core.provider import AgentEvent, AgentProvider, AgentRequest, ScriptedProvider

__all__ = [
    "AgentEvent",
    "AgentProvider",
    "AgentRequest",
    "CodexProvider",
    "EverTree",
    "EverTreeEvent",
    "ScriptedProvider",
    "SupervisorFeedback",
]


def __getattr__(name):
    if name in {"EverTree", "EverTreeEvent"}:
        return getattr(import_module(".application", __name__), name)
    if name == "CodexProvider":
        return getattr(import_module(".core.codex_provider", __name__), name)
    if name == "SupervisorFeedback":
        return getattr(import_module(".core.evaluation", __name__), name)
    if name in {"AgentProvider", "AgentRequest", "AgentEvent", "ScriptedProvider"}:
        return getattr(import_module(".core.provider", __name__), name)
    raise AttributeError(name)
