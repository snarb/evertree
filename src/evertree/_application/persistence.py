"""Agent stores, bootstrap, input journal, backups and maintenance."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from ..core.actions import ActionGateway
from ..core.attribution import AttributionRuntime
from ..core.backup import _restore_io, safe_remove_tree
from ..core.beliefs import BeliefStore
from ..core.cache import prune
from ..core.cognition import AttentionRuntime, TaskSpecification, TaskStore
from ..core.datasets import DatasetStore
from ..core.environment import validate_runtime
from ..core.evaluation import EvaluationStore
from ..core.graph import GraphDelta, GraphStore, Node
from ..core.learning import LearningBinding, LearningStore
from ..core.memory import TraceStore
from ..core.programs.lifecycle import fetch_programs, git, publish_programs


class PersistenceMixin:
    """Internal EverTree method group; state is owned and initialized by EverTree."""

    def _reset_stores(self):
        self.graph, self.memory, self.beliefs = GraphStore(), TraceStore(), BeliefStore()
        self.graph.belief_reader = self.beliefs.read
        self.attribution = AttributionRuntime(self.graph, self.beliefs)
        self.tasks = TaskStore()
        self.attention = AttentionRuntime(self.tasks)
        self.datasets, self.evaluations, self.learning = (
            DatasetStore(),
            EvaluationStore(),
            LearningStore(),
        )
        self.actions = ActionGateway(journal=self.state_dir / "actions.jsonl")
        self._inputs: dict[str, list[dict]] = {}
        self._sessions: dict[str, dict] = {}
        self._run_map: dict[str, int] = {}
        self._seen_inputs: dict[str, str] = {}
        self._protected_nodes: set[int] = set()
        self._evaluation_bindings: dict[str, dict] = {}
        self._pending_programs: dict[str, dict] = {}
        self._observations: set[int] = set()
        self._predictions: dict[str, float] = {}

    def _bootstrap(self):
        from ..core.programs.bootstrap import INITIAL_PRINCIPLES, seed_process_delta

        revision = git(self.repository, "rev-parse", "main")
        run = self.memory.start_run("bootstrap", revision, {})
        event = self.memory.record(run, "bootstrap", output={"revision": revision})
        ref = self.memory.output_ref(event)
        ids = self.graph.bootstrap(provenance=ref)
        creates = []
        for name in (
            "Self",
            "SelfModel",
            "SelfRegulation",
            "EpistemicQuality",
            "AgentCapability",
            "supervisor_feedback_signal",
        ):
            node = Node(
                self.graph.reserve_id(),
                name,
                kind="value" if name in {"EpistemicQuality", "AgentCapability"} else "concept",
            )
            creates.append(node)
            self._protected_nodes.add(node.id)
        self_id = next(node.id for node in creates if node.name == "Self")
        creates.extend(seed_process_delta(self.graph, self_id=self_id, revision=revision).creates)
        self.graph.apply(GraphDelta(creates=tuple(creates)), provenance=ref)
        self._validate_program_layout(None, revision)
        self._protected_nodes.add(self.graph.find("SelfProcess").id)
        principles = tuple(
            Node(self.graph.reserve_id(), name, kind="principle", description=description)
            for name, description in INITIAL_PRINCIPLES.items()
        )
        self.graph.apply(GraphDelta(creates=principles), provenance=ref)
        self._protected_nodes.update(node.id for node in principles)
        self._protected_nodes.update(ids.values())
        for node in self.graph.nodes():
            self.memory.retain(ref, "graph:" + str(node.id))
        self.memory.finish_run(run)
        self.learning.create_state("beta_bernoulli", state_id="verified_task_rate")
        self.learning.register_binding(
            LearningBinding("verified_task_rate", "verified_task_rate", ("brier",))
        )

    def _append_input(self, record):
        # Intake is durable even while another task occupies the runtime.
        with (self.state_dir / "intake.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _recover_inputs(self):
        path = self.state_dir / "intake.jsonl"
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                # Only the last, torn write can be incomplete.
                if line != path.read_text(encoding="utf-8").splitlines()[-1]:
                    raise
                break
            incoming, raw = record["input"], record["task"]
            if incoming["source_id"] in self._seen_inputs:
                continue
            try:
                state = self.tasks.get(raw["id"])
            except KeyError:
                state = self.tasks.create_task(
                    TaskSpecification.from_dict(raw["specification"]),
                    task_id=raw["id"],
                    source_ids=raw["source_ids"],
                    hard_limits=raw["hard_limits"],
                    episode_id=raw["episode_ids"][0] if raw["episode_ids"] else None,
                )
            self._inputs.setdefault(state.id, []).append(incoming)
            self._seen_inputs[incoming["source_id"]] = state.id
            state.status = "suspended"
            state.execution_stopped = True

    def snapshot(self):
        return {
            "format": 1,
            "environment": json.loads(json.dumps(self._environment)),
            "program_revision": git(self.repository, "rev-parse", "main"),
            "program_remote": self._program_remote,
            "lifecycle": self.lifecycle.snapshot(),
            "graph": self.graph.snapshot(),
            "memory": self.memory.snapshot(),
            "attribution": self.attribution.snapshot(),
            "beliefs": self.beliefs.snapshot(),
            "tasks": self.tasks.snapshot(),
            "attention": self.attention.snapshot(),
            "datasets": self.datasets.snapshot(),
            "evaluations": self.evaluations.snapshot(),
            "learning": self.learning.snapshot(),
            "actions": self.actions.snapshot(),
            "inputs": self._inputs,
            "sessions": self._sessions,
            "run_map": self._run_map,
            "seen_inputs": self._seen_inputs,
            "protected_nodes": sorted(self._protected_nodes),
            "results": self._results,
            "evaluation_bindings": self._evaluation_bindings,
            "pending_programs": self._pending_programs,
            "observations": sorted(self._observations),
            "predictions": self._predictions,
        }

    def _restore_core(self, data):
        if data.get("format") != 1:
            raise ValueError("Unsupported EverTree backup")
        git(self.repository, "reset", "--hard", data["program_revision"])
        self._program_remote = data["program_remote"]
        self.lifecycle.restore(data["lifecycle"])
        self.graph, self.memory = (
            GraphStore.from_snapshot(data["graph"]),
            TraceStore.from_snapshot(data["memory"]),
        )
        self.beliefs, self.tasks = (
            BeliefStore.from_snapshot(data["beliefs"]),
            TaskStore.from_snapshot(data["tasks"]),
        )
        self.graph.belief_reader = self.beliefs.read
        self.attribution = AttributionRuntime.from_snapshot(
            data["attribution"], self.graph, self.beliefs
        )
        self.attention = AttentionRuntime.from_snapshot(data["attention"], self.tasks)
        self.datasets, self.evaluations = (
            DatasetStore.from_snapshot(data["datasets"]),
            EvaluationStore.from_snapshot(data["evaluations"]),
        )
        self.learning, self.actions = (
            LearningStore.from_snapshot(data["learning"]),
            ActionGateway.from_snapshot(data["actions"], journal=self.state_dir / "actions.jsonl"),
        )
        for name in (
            "inputs",
            "sessions",
            "run_map",
            "seen_inputs",
            "results",
            "evaluation_bindings",
            "pending_programs",
            "predictions",
        ):
            setattr(self, "_" + name, data.get(name, {}))
        self._protected_nodes = set(data["protected_nodes"])
        self._observations = set(data.get("observations", ()))
        for state in self.tasks.all():
            if not state.terminal:
                state.execution_stopped = True
                if state.status == "running":
                    state.status = "suspended"
        self.attention.running_task = self.attention.focus = None

    async def backup(self):
        if self.runtime is None:
            return None
        async with self._state_lock:
            if self._active_requests or self._operations:
                return None
            for identity in self.lifecycle.snapshot()["branches"]:
                if (self.lifecycle.state_dir / "candidates" / identity).exists():
                    await _restore_io(self.lifecycle.retain_candidate, identity)
            await _restore_io(publish_programs, self.repository, self._program_remote)
            path = await self.backups.create(
                self.runtime,
                self.snapshot,
                timeout=10,
            )
            for obsolete in self.backups.list()[2:]:
                root = self.backups.root.resolve()
                target = obsolete.resolve()
                if target.is_relative_to(root) and target != root:
                    await asyncio.to_thread(safe_remove_tree, target, root)
            return path

    async def restore(self, backup=None):
        async with self._state_lock:
            if (
                self._active_requests
                or self._operations
                or self.runtime.is_running()
                or (self._pump and not self._pump.done())
            ):
                raise RuntimeError("Stop the agent's tasks before restoring")

            async def validate(verified):
                saved = verified.state["core"]
                await _restore_io(
                    fetch_programs,
                    self.repository,
                    saved["program_remote"],
                    saved["program_revision"],
                )
                await asyncio.to_thread(
                    validate_runtime,
                    verified.state["core"].get("environment"),
                    Path(__file__).parent.parent,
                )

            await self.backups.restore(
                self.runtime,
                self._restore_core,
                snapshot_core=self.snapshot,
                backup=Path(backup) if backup else None,
                validate=validate,
            )
            await self._discard_workspaces()
            self._sessions.clear()
            self._pending_programs.clear()
            for run in self.memory.runs:
                if run.status == "running":
                    self.memory.finish_run(run.id, status="interrupted")
            for state in self.tasks.all():
                if not state.terminal:
                    self._inputs.setdefault(state.id, []).append(
                        {
                            "role": "observation",
                            "content": "Execution restarted. Temporary files and unfinished candidate work were discarded. "
                            "Recreate needed files or ask the user to provide them again. "
                            "Consult retained action receipts before repeating external effects.",
                        }
                    )

    async def _discard_workspaces(self, task_id=None):
        root = self.state_dir / "workspaces"
        target = root / task_id if task_id else root
        await _restore_io(safe_remove_tree, target, root if task_id else self.state_dir)
        candidates = [key for key, owner in self._candidate_owners.items() if owner == task_id]
        await _restore_io(self.lifecycle.discard_candidates, candidates if task_id else None)
        if task_id is None:
            await _restore_io(safe_remove_tree, self.state_dir / "evaluations", self.state_dir)
            self._candidate_owners.clear()
        for key in candidates:
            self._candidate_owners.pop(key, None)

    async def _periodic_maintenance(self):
        while not self._closed:
            await asyncio.sleep(300)
            try:
                await asyncio.to_thread(prune, self.directory)
                if not self._active_requests:
                    self.memory.review_batch()
                    self.memory.finalize_deletions()
                    await self.backup()
            except Exception as exc:  # noqa: BLE001 -- report failed background maintenance
                await self._publish("maintenance_error", data={"message": str(exc)})
