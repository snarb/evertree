"""Core-owned comparison of committed Programs against a fixed holdout.

The caller must obtain the dataset through DatasetStore.require_holdout before
calling this service. Labels and evaluation rules remain in core; workers get
only case inputs. Every side starts from the same independent state snapshot.
"""

from __future__ import annotations

import inspect
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from .datasets import DatasetRevision, content_revision, thaw_json
from .evaluation import EvaluationStore, evaluate_prediction, exact_json_equal
from .graph import GraphDelta, GraphStore, json_value
from .learning import (
    CreditAssignmentProgram,
    LearningCoordinator,
    LearningCredit,
    LearningObjective,
    LearningSignal,
    LearningStore,
    UpdatePlanner,
)
from .lifecycle import EvaluationReport, ProgramBranch
from .memory import TraceOutputRef, TraceStore
from .predictions import PredictionEvaluator, protect_prediction_delta
from .runtime import ProgramExecutionError, ProgramSpec, Runtime, _git


@dataclass(frozen=True)
class ExperimentContext:
    graph: GraphStore
    memory: TraceStore
    learning: LearningStore
    workspace: Path
    revision: str
    label: str


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
    model_call=None,
    observation_ids: frozenset[int] = frozenset(),
    timeout: float = 300,
) -> EvaluationExperiment:
    """Run a holdout without giving Programs labels, live state, or live effects.

    ``model_call(payload, context)`` is a trusted optional adapter. It must use
    the isolated context workspace, no live tools, and model mode. The service
    forces model mode and does not pass evaluation outcomes to this adapter.
    ``runtime_factory`` is an injection point for deterministic runtime tests;
    production callers use Runtime, which requires the native OS sandbox.
    """
    if dataset.purpose != "evaluation" or not dataset.cases:
        raise ValueError("A nonempty, independent evaluation dataset is required")
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
    root = Path(root).resolve() / uuid4().hex
    root.mkdir(parents=True)
    snapshots = {
        "graph": graph.snapshot(),
        "memory": memory.snapshot(),
        "learning": learning.snapshot(),
    }
    # A serialization round trip rejects incidental shared mutable references.
    snapshots = json.loads(json.dumps(snapshots, allow_nan=False))
    (root / "initial-state.json").write_text(json.dumps(snapshots), encoding="utf-8")
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
            if resolved.program_id != node.id or resolved.git_path != node.properties["git_path"]:
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
        context = ExperimentContext(
            GraphStore.from_snapshot(snapshots["graph"]),
            TraceStore.from_snapshot(snapshots["memory"]),
            LearningStore.from_snapshot(snapshots["learning"]),
            side / "model-workspace",
            commit,
            label,
        )
        context.workspace.mkdir()
        evaluations = EvaluationStore()
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

        async def gateway(
            method, payload, *, context=context, run_map=run_map, evaluations=evaluations
        ):
            metadata = payload.pop("_runtime")
            model_reads = {
                "resolve_program",
                "agent.run",
                "graph.read",
                "graph.get",
                "graph.query",
                "memory.retrieve",
                "memory.rank",
                "memory.resolve",
                "learning.predict",
                "learning.prepare",
                "evaluation.predict",
            }
            if metadata["program"]["role"] == "model" and method not in model_reads:
                raise PermissionError("A model Program cannot mutate evaluation state")
            if method == "resolve_program":
                resolved = registry[payload["program_id"]]
                return asdict(replace(resolved, revision=context.revision))
            if method == "agent.run":
                if model_call is None:
                    raise PermissionError("No isolated model adapter was supplied")
                payload["mode"] = "model"
                result = await model_call(payload, context)
            elif method in {"graph.get", "graph.read"}:
                result = context.graph.get(payload["id"])
            elif method == "graph.query":
                result = context.graph.query_view(
                    payload["relation"], payload["view"], **payload.get("inputs", {})
                )
            elif method == "graph.apply":
                delta = GraphDelta.from_dict(payload)
                protect_prediction_delta(context.graph, delta)
                event = context.memory.record(
                    run_map[metadata["run_id"]], "graph_delta", output=payload
                )
                result = context.graph.apply(delta, provenance=context.memory.output_ref(event))
            elif method in {"memory.retrieve", "memory.rank"}:
                result = context.memory.retrieve(
                    payload.get("query", ""), limit=payload.get("limit", 10)
                )
            elif method == "memory.resolve":
                result = context.memory.resolve(TraceOutputRef(**payload["reference"]))
            elif method == "learning.predict":
                result = context.learning.predict(payload["state_id"], payload.get("inputs"))
            elif method == "learning.learn":
                result = LearningCoordinator(context.learning).learn(
                    LearningSignal.from_dict(payload["signal"]),
                    payload["target"],
                    context=payload.get("context"),
                    attribution_weight=payload.get("attribution_weight", 1),
                    ambiguous=payload.get("ambiguous", False),
                )
            elif method == "learning.credit":
                signal = (
                    LearningSignal.from_dict(payload["signal"]) if payload.get("signal") else None
                )
                result = CreditAssignmentProgram(context.learning).assign(
                    payload["target"],
                    signal,
                    observation_ids=payload.get("observation_ids", ()),
                    context=payload.get("context"),
                    ambiguous=payload.get("ambiguous", False),
                )
            elif method == "learning.prepare":
                result = UpdatePlanner(context.learning).prepare(
                    LearningCredit.from_dict(payload["credit"])
                )
            elif method == "learning.coordinate":
                signal = LearningSignal(
                    evaluations.get(payload["evaluation_id"]),
                    LearningObjective(**payload["objective"]),
                    payload["outcome_values"],
                )
                result = LearningCoordinator(context.learning).learn(
                    signal, payload["target"], context=payload.get("context")
                )
            elif method == "evaluation.predict":
                result = evaluations.add(evaluate_prediction(**payload))
            elif method in {
                "evaluation.save_prediction",
                "evaluation.match",
                "evaluation.decide_prediction",
            }:
                evaluator = PredictionEvaluator(
                    context.graph, context.memory, evaluations, observation_ids=observation_ids
                )
                if method == "evaluation.save_prediction":
                    reference = TraceOutputRef(**payload.pop("reference"))
                    result = evaluator.save_prediction(reference=reference, **payload)
                elif method == "evaluation.match":
                    result = evaluator.evaluate(**payload, revision=context.revision)
                else:
                    result = evaluator.record_decision(**payload, revision=context.revision)
            elif method == "evaluation.review":
                # Reviews in an experiment belong to its own memory; they must
                # never schedule attention in the live agent.
                cases = payload["cases"]
                event = context.memory.record(
                    run_map[metadata["run_id"]],
                    "prediction_review",
                    output=payload,
                    dependencies=tuple(
                        TraceOutputRef(int(identity))
                        for case in cases
                        for identity in case["observation_ids"]
                    ),
                )
                context.memory.request_review(event.id, "Unmatched prediction experience")
                result = {"queued": sorted(case["id"] for case in cases)}
            else:
                raise PermissionError("Operation unavailable in isolated evaluation: " + method)
            result = json_value(result)
            return result

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
        (side / "final-state.json").write_text(
            json.dumps(
                {
                    "graph": context.graph.snapshot(),
                    "memory": context.memory.snapshot(),
                    "learning": context.learning.snapshot(),
                },
                allow_nan=False,
            ),
            encoding="utf-8",
        )
    report = EvaluationReport(
        revision,
        dataset.revision,
        {
            "contracts": valid["candidate"],
            "tests": not syntax_errors and valid["candidate"],
            "holdout": True,
        },
        metrics["candidate"],
        True,
        tuple(sorted({source for case in dataset.cases for source in case.source_ids})),
        tuple(content_revision(trace) for trace in traces),
        baseline_metrics=metrics.get("baseline"),
    )
    (root / "trace.json").write_text(json.dumps(traces, allow_nan=False), encoding="utf-8")
    return EvaluationExperiment(report, tuple(traces))
