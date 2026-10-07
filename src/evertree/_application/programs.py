"""Program lookup, execution, traces and candidate evaluation."""

from __future__ import annotations

import dataclasses
import io
import zipfile
from pathlib import Path
from uuid import uuid4

from ..core.anchors import AnchorResolver, parse_anchors
from ..core.evaluation import AcceptanceCriteria, MetricGuardrail
from ..core.graph import GraphDelta, Node, NodeUpdate, Prototype
from ..core.programs.layout import process_directory, process_slug, validate_process_layout
from ..core.programs.lifecycle import ProgramLifecycleRuntime, git
from ..core.provider import AgentRequest
from ..core.runtime import ProgramSpec, _git
from ..core.values import json_value


class ProgramsMixin:
    """Internal EverTree method group; state is owned and initialized by EverTree."""

    def _make_lifecycle(self):
        self.lifecycle = ProgramLifecycleRuntime(
            self.repository,
            self.state_dir / "lifecycle",
            self._acceptance_criteria,
            on_activate=self._activated,
            validate_layout=self._validate_program_layout,
            program_path=self._program_graph_path,
        )

    def _program_graph_path(self, identity):
        program = self.graph.get(int(identity))
        process = self.graph.get(program.properties["process"])
        lineage = [process, *self.graph.ancestors(process.id)]
        root = self.graph.find("SelfProcess")
        names = []
        for node in lineage:
            if node.id == root.id:
                break
            names.append(node.name)
        else:
            raise ValueError("Program must belong to Self/Process")
        return "/".join(("Self", "Process", *reversed(names), program.properties["role"]))

    def _validate_program_layout(self, branch, revision):
        repository = Path(branch.workspace) if branch else self.repository
        archive = _git(repository, "archive", "--format=zip", revision, "src/evertree/processes")
        with zipfile.ZipFile(io.BytesIO(archive)) as sources:
            validate_process_layout(
                self.graph,
                sources.namelist(),
                lambda path: sources.read(path).decode("utf-8"),
                candidate_program_id=int(branch.program_id) if branch else None,
            )

    def _acceptance_criteria(self, candidate):
        binding = self._evaluation_bindings.get(str(candidate.program_id))
        if binding is None:
            raise ValueError("No independent evaluation is bound to this Program")
        values = dict(binding["criteria"])
        values["guardrails"] = tuple(MetricGuardrail(**item) for item in values["guardrails"])
        return AcceptanceCriteria(**values)

    def _program_revision(self):
        return git(self.repository, "rev-parse", "main")

    def _program_source(self, spec):
        return _git(self.repository, "show", f"{spec['revision']}:{spec['git_path']}").decode(
            "utf-8"
        )

    def _program(self, identity: int | str, *, allow_inactive=False) -> ProgramSpec:
        node = self.graph.get(identity) if isinstance(identity, int) else self.graph.find(identity)
        if node is None and isinstance(identity, str):
            node = next(
                (
                    item
                    for item in self.graph.nodes(kind="program")
                    if item.properties.get("slug") == identity
                ),
                None,
            )
        if node is None:
            raise ValueError(f"Unknown Program/process: {identity}")
        if node.properties.get("process") is True:
            program_id = node.properties.get("active_exec", node.properties.get("active_model"))
            if program_id is None:
                raise ValueError("Process has no active Program")
            node = self.graph.get(program_id)
        if node.kind != "program":
            raise ValueError("Selected object is not a Program")
        if not node.properties.get("active", True) and not allow_inactive:
            raise PermissionError("Program has not passed activation")
        return ProgramSpec(
            node.id,
            node.properties["git_path"],
            self._program_revision(),
            node.properties.get("entrypoint", "run"),
            node.properties["role"],
        )

    def programs(self):
        return [json_value(node) for node in self.graph.nodes(kind="program")]

    def propose_program(
        self,
        name: str,
        *,
        role: str,
        claim: str,
        description="",
        candidate_name: str | None = None,
        parent: int | str | None = None,
    ):
        """Propose a role for an existing process or a new subtype of parent."""
        if role not in {"exec", "model"} or not name.isidentifier():
            raise ValueError("A Program requires an identifier name and model/exec role")
        process = self.graph.find(name)
        creates = []
        slug = process_slug(name)
        if process is not None:
            if parent is not None:
                raise ValueError("parent is only used when creating a new process")
            if process.properties.get("process") is not True:
                raise ValueError("The existing name must identify a process in Self/Process")
            directory = process_directory(self.graph, process.id).rstrip("/")
            if any(
                node.properties.get("process") == process.id and node.properties.get("role") == role
                for node in self.graph.nodes(kind="program")
            ):
                raise ValueError("Process already has this Program role; use create_candidate")
        else:
            parent_node = (
                self.graph.find("SelfProcess")
                if parent is None
                else self.graph.get(parent)
                if isinstance(parent, int)
                else self.graph.find(parent)
            )
            if parent_node is None or parent_node.properties.get("process") is not True:
                raise ValueError("parent must identify a process in Self/Process")
            directory = process_directory(self.graph, parent_node.id).rstrip("/") + "/" + slug
            if slug.startswith("_") or any(
                process_directory(self.graph, node.id).rstrip("/") == directory
                for node in self.graph.descendants(self.graph.find("SelfProcess").id)
            ):
                raise ValueError("Process name collides with an existing or reserved directory")
            process = Prototype(self.graph.reserve_id(), name, properties={"process": True})
            creates.extend(
                (
                    process,
                    self.graph.new_fact(
                        "SUBTYPE_OF", {"type": process.id, "supertype": parent_node.id}
                    ),
                )
            )
        if self.graph.find(name + "." + role):
            raise ValueError("Program name is already registered")
        run = self.memory.start_run("ProgramProposal", self._program_revision(), {"name": name})
        event = self.memory.record(
            run, "propose_program", output={"claim": claim, "description": description}
        )
        program = Node(
            self.graph.reserve_id(),
            name + "." + role,
            kind="program",
            description=description,
            properties={
                "git_path": f"{directory}/_{role}.py",
                "process": process.id,
                "role": role,
                "roles": (role,),
                "slug": slug,
                "active": False,
                "entrypoint": "run",
            },
        )
        delta = GraphDelta(
            creates=(
                *creates,
                program,
                self.graph.new_fact(
                    "PROGRAM_FOR_PROCESS", {"program": program.id, "process": process.id}
                ),
            )
        )
        ref = self.memory.output_ref(event)
        self.graph.apply(delta, provenance=ref)
        self.memory.retain(ref, "graph:" + str(program.id))
        self.memory.finish_run(run)
        candidate = self.lifecycle.create_candidate(
            program.id, claim, candidate_name=candidate_name
        )
        if self._current_task:
            self._candidate_owners[candidate.id] = self._current_task
        return {"program": json_value(program), "candidate": dataclasses.asdict(candidate)}

    async def _run_program(self, task_id, identity, arguments, *, timeout=None):
        spec = self._program(identity)
        async with self._state_lock:
            pending = self._pending_programs.get(task_id)
            if pending and (pending["identity"] != identity or pending["arguments"] != arguments):
                raise RuntimeError("Resume the pending ProgramRun before starting another Program")
            pending = pending or {
                "identity": identity,
                "arguments": arguments,
                "run_id": uuid4().hex,
                "spec": dataclasses.asdict(spec),
            }
            self._pending_programs[task_id] = pending
            spec = ProgramSpec(**pending["spec"])
            self._operations += 1
        try:
            with self._meter(task_id):
                result = await self.runtime.execute(
                    task_id,
                    spec,
                    arguments,
                    run_id=pending["run_id"],
                    timeout=timeout or self._remaining_seconds(self.tasks.get(task_id)),
                )
            self._pending_programs.pop(task_id, None)
            return dataclasses.asdict(result)
        finally:
            self._operations -= 1

    async def _runtime_trace(self, event):
        kind, identity = event["type"], event.get("run_id")
        if kind == "run_started":
            if identity not in self._run_map:
                spec = event["program"]
                parent_id = self._run_map.get(event.get("parent_run_id"))
                caller = (
                    self.memory.record(
                        parent_id,
                        "call_program",
                        arguments=event.get("arguments", {}),
                        output={"program": spec["program_id"], "run_id": identity},
                    )
                    if parent_id
                    else None
                )
                run = self.memory.start_run(
                    spec["program_id"],
                    spec["revision"],
                    event.get("arguments", {}),
                    run_mode=event.get("run_mode", "live"),
                    caller_event=caller.id if caller else None,
                )
                self._run_map[identity] = run.id
                state = self.tasks.get(event["task_id"])
                state.program_run_ids.append(identity)
                source = self._program_source(spec)
                anchors = parse_anchors(
                    source,
                    code_node_id=spec["program_id"],
                    git_path=spec["git_path"],
                    commit_sha=spec["revision"],
                )
                if anchors:
                    anchor_event = self.memory.record(
                        run, "code_anchors", output=json_value(anchors)
                    )
                    ref = self.memory.output_ref(anchor_event)
                    AnchorResolver(self.graph).install(anchors, provenance=ref)
                    self.memory.retain(
                        ref, "code_anchors:" + str(spec["program_id"]) + ":" + spec["revision"]
                    )
        elif identity in self._run_map:
            run = self.memory.get_run(self._run_map[identity])
            if run.status == "running":
                operator = event.get("operator", kind)
                anchored = self.graph.find(f"op:{run.program}:{event.get('anchor', operator)}")
                self.memory.record(
                    run,
                    anchored.id if anchored else operator,
                    arguments=event.get("arguments", {}),
                    output=event.get("output", event),
                    status=event.get("status", "completed"),
                )
                if kind in {"run_finished", "run_failed"}:
                    self.memory.finish_run(
                        run, status="completed" if kind == "run_finished" else "failed"
                    )

    def _activated(self, branch, revision):
        self._validate_program_layout(branch, revision)
        node = self.graph.get(int(branch.program_id))
        run = self.memory.start_run("EvaluationChoice", revision, {"candidate": branch.id})
        event = self.memory.record(
            run, "activate_program", output={"program": node.id, "revision": revision}
        )
        process = self.graph.get(node.properties["process"])
        self.graph.apply(
            GraphDelta(
                updates=(
                    NodeUpdate(
                        node.id,
                        {"properties": {**node.properties, "revision": revision, "active": True}},
                    ),
                    NodeUpdate(
                        process.id,
                        {
                            "properties": {
                                **process.properties,
                                "active_" + node.properties["role"]: node.id,
                            }
                        },
                    ),
                )
            ),
            provenance=self.memory.output_ref(event),
        )
        self.memory.retain(self.memory.output_ref(event), "graph:" + str(node.id))
        self.memory.finish_run(run)

    def bind_evaluation(
        self,
        program_id: int,
        dataset_revision: str,
        *,
        criteria: AcceptanceCriteria | None = None,
    ):
        """Developer API: fix independent acceptance cases before candidate development.

        Deliberately not an agent tool. Candidate-owned checks cannot certify
        their own code or redefine the protected acceptance criteria.
        """
        self._program(program_id, allow_inactive=True)
        dataset = self.datasets.get(dataset_revision)
        if dataset.purpose != "evaluation" or not dataset.cases:
            raise ValueError("Acceptance needs a nonempty evaluation dataset")
        criteria = criteria or AcceptanceCriteria(
            required_checks=("contracts", "tests", "holdout"),
            target_metric="accuracy",
            threshold=1.0,
        )
        if (
            not {"contracts", "tests", "holdout"}.issubset(criteria.required_checks)
            or not criteria.require_independent
        ):
            raise ValueError("Independent holdout, contracts and tests are mandatory core checks")
        metrics = set(dataset.target_metrics or ("accuracy",))
        required_metrics = {guardrail.metric for guardrail in criteria.guardrails}
        if criteria.target_metric:
            required_metrics.add(criteria.target_metric)
        if required_metrics - metrics:
            raise ValueError("Acceptance metrics must be fixed in the evaluation dataset")
        for case in dataset.cases:
            for reference in case.source_refs:
                self.memory.resolve(reference)
        for case in dataset.cases:
            for reference in case.source_refs:
                self.memory.retain(reference, "dataset:" + dataset_revision)
        self._evaluation_bindings[str(program_id)] = {
            "dataset_revision": dataset_revision,
            "criteria": dataclasses.asdict(criteria),
        }

    async def evaluate_candidate(self, candidate_id: str, *, task_id: str):
        from ..core.programs.experiments import evaluate_pair

        candidate = self.lifecycle.candidate(candidate_id)
        binding = self._evaluation_bindings.get(str(candidate.program_id))
        if binding is None:
            return {
                "status": "unresolved",
                "reason": "No independent evaluation dataset is bound to this Program",
            }
        dataset = self.datasets.require_holdout(candidate_id, binding["dataset_revision"])
        program = self._program(candidate.program_id, allow_inactive=True)

        async def evaluate(branch, revision):
            async def model_call(payload, context):
                return await self._invoke(
                    task_id,
                    AgentRequest(
                        payload["prompt"],
                        context.workspace,
                        instructions=payload.get("instructions", ""),
                        mode="model",
                        output_schema=payload.get("output_schema"),
                        timeout_seconds=self._remaining_seconds(self.tasks.get(task_id)),
                    ),
                )

            experiment = await evaluate_pair(
                branch,
                revision,
                program,
                dataset,
                self.state_dir / "evaluations",
                self.repository,
                self.graph,
                self.memory,
                self.learning,
                self._program,
                runtime_factory=self._runtime_factory,
                model_call=model_call,
                observation_ids=frozenset(self._observations),
                beliefs=self.beliefs,
                attribution=self.attribution,
                evaluations=self.evaluations,
                protected_nodes=frozenset(self._protected_nodes),
                timeout=self._remaining_seconds(self.tasks.get(task_id)),
            )
            trace_run = self.memory.start_run(
                "CandidateEvaluation", revision, {"candidate": branch.id}
            )
            event = self.memory.record(
                trace_run,
                "evaluation",
                output={"traces": experiment.traces, "report": json_value(experiment.report)},
            )
            self.memory.retain(event.id, "evaluation:" + branch.id)
            self.memory.finish_run(trace_run)
            return dataclasses.replace(experiment.report, trace_ids=(str(event.id),))

        try:
            result = await self.lifecycle.evaluate(candidate_id, evaluate)
            return {"status": "evaluated", **dataclasses.asdict(result)}
        finally:
            self.datasets.mark_exposed(candidate_id, dataset.revision)
            self.datasets.mark_exposed("program:" + str(candidate.program_id), dataset.revision)
