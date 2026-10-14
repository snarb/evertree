"""Existing pump knowledge for retrieval and integration flow evaluations."""

from datetime import UTC, datetime

from evertree.core.graph.types import Facet, GraphDelta, Instance, Prototype


def seed_pump_history(graph):
    equipment = Prototype(graph.reserve_id(), "Оборудование", description="Технические устройства")
    prototype = Prototype(graph.reserve_id(), "Насос", description="Pump: перекачивает жидкость")
    pump = Instance(graph.reserve_id(), "Н-1", description="Насос контура охлаждения")
    other = Instance(graph.reserve_id(), "Н-2", description="Резервный насос контура охлаждения")
    start = datetime(2026, 10, 12, 9, tzinfo=UTC)
    end = start.replace(minute=10)
    off = Facet(
        graph.reserve_id(),
        "Н-1 выключен",
        description="Рабочее состояние насоса Н-1: выключен, 12 октября 2026, 09:00–09:10 UTC.",
        valid_from=start,
        valid_until=end,
    )
    other_state = Facet(
        graph.reserve_id(),
        "Н-2 работает",
        description="Резервный насос работает в контуре охлаждения.",
        valid_from=start,
        valid_until=end.replace(minute=20),
    )
    nodes = [equipment, prototype, pump, other, off, other_state]
    nodes += [graph.new_fact("SUBTYPE_OF", {"type": prototype.id, "supertype": equipment.id})]
    nodes += [
        graph.new_fact("IDENTITY_TYPE", {"instance": obj.id, "type": prototype.id})
        for obj in (pump, other)
    ]
    nodes += [
        graph.new_fact("STATE_IDENTITY", {"facet": state.id, "instance": obj.id})
        for state, obj in ((off, pump), (other_state, other))
    ]
    graph.apply(GraphDelta(creates=tuple(nodes)), provenance="retrieval-evaluation-seed")
    return {"prototype": prototype, "pump": pump, "off": off, "other": other_state}
