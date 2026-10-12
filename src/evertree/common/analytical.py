"""Typed analytical products shared by Programs and conscious iterations."""

from copy import deepcopy

from evertree.core.cognition.steps import AnalyticalNote, trace_reference


def analytical_schema(schema):
    result = deepcopy(schema)
    note = AnalyticalNote.model_json_schema()
    result.setdefault("$defs", {}).update(note.pop("$defs", {}))
    result["properties"]["analysis"] = note
    result["properties"]["findings"] = {"type": "array", "items": deepcopy(note)}
    result["required"].append("analysis")
    return result


def validate_analytical_output(output, context):
    """Keep Program conclusions linked to supplied experience, not invented sources."""
    result = output["result"]
    supplied = [trace_reference(ref) for ref in context.get("experience_refs", ())]
    analysis = AnalyticalNote.model_validate(result["analysis"])
    findings = [AnalyticalNote.model_validate(note) for note in result.get("findings", ())]
    for note in (analysis, *findings):
        for reference in note.source_refs:
            if not any(
                source.event_ref == reference.event_ref
                and reference.output_path[: len(source.output_path)] == source.output_path
                for source in supplied
            ):
                raise ValueError("Analytical source references must come from supplied experience")
    result["analysis"] = analysis.model_dump(mode="json")
    result["findings"] = [note.model_dump(mode="json") for note in findings]
    return output
