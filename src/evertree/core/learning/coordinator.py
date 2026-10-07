"""Coordination of credit, planning and transactional learning updates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import (
    LearningSignal,
    UnresolvedCredit,
    UpdateBlocked,
    UpdateReceipt,
)
from .state import (
    LearningStore,
)
from .updates import (
    CreditAssignmentProgram,
    UpdatePlanner,
    UpdateTransactionManager,
)


class LearningCoordinator:
    def __init__(self, store: LearningStore) -> None:
        self.store = store
        self.credit_assignment = CreditAssignmentProgram(store)
        self.planner = UpdatePlanner(store)
        self.transactions = UpdateTransactionManager(store)

    def learn(
        self,
        signal: LearningSignal,
        target: str,
        *,
        context: Mapping[str, Any] | None = None,
        attribution_weight: float = 1.0,
        ambiguous: bool = False,
    ) -> UpdateReceipt | UpdateBlocked | UnresolvedCredit:
        credit = self.credit_assignment.assign(
            target,
            signal,
            context=context,
            attribution_weight=attribution_weight,
            ambiguous=ambiguous,
        )
        if isinstance(credit, UnresolvedCredit):
            return credit
        update = self.planner.prepare(credit)
        if isinstance(update, UpdateBlocked):
            return update
        return self.transactions.apply(update)

    def missing_prediction(
        self,
        target: str,
        observation_ids: tuple[str, ...],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> UnresolvedCredit:
        result = self.credit_assignment.assign(
            target, observation_ids=observation_ids, context=context
        )
        assert isinstance(result, UnresolvedCredit)
        return result
