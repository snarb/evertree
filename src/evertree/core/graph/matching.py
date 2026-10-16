"""Typed fact selection shared by declared views and interactive graph reads."""

from collections.abc import Mapping

from ..values import UNKNOWN, ContractError
from .types import Clause, Slot

NODE_TYPES = frozenset({"node", "concept", "prototype", "instance", "facet"})


def _equal(left, right):
    # JSON booleans must not match numeric conditions such as enabled == 0.
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return left == right


def node_ids(fact, relation):
    """Yield participant identities from a fact's declared node-valued slots."""
    for slot in relation.signature:
        if slot.value_type in NODE_TYPES:
            value = fact.args.get(slot.label)
            yield from (
                value if isinstance(value, (list, tuple)) else (() if value is None else (value,))
            )


def compare(value, clause):
    """Evaluate a scalar or collection predicate with JSON-aware equality and null handling."""
    if clause.op == "is_null":
        return value is None
    if clause.op == "not_null":
        return value is not None
    if value is None:
        return False
    if clause.op in {"<", "<=", ">", ">="} and (
        type(value) not in {int, float, str} or type(clause.value) not in {int, float, str}
    ):
        raise ContractError("ordered predicates require a scalar ordered field")
    operations = {
        "==": lambda: _equal(value, clause.value),
        "!=": lambda: not _equal(value, clause.value),
        "in": lambda: any(_equal(value, item) for item in clause.value),
        "not_in": lambda: not any(_equal(value, item) for item in clause.value),
        "<": lambda: value < clause.value,
        "<=": lambda: value <= clause.value,
        ">": lambda: value > clause.value,
        ">=": lambda: value >= clause.value,
        "contains": lambda: (
            clause.value in value
            if isinstance(value, str)
            else any(_equal(clause.value, item) for item in value)
        ),
    }
    try:
        return operations[clause.op]()
    except TypeError as exc:
        raise ContractError("predicate is incompatible with field type") from exc


def validate_clause(graph, slot, clause, nodes=None):
    """Check a query predicate against its slot type and referenced graph nodes."""
    nodes = graph._nodes if nodes is None else nodes
    if clause.op in {"is_null", "not_null"}:
        return
    if clause.op in {"<", "<=", ">", ">="} and (
        slot.value_type not in {"number", "integer", "string"} or slot.arity.startswith("list")
    ):
        raise ContractError("ordered predicates require a scalar ordered field")
    if clause.op == "contains":
        if not slot.arity.startswith("list") and slot.value_type != "string":
            raise ContractError("contains requires a list or string field")
        graph._validate_scalar(clause.value, slot, nodes)
    elif clause.op in {"in", "not_in"}:
        if not isinstance(clause.value, (tuple, list, frozenset)):
            raise ContractError("membership predicate requires a list of values")
        for value in clause.value:
            graph._validate_slot(value, slot, nodes)
    else:
        graph._validate_slot(clause.value, slot, nodes)


def prepare(graph, relation, bindings, where):
    """Validate relation bindings and compile supported fact, argument and condition predicates."""
    slots = {slot.label: slot for slot in relation.signature}
    for label, value in bindings.items():
        if label not in slots:
            raise ContractError(f"Unknown slot: {label}")
        graph._validate_slot(value, slots[label], graph._nodes)
    clauses = []
    for raw in where:
        clause = Clause(**raw)
        namespace, _, label = clause.field.partition(".")
        if namespace == "args" and label in slots:
            slot = slots[label]
        elif namespace == "fact" and label in {"id", "name"}:
            slot = Slot(label, "integer" if label == "id" else "string")
        elif namespace == "conditions" and label and "." not in label:
            # Condition names have no declared schema. Their values are checked on read.
            if clause.op in {"in", "not_in"} and not isinstance(clause.value, (tuple, list)):
                raise ContractError("membership predicate requires a list of values")
            clauses.append(clause)
            continue
        else:
            raise ContractError(f"Unknown filter field: {clause.field}")
        validate_clause(graph, slot, clause)
        clauses.append(clause)
    return tuple(clauses)


def predicate_matches(graph, fact, relation, clauses, *, valid_at=None, known_at=None):
    """Evaluate fact predicates, preserving UNKNOWN when required belief data is unavailable."""
    unknown = False
    slots = {slot.label for slot in relation.signature}
    for clause in clauses:
        field = clause.field
        if field.startswith("args."):
            value = fact.args.get(field[5:])
        elif field.startswith("conditions."):
            conditions = fact.properties.get("conditions", {})
            value = conditions.get(field[11:]) if isinstance(conditions, Mapping) else None
        elif field.startswith("fact."):
            value = getattr(fact, field[5:])
        elif field in slots:
            value = fact.args.get(field)
        elif field in {"id", "name"}:
            value = getattr(fact, field)
        else:
            if graph.belief_reader is None or fact.belief_target is None:
                unknown = True
                continue
            try:
                belief = graph.belief_reader(
                    fact.belief_target, valid_at=valid_at, known_at=known_at
                )
            except KeyError:
                belief = UNKNOWN
            if belief is UNKNOWN:
                unknown = True
                continue
            profile = getattr(belief, "profile", None)
            if field == "strength" and profile is not None:
                alternative = str(fact.args.get("class"))
                if relation.name != "CLASSIFIED_AS" or alternative not in profile:
                    unknown = True
                    continue
                value = profile[alternative]
            else:
                value = getattr(getattr(belief, "data", belief), field)
        if not compare(value, clause):
            return False
    return UNKNOWN if unknown else True


def match_fact(graph, fact, relation, bindings, clauses, *, valid_at=None, known_at=None):
    """Combine bindings, predicates and Facet applicability into a match status or no match."""
    if any(fact.args.get(key) != value for key, value in bindings.items()):
        return None
    temporal = graph.fact_applicability(fact, valid_at) if valid_at is not None else "applicable"
    if temporal == "outside":
        return None
    accepted = predicate_matches(
        graph, fact, relation, clauses, valid_at=valid_at, known_at=known_at
    )
    if accepted is False:
        return None
    return "unknown" if accepted is UNKNOWN else temporal
