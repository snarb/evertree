"""Explicit, resumable products of a bounded conscious iteration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)

from ..memory.types import TraceOutputRef
from .schema import ResponseSchema


def trace_reference(value: Any) -> TraceOutputRef:
    """Validate references before dataclass parsing can coerce their identities."""
    if isinstance(value, TraceOutputRef):
        event_ref, output_path = value.event_ref, value.output_path
    elif isinstance(value, Mapping) and set(value) <= {"event_ref", "output_path"}:
        event_ref, output_path = value.get("event_ref"), value.get("output_path", ())
    else:
        raise ValueError("Expected a trace output reference")
    if type(event_ref) is not int or event_ref <= 0:
        raise ValueError("Trace references require a positive integer event identity")
    if not isinstance(output_path, (list, tuple)) or any(
        type(part) not in (str, int) or (isinstance(part, int) and part < 0) for part in output_path
    ):
        raise ValueError("Trace output paths require string keys or nonnegative integer indices")
    return TraceOutputRef(event_ref, tuple(output_path))


class ConsciousStepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    local_goal: Annotated[
        StrictStr, Field(min_length=1, description="One local objective for this iteration.")
    ]
    expected_result: Annotated[
        StrictStr,
        Field(min_length=1, description="The intermediate result that ends this step."),
    ]
    active_time_minutes: Annotated[
        float,
        Field(
            strict=True,
            gt=0,
            allow_inf_nan=False,
            description="Positive time limit in minutes, within the remaining task allowance.",
        ),
    ]


class AnalyticalNote(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: Annotated[
        StrictStr,
        Field(min_length=1, description="Readable work product with relevant grounds and limits."),
    ]
    source_refs: list[TraceOutputRef] = Field(
        default_factory=list,
        description="Available trace references supporting this note; use [] when none exist.",
    )
    kind: Literal["note", "claim"] = Field(
        "note", description="note for a connected analysis; claim for one assessable assertion."
    )

    @field_validator("source_refs", mode="before")
    @classmethod
    def validate_source_refs(cls, value: Any) -> list[TraceOutputRef]:
        if not isinstance(value, (list, tuple)):
            # Pydantic wraps ValueError as a validation error, but lets TypeError escape.
            raise ValueError("source_refs must be a sequence of trace references")  # noqa: TRY004
        return [trace_reference(item) for item in value]


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    step: Annotated[
        StrictStr, Field(min_length=1, description="Work to perform or already performed.")
    ]
    status: Annotated[
        StrictStr, Field(min_length=1, description="Current progress of this plan item.")
    ]


class ConsciousStepResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    analysis: AnalyticalNote = Field(
        description="This iteration's analytical result, possibly partial."
    )
    findings: list[AnalyticalNote] = Field(
        default_factory=list, description="Optional separately selected insights or hypotheses."
    )
    plan: list[PlanStep] = Field(
        default_factory=list,
        description="Complete updated working plan; use clear descriptions and statuses for steps.",
    )
    progress: StrictStr = Field("", description="Brief progress summary, including any obstacle.")
    unresolved_questions: list[Annotated[StrictStr, Field(min_length=1)]] = Field(
        default_factory=list, description="Questions still needed to advance or verify the task."
    )
    disposition: Literal["continue", "waiting", "propose_completion", "failed"]
    next_step: ConsciousStepSpec | None = Field(
        None, description="Required for continue; the next bounded iteration to perform."
    )
    user_message: Annotated[StrictStr, Field(min_length=1)] | None = Field(
        None,
        description="Only this text is delivered to the user; required for propose_completion.",
    )

    @classmethod
    def response_schema(cls):
        return cls.model_json_schema(schema_generator=ResponseSchema)

    @model_validator(mode="after")
    def validate_continuation(self) -> Self:
        if self.disposition == "continue" and self.next_step is None:
            raise ValueError("Continuing requires a next_step with a local goal and budget")
        if self.disposition == "propose_completion" and self.user_message is None:
            raise ValueError("Proposed completion requires a separate user_message")
        return self
