"""Match immutable prediction projections to retained observations.

The graph indexes what was predicted. Payloads remain in their original trace
outputs, and evaluation never reruns a model or learns from its observations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .datasets import content_revision
from .evaluation import (
    EvaluationStore,
    UnresolvedEvaluationResult,
    evaluate_prediction,
    exact_json_equal,
)
from .graph import GraphDelta, RelationType, Slot, json_value, timestamp
from .memory import TraceOutputRef


def prediction_context(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    if set(result) - {"process_id", "subject", "episode", "conditions"}:
        raise ValueError("Prediction context contains undeclared fields")
    for key in ("process_id", "subject", "episode"):
        if not isinstance(result.get(key), (str, int)) or isinstance(result[key], bool):
            raise TypeError(f"Prediction context requires {key}")
        if not str(result[key]):
            raise ValueError(f"Prediction context requires {key}")
        result[key] = str(result[key])
    result.setdefault("conditions", {})
    return json_value(result)


def protect_prediction_delta(graph, delta):
    """Semantic edits cannot backdate or rewrite the protected prediction index."""
    relation = graph.find("PREDICTS")
    relation_id = relation.id if relation is not None else None

    def reserved(node):
        return node.name == "PREDICTS" or (
            relation_id is not None and getattr(node, "relation_type", None) == relation_id
        )

    if (
        any(reserved(node) for node in delta.creates)
        or any(
            reserved(graph.get(update.id))
            or update.changes.get("name") == "PREDICTS"
            or (relation_id is not None and update.changes.get("relation_type") == relation_id)
            for update in delta.updates
        )
        or any(reserved(graph.get(identity)) for identity in delta.deletes)
    ):
        raise PermissionError("Prediction index changes require evaluation.save_prediction")


class PredictionEvaluator:
    def __init__(
        self, graph, memory, evaluations: EvaluationStore, *, observation_ids=None, run_mode="live"
    ):
        self.graph, self.memory, self.evaluations = graph, memory, evaluations
        self.observation_ids = observation_ids
        self.run_mode = run_mode

    def target(self, target: str | int) -> int:
        node = self.graph.get(target) if isinstance(target, int) else self.graph.find(target)
        if node is None and isinstance(target, str) and target.isdecimal():
            node = self.graph.get(int(target))
        if node is None:
            raise ValueError("Prediction target must identify an existing semantic node")
        return node.id

    def project_observation(self, value, projections, context) -> dict[str, Any]:
        """Validate semantic paths before storing the original observation payload."""
        normalized = {}
        for target, parts in projections.items():
            identity = str(self.target(target))
            if not parts or not isinstance(parts, Mapping):
                raise ValueError("Observation projection needs named parts and output paths")
            normalized[identity] = {}
            for part, path in parts.items():
                if not isinstance(part, str) or not part:
                    raise ValueError("Observation parts need nonempty names")
                selected = value
                for key in path:
                    selected = selected[key]
                normalized[identity][part] = list(path)
        return {"context": prediction_context(context), "projections": normalized}

    def save_prediction(
        self,
        target: str | int,
        reference: TraceOutputRef,
        context: Mapping[str, Any],
        *,
        parts: tuple[str, ...] = ("value",),
        period: tuple[str, str] | None = None,
        calibration: Mapping[str, Any] | None = None,
        comparison_key: str | None = None,
    ):
        target = self.target(target)
        self.memory.resolve(reference)
        if not parts or len(set(parts)) != len(parts) or any(not part for part in parts):
            raise ValueError("Prediction must declare distinct required outcome parts")
        if period is not None and (
            len(period) != 2 or timestamp(period[0]) >= timestamp(period[1])
        ):
            raise ValueError("Prediction horizon must be a nonempty [start, end) interval")
        definition = {
            "reference": json_value(reference),
            "context": prediction_context(context),
            "parts": list(parts),
            "period": list(period) if period else None,
            "calibration": json_value(calibration),
            "comparison_key": comparison_key,
        }
        for existing in self.graph.facts("PREDICTS"):
            _, previous = self._assignment(existing)
            if existing.args["target"] == target and exact_json_equal(previous, definition):
                return existing
        run = self.memory.start_run(
            "PredictionAssignment",
            self.memory.get_run(
                self.memory.get_event(reference.event_ref).program_run
            ).base_commit_sha,
            {},
            run_mode=self.run_mode,
        )
        assignment = self.memory.record(
            run,
            "prediction_assignment",
            arguments={"target": target},
            output=definition,
            dependencies=(reference,),
        )
        self.memory.finish_run(run)
        relation = self.graph.find("PREDICTS")
        if relation is None:
            relation = RelationType(
                self.graph.reserve_id(),
                "PREDICTS",
                signature=(Slot("target"), Slot("assignment_ref", "integer")),
            )
            self.graph.apply(
                GraphDelta(creates=(relation,)), provenance=self.memory.output_ref(assignment)
            )
        if not isinstance(relation, RelationType) or relation.signature != (
            Slot("target"),
            Slot("assignment_ref", "integer"),
        ):
            raise ValueError("PREDICTS has an incompatible semantic contract")
        fact = self.graph.new_fact("PREDICTS", {"target": target, "assignment_ref": assignment.id})
        self.graph.apply(GraphDelta(creates=(fact,)), provenance=self.memory.output_ref(assignment))
        self.memory.retain(reference, "prediction:" + str(fact.id))
        self.memory.retain(assignment.id, "prediction:" + str(fact.id))
        return fact

    def _assignment(self, fact):
        """Resolve the immutable assignment; the semantic graph is only its index."""
        identity = fact.args["assignment_ref"]
        if type(identity) is not int or identity <= 0:
            raise PermissionError("Prediction assignment reference must be a positive event ID")
        assignment = self.memory.get_event(identity)
        saved = json_value(assignment.output)
        if (
            assignment.operator != "prediction_assignment"
            or self.memory.get_run(assignment.program_run).program != "PredictionAssignment"
            or assignment.arguments.get("target") != fact.args["target"]
            or not isinstance(saved, dict)
            or "reference" not in saved
            or TraceOutputRef(**saved["reference"]) not in assignment.dependencies
        ):
            raise PermissionError("Prediction projection lacks an authentic assignment")
        return assignment, saved

    def _observations(self, context):
        for event in self.memory.events:
            arguments = event.arguments
            if (
                event.status == "completed"
                and (self.observation_ids is None or event.id in self.observation_ids)
                and event.operator in {"observation", "supervisor_feedback_signal"}
                and isinstance(arguments, Mapping)
                and exact_json_equal(json_value(arguments.get("context")), context)
            ):
                for target, parts in arguments.get("projections", {}).items():
                    for part, path in parts.items():
                        yield {
                            "target": str(target),
                            "part": part,
                            "event": event,
                            "reference": TraceOutputRef(event.id, tuple(path)),
                        }

    def match_predictions(self, observations, context):
        """Return original forecasts with all matching old/new observation parts."""
        context = prediction_context(context)
        event_ids = {int(identity) for identity in observations}
        for identity in event_ids:
            event = self.memory.get_event(identity)
            if self.observation_ids is not None and identity not in self.observation_ids:
                raise PermissionError("An agent-generated trace is not an external observation")
            if event.operator not in {"observation", "supervisor_feedback_signal"}:
                raise ValueError("Prediction evaluation requires retained observations")
            if not exact_json_equal(json_value(event.arguments.get("context")), context):
                raise ValueError("Observation does not belong to the requested context")
        pieces = list(self._observations(context))
        matched = set()
        matches = []
        for fact in self.graph.facts("PREDICTS"):
            assignment, saved = self._assignment(fact)
            if not exact_json_equal(saved["context"], context):
                continue
            reference = TraceOutputRef(**saved["reference"])
            prediction_event = self.memory.get_event(reference.event_ref)
            related = [
                piece
                for piece in pieces
                if piece["target"] == str(fact.args["target"])
                and piece["part"] in saved["parts"]
                and prediction_event.occurred_at < piece["event"].occurred_at
                and prediction_event.id < piece["event"].id
                and assignment.id < piece["event"].id
                and assignment.occurred_at < piece["event"].occurred_at
                and (
                    saved["period"] is None
                    or timestamp(saved["period"][0])
                    <= piece["event"].occurred_at
                    < timestamp(saved["period"][1])
                )
            ]
            if not any(piece["event"].id in event_ids for piece in related):
                continue
            for piece in related:
                matched.add((piece["event"].id, piece["target"], piece["part"]))
            matches.append({"fact": fact, "saved": saved, "pieces": related})
        unmatched = [
            piece
            for piece in pieces
            if piece["event"].id in event_ids
            and (piece["event"].id, piece["target"], piece["part"]) not in matched
        ]
        # Entirely unprojected observations also require a conscious decision.
        projected = {piece["event"].id for piece in pieces}
        unmatched.extend(
            {
                "target": None,
                "part": None,
                "event": self.memory.get_event(identity),
                "reference": TraceOutputRef(identity),
            }
            for identity in event_ids - projected
        )
        return matches, unmatched

    def evaluate_prediction(self, match, metrics):
        fact, saved, pieces = match["fact"], match["saved"], match["pieces"]
        reference = TraceOutputRef(**saved["reference"])
        grouped = {
            part: [piece for piece in pieces if piece["part"] == part] for part in saved["parts"]
        }
        sources = tuple(dict.fromkeys(str(piece["event"].id) for piece in pieces))
        provenance = (str(reference.event_ref), str(fact.args["assignment_ref"]), *sources)
        missing = tuple(part for part, values in grouped.items() if not values)
        ambiguous = tuple(part for part, values in grouped.items() if len(values) > 1)
        if missing or ambiguous:
            result = UnresolvedEvaluationResult(
                outcome_ids=sources,
                provenance=provenance,
                evaluated_subject=str(fact.id),
                reason="Incomplete or ambiguous observation parts",
                missing_requirements=tuple("part:" + part for part in missing)
                + tuple("unambiguous_part:" + part for part in ambiguous),
            )
        else:
            values = {
                part: self.memory.resolve(values[0]["reference"])
                for part, values in grouped.items()
            }
            observed = values["value"] if saved["parts"] == ["value"] else values
            result = evaluate_prediction(
                self.memory.resolve(reference),
                observed,
                metrics=tuple(metrics),
                outcome_ids=sources,
                provenance=provenance,
                subject=str(fact.id),
                process_id=saved["context"]["process_id"],
                observed_at=max(piece["event"].occurred_at for piece in pieces).isoformat(),
                calibration=saved["calibration"],
                comparison_key=saved["comparison_key"],
            )
        for source in provenance:
            self.memory.retain(int(source), "evaluation:" + result.id)
        return self.evaluations.add(result)

    def record_decision(self, target, context, *, required: bool, reason: str, revision: str):
        if not reason or not isinstance(required, bool):
            raise ValueError("A prediction decision needs explicit necessity and a reason")
        value = {
            "target": str(self.target(target)),
            "context": prediction_context(context),
            "required": required,
            "reason": reason,
        }
        run = self.memory.start_run("PredictionDecision", revision, {}, run_mode=self.run_mode)
        event = self.memory.record(run, "prediction_decision", output=value)
        self.memory.retain(event.id, "prediction_decision")
        self.memory.finish_run(run)
        return event

    def handle_unmatched_observations(self, pieces, context, selected_targets):
        context = prediction_context(context)
        selected = {str(self.target(target)) for target in selected_targets}
        decisions = {}
        for event in self.memory.events:
            if (
                event.operator == "prediction_decision"
                and self.memory.get_run(event.program_run).program == "PredictionDecision"
                and exact_json_equal(json_value(event.output["context"]), context)
            ):
                decisions[event.output["target"]] = event.output
        grouped = {}
        for piece in pieces:
            target = piece["target"]
            decision = decisions.get(target)
            if target not in selected and decision is not None and decision["required"] is False:
                continue
            key = target or "unprojected"
            case = grouped.setdefault(
                key,
                {
                    "target": target,
                    "context": context,
                    "observation_ids": [],
                    "parts": [],
                    "reason": "missing_prediction"
                    if target in selected or (decision and decision["required"])
                    else "prediction_target_not_selected",
                },
            )
            identity = str(piece["event"].id)
            if identity not in case["observation_ids"]:
                case["observation_ids"].append(identity)
            case["parts"].append(
                {
                    "observation_id": identity,
                    "part": piece["part"],
                    "reference": json_value(piece["reference"]),
                }
            )
        return list(grouped.values())

    def evaluate(self, observations, context, metrics, *, selected_targets=(), revision="core"):
        matches, unmatched = self.match_predictions(observations, context)
        results = [self.evaluate_prediction(match, metrics) for match in matches]
        cases = self.handle_unmatched_observations(unmatched, context, selected_targets)
        for case in cases:
            case["id"] = content_revision(case)
        run = self.memory.start_run(
            "PredictionEvaluator", revision, {"context": context}, run_mode=self.run_mode
        )
        dependencies = tuple(
            TraceOutputRef(int(source)) for result in results for source in result.provenance
        )
        event = self.memory.record(
            run,
            "prediction_evaluation",
            output={"results": [result.to_dict() for result in results], "unmatched": cases},
            dependencies=dependencies,
        )
        self.memory.finish_run(run)
        return {
            "results": [result.to_dict() for result in results],
            "unmatched": cases,
            "trace": json_value(self.memory.output_ref(event)),
        }
