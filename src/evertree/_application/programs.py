"""Program lookup, execution, traces and the candidate lifecycle shared by tools and meta Programs."""

from __future__ import annotations

import dataclasses
import io
import json
import re
import zipfile
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from evertree.core.evaluation.acceptance import (
    META_MIN_CASES,
    AcceptanceCriteria,
    MetricGuardrail,
    meta_criteria,
)
from evertree.core.graph.types import GraphDelta, Node, NodeUpdate, Prototype
from evertree.core.runtime.controller import ProgramSpec
from evertree.core.runtime.repository import ProgramFailed, _git

from ..core.anchors import AnchorResolver, parse_anchors
from ..core.datasets import EvaluationCase, thaw_json, validate_holdout
from ..core.learning.declaration import read_learning
from ..core.memory.types import TraceOutputRef
from ..core.predictions import ensure_target
from ..core.programs.design import check_design, design_profile
from ..core.programs.layout import (
    process_directory,
    process_slug,
    program_active,
    validate_process_layout,
)
from ..core.programs.lifecycle import LifecycleError, ProgramLifecycleRuntime, git
from ..core.provider import LLMRequest, ToolDefinition
from ..core.values import json_value
from .integration import EVIDENCE_ASSESSMENT_SLUGS
from .prompts import candidate_instructions

ACTIVATING = {"merge_branch", "activate_program"}


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
            if branch is not None:
                self._validate_design(branch, revision, sources)

    def _validate_design(self, branch, revision, sources):
        """Require the design profile of a policy or meta Program whose entry module changed."""
        node = self.graph.get(int(branch.program_id))
        binding = self._binding(node.id)
        policy = bool(
            binding
            and self.datasets.get(binding["dataset_revision"]).cases[0].evaluation_rule == "policy"
        )
        profile = design_profile(meta=self._is_meta(node.id), policy=policy)
        path = node.properties["git_path"]
        changed = git(
            Path(branch.workspace),
            "diff",
            "--name-only",
            branch.base_revision,
            revision,
            "--",
            path,
        )
        if profile is not None and changed:
            check_design(sources.read(path).decode("utf-8"), path, profile)

    def _install_seed_learning(self):
        """Bind the declared estimators of the seed's active Programs."""
        for node in self.graph.nodes(kind="program"):
            if program_active(node):
                self._install_learning(
                    node, self._program_source(dict(node.properties)), node.properties["revision"]
                )

    def _install_learning(self, node, source, revision):
        """Bind an active Program's declared estimators and create its declared targets."""
        path = node.properties["git_path"]
        declaration = read_learning(source, path)
        if declaration is None:
            self.learning.release(str(node.id))
            return
        declaration.check_role(node.properties["role"])
        for name in declaration.targets:
            ensure_target(
                self.graph, self.memory, node.properties["process"], name, revision=revision
            )
        self.learning.install(str(node.id), declaration)

    def _slot(self, program_id) -> str:
        """Name the process role a Program competes for; alternatives and branches share it."""
        node = self.graph.get(int(program_id))
        return f"slot:{node.properties['process']}:{node.properties['role']}"

    def _binding(self, program_id):
        return self._evaluation_bindings.get(self._slot(program_id))

    def _is_meta(self, program_id) -> bool:
        return "meta" in self.graph.get(int(program_id)).properties.get("roles", ())

    def _acceptance_criteria(self, candidate):
        binding = self._binding(candidate.program_id)
        if binding is None:
            raise ValueError("No independent evaluation is bound to this Program")
        values = dict(binding["criteria"])
        values["guardrails"] = tuple(MetricGuardrail(**item) for item in values["guardrails"])
        criteria = AcceptanceCriteria(**values)
        return meta_criteria(criteria) if self._is_meta(candidate.program_id) else criteria

    def _program_revision(self):
        return git(self.repository, "rev-parse", "main")

    def _program_source(self, spec):
        return _git(self.repository, "show", f"{spec['revision']}:{spec['git_path']}").decode(
            "utf-8"
        )

    def _program(self, identity: int | str, *, allow_inactive=False) -> ProgramSpec:
        """Resolve a Program or active process role into a spec pinned to the current repository revision."""
        node = self.graph.get(identity) if isinstance(identity, int) else self.graph.find(identity)
        if node is None and isinstance(identity, str):
            # Alternatives share their slot's slug; the active one answers to it.
            matches = [
                item
                for item in self.graph.nodes(kind="program")
                if item.properties.get("slug") == identity
            ]
            node = next((item for item in matches if program_active(item)), None) or next(
                iter(matches), None
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
        if not program_active(node) and not allow_inactive:
            raise PermissionError("Program has not passed activation")
        return ProgramSpec(
            node.id,
            node.properties["git_path"],
            self._program_revision(),
            node.properties.get("entrypoint", "run"),
            node.properties["role"],
            "meta" in node.properties.get("roles", ()),
        )

    def programs(self):
        """List graph-registered Programs as serializable records."""
        return [json_value(node) for node in self.graph.nodes(kind="program")]

    def _lifecycle_event(self, name, output):
        """Record a lifecycle decision as trace provenance for the graph change it causes."""
        run = self.memory.start_run("ProgramLifecycle", self._program_revision(), {"name": name})
        event = self.memory.record(run, name, output=output)
        self.memory.finish_run(run)
        return self.memory.output_ref(event)

    def propose_program(
        self,
        name: str,
        *,
        role: str,
        claim: str,
        description="",
        candidate_name: str | None = None,
        parent: int | str | None = None,
        alternative_to: int | None = None,
        meta: bool = False,
    ):
        """Propose a role for a process, a new subtype of parent, or an alternative Program.

        An alternative competes for an occupied slot with a different solution
        principle. It shares the slot's source path; its code lives on its own branch
        until an EvaluationChoice activates it.
        """
        if role not in {"exec", "model"} or not name.isidentifier():
            raise ValueError("A Program requires an identifier name and model/exec role")
        if meta and role != "exec":
            raise ValueError("Only an exec Program can have the meta role")
        process = self.graph.find(name)
        creates = []
        slug = process_slug(name)
        program_name = name + "." + role
        roles = (role, "meta") if meta else (role,)
        extra = {}
        if process is not None:
            if parent is not None:
                raise ValueError("parent is only used when creating a new process")
            if process.properties.get("process") is not True:
                raise ValueError("The existing name must identify a process in Self/Process")
            directory = process_directory(self.graph, process.id).rstrip("/")
            git_path = f"{directory}/_{role}.py"
            occupants = [
                node
                for node in self.graph.nodes(kind="program")
                if node.properties.get("process") == process.id
                and node.properties.get("role") == role
            ]
            if occupants and alternative_to is None:
                raise ValueError(
                    "Process already has this Program role; use create_candidate to change it, "
                    "or alternative_to for a different solution principle"
                )
            if occupants:
                target = next((node for node in occupants if node.id == int(alternative_to)), None)
                if target is None:
                    raise ValueError("alternative_to must name a Program in the same process role")
                words = re.findall(r"[^\W_]+", (candidate_name or claim).casefold())[:3]
                program_name = f"{program_name}.{'_'.join(words)}"
                git_path = target.properties["git_path"]
                roles = tuple(target.properties.get("roles", (role,)))
                extra = {"alternative_to": target.id}
        else:
            if alternative_to is not None:
                raise ValueError("alternative_to requires an existing process")
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
            git_path = f"{directory}/_{role}.py"
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
        if self.graph.find(program_name):
            raise ValueError("Program name is already registered")
        run = self.memory.start_run("ProgramProposal", self._program_revision(), {"name": name})
        event = self.memory.record(
            run, "propose_program", output={"claim": claim, "description": description}
        )
        program = Node(
            self.graph.reserve_id(),
            program_name,
            kind="program",
            description=description,
            properties={
                "git_path": git_path,
                "process": process.id,
                "role": role,
                "roles": roles,
                "slug": slug,
                "lifecycle_status": "candidate",
                "entrypoint": "run",
                **extra,
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
        self.datasets.inherit_exposure(self._slot(program.id), candidate.id)
        if self._current_task:
            self._candidate_owners[candidate.id] = self._current_task
        return {"program": json_value(program), "candidate": dataclasses.asdict(candidate)}

    async def _run_program(self, *args, **kwargs):
        """Run within the application's exclusive execution chain."""
        with self._execution.enter():
            return await self._run_program_owned(*args, **kwargs)

    async def _run_program_owned(self, task_id, identity, arguments, *, timeout=None):
        """Execute or recover the task's pinned pending ProgramRun while metering resource use."""
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
        except ProgramFailed:
            # A finished failure is not resumable work; it must not block the task's next run.
            self._pending_programs.pop(task_id, None)
            raise
        finally:
            self._operations -= 1

    async def _runtime_trace(self, event):
        """Translate worker lifecycle notifications into semantic runs, outputs and task provenance."""
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
                if kind == "run_finished":
                    product = event.get("result", {}).get("result")
                    slug = self.graph.get(run.program).properties.get("slug")
                    if (
                        isinstance(product, dict)
                        and "analysis" in product
                        and slug
                        not in {
                            "knowledge_integration",
                            "task_framing",
                            "resource_control",
                            "semantic_search",
                            *EVIDENCE_ASSESSMENT_SLUGS,
                        }
                    ):
                        for note in [product["analysis"], *product.get("findings", [])]:
                            self._record_analysis(
                                event["task_id"],
                                note,
                                producer=run.program,
                                revision=run.base_commit_sha,
                                owner_run=run.id,
                            )

    def _activated(self, branch, revision):
        """Record accepted Program activation and move the process role binding with provenance.

        An activated alternative displaces the slot's previous Program, which stays
        a candidate with its last revision so a later choice can reactivate it.
        """
        self._validate_program_layout(branch, revision)
        node = self.graph.get(int(branch.program_id))
        role = node.properties["role"]
        process = self.graph.get(node.properties["process"])
        displaced = process.properties.get("active_" + role)
        run = self.memory.start_run("EvaluationChoice", revision, {"candidate": branch.id})
        event = self.memory.record(
            run,
            "activate_program",
            output={"program": node.id, "revision": revision, "displaced": displaced},
        )
        updates = [
            NodeUpdate(
                node.id,
                {
                    "properties": {
                        **node.properties,
                        "revision": revision,
                        "lifecycle_status": "active",
                    }
                },
            ),
            NodeUpdate(
                process.id,
                {"properties": {**process.properties, "active_" + role: node.id}},
            ),
        ]
        if displaced is not None and displaced != node.id:
            previous = self.graph.get(displaced)
            updates.append(
                NodeUpdate(
                    previous.id,
                    {"properties": {**previous.properties, "lifecycle_status": "candidate"}},
                )
            )
        self.graph.apply(
            GraphDelta(updates=tuple(updates)), provenance=self.memory.output_ref(event)
        )
        self.memory.retain(self.memory.output_ref(event), "graph:" + str(node.id))
        self.memory.finish_run(run)
        if displaced is not None and displaced != node.id:
            self.learning.release(str(displaced))
        self._install_learning(
            node, self._program_source({**node.properties, "revision": revision}), revision
        )

    def bind_evaluation(
        self,
        program_id: int,
        dataset_revision: str,
        *,
        criteria: AcceptanceCriteria | None = None,
        history_dataset_revision: str | None = None,
    ):
        """Developer API: fix independent acceptance cases for a Program's slot before development.

        Deliberately not an agent tool. Candidate-owned checks cannot certify
        their own code or redefine the protected acceptance criteria. Every branch
        and alternative of the slot meets the same holdout. A meta Program also
        needs a history dataset of past lifecycle situations on which it must not regress.
        """
        self._program(program_id, allow_inactive=True)
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
        revisions = [dataset_revision]
        if self._is_meta(program_id):
            if history_dataset_revision is None:
                raise ValueError("A meta Program needs a history dataset of past improvements")
            revisions.append(history_dataset_revision)
        elif history_dataset_revision is not None:
            raise ValueError("Only a meta Program is checked against an improvement history")
        required_metrics = {guardrail.metric for guardrail in criteria.guardrails}
        if criteria.target_metric:
            required_metrics.add(criteria.target_metric)
        for revision in revisions:
            dataset = self.datasets.get(revision)
            if dataset.purpose != "evaluation" or not dataset.cases:
                raise ValueError("Acceptance needs a nonempty evaluation dataset")
            if len(revisions) > 1 and len(dataset.cases) < META_MIN_CASES:
                raise ValueError(
                    f"A meta Program needs at least {META_MIN_CASES} cases per dataset"
                )
            if required_metrics - set(dataset.target_metrics or ("accuracy",)):
                raise ValueError("Acceptance metrics must be fixed in the evaluation dataset")
            for case in dataset.cases:
                for reference in case.source_refs:
                    self.memory.resolve(reference)
        for revision in revisions:
            for case in self.datasets.get(revision).cases:
                for reference in case.source_refs:
                    self.memory.retain(reference, "dataset:" + revision)
        self._evaluation_bindings[self._slot(program_id)] = {
            "dataset_revision": dataset_revision,
            "history_dataset_revision": history_dataset_revision,
            "criteria": dataclasses.asdict(criteria),
        }

    def _own(self, task_id, candidate_id):
        if task_id:
            self._candidate_owners[candidate_id] = task_id

    def create_candidate(self, task_id, program, claim, *, candidate_name=None):
        """Open a candidate branch of an existing Program in the slot's holdout lineage."""
        spec = self._program(program, allow_inactive=True)
        candidate = self.lifecycle.create_candidate(
            spec.program_id, claim, candidate_name=candidate_name
        )
        self._own(task_id, candidate.id)
        self.datasets.inherit_exposure(self._slot(spec.program_id), candidate.id)
        return dataclasses.asdict(candidate)

    async def develop_candidate(self, task_id, candidate_id, instruction):
        """Let the coding provider change the candidate checkout, then commit and retain it."""
        candidate = self.lifecycle.candidate(candidate_id)
        if candidate.status != "active":
            raise LifecycleError("Candidate is not open; refresh it first")
        workspace = Path(candidate.workspace)
        node = self.graph.get(int(candidate.program_id))
        binding = self._binding(candidate.program_id)
        evaluation = None
        if binding:
            dataset = self.datasets.get(binding["dataset_revision"])
            # The contract of the protected evaluation, never its cases or labels.
            evaluation = {
                "rule": dataset.cases[0].evaluation_rule,
                "metrics": list(dataset.target_metrics or ("accuracy",)),
                "input_keys": sorted({key for case in dataset.cases for key in case.inputs}),
            }
        result = await self._invoke(
            task_id,
            LLMRequest(
                json.dumps(
                    {
                        "instruction": instruction,
                        "candidate": dataclasses.asdict(candidate),
                        "program": json_value(node),
                        "evaluation": evaluation,
                    },
                    ensure_ascii=False,
                ),
                workspace,
                mode="exec",
                native_coding=True,
                instructions=candidate_instructions(node.properties, evaluation),
                timeout_seconds=self._remaining_seconds(self.tasks.get(task_id)),
            ),
        )
        if git(workspace, "status", "--porcelain"):
            git(workspace, "add", "--all")
            git(workspace, "commit", "-m", candidate.change_claim)
        self.lifecycle.retain_candidate(candidate.id)
        return {
            "candidate": candidate.id,
            "revision": git(workspace, "rev-parse", "HEAD"),
            "result": result["text"],
        }

    def _holdout(self, candidate_id, revision):
        """Require independence, except for an unchanged refreshed change meeting its holdout again."""
        if self.lifecycle.recertifiable(candidate_id, revision):
            dataset = self.datasets.get(revision)
            validate_holdout(dataset)
            return dataset
        return self.datasets.require_holdout(candidate_id, revision)

    async def evaluate_candidate(self, candidate_id: str, *, task_id: str):
        """Compare a candidate with its baseline on the slot's protected independent dataset.

        A meta Program's candidate is also compared on the improvement history;
        those metrics carry a history: prefix and feed the fixed meta guardrail.
        """
        from ..core.programs.experiments import evaluate_pair

        candidate = self.lifecycle.candidate(candidate_id)
        binding = self._binding(candidate.program_id)
        if binding is None:
            return {
                "status": "unresolved",
                "reason": "No independent evaluation dataset is bound to this Program",
            }
        datasets = [self._holdout(candidate_id, binding["dataset_revision"])]
        if self._is_meta(candidate.program_id):
            datasets.append(self._holdout(candidate_id, binding["history_dataset_revision"]))
        program = self._program(candidate.program_id, allow_inactive=True)

        async def model_call(payload, context):
            if payload.get("tools") and not callable(payload.get("_tool_handler")):
                raise PermissionError("Evaluation tools require a scoped runtime handler")
            profile_name = payload.get("profile")
            if profile_name not in {None, "remember"}:
                raise ValueError("Unknown model profile")
            profile = getattr(self.semantic_config, profile_name) if profile_name else None
            return await self._invoke(
                task_id,
                LLMRequest(
                    payload["prompt"],
                    context.workspace,
                    model=profile.model if profile else None,
                    effort=profile.effort if profile else None,
                    instructions=payload.get("instructions", ""),
                    mode=payload.get("mode", "model"),
                    tools=tuple(ToolDefinition(**tool) for tool in payload.get("tools", [])),
                    output_schema=payload.get("output_schema"),
                    timeout_seconds=self._remaining_seconds(self.tasks.get(task_id)),
                ),
                tool_handler=payload.get("_tool_handler"),
            )

        # A candidate that returned no result on any case learned nothing about the labels.
        unrevealed = set()

        async def evaluate(branch, revision):
            reports, traces = [], []
            for dataset in datasets:
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
                    semantic_config=self.semantic_config,
                    observation_ids=frozenset(self._observations),
                    beliefs=self.beliefs,
                    attribution=self.attribution,
                    evaluations=self.evaluations,
                    protected_nodes=frozenset(self._protected_nodes),
                    sealed=frozenset(self.memory.sealed),
                    timeout=self._remaining_seconds(self.tasks.get(task_id)),
                )
                reports.append(experiment.report)
                traces.extend(experiment.traces)
                cases = [
                    trace
                    for trace in experiment.traces
                    if trace.get("kind") == "case" and trace.get("side") == "candidate"
                ]
                if cases and all("error" in trace for trace in cases):
                    unrevealed.add(dataset.revision)
            trace_run = self.memory.start_run(
                "CandidateEvaluation", revision, {"candidate": branch.id}
            )
            event = self.memory.record(
                trace_run,
                "evaluation",
                output={"traces": traces, "reports": [json_value(item) for item in reports]},
            )
            self.memory.retain(event.id, "evaluation:" + branch.id)
            self.memory.finish_run(trace_run)
            report = reports[0]
            if len(reports) > 1:
                history = reports[1]
                report = dataclasses.replace(
                    report,
                    checks={**report.checks, "improvement_history": history.checks["contracts"]},
                    metrics={
                        **report.metrics,
                        **{"history:" + key: value for key, value in history.metrics.items()},
                    },
                    baseline_metrics=None
                    if report.baseline_metrics is None
                    else {
                        **report.baseline_metrics,
                        **{
                            "history:" + key: value
                            for key, value in (history.baseline_metrics or {}).items()
                        },
                    },
                    source_ids=tuple(sorted({*report.source_ids, *history.source_ids})),
                )
            return dataclasses.replace(report, trace_ids=(str(event.id),))

        try:
            result = await self.lifecycle.evaluate(candidate_id, evaluate)
            receipt = self.lifecycle.receipt(candidate_id)
            return {
                "status": "evaluated",
                **dataclasses.asdict(result),
                "verification": receipt["verification"],
            }
        finally:
            for dataset in datasets:
                if dataset.revision in unrevealed:
                    continue
                self.datasets.mark_exposed(candidate_id, dataset.revision)
                self.datasets.mark_exposed(self._slot(candidate.program_id), dataset.revision)

    def compare_candidates(self, candidate_ids):
        """Rank evaluated candidates of one slot on its fixed target metric and holdout."""
        rows, keys = [], set()
        for identity in dict.fromkeys(candidate_ids):
            candidate = self.lifecycle.candidate(identity)
            receipt = self.lifecycle.receipt(identity)
            if receipt is None:
                raise ValueError(f"Candidate {identity} has no evaluation of its current revision")
            keys.add((self._slot(candidate.program_id), receipt["report"]["dataset_revision"]))
            rows.append((candidate, receipt))
        if len(keys) != 1:
            raise ValueError("Compare only candidates of one slot evaluated on the same holdout")
        criteria = self._acceptance_criteria(rows[0][0])
        metric, sign = criteria.target_metric, 1 if criteria.direction == "maximize" else -1

        def score(row):
            value = row[1]["report"]["metrics"].get(metric)
            return float("-inf") if value is None else sign * value

        ranking = [
            {
                "candidate": candidate.id,
                "program": candidate.program_id,
                "status": candidate.status,
                "base_revision": candidate.base_revision,
                "metrics": receipt["report"]["metrics"],
                "baseline_metrics": receipt["report"]["baseline_metrics"],
                "verification": receipt["verification"],
            }
            for candidate, receipt in sorted(rows, key=score, reverse=True)
        ]
        return {
            "dataset_revision": next(iter(keys))[1],
            "target_metric": metric,
            "direction": criteria.direction,
            "ranking": ranking,
        }

    def refresh_candidate(self, task_id, candidate_id):
        """Reopen a paused or stale candidate on the current main for further work or evaluation."""
        candidate = self.lifecycle.refresh_candidate(candidate_id)
        self._own(task_id, candidate.id)
        return dataclasses.asdict(candidate)

    def _dominating_sibling(self, candidate):
        """Find an undecided verified sibling that beats the candidate on the same holdout."""
        receipt = self.lifecycle.receipt(candidate.id)
        # A candidate that failed a mandatory check is refused for that reason first.
        if receipt is None or False in receipt["report"]["checks"].values():
            return None
        criteria = self._acceptance_criteria(candidate)
        metric, sign = criteria.target_metric, 1 if criteria.direction == "maximize" else -1
        own = receipt["report"]["metrics"].get(metric)
        if metric is None or own is None:
            return None
        slot = self._slot(candidate.program_id)
        for sibling in self.lifecycle.branches():
            other = self.lifecycle.receipt(sibling.id)
            if (
                sibling.id == candidate.id
                or sibling.status not in {"active", "paused"}
                or other is None
                or self._slot(sibling.program_id) != slot
                or other["report"]["dataset_revision"] != receipt["report"]["dataset_revision"]
                or other["verification"]["status"] != "verified"
            ):
                continue
            value = other["report"]["metrics"].get(metric)
            if value is not None and sign * (value - own) > 0:
                return sibling.id
        return None

    async def choose_candidate(self, task_id, candidate_id, decision, reason):
        """Record an EvaluationChoice; Core checks it against the candidate kind and its siblings."""
        candidate = self.lifecycle.candidate(candidate_id)
        node = self.graph.get(int(candidate.program_id))
        holds_slot = program_active(node)
        binding = self._binding(candidate.program_id)
        if decision in ACTIVATING:
            better = self._dominating_sibling(candidate)
            if better is not None:
                raise LifecycleError(
                    f"Verified candidate {better} is better on the same holdout; "
                    "choose it, or reject or archive it first"
                )
        revision = await self.lifecycle.choose(
            candidate_id,
            decision,
            reason=reason,
            expected_dataset_revision=binding["dataset_revision"] if binding else None,
            holds_slot=holds_slot,
        )
        status = {"reject_program": "rejected", "archive_program": "archived"}.get(decision)
        if status and not holds_slot:
            ref = self._lifecycle_event(decision, {"program": node.id, "reason": reason})
            self.graph.apply(
                GraphDelta(
                    updates=(
                        NodeUpdate(
                            node.id, {"properties": {**node.properties, "lifecycle_status": status}}
                        ),
                    )
                ),
                provenance=ref,
            )
            self.memory.retain(ref, "graph:" + str(node.id))
        return {"revision": revision, "decision": decision}

    def derive_holdout(self, program):
        """Extend a slot's holdout with outcomes of its live runs that no model has seen.

        An outcome is an observation recorded with outcome_of and no task. It is
        eligible only while it was never surfaced and nothing else uses it. Core
        seals eligible outcomes, keeps the bound cases the slot has not yet seen,
        and rebinds the slot under the same criteria. Only counts are returned.
        """
        spec = self._program(program, allow_inactive=True)
        slot = self._slot(spec.program_id)
        binding = self._evaluation_bindings.get(slot)
        if binding is None:
            raise ValueError("Bind a developer holdout first; derived cases share its criteria")
        base = self.datasets.get(binding["dataset_revision"])
        rule = base.cases[0].evaluation_rule
        members = {
            node.id for node in self.graph.nodes(kind="program") if self._slot(node.id) == slot
        }
        runs = {
            run.id: run
            for run in self.memory.runs
            if run.program in members and run.run_mode == "live" and run.status == "completed"
        }
        known = {case.id for case in base.cases}
        derived, excluded = [], 0
        for event in self.memory.events:
            arguments = event.arguments
            if (
                event.id not in self._observations
                or not isinstance(arguments, Mapping)
                or arguments.get("outcome_of") not in runs
                or f"experience:{event.id}" in known
            ):
                continue
            uses = self.memory.retention_reasons(event.id)
            if (
                event.id in self._surfaced
                or self.memory.get_run(event.program_run).arguments.get("task_id") is not None
                or any(not reason.startswith("observation:") for reason in uses)
                or len(self.memory.dependents_of(TraceOutputRef(event.id))) > 1
            ):
                excluded += 1
                continue
            derived.append(
                EvaluationCase(
                    f"experience:{event.id}",
                    thaw_json(runs[arguments["outcome_of"]].arguments),
                    json_value(event.output),
                    rule,
                    (f"trace:{event.id}",),
                )
            )
        if not derived:
            return {"dataset_revision": base.revision, "derived": 0, "excluded": excluded}
        self.memory.seal(int(case.id.removeprefix("experience:")) for case in derived)
        unseen = self.datasets.independent_cases(slot, base.revision)
        dataset = self.datasets.create(
            base.name,
            (*unseen, *derived),
            dataset_id=base.dataset_id,
            target_metrics=base.target_metrics,
            description=base.description,
        )
        self._evaluation_bindings[slot] = {**binding, "dataset_revision": dataset.revision}
        return {"dataset_revision": dataset.revision, "derived": len(derived), "excluded": excluded}
