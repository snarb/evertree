"""Typed Program access to semantic graph reads."""

from __future__ import annotations

from typing import Any

from ..contracts import ProgramContext


async def describe(ctx: ProgramContext, subject: str | int) -> Any:
    """Describe one graph subject with its properties and relations."""
    return await ctx.step("graph.describe", {"subject": subject}, journal=False)


async def read(ctx: ProgramContext, name: str, arguments: dict) -> Any:
    """Run a graph read tool (for example query, walk or read_property) by name with its arguments."""
    if name in {"read_property", "read_property_at", "select_properties"}:
        from ..attribution_sources import read_property, select_properties
        from ..runtime.api import call_program

        async def step(method, payload):
            return await ctx.step(method, payload, journal=method.startswith("attribution.finish_"))

        async def call(program, payload):
            return await call_program(ctx, program, payload)

        if name == "select_properties":
            payload = dict(arguments)
            payload["valid_at"] = payload.pop("at", None)
            return await select_properties(step, call, **payload)
        return await read_property(
            step,
            call,
            arguments["subject"],
            arguments["property"],
            valid_at=arguments.get("at", arguments.get("valid_at")),
            known_at=arguments.get("known_at"),
            parameters=arguments.get("parameters"),
            point_policy=arguments.get("point_policy"),
        )
    return await ctx.step("graph." + name, arguments, journal=False)
