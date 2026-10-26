"""In-process semantic domain fixture; models and the external index are injected."""

from types import SimpleNamespace
from uuid import uuid4

from evertree.core.attribution import AttributionRuntime
from evertree.core.beliefs import BeliefStore
from evertree.core.evaluation.store import EvaluationStore
from evertree.core.graph.store import GraphStore
from evertree.core.learning.state import LearningStore
from evertree.core.memory.store import TraceStore
from evertree.core.operations import CoreOperations, authorize_operation
from evertree.core.semantics.config import SemanticConfig
from evertree.core.semantics.service import SemanticService
from evertree.core.semantics.tools import CREATE_ACTIONS
from evertree.core.values import json_value


class EmptyIndex:
    async def lexical(self, *args):
        return [{"ids": []} for _ in args[1]]

    async def vector(self, *args):
        return [{"ids": []} for _ in args[1]]

    async def close(self):
        pass


def semantic_world(*, index=None, config=None):
    graph, memory, beliefs = GraphStore(), TraceStore(), BeliefStore()
    graph.bootstrap(provenance="seed")
    graph.belief_reader = beliefs.read
    attribution = AttributionRuntime(graph, beliefs)
    operations = CoreOperations(
        graph, memory, beliefs, attribution, EvaluationStore(), LearningStore(), set()
    )
    service = SemanticService(
        graph, memory, attribution, config or SemanticConfig(), index or EmptyIndex(), operations
    )
    return SimpleNamespace(
        graph=graph,
        memory=memory,
        beliefs=beliefs,
        attribution=attribution,
        service=service,
        operations=operations,
    )


def recorded_experience(world, *contents, run_mode="live", context=None):
    run = world.memory.start_run("experience", "revision", {}, run_mode=run_mode)
    refs = [
        json_value(world.memory.output_ref(world.memory.record(run, "input", output=value)))
        for value in contents
    ]
    world.memory.finish_run(run)
    return refs, {
        "task_id": "task",
        "semantic_scope": "packet",
        "run_id": "original-run",
        "program": {"role": "exec", "revision": "revision"},
        "knowledge_integration_authorized": True,
        "integration_operation_id": "packet",
        "integration_context": context or {},
    }


def recorded_messages(world, *texts, kind="user"):
    """Record user messages or tool observations the way the application stores them."""
    refs = []
    for index, text in enumerate(texts):
        run = world.memory.start_run("Observation", "revision", {"task_id": "task"})
        if kind == "user":
            source_id, value = f"input:{uuid4().hex}", {"role": "user", "content": text}
        else:
            source_id, value = f"sensor:{index}", {"reading": text}
        event = world.memory.record(
            run, "observation", arguments={"source_id": source_id}, output=value
        )
        world.memory.finish_run(run)
        refs.append(json_value(world.memory.output_ref(event)))
    return refs


def write_action(world, refs, metadata, action, *, key="write", searched=True):
    """Exercise Core validation; Program tests separately exercise the actual search path."""
    if searched and action["action"] in CREATE_ACTIONS:
        world.service.results(
            action["name"], None, [], [], 10, metadata["task_id"], scope=metadata["semantic_scope"]
        )
    return world.service.write(
        {"experience_refs": refs, "action": action, "operation_key": key}, metadata
    )


def context(
    world, model, *, role="model", integration_context=None, operation_id="packet", scope="packet"
):
    run_id = uuid4().hex
    invocation = 0
    scopes = []

    async def llm(payload, *, tools, tool_handler, stop_when=None, max_tool_calls=40):
        nonlocal scope, invocation
        invocation += 1
        scope = f"{run_id}:llm:{invocation}"

        class Finished(BaseException):
            def __init__(self, result):
                self.result = result

        names = {tool.name for tool in tools}
        calls = 0

        async def call_tool(name, arguments):
            nonlocal calls
            assert name in names, f"Undeclared tool: {name}"
            calls += 1
            assert calls <= max_tool_calls, "Model exceeded the tool-call limit"
            result = await tool_handler(name, arguments)
            if stop_when and stop_when(name, result):
                raise Finished({"tool": name, "result": result})
            return result

        try:
            result = await model(payload, call_tool)
            if result is None and "finish_section" in names:
                await call_tool("finish_section", {"complete": True, "remaining": ""})
        except Finished as finished:
            return finished.result
        return result or {"text": ""}

    async def step(method, payload, *, journal=True):
        nonlocal scope
        if method == "llm.enter":
            scopes.append(scope)
            scope = payload["invocation_id"]
            return
        if method == "llm.leave":
            assert scope == payload["invocation_id"]
            scope = scopes.pop()
            return
        authorize_operation(method, role)
        if method == "trace":
            run = world.memory.start_run("IntegrationProgress", "revision", {})
            world.memory.record(run, payload["operator"], output=json_value(payload["output"]))
            world.memory.finish_run(run)
            return
        if method == "llm.run":
            return {"parsed": await model(payload)}
        metadata = {
            "task_id": "task",
            "run_id": run_id,
            "semantic_scope": scope,
            "program": {"role": role, "revision": "revision"},
            "knowledge_integration_authorized": role == "exec",
            "integration_operation_id": operation_id,
            "integration_context": integration_context or {},
        }
        if method.startswith("semantic.") or method in {
            "graph.query",
            "graph.walk",
            "graph.sources",
            "memory.read_source",
        }:
            return await world.service.execute(method, payload, metadata)
        return world.operations.execute(method, payload, metadata=metadata)

    async def call(program, arguments):
        from evertree.processes.self_semantic_processing.self_semantic_search._model import run

        if program != "semantic_search":
            raise AssertionError("Unsupported semantic child: " + program)
        result = await run(context(world, model, role="model", scope=scope), **arguments)
        return SimpleNamespace(**result)

    return SimpleNamespace(step=step, call=call, llm=llm)


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


def structured_fact_world(*, index=None, count=96):
    """Opaque, description-free facts must be found by participants, values and conditions."""
    from evertree.core.graph.types import GraphDelta, Node, RelationInstance, RelationType, Slot

    world = semantic_world(index=index)
    graph = world.graph
    recipient = Node(graph.reserve_id(), "Reservoir")
    senders = [
        Node(graph.reserve_id(), "Kestrel" if i == count - 1 else f"Sender {i}")
        for i in range(count)
    ]
    relation = RelationType(
        graph.reserve_id(),
        "TRANSFER",
        description="Directed transfer from a sender to receiving objects.",
        signature=(
            Slot("sender", "node"),
            Slot("receivers", "node", "list1"),
            Slot("flow", "number"),
            Slot("unit", "string"),
            Slot("annotation", "any", "optional"),
        ),
    )
    graph.apply(GraphDelta(creates=[recipient, *senders, relation]), provenance="fixture")
    facts = [
        RelationInstance(
            graph.reserve_id(),
            relation.name,
            relation_type=relation.id,
            args={
                "sender": sender.id,
                "receivers": [recipient.id],
                "flow": 83.75 if i == count - 1 else float(i),
                "unit": "l/min",
                "annotation": 99001,
            },
            properties={
                "conditions": {"mode": "backup" if i == count - 1 else "normal"},
                "opaque": {"id": 99001, "name": "batch", "kind": "sample"},
            },
        )
        for i, sender in enumerate(senders)
    ]
    graph.apply(GraphDelta(creates=facts), provenance="fixture")
    world.target, world.sender, world.recipient, world.relation = (
        facts[-1],
        senders[-1],
        recipient,
        relation,
    )
    return world
