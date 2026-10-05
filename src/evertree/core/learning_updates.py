"""Credit assignment, update planning and atomic update/retraction transactions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .datasets import content_revision, freeze_json, thaw_json
from .learning_contracts import (
    CreditRetraction,
    LearningCredit,
    LearningSignal,
    PreparedUpdate,
    UnresolvedCredit,
    UpdateBlocked,
    UpdateReceipt,
)
from .learning_state import LearningStore


class CreditAssignmentProgram:
    def __init__(self, store: LearningStore) -> None:
        self.store = store

    def assign(
        self,
        target: str,
        signal: LearningSignal | None = None,
        *,
        ambiguous: bool = False,
        observation_ids: tuple[str, ...] = (),
        context: Mapping[str, Any] | None = None,
        attribution_weight: float = 1.0,
        resolves: str | None = None,
    ) -> LearningCredit | UnresolvedCredit:
        if signal is None:
            # Replaying the same unmatched experience cannot create new credit.
            for existing in self.store._unresolved.values():
                if (
                    existing.reason == "missing_prediction"
                    and existing.target == target
                    and existing.observation_ids == tuple(observation_ids)
                    and thaw_json(existing.context) == thaw_json(context or {})
                ):
                    return existing
            credit = UnresolvedCredit(
                target, "missing_prediction", observation_ids, context=context or {}
            )
            self.store._unresolved[credit.id] = credit
            return credit
        if ambiguous:
            unresolved = UnresolvedCredit(
                target,
                "ambiguous_attribution",
                tuple(signal.outcome_values),
                signal,
                context=context or {},
            )
            self.store._unresolved[unresolved.id] = unresolved
            return unresolved
        if resolves and resolves not in self.store._unresolved:
            raise ValueError("Resolved credit refers to an unknown unresolved case")
        result = LearningCredit(target, signal, attribution_weight, context or {}, resolves)
        self.store._credits[result.id] = result
        return result


class UpdatePlanner:
    def __init__(self, store: LearningStore) -> None:
        self.store = store

    def prepare(self, credit: LearningCredit) -> PreparedUpdate | UpdateBlocked:
        if not isinstance(credit, LearningCredit):
            raise TypeError("Unresolved credit cannot be passed to UpdatePlanner")
        candidates = [
            binding
            for binding in self.store._bindings
            if binding.target == credit.target
            and (
                binding.subject is None
                or binding.subject == credit.signal.evaluation.evaluated_subject
            )
        ]
        if not candidates:
            return UpdateBlocked(credit, "no_learning_binding")
        candidates = [
            binding
            for binding in candidates
            if set(credit.signal.objective.metrics) <= set(binding.metrics)
            and binding.direction == credit.signal.objective.direction
        ]
        if not candidates:
            return UpdateBlocked(credit, "unsupported_signal")
        if len(candidates) != 1:
            return UpdateBlocked(credit, "ambiguous_learning_binding")
        binding = candidates[0]
        context = thaw_json(credit.context)
        example = context.get("example_id")
        if example and not binding.allow_multiple_examples:
            return UpdateBlocked(credit, "incompatible_updater_contract")
        samples = []
        for identity, value in credit.signal.outcome_values.items():
            corrections = context.get("correction_of", {})
            corrected_source = corrections.get(identity) if isinstance(corrections, dict) else None
            key = content_revision(
                {
                    "state": binding.state,
                    "outcome": corrected_source or identity,
                    "example": example,
                }
            )
            with self.store._lock:
                old = self.store._ledger.get(key)
                if old and not (corrected_source and old["status"] == "retracted"):
                    return UpdateBlocked(credit, "already_accounted")
                if corrected_source and (not old or old["status"] != "retracted"):
                    return UpdateBlocked(credit, "incompatible_updater_contract")
            sample = {
                "outcome_id": identity,
                "value": thaw_json(value),
                "weight": credit.attribution_weight,
                "logical_key": key,
            }
            if "features" in context:
                sample["features"] = context["features"]
            samples.append(sample)
        data = {"samples": samples, "example_id": example}
        state = self.store.state(binding.state)
        try:
            # Validate compatibility without storing anything or using stale output.
            # The transaction recalculates against current parameters under its lock.
            self.store.dispatcher.get(state["kind"]).apply(
                state["parameters"], data, state["settings"]
            )
        except (ValueError, TypeError, KeyError, OverflowError):
            return UpdateBlocked(credit, "incompatible_updater_contract")
        return PreparedUpdate(credit, binding.state, data)


class UpdateTransactionManager:
    def __init__(self, store: LearningStore) -> None:
        self.store = store

    def _receipt(
        self,
        request: PreparedUpdate | CreditRetraction,
        status: str,
        reason: str | None,
        fingerprint: str,
        revision: int | None = None,
    ) -> UpdateReceipt:
        receipt = UpdateReceipt(request.id, request.state, status, reason, revision)
        try:
            self.store._receipts[request.id] = receipt
            self.store._requests[request.id] = fingerprint
        except BaseException:
            self.store._receipts.pop(request.id, None)
            self.store._requests.pop(request.id, None)
            raise
        return receipt

    def _retry(self, identity: str, fingerprint: str) -> UpdateReceipt | None:
        if identity in self.store._receipts:
            if self.store._requests[identity] != fingerprint:
                raise ValueError("Update request identity reused with different parameters")
            return self.store._receipts[identity]
        return None

    def _commit(
        self,
        request: PreparedUpdate | CreditRetraction,
        state: dict[str, Any],
        entries: dict[str, dict[str, Any]],
        status: str,
        fingerprint: str,
    ) -> UpdateReceipt:
        """Publish one update together, restoring affected entries if commit fails."""
        old_state = self.store._states[request.state]
        old_entries = {key: self.store._ledger.get(key) for key in entries}
        credit = request.source_credit if isinstance(request, PreparedUpdate) else None
        credit_existed = credit is not None and credit.id in self.store._credits
        try:
            self.store._states[request.state] = state
            self.store._ledger.update(entries)
            if credit is not None:
                self.store._credits.setdefault(credit.id, credit)
            return self._receipt(request, status, None, fingerprint, state["revision"])
        except BaseException:
            self.store._states[request.state] = old_state
            for key, previous in old_entries.items():
                if previous is None:
                    self.store._ledger.pop(key, None)
                else:
                    self.store._ledger[key] = previous
            if credit is not None and not credit_existed:
                self.store._credits.pop(credit.id, None)
            self.store._receipts.pop(request.id, None)
            self.store._requests.pop(request.id, None)
            raise

    def apply(self, update: PreparedUpdate) -> UpdateReceipt:
        if not isinstance(update, PreparedUpdate):
            raise TypeError("Only prepared resolved updates can be applied")
        fingerprint = content_revision({"kind": "apply", **update.to_dict()})
        with self.store._lock:
            retry = self._retry(update.id, fingerprint)
            if retry:
                return retry
            state = self.store._states.get(update.state)
            if state is None:
                return self._receipt(update, "rejected", "unknown_state", fingerprint)
            # Check that callers did not construct a request bypassing its declared binding.
            planned = UpdatePlanner(self.store).prepare(update.source_credit)
            if isinstance(planned, UpdateBlocked):
                return self._receipt(
                    update, "rejected", planned.reason, fingerprint, state["revision"]
                )
            if planned.state != update.state or thaw_json(planned.updater_input) != thaw_json(
                update.updater_input
            ):
                return self._receipt(
                    update,
                    "rejected",
                    "incompatible_updater_contract",
                    fingerprint,
                    state["revision"],
                )
            samples = thaw_json(update.updater_input)["samples"]
            keys = [sample["logical_key"] for sample in samples]
            if len(set(keys)) != len(keys) or any(
                key in self.store._ledger and self.store._ledger[key]["status"] != "retracted"
                for key in keys
            ):
                return self._receipt(
                    update, "rejected", "already_accounted", fingerprint, state["revision"]
                )
            # No live state is handed to the updater. A failure leaves all three
            # authoritative maps (state, contribution ledger, receipt) unchanged.
            working = thaw_json(freeze_json(state["parameters"]))
            new_parameters = self.store.dispatcher.get(state["kind"]).apply(
                working, thaw_json(update.updater_input), dict(state["settings"])
            )
            new_parameters = thaw_json(freeze_json(new_parameters))
            revision = state["revision"] + 1
            entries = {
                sample["logical_key"]: {
                    "state": update.state,
                    "credit_id": update.source_credit.id,
                    "request_id": update.id,
                    "sample": sample,
                    "status": "applied",
                    "previous": self.store._ledger.get(sample["logical_key"]),
                }
                for sample in samples
            }
            new_state = {
                **state,
                "parameters": new_parameters,
                "revision": revision,
            }
            return self._commit(update, new_state, entries, "applied", fingerprint)

    def retract(self, retraction: CreditRetraction) -> UpdateReceipt:
        if not isinstance(retraction, CreditRetraction):
            raise TypeError("Retraction needs an immutable request")
        fingerprint = content_revision({"kind": "retract", **retraction.to_dict()})
        with self.store._lock:
            retry = self._retry(retraction.id, fingerprint)
            if retry:
                return retry
            state = self.store._states.get(retraction.state)
            if state is None:
                return self._receipt(retraction, "rejected", "unknown_state", fingerprint)
            entries = [
                (key, entry)
                for key, entry in self.store._ledger.items()
                if entry["state"] == retraction.state
                and entry["credit_id"] == retraction.credit.id
                and entry["status"] == "applied"
            ]
            if not entries:
                return self._receipt(
                    retraction, "skipped", "no_applied_contribution", fingerprint, state["revision"]
                )
            working = thaw_json(freeze_json(state["parameters"]))
            data = {"samples": [entry["sample"] for _, entry in entries]}
            updater = self.store.dispatcher.get(state["kind"])
            retract = getattr(updater, "retract", None)
            new_parameters = retract(working, data, dict(state["settings"])) if retract else None
            if new_parameters is None:
                return self._receipt(
                    retraction, "skipped", "unsupported_retraction", fingerprint, state["revision"]
                )
            new_parameters = thaw_json(freeze_json(new_parameters))
            revision = state["revision"] + 1
            new_state = {
                **state,
                "parameters": new_parameters,
                "revision": revision,
            }
            retracted = {
                key: {
                    **entry,
                    "status": "retracted",
                    "retraction_id": retraction.id,
                }
                for key, entry in entries
            }
            return self._commit(retraction, new_state, retracted, "retracted", fingerprint)


# Keep existing trace type names and pickled references valid through the public module.
for _export in (
    CreditAssignmentProgram,
    UpdatePlanner,
    UpdateTransactionManager,
):
    _export.__module__ = "evertree.core.learning"
