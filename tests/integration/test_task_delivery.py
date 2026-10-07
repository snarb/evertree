from __future__ import annotations

import json
from functools import partial

import pytest

from evertree.application import EverTree
from evertree.core.provider import ScriptedProvider
from evertree.core.runtime.controller import Runtime
from tests.support.application import completed, decision, verification, wait_for_event
from tests.support.runtime import TestProcess

TEST_RUNTIME = partial(Runtime, process_factory=TestProcess)


def task_frame(objective, *, constraints=(), success_criteria=()):
    return completed(
        {
            "objective": objective,
            "success_criteria": list(success_criteria),
            "constraints": list(constraints),
            "preferences": [],
            "execution_budget": {"active_time_minutes": 3},
            "self_improvement_budget": 0,
            "budget_reason": "Small deterministic acceptance scenario",
        }
    )


@pytest.mark.parametrize(
    ("wrong_answer", "rejection"),
    [
        ("The report is ready.", "The report must be in Russian"),
        ("Первая страница.\fВторая страница.", "The report exceeds one page"),
    ],
    ids=["wrong-language", "too-many-pages"],
)
async def test_durable_intake_and_program_provenance_before_delivery(
    tmp_path, wrong_answer, rejection
):
    """Real worker traces and durable intake must preserve provenance through delivery."""
    request = "Подготовь краткий отчёт на русском, максимум одна страница."
    constraints = ("Language: Russian", "At most one page in the requested report format")
    corrected = "Краткий отчёт: работа выполнена."
    provider = ScriptedProvider(
        [
            task_frame("Подготовить краткий отчёт", constraints=constraints),
            decision(wrong_answer),
            completed({"verified": False, "reason": rejection}),
            decision(corrected),
            verification(True),
        ]
    )
    async with EverTree(tmp_path / "agent", provider=provider, runtime_factory=TEST_RUNTIME) as app:
        task = await app.submit(request, source_id="report-request")
        answer, seen = await wait_for_event(app, "answer")
        assert answer.data["text"] == corrected
        assert [event.data["text"] for event in seen if event.kind == "answer"] == [corrected]
        assert not task.terminal
        assert task.specification.constraints == constraints
        assert task.specification.source_ids == ("report-request",)
        assert json.loads(provider.requests[0].prompt)["request"] == request
        for index, candidate in ((2, wrong_answer), (4, corrected)):
            check = json.loads(provider.requests[index].prompt)
            assert check["answer"] == candidate
            assert check["specification"]["constraints"] == list(constraints)
            assert check["specification"]["source_ids"] == ["report-request"]
        assert rejection in provider.requests[3].prompt
        intake = [
            json.loads(line)
            for line in (app.state_dir / "intake.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert intake[0]["input"]["source_id"] == "report-request"
        assert intake[0]["input"]["content"] == request
        revisions = [
            event
            for event in app.tasks.snapshot()["events"]
            if event["kind"] == "specification_revised" and event["task_id"] == task.id
        ]
        assert len(revisions) == 1
        assert revisions[0]["provenance"] in {"run:" + run_id for run_id in task.program_run_ids}
        await app.acknowledge_delivery(answer.data["delivery_id"])
        await wait_for_event(app, "task_completed")
        assert task.status == "succeeded"


pytestmark = pytest.mark.usefixtures("offline_application")
