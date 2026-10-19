"""Trusted invocation context shared by application and Program admission."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar

semantic_scope = ContextVar("evertree_semantic_scope", default=None)


class ExecutionOwner:
    """Keep unrelated application callers outside the active execution chain."""

    def __init__(self):
        self._owner = None
        self._idle = asyncio.Event()
        self._idle.set()
        self._context = ContextVar("evertree_execution_owner", default=None)

    @property
    def busy(self):
        """Whether an execution chain currently owns application state."""
        return self._owner is not None

    def check(self):
        """Reject mutations from outside the admitted execution chain."""
        if self._owner is not None and self._context.get() is not self._owner:
            from .controller import RuntimeBusy

            raise RuntimeBusy("Agent state belongs to the current execution chain")

    async def wait_idle(self):
        """Let queued input wait for maintenance without admitting concurrent execution."""
        while self.busy and self._context.get() is not self._owner:
            await self._idle.wait()

    @contextmanager
    def enter(self):
        """Admit an idle caller or a nested call from the current owner."""
        self.check()
        if self._owner is not None:
            yield
            return
        self._owner = object()
        self._idle.clear()
        token = self._context.set(self._owner)
        try:
            yield
        finally:
            self._owner = None
            self._context.reset(token)
            self._idle.set()
