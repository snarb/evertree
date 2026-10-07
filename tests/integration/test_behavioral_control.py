from functools import partial

import pytest

from evertree.application import EverTree
from evertree.core.graph.types import (
    AccessView,
    Clause,
    GraphDelta,
    Node,
    Predicate,
    RelationType,
    Slot,
)
from evertree.core.provider import ScriptedProvider
from evertree.core.runtime.controller import Runtime
from tests.support.runtime import TestProcess


@pytest.fixture
async def app(tmp_path):
    async def approve(_):
        return True

    async with EverTree(
        tmp_path / "agent",
        provider=ScriptedProvider([]),
        runtime_factory=partial(Runtime, process_factory=TestProcess),
        approval_handler=approve,
    ) as agent:
        yield agent


async def test_sem_02_belief_filtered_views_remain_connected_after_app_restore(app):
    """SEM-02 integration: view filters read the source belief before/after restore."""
    relation = RelationType(
        app.graph.reserve_id(),
        "CHECKED_FACT",
        signature=(Slot("subject"),),
        views=(
            AccessView(
                "supported",
                (),
                ("subject",),
                "one",
                Predicate((Clause("strength", ">=", 0.75),)),
            ),
        ),
    )
    subject = Node(app.graph.reserve_id(), "Supported subject")
    app.graph.apply(GraphDelta(creates=(relation, subject)), provenance="schema")
    app.beliefs.register_binary("checked-fact", prior=0.8, prior_backed=True)
    fact = app.graph.new_fact(relation.id, {"subject": subject.id}, belief_target="checked-fact")
    app.graph.apply(GraphDelta(creates=(fact,)), provenance="observation")
    assert app.graph.query_view(relation.id, "supported").source_fact.id == fact.id
    app._restore_core(app.snapshot())
    assert app.graph.query_view(relation.id, "supported").source_fact.id == fact.id


pytestmark = pytest.mark.usefixtures("offline_application")
