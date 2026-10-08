"""In-process semantic domain fixture; models and the external index are injected."""

from types import SimpleNamespace

from evertree.core.attribution import AttributionRuntime
from evertree.core.beliefs import BeliefStore
from evertree.core.evaluation.store import EvaluationStore
from evertree.core.graph.store import GraphStore
from evertree.core.learning.state import LearningStore
from evertree.core.memory.store import TraceStore
from evertree.core.operations import CoreOperations, authorize_operation
from evertree.core.semantics.config import SemanticConfig
from evertree.core.semantics.service import SemanticService


class EmptyIndex:
    async def lexical(self, *args):
        return []

    async def vector(self, *args):
        return []

    async def close(self):
        pass


def semantic_world(*, index=None, config=None):
    graph, memory, beliefs = GraphStore(), TraceStore(), BeliefStore()
    graph.bootstrap(provenance="seed")
    attribution = AttributionRuntime(graph, beliefs)
    operations = CoreOperations(
        graph, memory, beliefs, attribution, EvaluationStore(), LearningStore(), set()
    )
    service = SemanticService(
        graph, memory, attribution, config or SemanticConfig(), index or EmptyIndex(), operations
    )
    return SimpleNamespace(
        graph=graph, memory=memory, attribution=attribution, service=service, operations=operations
    )


def context(world, model, *, role="model"):
    async def step(method, payload):
        authorize_operation(method, role)
        if method == "agent.run":
            return {"parsed": await model(payload)}
        metadata = {
            "task_id": "task",
            "run_id": "run",
            "program": {"role": role, "revision": "revision"},
        }
        if method.startswith("semantic."):
            return await world.service.execute(method, payload, metadata)
        return world.operations.execute(method, payload, metadata=metadata)

    return SimpleNamespace(step=step)


def populated_search_world(**kwargs):
    """A small real taxonomy, homonyms, states and family facts with distractors."""
    from evertree.core.graph.types import (
        AccessView,
        Facet,
        GraphDelta,
        Instance,
        Node,
        Prototype,
        RelationInstance,
        RelationType,
        Slot,
    )

    world = semantic_world(**kwargs)
    g = world.graph
    living = Prototype(g.reserve_id(), "Живое", description="Живые организмы")
    animal = Prototype(g.reserve_id(), "Животное", description="Царство животных")
    mammal = Prototype(
        g.reserve_id(), "Млекопитающее", description="Животные, кормящие детёнышей молоком"
    )
    cat = Prototype(
        g.reserve_id(),
        "Домашняя кошка",
        description="Небольшой домашний питомец семейства кошачьих, ловит мышей",
    )
    person = Prototype(g.reserve_id(), "Человек", description="Люди и их семейные отношения")
    machine = Prototype(g.reserve_id(), "Машина", description="Технические устройства")
    purr = Node(g.reserve_id(), "Мурлыканье", description="Тихий вибрирующий звук довольной кошки")
    murka = Instance(g.reserve_id(), "Мурка", description="Питомец")
    facet = Facet(g.reserve_id(), "Состояние Мурки", description="Питомец спит на подоконнике")
    mother = Instance(g.reserve_id(), "Светлана")
    anna, maria, other = (Instance(g.reserve_id(), name) for name in ("Анна", "Мария", "Вера"))
    daughter = RelationType(
        g.reserve_id(),
        "Дочь",
        description="Первый участник — ребёнок женского пола второго участника",
        signature=(Slot("daughter", "instance"), Slot("mother", "instance")),
        views=(AccessView("get_daughters", ("mother",), ("daughter",)),),
    )
    anna_state = Facet(g.reserve_id(), "Состояние Анны", description="На работе")
    maria_state = Facet(g.reserve_id(), "Состояние Марии", description="Дома")
    nodes = [
        living,
        animal,
        mammal,
        cat,
        person,
        machine,
        purr,
        murka,
        facet,
        mother,
        anna,
        maria,
        other,
        daughter,
        anna_state,
        maria_state,
    ]
    facts = [
        g.new_fact("SUBTYPE_OF", {"type": child.id, "supertype": parent.id})
        for child, parent in ((animal, living), (mammal, animal), (cat, mammal), (person, living))
    ]
    facts += [
        g.new_fact("IDENTITY_TYPE", {"instance": item.id, "type": type_.id})
        for item, type_ in (
            (murka, cat),
            (mother, person),
            (anna, person),
            (maria, person),
            (other, person),
        )
    ]
    facts += [
        g.new_fact("STATE_IDENTITY", {"facet": state.id, "instance": instance.id})
        for state, instance in ((facet, murka), (anna_state, anna), (maria_state, maria))
    ]
    kinship = [
        RelationInstance(
            g.reserve_id(),
            daughter.name,
            relation_type=daughter.id,
            description="Зафиксированное родство",
            args={"daughter": child.id, "mother": mother.id},
        )
        for child in (anna, maria)
    ]
    g.apply(GraphDelta(creates=tuple(nodes + facts + kinship)), provenance="search-corpus")
    world.targets = {
        "concept": purr,
        "prototype": cat,
        "facet": facet,
        "instance": murka,
        "relation_type": daughter,
        "relation_instance": kinship[0],
    }
    world.family = {
        "mother": mother,
        "daughters": (anna, maria),
        "facets": (anna_state, maria_state),
        "facts": kinship,
        "mammals": (mammal,),
    }
    return world
