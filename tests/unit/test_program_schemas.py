"""Program response schemas meet the provider's strict structured-output contract.

Strict output rejects an object schema unless every declared property is required; a
violating schema fails each live call of its Program, which scripted tests never see.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import evertree.common.bootstrap_schemas as bootstrap
from evertree import processes


def schemas():
    modules = [bootstrap] + [
        importlib.import_module(item.name)
        for item in pkgutil.walk_packages(processes.__path__, processes.__name__ + ".")
    ]
    for module in modules:
        for name in dir(module):
            value = getattr(module, name)
            if name.endswith("SCHEMA") and isinstance(value, dict):
                yield pytest.param(value, id=f"{module.__name__}.{name}")


def loose_objects(schema, path=""):
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" in schema:
            missing = set(schema["properties"]) - set(schema.get("required", ()))
            if missing:
                yield path or "/", sorted(missing)
        for key, value in schema.items():
            yield from loose_objects(value, f"{path}/{key}")
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            yield from loose_objects(value, f"{path}[{index}]")


@pytest.mark.parametrize("schema", schemas())
def test_every_declared_property_is_required(schema):
    assert list(loose_objects(schema)) == []
