"""Durable exact source sections and their narrowly scoped integration authority."""

import hashlib
import json
from collections.abc import Mapping

from ...common.source_sections import section_context, section_value
from ..memory.types import TraceOutputRef
from ..values import ContractError, json_value


def _fragment_material(item):
    """Keep a trusted fragment's source data separate from its retained delivery envelope."""
    origin, content = item.get("origin", {}), item["content"]
    if (
        origin.get("program") == "ExperienceFragments"
        and origin.get("operator") == "experience_fragment"
        and not item["reference"].get("output_path")
        and isinstance(content, dict)
        and content.get("encoding") in {"structured", "analytical_text"}
    ):
        field = "text" if "text" in content else "value"
        if field not in content:
            raise ContractError("Retained experience fragment has no source content")
        return {
            **item,
            "reference": {**item["reference"], "output_path": [field]},
            "context_reference": item["reference"],
            "content": content[field],
            "source_reference": content["source_ref"],
            "location": content["location"],
            "source_context": content.get("context", []),
        }
    return item


def _selection(value, section):
    """Reject ambiguous or silently clipped locations before creating any retained event."""
    if not isinstance(section, dict) or set(section) - {"path", "start", "end", "keys"}:
        raise ContractError("Unknown source section fields")
    path = section.get("path")
    if not isinstance(path, list) or any(
        type(part) not in {str, int} or type(part) is int and part < 0 for part in path
    ):
        raise ContractError("Source section path must contain keys or nonnegative indices")
    selected = value
    try:
        for part in path:
            if not (
                isinstance(selected, dict)
                and type(part) is str
                or isinstance(selected, list)
                and type(part) is int
            ):
                raise ContractError("Source section path does not address structured data")
            selected = selected[part]
    except (KeyError, IndexError) as error:
        raise ContractError("Source section path is unavailable") from error
    if "keys" in section:
        keys = section["keys"]
        if (
            "start" in section
            or "end" in section
            or not isinstance(selected, dict)
            or not isinstance(keys, list)
            or not keys
            or any(type(key) is not str or key not in selected for key in keys)
            or len(set(keys)) != len(keys)
        ):
            raise ContractError("Source section keys must select distinct existing fields")
    elif "start" in section or "end" in section:
        start, end = section.get("start"), section.get("end")
        if (
            not isinstance(selected, (str, list))
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(selected)
        ):
            raise ContractError("Source section bounds must select an exact nonempty range")
    return section_value(value, section)


def prepare_sections(memory, material, sections, metadata):
    """Materialize partial selections once; whole values retain their existing addresses."""
    if not isinstance(sections, list) or not sections:
        raise ContractError("Integration sections must be a nonempty list")
    inputs = tuple(
        memory.producer_of(TraceOutputRef(**item["reference"])) for item in material["experience"]
    )
    selections = []
    for part in sections:
        if not isinstance(part, dict) or type(part.get("source")) is not int:
            raise ContractError("Source section requires an integer source index")
        index = part["source"]
        if not 0 <= index < len(material["experience"]):
            raise ContractError("Source section index is outside supplied experience")
        item = material["experience"][index]
        producer = memory.producer_of(TraceOutputRef(**item["reference"]))
        item = _fragment_material({**item, "reference": json_value(producer)})
        section = {key: value for key, value in part.items() if key != "source"}
        value = _selection(item["content"], section)
        if not any(key in section for key in ("start", "keys")):
            child = TraceOutputRef(
                producer.event_ref, (*item["reference"].get("output_path", []), *section["path"])
            )
            target = memory.producer_of(child)
            if target != child:
                if not any(
                    root.event_ref == target.event_ref
                    and target.output_path[: len(root.output_path)] == root.output_path
                    for root in inputs
                ):
                    raise ContractError("Source section points outside supplied experience")
                value = json_value(memory.resolve(target))
                event = memory.get_event(target.event_ref)
                run = memory.get_run(event.program_run)
                item = {
                    **item,
                    "origin": {
                        "program": run.program,
                        "revision": run.base_commit_sha,
                        "run_mode": run.run_mode,
                        "operator": event.operator,
                        "output_type": event.output_type,
                    },
                }
        selections.append((item, section, value))

    scope = {
        "task_id": metadata["task_id"],
        "integration_operation_id": metadata["integration_operation_id"],
    }
    revision = metadata["program"]["revision"]
    prepared = []
    with memory.transaction():
        existing = {
            event.arguments["preparation_key"]: event
            for event in memory.events
            if event.operator == "experience_fragment"
            and isinstance(event.arguments, Mapping)
            and "preparation_key" in event.arguments
            and memory.get_run(event.program_run).program == "ExperienceFragments"
            and all(
                memory.get_run(event.program_run).arguments.get(key) == value
                for key, value in scope.items()
            )
        }
        run = None
        for item, section, value in selections:
            if section == {"path": []}:
                if item.get("origin", {}).get("program") == "ExperienceFragments":
                    memory.retain(
                        TraceOutputRef(**item["reference"]), "task:" + metadata["task_id"]
                    )
                prepared.append(item)
                continue
            original = item["reference"]
            context = section_context(item["content"], section)
            details = {
                "source_reference": original,
                "location": section,
                "source_context": context,
            }
            if not any(key in section for key in ("start", "keys")):
                reference = {
                    "event_ref": original["event_ref"],
                    "output_path": [*original.get("output_path", []), *section["path"]],
                }
                prepared.append(
                    {
                        **item,
                        **details,
                        "reference": reference,
                        "content": value,
                        "context_reference": original,
                    }
                )
                continue
            field = "text" if isinstance(value, str) else "value"
            output = {
                "source_ref": original,
                "encoding": "structured",
                "location": section,
                "context": context,
                field: value,
            }
            key = hashlib.sha256(
                json.dumps(
                    {"source": original, "location": section, "revision": revision},
                    sort_keys=True,
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            event = existing.get(key)
            if event is not None and json_value(event.output) != output:
                raise ContractError("Prepared source content changed; start a new integration")
            if event is None:
                if run is None:
                    run = memory.start_run(
                        "ExperienceFragments",
                        revision,
                        scope,
                        run_mode=metadata.get("run_mode", "live"),
                    )
                event = memory.record(
                    run,
                    "experience_fragment",
                    arguments={"preparation_key": key},
                    output=output,
                    dependencies=(TraceOutputRef(**original),),
                )
                existing[key] = event
            memory.retain(event.id, "task:" + metadata["task_id"])
            producer = memory.get_run(event.program_run)
            prepared.append(
                {
                    **item,
                    **details,
                    "reference": json_value(memory.output_ref(event, (field,))),
                    "context_reference": json_value(memory.output_ref(event)),
                    "content": value,
                    "origin": {
                        "program": producer.program,
                        "revision": producer.base_commit_sha,
                        "run_mode": producer.run_mode,
                        "operator": event.operator,
                        "output_type": event.output_type,
                    },
                }
            )
        if run is not None:
            memory.finish_run(run)
    return {**material, "experience": prepared}


def authorized_fragment(memory, ref, inputs, metadata):
    """Accept only data from a Core-prepared section of this operation's supplied inputs."""
    try:
        event = memory.get_event(ref.event_ref)
        run = memory.get_run(event.program_run)
        value = json_value(event.output)
        if (
            run.program != "ExperienceFragments"
            or event.operator != "experience_fragment"
            or not isinstance(event.arguments, Mapping)
            or "preparation_key" not in event.arguments
            or run.arguments.get("task_id") != metadata["task_id"]
            or run.arguments.get("integration_operation_id") != metadata["integration_operation_id"]
            or not isinstance(value, dict)
            or not ref.output_path
            or ref.output_path[0] not in {"text", "value"}
        ):
            return False
        parent = TraceOutputRef(**value["source_ref"])
        resolved = memory.producer_of(ref)
        # A nested historical pointer is readable, but is not data inside this fragment.
        inside = (
            resolved.event_ref == ref.event_ref and resolved.output_path[:1] == ref.output_path[:1]
        )
        supplied = any(
            source.event_ref == resolved.event_ref
            and resolved.output_path[: len(source.output_path)] == source.output_path
            for source in inputs
        )
        if not inside and not supplied:
            return False
        return parent in event.dependencies and any(
            source.event_ref == parent.event_ref
            and parent.output_path[: len(source.output_path)] == source.output_path
            for source in inputs
        )
    except (KeyError, TypeError, ValueError):
        return False
