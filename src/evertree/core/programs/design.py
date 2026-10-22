"""Design profiles a Program revision declares as a module-level DESIGN literal.

Core reads module literals from source without importing candidate code. Pydantic
checks presence and shape; reviewers and Evaluation check substance.
"""

from __future__ import annotations

import ast

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ProgramDesign(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    applicability: str = Field(
        min_length=1,
        description="Conditions of applicability and material assumptions; "
        "what to do when it is unknown whether they hold.",
    )
    adaptation: str = Field(
        min_length=1,
        description="How to detect when assumptions are no longer valid or conditions "
        "change; what response is planned and who is responsible for revision.",
    )
    learning: str = Field(
        min_length=1,
        description="What is learned, from which data, by whom, and when; how improvement "
        "is checked, or why the mechanism is fixed.",
    )


class PolicyDesign(ProgramDesign):
    exploration: str = Field(
        min_length=1,
        description="Where and by what mechanism useful new experience is obtained; how risk "
        "and budget are handled; which programs are responsible, or why exploration is not used.",
    )


def design_profile(*, meta: bool, policy: bool) -> type[ProgramDesign] | None:
    """Select the required profile; only action-selecting and lifecycle Programs need one."""
    return PolicyDesign if meta or policy else None


def read_literal(source: str, path: str, name: str) -> dict | None:
    """Extract a module-level literal mapping, or None when the module declares none."""
    tree = ast.parse(source, filename=path)
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            try:
                value = ast.literal_eval(node.value)
            except ValueError as error:
                raise ValueError(f"{name} must be a literal mapping: {path}") from error
            if not isinstance(value, dict):
                raise ValueError(f"{name} must be a literal mapping: {path}")
            return value
    return None


def check_design(source: str, path: str, profile: type[ProgramDesign]) -> None:
    """Require a complete design of the profile in the Program's entry module."""
    design = read_literal(source, path, "DESIGN")
    if design is None:
        raise ValueError(f"{path} must declare DESIGN answering {profile.__name__}")
    try:
        profile.model_validate(design)
    except ValidationError as error:
        raise ValueError(f"Invalid {profile.__name__} in {path}: {error}") from error
