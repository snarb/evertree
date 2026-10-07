"""The domain operations shared by live execution and isolated experiments.

Stores define the environment; this module never opens live files, invokes a
provider, schedules a task or performs an external action.
"""

from dataclasses import dataclass, field

from evertree.core.evaluation.contracts import exact_json_equal
from evertree.core.evaluation.scoring import evaluate_prediction
from evertree.core.evaluation.store import EvaluationStore
from evertree.core.graph.store import GraphStore
from evertree.core.graph.types import GraphDelta
from evertree.core.learning.contracts import LearningCredit, LearningObjective, LearningSignal
from evertree.core.learning.coordinator import LearningCoordinator
from evertree.core.learning.state import LearningStore
from evertree.core.learning.updates import CreditAssignmentProgram, UpdatePlanner
from evertree.core.memory.store import TraceStore
from evertree.core.memory.types import TraceOutputRef

from .attribution import AttributionRuntime
from .beliefs import BeliefStore
from .predictions import PredictionEvaluator, protect_prediction_delta
from .topology import inspect_topology
from .values import json_value

MODEL_OPERATIONS = frozenset(
    {
        "resolve_program",
        "agent.run",
        "graph.read",
        "graph.get",
        "graph.query",
        "memory.retrieve",
        "memory.rank",
        "memory.resolve",
        "belief.read",
        "learning.predict",
        "learning.prepare",
        "evaluation.predict",
        "attribution.read",
        "attribution.measure",
        "attribution.normalize",
        "topology.inspect",
    }
)


def authorize_operation(method: str, role: str) -> None:
    if role not in {"model", "exec"}:
        raise PermissionError("Unknown Program role")
    if role == "model" and method not in MODEL_OPERATIONS:
        raise PermissionError("A model Program cannot perform effects or obtain new observations")


@dataclass
class CoreOperations:
    graph: GraphStore
    memory: TraceStore
    beliefs: BeliefStore
    attribution: AttributionRuntime
    evaluations: EvaluationStore
    learning: LearningStore
    observation_ids: set[int] | frozenset[int]
    protected_nodes: set[int] | frozenset[int] = field(default_factory=frozenset)

    def predictions(self, run_mode="live") -> PredictionEvaluator:
        return PredictionEvaluator(
            self.graph,
            self.memory,
            self.evaluations,
            observation_ids=self.observation_ids,
            run_mode=run_mode,
        )

    def apply_delta(self, delta: GraphDelta, *, task_id: str, revision: str, run_mode="live"):
        protect_prediction_delta(self.graph, delta)
        binding = self.graph.find("PROGRAM_FOR_PROCESS")
        if binding is not None:

            def is_binding(node):
                return node.id == binding.id or getattr(node, "relation_type", None) == binding.id

            if (
                any(is_binding(node) for node in delta.creates)
                or any(
                    is_binding(self.graph.get(update.id))
                    or update.changes.get("relation_type") == binding.id
                    for update in delta.updates
                )
                or any(is_binding(self.graph.get(identity)) for identity in delta.deletes)
            ):
                raise PermissionError("Program bindings can only change through lifecycle")
        if any(update.id in self.protected_nodes for update in delta.updates) or (
            set(delta.deletes) & self.protected_nodes
        ):
            raise PermissionError("Protected Self/Values are not autonomously mutable")
        if any(
            node.kind in {"program", "process"}
            or node.properties.get("process")
            or any(key.startswith("active_") for key in node.properties)
            for node in delta.creates
        ):
            raise PermissionError("Program bindings can only be created through lifecycle")
        for update in delta.updates:
            node = self.graph.get(update.id)
            if node.kind in {"program", "process"} or node.properties.get("process"):
                raise PermissionError("Program bindings can only change through lifecycle")
            if update.changes.get("kind") in {"program", "process"} or any(
                key.startswith("active_") or key == "process"
                for key in update.changes.get("properties", {})
            ):
                raise PermissionError("Semantic edits cannot create executable authority")
        if any(
            self.graph.get(identity).kind in {"program", "process"}
            or self.graph.get(identity).properties.get("process")
            for identity in delta.deletes
        ):
            raise PermissionError("Programs cannot be removed through graph tools")
        run = self.memory.start_run(
            "GraphMutation", revision, {"task_id": task_id}, run_mode=run_mode
        )
        event = self.memory.record(run, "graph_delta", output=json_value(delta))
        ref = self.memory.output_ref(event)
        try:
            result = self.graph.apply(delta, provenance=ref)
            for node in (*delta.creates, *delta.updates):
                self.memory.retain(ref, "graph:" + str(node.id))
            return result
        finally:
            self.memory.finish_run(run)

    def _signal(self, data) -> LearningSignal:
        signal = LearningSignal.from_dict(data)
        if self.evaluations.get(signal.evaluation.id).to_dict() != signal.evaluation.to_dict():
            raise PermissionError("Learning needs the retained original Evaluation")
        return signal

    def review(self, payload, *, task_id, revision, run_mode):
        originals = {
            case["id"]: json_value(case)
            for event in self.memory.events
            if event.operator == "prediction_evaluation"
            and self.memory.get_run(event.program_run).program == "PredictionEvaluator"
            for case in event.output["unmatched"]
        }
        if any(not exact_json_equal(originals.get(case["id"]), case) for case in payload["cases"]):
            raise PermissionError("Prediction review requires original evaluator cases")
        case_ids = {case["id"] for case in payload["cases"]}
        for event in self.memory.events:
            if event.operator == "prediction_review" and event.arguments.get("task_id") == task_id:
                case_ids.difference_update(case["id"] for case in event.output["cases"])
        cases = [case for case in payload["cases"] if case["id"] in case_ids]
        if not cases:
            return {"queued": []}
        run = self.memory.start_run(
            "PredictionReview", revision, {"task_id": task_id}, run_mode=run_mode
        )
        event = self.memory.record(
            run,
            "prediction_review",
            arguments={"task_id": task_id},
            output={"cases": cases, "credits": payload["credits"]},
            dependencies=tuple(
                TraceOutputRef(int(identity))
                for case in cases
                for identity in case["observation_ids"]
            ),
        )
        self.memory.finish_run(run)
        self.memory.retain(event.id, "prediction_review:" + task_id)
        self.memory.request_review(
            event.id, "Unmatched prediction experience requires conscious analysis"
        )
        return {"queued": sorted(case_ids), "review_ref": json_value(self.memory.output_ref(event))}

    def execute(self, method: str, payload: dict, *, metadata: dict):
        authorize_operation(method, metadata["program"]["role"])
        payload = dict(payload)
        task_id = metadata["task_id"]
        revision = metadata["program"]["revision"]
        run_mode = metadata.get("run_mode", "live")
        if method.startswith("learning.") and method != "learning.predict":
            target = payload.get("target", payload.get("credit", {}).get("target"))
            if target == "verified_task_rate":
                raise PermissionError(
                    "Runtime verification statistics can only learn from core task outcomes"
                )
        if method in {"graph.read", "graph.get"}:
            result = self.graph.get(payload["id"])
        elif method == "graph.query":
            result = self.graph.query_view(
                payload["relation"],
                payload["view"],
                valid_at=payload.get("valid_at"),
                known_at=payload.get("known_at"),
                **payload.get("inputs", {}),
            )
        elif method == "graph.apply":
            result = self.apply_delta(
                GraphDelta.from_dict(payload), task_id=task_id, revision=revision, run_mode=run_mode
            )
        elif method in {"memory.retrieve", "memory.rank"}:
            result = self.memory.retrieve(payload.get("query", ""), limit=payload.get("limit", 10))
        elif method == "memory.resolve":
            result = self.memory.resolve(TraceOutputRef(**payload["reference"]))
        elif method == "memory.review":
            result = self.memory.review_batch(limit=payload.get("limit", 100))
        elif method == "memory.complete_review":
            self.memory.complete_review(payload["event_id"])
            result = {"reviewed": payload["event_id"]}
        elif method == "memory.compact":
            result = self.memory.compact(payload["run_id"], tuple(payload["keep_events"]))
        elif method == "memory.delete":
            self.memory.delete(payload["event_id"])
            result = {"pending_deletion": payload["event_id"]}
        elif method == "belief.read":
            result = self.beliefs.read(payload["target"])
        elif method in {"attribution.read", "attribution.measure"}:
            result = self.attribution.read_property(**payload)
        elif method == "attribution.normalize":
            result = self.attribution.normalize(**payload)
        elif method == "topology.inspect":
            result = inspect_topology(self.graph, **payload)
        elif method == "evidence.assess":
            target = payload["target"]
            try:
                self.beliefs.target(target)
            except KeyError:
                self.beliefs.register_binary(target)
            source = TraceOutputRef(**payload["source_ref"])
            self.memory.resolve(source)
            result = self.beliefs.assess_likelihoods(
                target,
                source,
                payload["likelihoods"],
                # A stored observation does not validate the Program's supplied
                # likelihood model. Keep the unsupported-influence cap.
                backed=False,
                dependency_root=payload.get("dependency_root"),
                created_by=metadata["run_id"],
            )
            self.memory.retain(source, "evidence:" + target)
        elif method == "learning.predict":
            result = self.learning.predict(payload["state_id"], payload.get("inputs"))
        elif method == "learning.learn":
            result = LearningCoordinator(self.learning).learn(
                self._signal(payload["signal"]),
                payload["target"],
                context=payload.get("context"),
                attribution_weight=payload.get("attribution_weight", 1),
                ambiguous=payload.get("ambiguous", False),
            )
        elif method == "learning.credit":
            result = CreditAssignmentProgram(self.learning).assign(
                payload["target"],
                self._signal(payload["signal"]) if payload.get("signal") else None,
                observation_ids=payload.get("observation_ids", ()),
                context=payload.get("context"),
                ambiguous=payload.get("ambiguous", False),
            )
        elif method == "learning.prepare":
            result = UpdatePlanner(self.learning).prepare(
                LearningCredit.from_dict(payload["credit"])
            )
        elif method == "learning.coordinate":
            signal = LearningSignal(
                self.evaluations.get(payload["evaluation_id"]),
                LearningObjective(**payload["objective"]),
                payload["outcome_values"],
            )
            result = LearningCoordinator(self.learning).learn(
                signal, payload["target"], context=payload.get("context")
            )
        elif method == "evaluation.predict":
            for reference in payload.get("provenance", ()):
                event = self.memory.get_event(int(reference))
                self.memory.retain(event.id, "evaluation_source")
            result = self.evaluations.add(evaluate_prediction(**payload)).to_dict()
        elif method == "evaluation.save_prediction":
            reference = TraceOutputRef(**payload.pop("reference"))
            result = self.predictions(run_mode).save_prediction(reference=reference, **payload)
        elif method == "evaluation.match":
            result = self.predictions(run_mode).evaluate(**payload, revision=revision)
        elif method == "evaluation.decide_prediction":
            result = self.predictions(run_mode).record_decision(**payload, revision=revision)
        elif method == "evaluation.review":
            result = self.review(payload, task_id=task_id, revision=revision, run_mode=run_mode)
        else:
            raise PermissionError("Unsupported core operation: " + method)
        return json_value(result)
