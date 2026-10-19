"""Evidence-backed binary and categorical beliefs.

Assignments are immutable.  Revision changes the current logical-source map;
read-time reduction preserves support, dependency identity, and the shared cap
on approximate influence, including after consolidation.
"""

from __future__ import annotations

import dataclasses
import json
import math
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .values import UNKNOWN, ContractError, freeze, json_value, restore_value, timestamp, utcnow


def _source_key(source: Any) -> str:
    return json.dumps(json_value(source), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# The alternative that none of a scope's listed alternatives is true.
OTHER = "other"


def element_target(element: Any) -> str:
    """Return the belief target of a graph element: its explicit binding or its identity."""
    return getattr(element, "belief_target", None) or f"graph:{element.id}"


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1.0 + exp)


def _center(values: tuple[float, ...]) -> tuple[float, ...]:
    mean = sum(values) / len(values)
    return tuple(value - mean for value in values)


def _magnitude(values: tuple[float, ...]) -> float:
    return abs(values[0]) if len(values) == 1 else max(values) - min(values)


@dataclasses.dataclass(frozen=True)
class BeliefData:
    strength: float
    support: float
    prior_support: float = 0.0

    @property
    def Strength(self) -> float:
        """Return the estimated probability carried by this belief."""
        return self.strength

    @property
    def Support(self) -> float:
        """Return the support attributed to this belief's evidence."""
        return self.support

    @property
    def PriorSupport(self) -> float:
        """Return the support attributed to this belief's prior."""
        return self.prior_support


@dataclasses.dataclass(frozen=True)
class EvidenceStats:
    evidence_count: int
    max_component_mass: float
    max_component_effect: float


@dataclasses.dataclass(frozen=True)
class BeliefReading:
    target: str
    data: BeliefData
    stats: EvidenceStats
    profile: Mapping[str, float] | None = None

    @property
    def strength(self) -> float:
        """Return the probability from the resolved belief data."""
        return self.data.strength

    @property
    def support(self) -> float:
        """Return the evidence support from the resolved belief data."""
        return self.data.support

    @property
    def prior_support(self) -> float:
        """Return the prior support from the resolved belief data."""
        return self.data.prior_support

    def for_alternative(self, alternative: str) -> BeliefData:
        """Project a categorical reading onto one alternative while preserving support."""
        if self.profile is None:
            raise ContractError("binary belief has no categorical alternatives")
        return dataclasses.replace(self.data, strength=self.profile[alternative])


@dataclasses.dataclass(frozen=True)
class BeliefTarget:
    id: str
    alternatives: tuple[str, ...]
    prior: tuple[float, ...]
    prior_backed: bool = False
    upstream: str | None = None
    applicability: float = 1.0


@dataclasses.dataclass(frozen=True)
class EvidenceComponent:
    source_key: str
    source_ref: Any
    contribution: tuple[float, ...]
    mass: float
    backed: bool
    dependency_root: str
    dependency_depth: int
    observed_scope: Any = None


@dataclasses.dataclass(frozen=True)
class EvidenceAssignment:
    id: int
    target: str
    contribution: tuple[float, ...]
    evidence_mass: float
    components: tuple[EvidenceComponent, ...]
    created_at: datetime
    created_by: Any = None


class BeliefStore:
    def __init__(self) -> None:
        self._targets: dict[str, BeliefTarget] = {}
        self._assignments: dict[int, EvidenceAssignment] = {}
        self._current: dict[str, dict[str, int | None]] = {}
        self._next_id = 1
        self._lock = threading.RLock()
        self._last_changed: datetime | None = None
        # Graph revision at which each target was last assessed, and the graph history
        # sequence below which every assessable change has been assessed.
        self._assessed: dict[str, int] = {}
        self._assessment_cursor = 0
        # How each active contribution was judged (stance, source origin and the origin's
        # reliability then), so a change in that reliability can revise it.
        self._basis: dict[str, dict[str, Any]] = {}
        # Competition scopes over element targets: scope -> {question, alternatives}, and
        # each member target -> its scope; a member reads as its alternative's probability.
        self._scopes: dict[str, dict[str, Any]] = {}
        self._members: dict[str, str] = {}
        # Sources their author withdrew, keyed by source, with the withdrawing source.
        self._withdrawn: dict[str, Any] = {}

    def register_binary(
        self, target: str, prior: float = 0.5, *, prior_backed: bool = False
    ) -> BeliefTarget:
        """Declare a revisable binary target; prior_backed marks its prior as supported."""
        if not math.isfinite(prior) or not 0 < prior < 1:
            raise ContractError("revisable binary prior must be strictly between zero and one")
        return self._register(BeliefTarget(str(target), (), (float(prior),), prior_backed))

    def register_scope(
        self,
        target: str,
        alternatives: Sequence[str],
        prior: Mapping[str, float] | None = None,
        *,
        prior_backed: bool = False,
    ) -> BeliefTarget:
        """Declare exhaustive competing alternatives with a positive normalized prior."""
        alternatives = tuple(alternatives)
        if len(alternatives) < 2 or len(set(alternatives)) != len(alternatives):
            raise ContractError(
                "a competition scope needs at least two unique exhaustive alternatives"
            )
        if prior is not None and set(prior) != set(alternatives):
            raise ContractError("scope prior must cover exactly the alternatives")
        values = tuple(
            float(prior[item]) if prior is not None else 1 / len(alternatives)
            for item in alternatives
        )
        if not all(math.isfinite(value) and value > 0 for value in values) or not math.isclose(
            sum(values), 1.0, abs_tol=1e-9
        ):
            raise ContractError("categorical prior must be positive and normalized")
        return self._register(BeliefTarget(str(target), alternatives, values, prior_backed))

    def _register(self, target: BeliefTarget) -> BeliefTarget:
        with self._lock:
            if target.id in self._targets:
                if self._targets[target.id] != target:
                    raise ContractError("target already has a different contract")
                return self._targets[target.id]
            self._targets[target.id] = target
            self._current[target.id] = {}
            self._last_changed = utcnow()
            return target

    def target(self, target: str) -> BeliefTarget:
        """Return the declared contract for a belief target."""
        return self._targets[str(target)]

    def set_prior_source(self, target: str, upstream: str, *, applicability: float = 1.0) -> None:
        """Transfer a compatible upstream prior with applicability weighting, rejecting cycles."""
        with self._lock:
            current, source = self.target(target), self.target(upstream)
            if current.alternatives != source.alternatives or not 0 <= applicability <= 1:
                raise ContractError(
                    "prior transfer requires compatible targets and applicability in [0,1]"
                )
            seen = {target}
            cursor = source
            while cursor:
                if cursor.id in seen:
                    raise ContractError("prior dependencies cannot contain cycles")
                seen.add(cursor.id)
                cursor = self.target(cursor.upstream) if cursor.upstream else None
            self._targets[target] = dataclasses.replace(
                current, upstream=upstream, applicability=applicability
            )
            self._last_changed = utcnow()

    def assessed_revision(self, target: str) -> int | None:
        """Return the graph revision at which a target was last assessed, if ever."""
        return self._assessed.get(str(target))

    def mark_assessed(self, target: str, revision: int) -> None:
        """Record that evidence for a target was assessed against this graph revision."""
        with self._lock:
            self._assessed[str(target)] = max(revision, self._assessed.get(str(target), 0))

    @property
    def assessment_cursor(self) -> int:
        """Return the graph history sequence up to which all changes were assessed."""
        return self._assessment_cursor

    def advance_assessment_cursor(self, seq: int) -> None:
        """Move the assessment cursor forward; it never moves back."""
        with self._lock:
            self._assessment_cursor = max(self._assessment_cursor, seq)

    def set_basis(self, target: str, source_ref: Any, basis: Mapping[str, Any] | None) -> None:
        """Record how an active contribution was judged, or discard it with None."""
        with self._lock:
            key = _source_key(source_ref)
            if basis is None:
                self._basis.get(str(target), {}).pop(key, None)
                return
            if self._current[str(target)].get(key) is None:
                raise ContractError("basis needs an active contribution")
            self._basis.setdefault(str(target), {})[key] = freeze(dict(basis))

    def declare_scope(
        self,
        target: str,
        question: str,
        alternatives: Sequence[str],
        prior: Mapping[str, float] | None = None,
    ) -> BeliefTarget:
        """Register a competition scope whose alternatives other than "other" are member
        targets; members then read as their alternative in the scope's Profile."""
        with self._lock:
            contract = self.register_scope(target, alternatives, prior)
            self._scopes[str(target)] = {"question": question, "alternatives": list(alternatives)}
            for alternative in alternatives:
                if alternative != OTHER:
                    self._members[alternative] = str(target)
            self._last_changed = utcnow()
            return contract

    def scope_of(self, target: str) -> str | None:
        """Return the competition scope a target is an alternative of, if any."""
        return self._members.get(str(target))

    def scope(self, target: str) -> dict[str, Any]:
        """Return a declared competition scope's question and alternatives."""
        return dict(self._scopes[str(target)])

    def known(self, target: str) -> bool:
        """Tell whether a target is registered or readable as a scope alternative."""
        return str(target) in self._targets or str(target) in self._members

    def withdraw(self, source_ref: Any, by: Any) -> None:
        """Mark a source withdrawn by a later one; withdrawals made by it become void."""
        with self._lock:
            key, by_key = _source_key(source_ref), _source_key(by)
            if key == by_key:
                raise ContractError("a source cannot withdraw itself")
            self._withdrawn = {
                source: withdrawer
                for source, withdrawer in self._withdrawn.items()
                if _source_key(withdrawer) != key
            }
            self._withdrawn[key] = freeze(by)
            self._last_changed = utcnow()

    def targets_of(self, source_ref: Any) -> tuple[str, ...]:
        """Return the targets a source currently contributes to."""
        key = _source_key(source_ref)
        with self._lock:
            return tuple(
                target for target, mapping in self._current.items() if mapping.get(key) is not None
            )

    def withdrawn_by(self, source_ref: Any) -> Any:
        """Return the source that withdrew a source, or None."""
        return self._withdrawn.get(_source_key(source_ref))

    def target_ids(self) -> tuple[str, ...]:
        """Return every declared target id in declaration order."""
        with self._lock:
            return tuple(self._targets)

    def bases(self) -> list[tuple[str, Any, Any]]:
        """Return (target, source_ref, basis) for every active contribution with a basis."""
        with self._lock:
            result = []
            for target, mapping in self._basis.items():
                for component in self._active_components(target):
                    if component.source_key in mapping:
                        result.append((target, component.source_ref, mapping[component.source_key]))
            return result

    def active_sources(self, target: str) -> tuple[EvidenceComponent, ...]:
        """Return the currently active per-source evidence components of a target.

        A scope alternative that never had its own binary target has none.
        """
        with self._lock:
            if str(target) not in self._current:
                return ()
            return tuple(self._active_components(str(target)))

    def _contribution(
        self, target: BeliefTarget, contribution: float | Mapping[str, float] | Sequence[float]
    ) -> tuple[float, ...]:
        if not target.alternatives:
            if isinstance(contribution, bool) or not isinstance(contribution, (int, float)):
                raise ContractError("binary contribution is signed log evidence")
            values = (float(contribution),)
        else:
            if isinstance(contribution, Mapping):
                if set(contribution) != set(target.alternatives):
                    raise ContractError("categorical evidence must cover the complete scope")
                values = tuple(float(contribution[key]) for key in target.alternatives)
            else:
                values = tuple(float(value) for value in contribution)
            if len(values) != len(target.alternatives):
                raise ContractError("contribution shape does not match scope")
            values = _center(values)
        if not all(math.isfinite(value) for value in values):
            raise ContractError("contributions must be finite")
        return values

    def assign(
        self,
        target: str,
        source_ref: Any,
        contribution: float | Mapping[str, float] | Sequence[float],
        *,
        backed: bool = False,
        dependency_root: Any = None,
        dependency_depth: int = 0,
        observed_scope: Any = None,
        created_by: Any = None,
    ) -> EvidenceAssignment:
        """Assign or replace one source's evidence contribution to a belief target.

        Contributions are log evidence coordinates. dependency_root groups dependent
        sources so repeated derivations cannot accumulate independent support.
        """
        with self._lock:
            contract = self.target(target)
            values = self._contribution(contract, contribution)
            if dependency_depth < 0:
                raise ContractError("dependency depth cannot be negative")
            key = _source_key(source_ref)
            root = _source_key(dependency_root) if dependency_root is not None else key
            component = EvidenceComponent(
                key,
                freeze(source_ref),
                values,
                _magnitude(values),
                backed,
                root,
                dependency_depth,
                freeze(observed_scope),
            )
            old_id = self._current[target].get(key)
            if old_id is not None:
                old = self._assignments[old_id]
                if any(existing == component for existing in old.components):
                    return old
            assignment = self._make_assignment(target, (component,), created_by)
            self._replace_current(target, {key}, assignment, created_by)
            return assignment

    def revise(
        self, target: str, source_ref: Any, contribution: Any, **kwargs: Any
    ) -> EvidenceAssignment:
        """Replace the contribution of a previously assigned evidence source."""
        if _source_key(source_ref) not in self._current[str(target)]:
            raise ContractError("cannot revise evidence that was never assigned")
        return self.assign(target, source_ref, contribution, **kwargs)

    def retract(self, target: str, source_ref: Any) -> None:
        """Remove a source's active contribution while preserving assignment history."""
        with self._lock:
            key = _source_key(source_ref)
            if key not in self._current[target]:
                raise ContractError("cannot retract missing evidence")
            self._replace_current(target, {key}, None, None)
            self._basis.get(target, {}).pop(key, None)
            self._last_changed = utcnow()

    def _replace_current(
        self,
        target: str,
        keys: set[str],
        replacement: EvidenceAssignment | None,
        created_by: Any,
    ) -> None:
        """Replace complete aggregates while retaining unaffected logical evidence.

        Called under the store lock after validating the replacement. A current
        aggregate must never still contain a revised, retracted or moved component.
        """
        current = self._current[target]
        previous_ids = {current[key] for key in keys if current.get(key) is not None}
        for identity in sorted(previous_ids):
            remainder = tuple(
                component
                for component in self._assignments[identity].components
                if component.source_key not in keys
                and current.get(component.source_key) == identity
            )
            if remainder:
                residual = self._make_assignment(target, remainder, created_by)
                for component in remainder:
                    current[component.source_key] = residual.id
        for key in keys:
            current[key] = replacement.id if replacement is not None else None

    def _make_assignment(
        self, target: str, components: tuple[EvidenceComponent, ...], created_by: Any
    ) -> EvidenceAssignment:
        size = len(components[0].contribution)
        contribution = tuple(
            sum(component.contribution[index] for component in components) for index in range(size)
        )
        assignment = EvidenceAssignment(
            self._next_id,
            target,
            contribution,
            sum(component.mass for component in components),
            components,
            utcnow(),
            freeze(created_by),
        )
        self._assignments[assignment.id] = assignment
        self._next_id += 1
        self._last_changed = assignment.created_at
        return assignment

    def active_assignments(self, target: str) -> tuple[EvidenceAssignment, ...]:
        """Return the assignments currently contributing evidence to a target."""
        return tuple(
            self._assignments[identity]
            for identity in sorted(
                {identity for identity in self._current[target].values() if identity is not None}
            )
        )

    def _active_components(self, target: str) -> list[EvidenceComponent]:
        return [
            component
            for assignment in self.active_assignments(target)
            for component in assignment.components
            if self._current[target].get(component.source_key) == assignment.id
        ]

    def consolidate(
        self, target: str, sources: Sequence[Any] | None = None, *, created_by: Any = None
    ) -> EvidenceAssignment:
        """Combine active evidence while preserving per-source contributions for exact retraction."""
        with self._lock:
            requested = {_source_key(source) for source in sources} if sources is not None else None
            components = tuple(
                component
                for component in self._active_components(target)
                if requested is None or component.source_key in requested
            )
            if not components or requested is not None and len(components) != len(requested):
                raise ContractError("consolidation requires active logical evidence")
            # Keeping per-source sufficient contributions permits exact retraction,
            # dependency filtering, and shared-cap recomputation after raw deletion.
            assignment = self._make_assignment(target, components, created_by)
            self._replace_current(
                target, {component.source_key for component in components}, assignment, created_by
            )
            return assignment

    def _gather(self, target: str, scale: float = 1.0) -> list[tuple[EvidenceComponent, float]]:
        contract = self.target(target)
        result = [(component, scale) for component in self._active_components(target)]
        if contract.upstream:
            result.extend(self._gather(contract.upstream, scale * contract.applicability))
        return result

    def _prior_coordinates(
        self, contract: BeliefTarget
    ) -> tuple[tuple[float, ...], tuple[float, ...]]:
        if contract.upstream:
            base, residual = self._prior_coordinates(self.target(contract.upstream))
            return tuple(value * contract.applicability for value in base), tuple(
                value * contract.applicability for value in residual
            )
        if contract.alternatives:
            raw = _center(tuple(math.log(value) for value in contract.prior))
        else:
            probability = contract.prior[0]
            raw = (math.log(probability / (1 - probability)),)
        zeros = tuple(0.0 for _ in raw)
        return (raw, zeros) if contract.prior_backed else (zeros, raw)

    def read(
        self, target: str, *, valid_at: datetime | None = None, known_at: datetime | None = None
    ) -> BeliefReading | Any:
        """Resolve a target's belief with dependency filtering and unsupported-influence caps.

        Return UNKNOWN when the requested knowledge time predates the available state.
        """
        with self._lock:
            if (
                known_at is not None
                and self._last_changed is not None
                and timestamp(known_at) < self._last_changed
            ):
                return UNKNOWN
            scope = self._members.get(str(target))
            if scope is not None:
                reading = self.read(scope, valid_at=valid_at, known_at=known_at)
                if reading is UNKNOWN:
                    return reading
                # One alternative of a scope reads as a binary belief: its Profile
                # probability with the support of the scope as a whole.
                return BeliefReading(
                    str(target),
                    reading.for_alternative(str(target)),
                    reading.stats,
                    None,
                )
            contract = self.target(target)
            if contract.alternatives:
                cap = math.log(3 * (len(contract.alternatives) - 1))
            else:
                cap = math.log(3)
            base, residual = self._prior_coordinates(contract)
            magnitude = _magnitude(residual)
            if magnitude > cap:
                residual = tuple(value * cap / magnitude for value in residual)
            own_keys = {component.source_key for component in self._active_components(target)}
            candidates: dict[str, tuple[EvidenceComponent, float, bool]] = {}
            own = [(component, 1.0, False) for component in self._active_components(target)]
            transferred = (
                [
                    (component, scale, True)
                    for component, scale in self._gather(contract.upstream, contract.applicability)
                ]
                if contract.upstream
                else []
            )
            for component, scale, prior in own + transferred:
                if prior and component.source_key in own_keys:
                    continue
                if (
                    valid_at is not None
                    and isinstance(component.observed_scope, tuple)
                    and len(component.observed_scope) == 2
                ):
                    start, end = component.observed_scope
                    at = timestamp(valid_at)
                    if (
                        start is not None
                        and at < timestamp(start)
                        or end is not None
                        and at >= timestamp(end)
                    ):
                        continue
                previous = candidates.get(component.dependency_root)
                # Prefer direct sources, never a source because it is favorable.
                order = (component.dependency_depth, prior, component.source_key)
                if previous is None or order < (
                    previous[0].dependency_depth,
                    previous[2],
                    previous[0].source_key,
                ):
                    candidates[component.dependency_root] = (component, scale, prior)
            approximate_mass = _magnitude(residual) + sum(
                component.mass * scale
                for component, scale, _ in candidates.values()
                if not component.backed
            )
            attenuation = min(1.0, cap / approximate_mass) if approximate_mass else 1.0
            logits = [value + attenuation * residual[index] for index, value in enumerate(base)]
            support = prior_support = 0.0
            own_masses, own_effects = [], []
            for component, scale, prior in candidates.values():
                factor = scale * (1.0 if component.backed else attenuation)
                for index, effect in enumerate(component.contribution):
                    logits[index] += factor * effect
                mass = component.mass * factor
                if prior:
                    prior_support += mass
                else:
                    support += mass
                    own_masses.append(mass)
                    own_effects.append(_magnitude(component.contribution) * factor)
            profile = None
            if contract.alternatives:
                maximum = max(logits)
                values = [math.exp(value - maximum) for value in logits]
                normalizer = sum(values)
                profile = freeze(
                    dict(zip(contract.alternatives, (value / normalizer for value in values)))
                )
                strength = max(profile.values())
            else:
                strength = _sigmoid(logits[0])
            stats = EvidenceStats(
                len(own_masses), max(own_masses, default=0.0), max(own_effects, default=0.0)
            )
            return BeliefReading(
                target, BeliefData(strength, support, prior_support), stats, profile
            )

    def assess_likelihoods(
        self,
        target: str,
        source_ref: Any,
        likelihoods: Mapping[str, float] | Sequence[float],
        **kwargs: Any,
    ) -> EvidenceAssignment:
        """Assess likelihoods keyed by alternatives, or by ``false``/``true``.

        A binary sequence is ordered as [P(observation|false), P(observation|true)].
        Mapping insertion order never determines the state of a likelihood.
        """
        contract = self.target(target)
        if contract.alternatives:
            if not isinstance(likelihoods, Mapping) or set(likelihoods) != set(
                contract.alternatives
            ):
                raise ContractError("scope likelihoods must identify every alternative")
            values = [float(likelihoods[key]) for key in contract.alternatives]
        else:
            if isinstance(likelihoods, Mapping):
                if set(likelihoods) != {"false", "true"}:
                    raise ContractError("binary likelihoods must identify false and true")
                values = [float(likelihoods[state]) for state in ("false", "true")]
            else:
                values = list(likelihoods)
            if len(values) != 2:
                raise ContractError(
                    "binary likelihoods are [P(observation|false), P(observation|true)]"
                )
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ContractError(
                "likelihoods must be positive and finite; smoothing belongs to the observation model"
            )
        contribution = (
            dict(zip(contract.alternatives, map(math.log, values)))
            if contract.alternatives
            else math.log(values[1]) - math.log(values[0])
        )
        return self.assign(target, source_ref, contribution, **kwargs)

    def snapshot(self) -> dict:
        """Capture belief targets, assignment history and current source contributions."""
        with self._lock:
            return {
                "targets": [json_value(target) for target in self._targets.values()],
                "assignments": [
                    json_value(assignment) for assignment in self._assignments.values()
                ],
                "current": json_value(self._current),
                "next_id": self._next_id,
                "last_changed": self._last_changed.isoformat() if self._last_changed else None,
                "assessed": dict(self._assessed),
                "assessment_cursor": self._assessment_cursor,
                "basis": json_value(self._basis),
                "scopes": json_value(self._scopes),
                "withdrawn": json_value(self._withdrawn),
                "members": dict(self._members),
            }

    @classmethod
    def from_snapshot(cls, data: dict) -> BeliefStore:
        """Restore belief contracts and their active evidence from a snapshot."""
        store = cls()
        store._targets = {
            item["id"]: BeliefTarget(**restore_value(item)) for item in data["targets"]
        }
        for raw in data["assignments"]:
            item = restore_value(raw)
            item["components"] = tuple(
                EvidenceComponent(
                    **{
                        **dict(component),
                        "source_ref": freeze(component["source_ref"]),
                        "observed_scope": freeze(component["observed_scope"]),
                    }
                )
                for component in item["components"]
            )
            item["created_by"] = freeze(item["created_by"])
            assignment = EvidenceAssignment(**item)
            store._assignments[assignment.id] = assignment
        store._current = {target: dict(mapping) for target, mapping in data["current"].items()}
        store._next_id = data["next_id"]
        store._last_changed = timestamp(data["last_changed"]) if data.get("last_changed") else None
        store._assessed = dict(data["assessed"])
        store._assessment_cursor = data["assessment_cursor"]
        store._scopes = {target: dict(value) for target, value in data["scopes"].items()}
        store._members = dict(data["members"])
        store._withdrawn = {key: freeze(value) for key, value in data["withdrawn"].items()}
        store._basis = {
            target: {key: freeze(value) for key, value in mapping.items()}
            for target, mapping in data["basis"].items()
        }
        for target, mapping in store._current.items():
            if target not in store._targets or any(
                identity is not None
                and (
                    identity not in store._assignments
                    or store._assignments[identity].target != target
                )
                for identity in mapping.values()
            ):
                raise ContractError("snapshot has dangling evidence references")
        return store
