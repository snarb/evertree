"""One admission and idempotency path for discrete external actions."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

type ActionStatus = Literal["accepted", "rejected", "unknown"]


@dataclass(frozen=True)
class ActionOption:
    command: Any
    description: str | None = None


class ActionAdapter(Protocol):
    async def list_actions(self) -> list[ActionOption]: ...
    async def execute(self, command: Any) -> ActionStatus: ...


def _key(command):
    return json.dumps(command, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ActionGateway:
    def __init__(self, *, journal: Path | None = None):
        self._adapters: dict[str, ActionAdapter] = {}
        self._sessions: dict[str, dict] = {}
        self._operations: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._journal_failed = False
        self._journal = Path(journal).resolve() if journal is not None else None
        if self._journal is not None:
            self._journal.parent.mkdir(parents=True, exist_ok=True)
            self._overlay_journal()

    def _append(self, identity: str, record: dict):
        if self._journal is None:
            return
        if self._journal_failed:
            raise OSError("External-action journal needs recovery before another action")
        session = self._sessions[record["session"]]
        entry = {
            "operation_id": identity,
            "operation": record,
            "binding": {"task_id": session["task_id"], "commit": session["commit"]},
        }
        try:
            with self._journal.open("ab") as stream:
                stream.write((_key(entry) + "\n").encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            self._journal_failed = True
            raise

    def _overlay_journal(self):
        if self._journal is None or not self._journal.exists():
            return
        records: dict[str, dict] = {}
        committed_offset = 0
        raw = self._journal.read_bytes()
        for line in raw.splitlines(keepends=True):
            if not line.endswith(b"\n"):
                # A pre-send intent is usable only after its complete fsynced
                # line. An incomplete outcome leaves its prior intent unknown.
                with self._journal.open("r+b") as stream:
                    stream.truncate(committed_offset)
                    stream.flush()
                    os.fsync(stream.fileno())
                break
            entry = json.loads(line)
            identity, operation, binding = (
                entry["operation_id"],
                entry["operation"],
                entry["binding"],
            )
            session = operation["session"]
            if (
                not identity
                or operation["status"] not in {"accepted", "rejected", "unknown"}
                or not binding.get("task_id")
                or not binding.get("commit")
            ):
                raise ValueError("Invalid external-action journal record")
            fingerprint_session, _ = json.loads(operation["fingerprint"])
            if fingerprint_session != session:
                raise ValueError("External-action journal fingerprint does not match its session")
            existing = self._sessions.get(session)
            if existing and any(existing[key] != binding[key] for key in ("task_id", "commit")):
                raise ValueError("External-action session identity collision during recovery")
            self._sessions.setdefault(session, {**binding, "issued": {}})
            previous = records.get(identity)
            self._validate_same_operation(previous, operation)
            if previous and previous["status"] != "unknown" and operation["status"] == "unknown":
                raise ValueError("External-action journal cannot reopen a resolved operation")
            records[identity] = operation
            committed_offset += len(line)
        for identity, operation in records.items():
            previous = self._operations.get(identity)
            self._validate_same_operation(previous, operation)
            # A retained snapshot can be newer than a journal's last complete
            # record. Never downgrade its resolved status to ambiguous.
            if previous and previous["status"] != "unknown" and operation["status"] == "unknown":
                continue
            self._operations[identity] = operation

    @staticmethod
    def _validate_same_operation(previous, operation):
        if previous is None:
            return
        if (
            previous["fingerprint"] != operation["fingerprint"]
            or previous["session"] != operation["session"]
        ):
            raise ValueError("External operation identity reused with different arguments")
        if (
            previous["status"] != "unknown"
            and operation["status"] != "unknown"
            and previous["status"] != operation["status"]
        ):
            raise ValueError("Conflicting resolved external-action outcomes")

    def bind(self, session: str, adapter: ActionAdapter, *, task_id: str, commit: str):
        if not session or not task_id or not commit:
            raise ValueError("Action binding requires session, task and exact adapter revision")
        existing = self._sessions.get(session)
        if existing and (existing["task_id"] != task_id or existing["commit"] != commit):
            raise ValueError("A new adapter session requires a new identity")
        self._adapters[session] = adapter
        self._sessions.setdefault(session, {"task_id": task_id, "commit": commit, "issued": {}})

    async def list(self, session: str, *, task_id: str, run_mode="live"):
        self._check(session, task_id, run_mode)
        options = await self._adapters[session].list_actions()
        issued = {
            _key(option.command): {
                "command": json.loads(_key(option.command)),
                "description": option.description,
            }
            for option in options
        }
        self._sessions[session]["issued"] = issued
        return list(issued.values())

    def _check(self, session, task_id, run_mode):
        if run_mode != "live":
            raise PermissionError("Simulation/replay cannot access live adapters")
        if session not in self._adapters:
            raise RuntimeError("Action session needs to be reconnected")
        if self._sessions[session]["task_id"] != task_id:
            raise PermissionError("Adapter belongs to another task")

    async def take(
        self, session, command, *, task_id, operation_id, run_mode="live", approved=False
    ):
        self._check(session, task_id, run_mode)
        if not operation_id:
            raise ValueError("External operations require stable identities")
        fingerprint = _key([session, command])
        async with self._lock:
            previous = self._operations.get(operation_id)
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise ValueError("Operation identity reused with different arguments")
                return previous["status"]
            if _key(command) not in self._sessions[session]["issued"]:
                raise ValueError("Command was not issued unchanged for this session")
            if not approved:
                raise PermissionError("External modification requires user approval")
            # Persist ambiguity before sending: interruption cannot authorize a resend.
            record = {"fingerprint": fingerprint, "session": session, "status": "unknown"}
            self._append(operation_id, record)
            self._operations[operation_id] = record
            try:
                result = await self._adapters[session].execute(json.loads(_key(command)))
            except Exception:  # noqa: BLE001 -- remote effects may have happened before any exception
                return "unknown"
            if result not in {"accepted", "rejected", "unknown"}:
                raise ValueError("Adapter returned an invalid action status")
            current = self._operations[operation_id]
            if current["status"] != "unknown":
                if result != "unknown" and result != current["status"]:
                    raise ValueError("Adapter result conflicts with host reconciliation")
                return current["status"]
            resolved = {**record, "status": result}
            try:
                self._append(operation_id, resolved)
            except OSError:
                # The action may have happened, but its resolved result did not
                # become durable. Recovery and callers must retain ambiguity.
                return "unknown"
            self._operations[operation_id] = resolved
            return result

    def reconcile(self, operation_id: str, status: ActionStatus, *, evidence: str):
        if status not in {"accepted", "rejected"} or not evidence:
            raise ValueError("Reconciliation needs a resolved status and source evidence")
        record = self._operations[operation_id]
        if record["status"] != "unknown":
            raise ValueError("Only unknown operations need reconciliation")
        resolved = {**record, "status": status, "reconciliation_evidence": evidence}
        self._append(operation_id, resolved)
        self._operations[operation_id] = resolved

    def pending(self, task_id: str) -> list[dict]:
        return [
            {"operation_id": identity, "session": record["session"], "status": "unknown"}
            for identity, record in self._operations.items()
            if record["status"] == "unknown"
            and self._sessions[record["session"]]["task_id"] == task_id
        ]

    def snapshot(self):
        return json.loads(_key({"sessions": self._sessions, "operations": self._operations}))

    @classmethod
    def from_snapshot(cls, data, *, journal: Path | None = None):
        store = cls()
        store._sessions = json.loads(_key(data.get("sessions", {})))
        store._operations = json.loads(_key(data.get("operations", {})))
        store._journal = Path(journal).resolve() if journal is not None else None
        if store._journal is not None:
            store._journal.parent.mkdir(parents=True, exist_ok=True)
            store._overlay_journal()
        return store
