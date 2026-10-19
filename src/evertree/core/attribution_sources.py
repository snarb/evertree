"""Semantically bound numeric results and read-only Program property computations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from .attribution import PropertyDefinition, PropertyReading, validate_parameters
from .attribution_population import convert_value, finite_number
from .beliefs import element_target
from .contracts import ProgramResult
from .graph.matching import values_equal
from .graph.types import Facet
from .values import UNKNOWN, ContractError, freeze, json_value, timestamp, utcnow


def typed_value(value, definition, unit):
    """Validate a scale value and convert numeric estimates without discarding their shape."""
    if definition.scale in {"nominal", "ordinal"}:
        if not any(values_equal(value, allowed) for allowed in definition.classes):
            raise ContractError("Result class is outside the property's declared scale")
        if unit is not None:
            raise ContractError("Categorical results cannot carry a numeric unit")
        return value
    target_unit = definition.unit or unit

    def number(item):
        return convert_value(item, unit, target_unit)

    if not isinstance(value, Mapping):
        return number(value)
    if definition.scale == "circular":
        raise ContractError("Circular estimates require a scalar value")
    kind = value.get("kind")
    if kind == "interval" and set(value) == {"kind", "lower", "upper"}:
        lower, upper = number(value["lower"]), number(value["upper"])
        if lower > upper:
            raise ContractError("Interval bounds must be ordered")
        return {"kind": kind, "lower": lower, "upper": upper}
    if kind == "normal" and set(value) == {"kind", "mean", "stddev"}:
        mean, stddev = number(value["mean"]), number(value["stddev"])
        if stddev < 0:
            raise ContractError("A distribution's standard deviation cannot be negative")
        return {"kind": kind, "mean": mean, "stddev": stddev}
    if kind == "quantiles" and set(value) == {"kind", "quantiles"}:
        rows = value["quantiles"]
        if not isinstance(rows, (list, tuple)) or len(rows) < 2:
            raise ContractError("A quantile estimate requires at least two quantiles")
        quantiles = []
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {"p", "value"}:
                raise ContractError("A quantile requires probability and value")
            probability, item = finite_number(row["p"]), number(row["value"])
            if (
                not 0 <= probability <= 1
                or quantiles
                and (probability <= quantiles[-1]["p"] or item < quantiles[-1]["value"])
            ):
                raise ContractError("Quantiles require increasing probabilities and ordered values")
            quantiles.append({"p": probability, "value": item})
        return {"kind": kind, "quantiles": quantiles}
    raise ContractError("Unsupported typed numeric result")


def validate_saved_result(record, nodes):
    """Validate a saved result's semantic identities, conditions, times and scale before commit."""
    required = {"subject", "property", "conditions", "value_U", "unit"}
    if not isinstance(record, Mapping) or set(record) - {"valid_from", "valid_until"} != required:
        raise ContractError("Saved property results require a complete semantic binding")
    if any(
        type(record[key]) is not int or record[key] not in nodes for key in ("subject", "property")
    ):
        raise ContractError(
            "Saved property results require existing subject and property identities"
        )
    prop = nodes[record["property"]]
    if prop.kind != "property" or "attribution" not in prop.properties:
        raise ContractError("Saved results require an explicitly declared property")
    definition = PropertyDefinition(id=prop.id, **prop.properties["attribution"])
    if definition.source != "result":
        raise ContractError("Saved result property must declare source=result")
    validate_parameters(record["conditions"])
    if set(definition.required_parameters) - record["conditions"].keys():
        raise ContractError("Saved result is missing required property parameters")
    definition.validate_inputs(record["conditions"], nodes)
    if any(
        kind == "node" and record["conditions"].get(name) not in nodes
        for name, kind in definition.parameter_types.items()
        if name in record["conditions"]
    ):
        raise ContractError("Saved result node parameters require existing graph identities")
    start, end = record.get("valid_from"), record.get("valid_until")
    if start is not None:
        start = timestamp(start)
    if end is not None:
        end = timestamp(end)
    if start is not None and end is not None and start >= end:
        raise ContractError("Saved result interval must be nonempty and half-open")
    typed_value(record["value_U"], definition, record["unit"])


def _result_recency(graph, node):
    """Rank corrections to the saved result without promoting descriptive metadata edits."""
    for change in reversed(graph.changes_of(node.id)):
        before, after = change.before.get(node.id), change.after[node.id]
        if before is None or not values_equal(
            before.properties.get("attribution_result"), after.properties.get("attribution_result")
        ):
            return change.at, change.seq, node.id
    raise AssertionError("Saved result has no retained creation")


def read_saved_result(runtime, subjects, definition, at, known_at, parameters):
    """Select immutable graph-backed outputs and read their current shared belief assessment."""
    candidates = []
    for node in runtime.graph.nodes():
        record = node.properties.get("attribution_result")
        if not record or record["subject"] not in subjects or record["property"] != definition.id:
            continue
        if not values_equal(record["conditions"], parameters):
            continue
        start, end = record.get("valid_from"), record.get("valid_until")
        if start is not None and at < timestamp(start) or end is not None and at >= timestamp(end):
            continue
        if any(key in record and record[key] is None for key in ("valid_from", "valid_until")):
            return UNKNOWN
        subject = runtime.graph.get(record["subject"])
        if isinstance(subject, Facet) and subject.applicability(at) != "applicable":
            return UNKNOWN
        try:
            belief = runtime.beliefs.read(element_target(node), valid_at=at, known_at=known_at)
        except KeyError:
            belief = None
        if belief is UNKNOWN:
            return UNKNOWN
        rank = _result_recency(runtime.graph, node)
        if definition.selection == "max_support":
            rank = (belief.support if belief else 0, *rank)
        candidates.append((rank, node, record, belief))
    if not candidates:
        return UNKNOWN
    if definition.scale in {"nominal", "ordinal"}:
        profile = runtime.classification_profile(
            [(node, record["value_U"]) for _, node, record, _ in candidates],
            definition,
            at,
            known_at,
            parameters,
        )
        if profile is not None:
            return profile
    if definition.selection == "unique" and len(candidates) != 1:
        return UNKNOWN
    _, node, record, belief = max(candidates, key=lambda candidate: candidate[0])
    value = typed_value(record["value_U"], definition, record["unit"])
    if belief is not None:
        if belief.profile is not None:
            value = None
        else:
            belief = belief.data
    return PropertyReading(
        freeze(value),
        belief,
        (node.id,),
        at,
        known_at,
        freeze(parameters),
        definition.unit or record["unit"],
    )


def read_retained_program_result(runtime, subject, definition, at, parameters):
    """Read an exact completed historical computation from its retained execution trace."""
    memory = getattr(runtime, "memory", None)
    if memory is None or runtime.graph.known_at is None or definition.program is None:
        return UNKNOWN
    arguments = {
        "subject": subject,
        "property": definition.id,
        "valid_at": at.isoformat(),
        "known_at": None,
        "parameters": parameters,
    }
    candidates = []
    for event in memory.events:
        run = memory.get_run(event.program_run)
        if (
            run.program != definition.program
            or run.status != "completed"
            or run.run_mode not in {"live", "replay"}
            or event.status != "completed"
            or not isinstance(event.output, Mapping)
            or event.output.get("type") != "run_finished"
            or not values_equal(run.arguments, arguments)
        ):
            continue
        reference = memory.output_ref(event, ("result", "result"))
        output = memory.resolve(reference)
        request = {
            "program": definition.program,
            "arguments": arguments,
            "definition": json_value(definition),
        }
        reading = finish_program_read(runtime, request, output)
        candidates.append((event.occurred_at, event.seq, reading, run, reference))
    if not candidates or definition.selection == "unique" and len(candidates) != 1:
        return UNKNOWN
    _, _, reading, run, reference = max(candidates, key=lambda item: item[:2])
    if reading is UNKNOWN:
        return UNKNOWN
    return replace(
        reading,
        known_at=runtime.graph.known_at,
        provenance=freeze(
            {
                "program": run.program,
                "program_run": run.id,
                "revision": run.base_commit_sha,
                "result": reference,
            }
        ),
    )


def prepare_program_read(
    runtime, subject, property, *, valid_at=None, known_at=None, parameters=None, point_policy=None
):
    """Read ordinary sources or prepare an explicitly bound active model Program call."""
    parameters = {} if parameters is None else parameters
    validate_parameters(parameters)
    known = timestamp(known_at) if known_at is not None else None
    if known is not None and runtime.graph.known_at != known:
        historical = runtime.historical_loader(known) if runtime.historical_loader else None
        if historical is None or historical.graph.known_at != known:
            return UNKNOWN
        return prepare_program_read(
            historical,
            subject,
            property,
            valid_at=valid_at,
            known_at=known,
            parameters=parameters,
            point_policy=point_policy,
        )
    resolved = []
    for identity in (subject, property):
        matches = runtime.graph.lookup(identity)
        if len(matches) != 1:
            return {"status": "ambiguous" if matches else "not_found"}
        resolved.append(matches[0].id)
    subject, property = resolved
    definition = runtime.definitions().get(property)
    if definition is None:
        return UNKNOWN
    missing = set(definition.required_parameters) - parameters.keys()
    if missing:
        return {"status": "needs_parameters", "required_parameters": sorted(missing)}
    at = timestamp(valid_at or utcnow())
    reading = runtime.read_property(
        subject,
        property,
        valid_at=valid_at,
        known_at=known,
        _compute=False,
        point_policy=point_policy,
        **parameters,
    )
    if reading is not UNKNOWN or definition.source != "program":
        return reading
    node = runtime.graph.get(subject)
    if not runtime.applies(subject, definition) or (
        isinstance(node, Facet) and node.applicability(at) != "applicable"
    ):
        return UNKNOWN
    # Saved historical state cannot borrow today's executable code or model state.
    if known is not None or runtime.graph.known_at is not None:
        return runtime.point_view(
            read_retained_program_result(runtime, subject, definition, at, parameters), point_policy
        )
    if definition.program is None:
        return UNKNOWN
    try:
        program = runtime.graph.get(definition.program)
    except KeyError:
        return UNKNOWN
    if (
        program.kind != "program"
        or program.properties.get("role") != "model"
        or program.properties.get("active", True) is not True
    ):
        return UNKNOWN
    return {
        "status": "requires_computation",
        "program": program.id,
        "arguments": {
            "subject": subject,
            "property": property,
            "valid_at": at.isoformat(),
            "known_at": None,
            "parameters": json_value(parameters),
        },
        "definition": json_value(definition),
    }


def finish_program_read(runtime, request, output):
    """Check the bound Program's result; malformed outputs fail instead of becoming unknown."""
    arguments = request["arguments"]
    definition = runtime.definitions().get(arguments["property"])
    if definition is None or not values_equal(json_value(definition), request["definition"]):
        raise ContractError("Property definition changed during computation")
    if definition.program != request["program"]:
        raise ContractError("Computed result does not belong to the property's Program")
    if output is UNKNOWN or output == {"$unknown": True}:
        return UNKNOWN
    expected = {"subject", "property", "valid_at", "known_at", "conditions", "value_U", "unit"}
    if not isinstance(output, Mapping) or set(output) != expected:
        raise ContractError("Computed property output requires a complete semantic binding")
    if (
        not values_equal(output["subject"], arguments["subject"])
        or not values_equal(output["property"], arguments["property"])
        or not values_equal(output["conditions"], arguments["parameters"])
    ):
        raise ContractError("Computed result has different subject, property or conditions")
    if (
        timestamp(output["valid_at"]) != timestamp(arguments["valid_at"])
        or output["known_at"] != arguments["known_at"]
    ):
        raise ContractError("Computed result has different temporal meaning")
    value = typed_value(output["value_U"], definition, output["unit"])
    return PropertyReading(
        freeze(value),
        None,
        (),
        timestamp(output["valid_at"]),
        None,
        freeze(output["conditions"]),
        definition.unit or output["unit"],
    )


async def read_property(
    step,
    call_program,
    subject,
    property,
    *,
    valid_at=None,
    known_at=None,
    parameters=None,
    point_policy=None,
):
    """Execute one prepared model child outside the gateway, preserving the ordinary call chain."""
    request = await step(
        "attribution.prepare_read",
        {
            "subject": subject,
            "property": property,
            "valid_at": valid_at,
            "known_at": known_at,
            "parameters": {} if parameters is None else parameters,
            "point_policy": point_policy,
        },
    )
    if not isinstance(request, Mapping) or request.get("status") != "requires_computation":
        return request
    result = await call_program(request["program"], request["arguments"])
    output = result.result if isinstance(result, ProgramResult) else result["result"]
    return await step("attribution.finish_read", {"request": request, "output": output})


def prepare_selection(
    runtime, subjects, *, filters=(), order_by=None, limit=20, valid_at=None, parameters=None
):
    """Prepare only the computed sources needed by a validated selection."""
    from .attribution_selection import selection_contract

    properties = selection_contract(runtime, subjects, filters, order_by, limit)
    parameters = {} if parameters is None else parameters
    validate_parameters(parameters)
    valid_at = timestamp(valid_at or utcnow())
    arguments = json_value(
        {
            "subjects": subjects,
            "filters": filters,
            "order_by": order_by,
            "limit": limit,
            "valid_at": valid_at.isoformat(),
            "parameters": parameters,
        }
    )
    requests = []
    for subject in dict.fromkeys(subjects):
        for prop in properties:
            if runtime.definitions()[prop].source != "program":
                continue
            request = prepare_program_read(
                runtime, subject, prop, valid_at=valid_at, parameters=parameters
            )
            if isinstance(request, Mapping) and request.get("status") == "requires_computation":
                requests.append(request)
    return {"arguments": arguments, "graph_revision": runtime.graph.revision, "requests": requests}


def finish_selection(runtime, plan, outputs):
    """Combine validated Program outputs with Core's own ordinary and Profile readings."""
    from .attribution_selection import select_properties, selection_contract

    if runtime.graph.revision != plan["graph_revision"]:
        raise ContractError("Graph changed during property selection")
    if not isinstance(outputs, (list, tuple)) or len(outputs) != len(plan["requests"]):
        raise ContractError("Selection requires one output per requested computation")
    arguments = plan["arguments"]
    properties = selection_contract(
        runtime,
        arguments["subjects"],
        arguments["filters"],
        arguments["order_by"],
        arguments["limit"],
    )
    readings = {
        (subject, prop): runtime.read_property(
            subject,
            prop,
            valid_at=arguments["valid_at"],
            _compute=False,
            **arguments["parameters"],
        )
        for subject in dict.fromkeys(arguments["subjects"])
        for prop in properties
    }
    completed = set()
    for request, output in zip(plan["requests"], outputs, strict=True):
        key = request["arguments"]["subject"], request["arguments"]["property"]
        if key not in readings or key in completed:
            raise ContractError("Selection computation does not match its requested candidates")
        readings[key] = finish_program_read(runtime, request, output)
        completed.add(key)
    return select_properties(runtime, **arguments, readings=readings)


async def select_properties(
    step,
    call_program,
    subjects,
    *,
    filters=(),
    order_by=None,
    limit=20,
    valid_at=None,
    parameters=None,
):
    """Read requested model sources serially, then select using trusted Core beliefs and values."""
    plan = await step(
        "attribution.prepare_selection",
        {
            "subjects": subjects,
            "filters": filters,
            "order_by": order_by,
            "limit": limit,
            "valid_at": valid_at,
            "parameters": parameters,
        },
    )
    outputs = []
    for request in plan["requests"]:
        result = await call_program(request["program"], request["arguments"])
        outputs.append(result.result if isinstance(result, ProgramResult) else result["result"])
    return await step("attribution.finish_selection", {"plan": plan, "outputs": outputs})
