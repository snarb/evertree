import asyncio
import os

import pytest

from evertree.application import EverTree
from evertree.core.provider import ScriptedProvider
from tests.support.application import decision, framing, verification


async def test_native_framing_verification_delivery_and_budget(tmp_path):
    """Real Windows isolation/tools are required; a test process cannot prove this OS contract."""
    provider = ScriptedProvider([framing(minutes=4, improvement=15), decision(), verification()])
    async with EverTree(tmp_path / "agent", provider=provider) as agent:
        result = await asyncio.wait_for(agent.run("Count the r characters in strawberry"), 60)
        assert result["status"] == "succeeded", result
        assert result["answer"] == "3"
        task = agent.tasks.get(result["task_id"])
        assert task.execution_budget.resources == {"active_time_minutes": 4}
        assert task.self_improvement_budget == 15
        assert len(provider.requests) == 3
        assert provider.requests[0].mode == "model"
        assert provider.requests[1].mode == "exec"
        assert provider.requests[2].mode == "model"
        assert task.specification.revision == 2
        assert not agent.runtime.is_running()
        assert any(event.operator == "provider_request" for event in agent.memory.events)
        assert any(event.operator == "run_finished" for event in agent.memory.events)


pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="Windows native workers"),
    pytest.mark.usefixtures("offline_application"),
]
