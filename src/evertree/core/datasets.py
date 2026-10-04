"""Immutable dataset versions and source-level separation of training and evaluation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from .memory import TraceOutputRef


def freeze_json(value: Any) -> Any:
    """Copy JSON data into immutable containers; reject non-JSON values and NaN."""
    value = json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))

    def freeze(item: Any) -> Any:
        if isinstance(item, dict):
            return MappingProxyType({key: freeze(child) for key, child in item.items()})
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        return item

    return freeze(value)


def thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_json(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw_json(child) for child in value]
    return value


def content_revision(value: Any) -> str:
    encoded = json.dumps(
        thaw_json(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    inputs: Mapping[str, Any]
    outcomes: Any
    evaluation_rule: str
    source_ids: tuple[str, ...]
    independence_group: str | None = None
    weight: float = 1.0
    name: str | None = None
    source_refs: tuple[TraceOutputRef, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.evaluation_rule or not self.source_ids:
            raise ValueError("A case needs an identity, rule and traceable source identities")
        if not isinstance(self.inputs, Mapping):
            raise TypeError("Case inputs must be an argument mapping")
        if not isinstance(self.weight, (int, float)) or not 0 < self.weight < float("inf"):
            raise ValueError("Case weight must be finite and positive")
        if any(not isinstance(source, str) or not source for source in self.source_ids):
            raise ValueError("Source identities must be nonempty strings")
        object.__setattr__(self, "inputs", freeze_json(thaw_json(self.inputs)))
        object.__setattr__(self, "outcomes", freeze_json(thaw_json(self.outcomes)))
        object.__setattr__(self, "source_ids", tuple(dict.fromkeys(self.source_ids)))
        if any(not isinstance(ref, TraceOutputRef) for ref in self.source_refs):
            raise TypeError("Internal dataset sources must be TraceOutputRef values")
        object.__setattr__(self, "source_refs", tuple(dict.fromkeys(self.source_refs)))

    @property
    def revision(self) -> str:
        return content_revision(self.to_dict())

    @property
    def independence_keys(self) -> frozenset[str]:
        keys = {"source:" + source for source in self.source_ids}
        keys.update("trace:" + str(ref.event_ref) for ref in self.source_refs)
        if self.independence_group:
            keys.add("group:" + self.independence_group)
        return frozenset(keys)

    def program_inputs(self) -> dict[str, Any]:
        """Only these arguments are delivered to the program under evaluation."""
        return thaw_json(self.inputs)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "inputs": thaw_json(self.inputs),
            "outcomes": thaw_json(self.outcomes),
            "evaluation_rule": self.evaluation_rule,
            "source_ids": list(self.source_ids),
            "independence_group": self.independence_group,
            "weight": self.weight,
            "name": self.name,
        }
        if self.source_refs:
            result["source_refs"] = [
                {"event_ref": ref.event_ref, "output_path": list(ref.output_path)}
                for ref in self.source_refs
            ]
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvaluationCase:
        values = dict(data)
        values["source_refs"] = tuple(
            TraceOutputRef(**ref) for ref in values.get("source_refs", ())
        )
        return cls(**values)


@dataclass(frozen=True)
class DatasetRevision:
    dataset_id: str
    name: str
    purpose: str
    cases: tuple[EvaluationCase, ...]
    target_metrics: tuple[str, ...] = ()
    description: str | None = None

    def __post_init__(self) -> None:
        if self.purpose not in {"training", "evaluation"}:
            raise ValueError("Dataset purpose must be training or evaluation")
        if not self.dataset_id or not self.name:
            raise ValueError("Dataset identity and name are required")
        object.__setattr__(self, "cases", tuple(self.cases))
        object.__setattr__(self, "target_metrics", tuple(self.target_metrics))
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("A dataset version cannot contain a case twice")

    @property
    def revision(self) -> str:
        return content_revision(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "purpose": self.purpose,
            "cases": [case.to_dict() for case in self.cases],
            "target_metrics": list(self.target_metrics),
            "aggregation_policy": "weighted_mean",
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DatasetRevision:
        values = dict(data)
        if values.pop("aggregation_policy", "weighted_mean") != "weighted_mean":
            raise ValueError("Dataset aggregation must be weighted_mean")
        values["cases"] = tuple(EvaluationCase.from_dict(case) for case in values["cases"])
        return cls(**values)


def validate_holdout(dataset: DatasetRevision) -> None:
    if dataset.purpose != "evaluation":
        raise ValueError("A holdout must be an evaluation dataset")
    if not dataset.cases:
        raise ValueError("An empty dataset supplies no independent evidence")
    if any(case.source_refs for case in dataset.cases):
        raise ValueError(
            "Holdout sources are already accessible through agent memory; "
            "use private evaluation sources, or keep this dataset for training/replay"
        )


class DatasetStore:
    """Versions remain addressable after later revisions or changed training choices.

    Exposure records use a candidate lineage identity, not just a commit: changing
    the code must not make already-seen holdouts independent again.
    """

    def __init__(self) -> None:
        self._versions: dict[str, DatasetRevision] = {}
        self._latest: dict[str, str] = {}
        self._exposures: dict[str, set[str]] = {}

    def add(self, dataset: DatasetRevision) -> str:
        revision = dataset.revision
        self._versions[revision] = dataset
        self._latest[dataset.dataset_id] = revision
        return revision

    def create(
        self,
        name: str,
        cases: tuple[EvaluationCase, ...] | list[EvaluationCase],
        *,
        purpose: str = "evaluation",
        dataset_id: str | None = None,
        target_metrics: tuple[str, ...] = (),
        description: str | None = None,
    ) -> DatasetRevision:
        dataset = DatasetRevision(
            dataset_id or str(uuid4()),
            name,
            purpose,
            tuple(cases),
            target_metrics,
            description=description,
        )
        self.add(dataset)
        return dataset

    def get(self, revision: str) -> DatasetRevision:
        return self._versions[revision]

    def latest(self, dataset_id: str) -> DatasetRevision:
        return self.get(self._latest[dataset_id])

    def mark_exposed(self, candidate_lineage: str, revision: str) -> None:
        if not candidate_lineage:
            raise ValueError("Exposure requires a stable candidate lineage")
        exposed = self._exposures.setdefault(candidate_lineage, set())
        for case in self.get(revision).cases:
            exposed.update(case.independence_keys)

    def mark_training(self, candidate_lineage: str, revision: str) -> None:
        if self.get(revision).purpose != "training":
            raise ValueError("Training requires an explicitly designated training dataset")
        self.mark_exposed(candidate_lineage, revision)

    def independent_cases(
        self, candidate_lineage: str, revision: str
    ) -> tuple[EvaluationCase, ...]:
        exposed = self._exposures.get(candidate_lineage, set())
        return tuple(
            case for case in self.get(revision).cases if not (case.independence_keys & exposed)
        )

    def require_holdout(self, candidate_lineage: str, revision: str) -> DatasetRevision:
        dataset = self.get(revision)
        validate_holdout(dataset)
        if len(self.independent_cases(candidate_lineage, revision)) != len(dataset.cases):
            raise ValueError("Evaluation sources overlap material used for training or refinement")
        return dataset

    def inherit_exposure(self, source_lineage: str, candidate_lineage: str) -> None:
        self._exposures.setdefault(candidate_lineage, set()).update(
            self._exposures.get(source_lineage, set())
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "versions": {key: value.to_dict() for key, value in self._versions.items()},
            "latest": dict(self._latest),
            "exposures": {key: sorted(value) for key, value in self._exposures.items()},
        }

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any]) -> DatasetStore:
        store = cls()
        for revision, values in data.get("versions", {}).items():
            dataset = DatasetRevision.from_dict(values)
            if dataset.revision != revision:
                raise ValueError("Dataset contents do not match their immutable revision")
            store._versions[revision] = dataset
        store._latest = dict(data.get("latest", {}))
        if any(revision not in store._versions for revision in store._latest.values()):
            raise ValueError("Latest dataset version is missing")
        store._exposures = {key: set(value) for key, value in data.get("exposures", {}).items()}
        return store
