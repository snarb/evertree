"""Core-owned comparison of committed Programs against a fixed holdout.

The caller must obtain the dataset through DatasetStore.require_holdout before
calling this service. Labels and evaluation rules remain in core; workers get
only case inputs. Every side starts from the same independent state snapshot.
"""

from __future__ import annotations

import inspect
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from .attribution import AttributionRuntime
from .backup import _restore_io, safe_remove_tree
from .beliefs import BeliefStore
from .datasets import DatasetRevision, content_revision, thaw_json, validate_holdout
from .evaluation import EvaluationStore, evaluate_prediction, exact_json_equal
from .graph import GraphStore, json_value
from .learning import (
    LearningStore,
)
from .lifecycle import EvaluationReport, ProgramBranch
from .memory import TraceStore
from .operations import CoreOperations, authorize_operation
from .program_tests import run_candidate_tests
from .runtime import ProgramExecutionError, ProgramSpec, Runtime, _git
from .serialization import decode_snapshot, encode_snapshot


@dataclass(frozen=True)
class ExperimentContext:
    graph: GraphStore
    memory: TraceStore
    learning: LearningStore
    workspace: Path
    revision: str
    label: str
    beliefs: BeliefStore


@dataclass(frozen=True)
class EvaluationExperiment:
    report: EvaluationReport
    traces: tuple[dict[str, Any], ...]


def _compile_changed(repository: Path, base: str, revision: str) -> list[dict[str, str]]:
    """Compile changed Python without importing or executing candidate code."""
    paths = _git(repository, "diff", "--name-only", "--diff-filter=ACMR", "-z", base, revision)
    errors = []
    for path in paths.decode("utf-8").split("\0"):
        if not path.endswith(".py"):
            continue
        try:
            compile(_git(repository, "show", f"{revision}:{path}"), path, "exec")
        except (SyntaxError, ValueError, ProgramExecutionError) as error:
            errors.append({"path": path, "error": str(error)})
    return errors


async def evaluate_pair(
    branch: ProgramBranch,
    revision: str,
    program: ProgramSpec,
    dataset: DatasetRevision,
    root: Path,
    repository: Path,
    graph: GraphStore,
    memory: TraceStore,
    learning: LearningStore,
    resolve_program,
    *,
    runtime_factory=Runtime,
    test_process_factory=None,
    model_call=None,
    observation_ids: frozenset[int] = frozenset(),
    timeout: float = 300,
    beliefs: BeliefStore | None = None,
    attribution: AttributionRuntime | None = None,
    evaluations: EvaluationStore | None = None,
    protected_nodes: frozenset[int] = frozenset(),
) -> EvaluationExperiment:
    """Run a holdout without giving Programs labels, live state, or live effects.

    ``model_call(payload, context)`` is a trusted optional adapter. It must use
    the isolated context workspace, no live tools, and model mode. The service
    forces model mode and does not pass evaluation outcomes to this adapter.
    ``runtime_factory`` is an injection point for deterministic runtime tests;
    production callers use Runtime, which requires the native OS sandbox.
    """
    validate_holdout(dataset)
    rules = {case.evaluation_rule for case in dataset.cases}
    if rules not in ({"exact"}, {"prediction"}):
        raise ValueError("Use one fixed evaluation rule per dataset: exact or prediction")
    requested_metrics = dataset.target_metrics or ("accuracy",)
    supported = (
        {"accuracy"}
        if rules == {"exact"}
        else {
            "brier",
            "squared_error",
            "mse",
            "absolute_error",
            "mae",
            "residual",
            "log_loss",
            "exact_match",
        }
    )
    if set(requested_metrics) - supported:
        raise ValueError("Dataset requests metrics unsupported by its evaluation rule")
    if program.program_id != branch.program_id:
        raise ValueError("Evaluation Program does not match candidate identity")
    # A case source already accessible through initial memory compromises the
    # holdout even when its outcome is hidden from the case inputs.
    heldout_sources = {source for case in dataset.cases for source in case.source_ids}
    memory_sources = {str(event.id) for event in memory.events}
    memory_sources.update(
        event.arguments["source_id"]
        for event in memory.events
        if isinstance(event.arguments, Mapping)
        and isinstance(event.arguments.get("source_id"), str)
    )
    if heldout_sources & memory_sources:
        raise ValueError("Evaluation sources are already accessible in initial memory")
    root = Path(root).resolve() / uuid4().hex
    root.mkdir(parents=True)
    try:
        beliefs = beliefs if beliefs is not None else BeliefStore()
        attribution = attribution if attribution is not None else AttributionRuntime(graph, beliefs)
        evaluations = evaluations if evaluations is not None else EvaluationStore()
        snapshots = {
            "graph": graph.snapshot(),
            "memory": memory.snapshot(),
            "learning": learning.snapshot(),
            "beliefs": beliefs.snapshot(),
            "attribution": attribution.snapshot(),
            "evaluations": evaluations.snapshot(),
        }
        # A serialization round trip rejects incidental shared mutable references.
        encoded = encode_snapshot(snapshots)
        snapshots = decode_snapshot(encoded)
        # Freeze the executable registry before either side runs. A callback into
        # the live application is never consulted while an experiment is executing.
        initial_graph = GraphStore.from_snapshot(snapshots["graph"])
        registry = {program.program_id: program}
        for node in initial_graph.nodes(kind="program"):
            if node.id == program.program_id:
                resolved = program
            elif node.properties.get("active", True):
                resolved = resolve_program(node.id)
                if inspect.isawaitable(resolved):
                    resolved = await resolved
                if not isinstance(resolved, ProgramSpec):
                    resolved = ProgramSpec(**resolved)
                if (
                    resolved.program_id != node.id
                    or resolved.git_path != node.properties["git_path"]
                ):
                    raise ValueError("Program registry changed while preparing the experiment")
            else:
                continue
            for key in (node.id, node.name, node.properties.get("slug")):
                if key is not None:
                    registry[key] = resolved
        for node in initial_graph.nodes():
            if node.properties.get("process") is True:
                active = node.properties.get("active_exec", node.properties.get("active_model"))
                if active in registry:
                    registry[node.id] = registry[node.name] = registry[active]
        candidate_repository = Path(branch.workspace)
        syntax_errors = _compile_changed(candidate_repository, branch.base_revision, revision)
        traces: list[dict[str, Any]] = [
            {"kind": "static_checks", "revision": revision, "errors": syntax_errors}
        ]
        test_outcome = await run_candidate_tests(
            candidate_repository,
            revision,
            root / "candidate-tests",
            process_factory=test_process_factory,
            timeout=timeout,
        )
        traces.append(test_outcome)
        try:
            _git(Path(repository), "cat-file", "-e", f"{branch.base_revision}:{program.git_path}")
            has_baseline = True
        except ProgramExecutionError:
            has_baseline = False
        metrics = {}
        valid = {}
        for label, source, commit in (
            ("baseline", Path(repository), branch.base_revision),
            ("candidate", candidate_repository, revision),
        ):
            if label == "baseline" and not has_baseline:
                traces.append(
                    {"kind": "baseline_absent", "revision": commit, "program": program.program_id}
                )
                continue
            side = root / label
            side.mkdir()
            side_beliefs = BeliefStore.from_snapshot(snapshots["beliefs"])
            context = ExperimentContext(
                GraphStore.from_snapshot(snapshots["graph"]),
                TraceStore.from_snapshot(snapshots["memory"]),
                LearningStore.from_snapshot(snapshots["learning"]),
                side / "model-workspace",
                commit,
                label,
                side_beliefs,
            )
            context.graph.belief_reader = side_beliefs.read
            context.workspace.mkdir()
            operations = CoreOperations(
                context.graph,
                context.memory,
                side_beliefs,
                AttributionRuntime.from_snapshot(
                    snapshots["attribution"], context.graph, side_beliefs
                ),
                EvaluationStore.from_snapshot(snapshots["evaluations"]),
                context.learning,
                observation_ids,
                protected_nodes,
            )
            run_map: dict[str, int] = {}
            side_events: list[dict[str, Any]] = []

            async def record(event, *, context=context, run_map=run_map, events=side_events):
                events.append(json.loads(json.dumps(event, allow_nan=False)))
                kind, identity = event["type"], event.get("run_id")
                if kind == "run_started":
                    parent = run_map.get(event.get("parent_run_id"))
                    caller = (
                        context.memory.record(parent, "call_program", output={"run_id": identity})
                        if parent
                        else None
                    )
                    spec = event["program"]
                    run = context.memory.start_run(
                        spec["program_id"],
                        spec["revision"],
                        event["arguments"],
                        run_mode="evaluation",
                        caller_event=caller,
                    )
                    run_map[identity] = run.id
                elif identity in run_map:
                    run = run_map[identity]
                    context.memory.record(
                        run,
                        event.get("operator", kind),
                        event.get("arguments"),
                        event.get("output", event.get("result", event.get("error"))),
                        status=event.get("status", "completed"),
                    )
                    if kind in {"run_finished", "run_failed"}:
                        context.memory.finish_run(
                            run, status="completed" if kind == "run_finished" else "failed"
                        )

            async def gateway(method, payload, *, context=context, operations=operations):
                payload = dict(payload)
                metadata = payload.pop("_runtime")
                # The default ready-model protocol must not train on held-out cases.
                if method in {"learning.learn", "learning.coordinate"}:
                    raise PermissionError("Learning is disabled during ready-model evaluation")
                authorize_operation(method, metadata["program"]["role"])
                if method == "resolve_program":
                    resolved = registry[payload["program_id"]]
                    return asdict(replace(resolved, revision=context.revision))
                if method == "agent.run":
                    if model_call is None:
                        raise PermissionError("No isolated model adapter was supplied")
                    payload["mode"] = "model"
                    return json_value(await model_call(payload, context))
                return operations.execute(method, payload, metadata=metadata)

            runtime = runtime_factory(side / "runtime", source, gateway, record)
            totals = {metric: 0.0 for metric in requested_metrics}
            measured = {metric: 0 for metric in requested_metrics}
            all_valid = True
            try:
                for case in dataset.cases:
                    start_event = len(side_events)
                    audit = {
                        "kind": "case",
                        "side": label,
                        "revision": commit,
                        "case": case.id,
                        "dataset_revision": dataset.revision,
                        "inputs": case.program_inputs(),
                    }
                    try:
                        outcome = await runtime.execute(
                            "evaluation-" + uuid4().hex,
                            replace(program, revision=commit),
                            case.program_inputs(),
                            run_mode="evaluation",
                            timeout=timeout,
                        )
                        audit["result"] = outcome.result
                        audit["feedback"] = outcome.feedback
                        if case.evaluation_rule == "exact":
                            audit["correct"] = exact_json_equal(
                                outcome.result, thaw_json(case.outcomes)
                            )
                            samples = {"accuracy": float(audit["correct"])}
                        else:
                            evaluation = evaluate_prediction(
                                outcome.result,
                                thaw_json(case.outcomes),
                                metrics=requested_metrics,
                                outcome_ids=(case.revision,),
                                provenance=case.source_ids,
                                subject=f"{program.program_id}:{commit}",
                                comparison_key=dataset.revision,
                            )
                            audit["evaluation"] = evaluation.to_dict()
                            samples = evaluation.metrics()
                        for metric, value in samples.items():
                            if (
                                isinstance(value, (float, int))
                                and not isinstance(value, bool)
                                and math.isfinite(value)
                            ):
                                totals[metric] += value * case.weight
                                measured[metric] += 1
                    except Exception as error:  # noqa: BLE001 -- failed Programs are evaluation evidence
                        all_valid = False
                        audit["error"] = f"{type(error).__name__}: {error}"
                        audit["correct"] = False
                        if case.evaluation_rule == "exact":
                            measured["accuracy"] += 1
                    audit["events"] = side_events[start_event:]
                    traces.append(audit)
            finally:
                await runtime.close()
            # A partial or infinite score cannot silently become a better mean.
            # Missing required metrics block acceptance in the protected policy.
            metrics[label] = {
                metric: value / sum(case.weight for case in dataset.cases)
                for metric, value in totals.items()
                if measured[metric] == len(dataset.cases)
            }
            valid[label] = all_valid
        report = EvaluationReport(
            revision,
            dataset.revision,
            {
                "contracts": valid["candidate"],
                "tests": not syntax_errors and test_outcome["passed"],
                "holdout": True,
            },
            metrics["candidate"],
            True,
            tuple(sorted({source for case in dataset.cases for source in case.source_ids})),
            tuple(content_revision(trace) for trace in traces),
            baseline_metrics=metrics.get("baseline"),
        )
        return EvaluationExperiment(report, tuple(traces))
    finally:
        await _restore_io(safe_remove_tree, root, root.parent)
