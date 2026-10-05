"""Property reads over semantic facts, competition scopes and bound programs."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from .beliefs import BeliefData, BeliefReading, BeliefStore
from .graph import (
    UNKNOWN,
    ContractError,
    Facet,
    GraphStore,
    Node,
    RelationInstance,
    freeze,
    json_value,
    restore_value,
    timestamp,
    utcnow,
)


@dataclasses.dataclass(frozen=True)
class PropertyDefinition:
    id: int
    scale: str = "numeric"
    unit: str | None = None
    classes: tuple[int | str, ...] = ()
    source: str = "numeric"
    relation_type: int | str | None = None
    view: str | None = None
    subject_slot: str = "entity"
    selection: str = "latest"
    period: float | None = None
    required_parameters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "classes", tuple(self.classes))
        object.__setattr__(self, "required_parameters", tuple(self.required_parameters))
        if self.scale not in {"nominal", "ordinal", "numeric", "circular"} or self.source not in {
            "numeric",
            "classification",
            "relation",
            "program",
        }:
            raise ContractError("unknown property scale or source")
        if self.selection not in {"latest", "max_support", "unique"}:
            raise ContractError("property source selection must be explicit")
        if self.scale == "circular" and (
            self.period is None or self.period <= 0 or not math.isfinite(self.period)
        ):
            raise ContractError("circular scales require a positive period")
        if self.source == "relation" and (self.relation_type is None or self.view is None):
            raise ContractError("relation properties require a declared view")
        if self.scale == "ordinal" and (
            not self.classes or len(set(self.classes)) != len(self.classes)
        ):
            raise ContractError("ordinal scales require an ordered unique class list")


@dataclasses.dataclass(frozen=True)
class PropertyReading:
    value_U: Any
    belief_data: BeliefData | BeliefReading | None
    source_facts: tuple[int, ...] = ()
    valid_at: datetime | None = None
    known_at: datetime | None = None
    conditions: Any = None


@dataclasses.dataclass(frozen=True)
class NormalizationRule:
    property_id: int
    domain: int | str
    mean: float | None = None
    stddev: float | None = None
    # Upper-inclusive numeric bounds, followed by the unbounded final class.
    boundaries: tuple[float, ...] = ()
    classes: tuple[int | str, ...] = ()
    belief_data: BeliefData | None = None

    def __post_init__(self) -> None:
        if self.boundaries:
            if len(self.classes) != len(self.boundaries) + 1 or any(
                a >= b for a, b in zip(self.boundaries, self.boundaries[1:])
            ):
                raise ContractError("normalization bands must be ordered and cover all values")
        elif self.mean is None or self.stddev is None or self.stddev <= 0:
            raise ContractError(
                "normalization requires bands or mean and positive standard deviation"
            )


class AttributionRuntime:
    def __init__(
        self,
        graph: GraphStore,
        beliefs: BeliefStore | None = None,
        *,
        program_reader: Callable | None = None,
        historical_loader: Callable[[datetime], AttributionRuntime | None] | None = None,
    ) -> None:
        self.graph = graph
        self.beliefs = beliefs or BeliefStore()
        self._properties: dict[int, PropertyDefinition] = {}
        self._scopes: dict[str, str] = {}
        self._rules: dict[tuple[int, int | str], NormalizationRule] = {}
        self.program_reader = program_reader
        self.historical_loader = historical_loader

    def register(self, definition: PropertyDefinition) -> None:
        self.graph.get(definition.id)
        self._properties[definition.id] = definition

    @staticmethod
    def _binding_key(subject: int, property_id: int, conditions: Mapping | None) -> str:
        import json

        return json.dumps([subject, property_id, json_value(conditions or {})], sort_keys=True)

    def bind_scope(
        self, subject: int, property_id: int, target: str, *, conditions: Mapping | None = None
    ) -> None:
        definition = self._properties[property_id]
        contract = self.beliefs.target(target)
        if not contract.alternatives or definition.scale not in {"nominal", "ordinal"}:
            raise ContractError(
                "categorical property scopes need exclusive exhaustive alternatives"
            )
        if definition.classes and set(map(str, definition.classes)) != set(contract.alternatives):
            raise ContractError("scope alternatives do not match the property scale")
        self._scopes[self._binding_key(subject, property_id, conditions)] = target

    def register_normalization(self, rule: NormalizationRule) -> None:
        self._properties[rule.property_id]
        self._rules[(rule.property_id, rule.domain)] = rule

    def _belief(
        self, fact: RelationInstance, valid_at: datetime, known_at: datetime | None
    ) -> BeliefData | BeliefReading | None | Any:
        if fact.belief_target is None:
            return None
        try:
            reading = self.beliefs.read(fact.belief_target, valid_at=valid_at, known_at=known_at)
        except KeyError:
            return UNKNOWN
        if reading is UNKNOWN:
            return UNKNOWN
        return reading if reading.profile is not None else reading.data

    def read_property(
        self,
        subject: int | Node,
        property: int | Node,
        *,
        valid_at: datetime | None = None,
        known_at: datetime | None = None,
        **parameters: Any,
    ) -> PropertyReading | Any:
        subject_id = subject.id if isinstance(subject, Node) else subject
        property_id = property.id if isinstance(property, Node) else property
        definition = self._properties.get(property_id)
        if definition is None:
            return UNKNOWN
        at = timestamp(valid_at or utcnow())
        if known_at is not None:
            known = timestamp(known_at)
            if self.graph.known_at is not None and known != self.graph.known_at:
                return UNKNOWN
            if (
                self.graph.known_at is None
                and self.graph._history
                and known < self.graph._history[-1].at
            ):
                if self.historical_loader:
                    historical = self.historical_loader(known)
                    return (
                        historical.read_property(
                            subject_id, property_id, valid_at=at, known_at=known, **parameters
                        )
                        if historical
                        else UNKNOWN
                    )
                return UNKNOWN
        if any(parameter not in parameters for parameter in definition.required_parameters):
            return UNKNOWN
        subjects = [subject_id]
        try:
            node = self.graph.get(subject_id)
        except KeyError:
            return UNKNOWN
        if isinstance(node, Facet):
            if at < node.valid_from or node.valid_until is not None and at >= node.valid_until:
                return UNKNOWN
        elif node.kind == "instance":
            facets = self.graph.query_view(
                "STATE_IDENTITY", "get_facets", instance=subject_id, valid_at=at, known_at=known_at
            )
            if facets is UNKNOWN:
                return UNKNOWN
            subjects.extend(match.value for match in facets)
        scope_readings = []
        for identity in subjects:
            target = self._scopes.get(self._binding_key(identity, property_id, parameters))
            if target:
                try:
                    reading = self.beliefs.read(target, valid_at=at, known_at=known_at)
                except KeyError:
                    return UNKNOWN
                if reading is UNKNOWN:
                    return UNKNOWN
                scope_readings.append(
                    PropertyReading(None, reading, (), at, known_at, freeze(parameters))
                )
        if scope_readings:
            # Overlapping applicable facets cannot silently become one profile.
            return scope_readings[0] if len(scope_readings) == 1 else UNKNOWN
        candidates: list[tuple[RelationInstance, Any]] = []
        if definition.source == "numeric":
            if definition.scale not in {"numeric", "circular"}:
                raise ContractError("numeric source requires numeric or circular reading")
            for fact in self.graph.facts("HAS_NUMERIC_VALUE"):
                if (
                    fact.args["entity"] in subjects
                    and fact.args["property"] == property_id
                    and (definition.unit is None or fact.args.get("unit") == definition.unit)
                    and dict(fact.properties.get("conditions", {})) == parameters
                ):
                    candidates.append((fact, fact.args["value"]))
        elif definition.source == "classification":
            for fact in self.graph.facts("CLASSIFIED_AS"):
                if (
                    fact.args["entity"] in subjects
                    and fact.args["class"] in definition.classes
                    and dict(fact.properties.get("conditions", {})) == parameters
                ):
                    candidates.append((fact, fact.args["class"]))
        elif definition.source == "relation":
            for identity in subjects:
                matches = self.graph.query_view(
                    definition.relation_type,
                    definition.view,
                    valid_at=at,
                    known_at=known_at,
                    **{definition.subject_slot: identity, **parameters},
                )
                if matches is UNKNOWN:
                    return UNKNOWN
                if matches is None:
                    continue
                for match in matches if isinstance(matches, list) else [matches]:
                    candidates.append((match.source_fact, match.value))
        else:
            if self.program_reader is None:
                return UNKNOWN
            # The caller executes the bound Program through runtime and records
            # its provenance; reading never creates or searches for new models.
            return self.program_reader(
                subject_id, definition, valid_at=at, known_at=known_at, **parameters
            )
        if not candidates:
            return UNKNOWN
        if definition.selection == "unique" and len(candidates) != 1:
            return UNKNOWN
        if definition.selection == "max_support":
            ranked = []
            for fact, value in candidates:
                belief = self._belief(fact, at, known_at)
                if belief is UNKNOWN:
                    return UNKNOWN
                support = getattr(belief, "support", 0.0) if belief is not None else 0.0
                ranked.append((support, self.graph.created_at(fact.id), fact.id, fact, value))
            _, _, _, fact, value = max(ranked, key=lambda item: item[:3])
        else:
            fact, value = max(
                candidates, key=lambda item: (self.graph.created_at(item[0].id), item[0].id)
            )
        belief = self._belief(fact, at, known_at)
        if belief is UNKNOWN:
            return UNKNOWN
        return PropertyReading(value, belief, (fact.id,), at, known_at, freeze(parameters))

    def measure(
        self, subject: int | Node, property: int | Node, **parameters: Any
    ) -> PropertyReading | Any:
        return self.read_property(subject, property, **parameters)

    def reconstruct_property(
        self,
        subject: int | Node,
        property: int | Node,
        *,
        valid_at: datetime,
        known_at: datetime,
        **parameters: Any,
    ) -> PropertyReading | Any:
        if self.graph.known_at == timestamp(known_at):
            return self.read_property(
                subject, property, valid_at=valid_at, known_at=known_at, **parameters
            )
        if self.historical_loader is None:
            return UNKNOWN
        historical = self.historical_loader(timestamp(known_at))
        if historical is None or historical.graph.known_at != timestamp(known_at):
            return UNKNOWN
        return historical.read_property(
            subject, property, valid_at=valid_at, known_at=known_at, **parameters
        )

    def compare(self, property_id: int, first: Any, second: Any) -> int:
        definition = self._properties[property_id]
        if definition.scale in {"nominal", "circular"}:
            raise ContractError("this scale has no linear ordering")
        if definition.scale == "ordinal":
            first, second = definition.classes.index(first), definition.classes.index(second)
        return (first > second) - (first < second)

    def distance(self, property_id: int, first: float, second: float) -> float:
        definition = self._properties[property_id]
        if definition.scale in {"nominal", "ordinal"}:
            raise ContractError("this scale has no numeric distance")
        delta = abs(first - second)
        if definition.scale == "circular":
            delta %= definition.period
            return min(delta, definition.period - delta)
        return delta

    def normalize(
        self,
        value: float,
        property_id: int,
        domain: int | str,
        *,
        valid_at: datetime | None = None,
        known_at: datetime | None = None,
    ) -> PropertyReading | Any:
        if known_at is not None and self.graph.known_at != timestamp(known_at):
            if self.historical_loader is None:
                return UNKNOWN
            historical = self.historical_loader(timestamp(known_at))
            return (
                historical.normalize(
                    value, property_id, domain, valid_at=valid_at, known_at=known_at
                )
                if historical
                else UNKNOWN
            )
        rule = self._rules.get((property_id, domain))
        if rule is None:
            return UNKNOWN
        if rule.boundaries:
            index = next(
                (index for index, boundary in enumerate(rule.boundaries) if value <= boundary),
                len(rule.boundaries),
            )
            normalized = rule.classes[index]
        else:
            normalized = (value - rule.mean) / rule.stddev
        return PropertyReading(
            normalized, rule.belief_data, (), valid_at, known_at, freeze({"domain": domain})
        )

    def snapshot(self) -> dict:
        return {
            "properties": [json_value(value) for value in self._properties.values()],
            "scopes": dict(self._scopes),
            "rules": [json_value(value) for value in self._rules.values()],
        }

    @classmethod
    def from_snapshot(
        cls, data: dict, graph: GraphStore | None = None, beliefs: BeliefStore | None = None
    ) -> AttributionRuntime:
        runtime = cls(graph or GraphStore(), beliefs)
        runtime._properties = {
            raw["id"]: PropertyDefinition(**restore_value(raw)) for raw in data["properties"]
        }
        runtime._scopes = dict(data["scopes"])
        for raw in data["rules"]:
            values = restore_value(raw)
            if values["belief_data"] is not None:
                values["belief_data"] = BeliefData(**values["belief_data"])
            rule = NormalizationRule(**values)
            runtime._rules[(rule.property_id, rule.domain)] = rule
        return runtime
