import asyncio
import json

import pytest

from evertree.core.cognition.control import verification_result
from evertree.core.cognition.tasks import TaskStore
from evertree.core.provider import ScriptedProvider
from tests.support.application import completed, decision, verification, wait_for_event
from tests.support.component import component_app


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
async def test_cog_01_requirements_and_sources_reach_verification_before_delivery(
    tmp_path, wrong_answer, rejection
):
    """COG-01: a verifier-rejected candidate cannot be delivered as task success."""
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
    async with component_app(
        tmp_path / "agent",
        provider=provider,
    ) as app:
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


async def test_cog_02_clarification_resumes_same_task_with_both_sources(tmp_path):
    """COG-02: the explicitly correlated reply continues one existing task."""
    provider = ScriptedProvider(
        [
            task_frame("Count the requested letter in strawberry"),
            decision("Which letter should I count?", "waiting"),
            decision("3"),
            verification(),
        ]
    )
    async with component_app(
        tmp_path / "agent",
        provider=provider,
    ) as app:
        first = await asyncio.wait_for(
            app.run("Count a letter in strawberry", source_id="question"), 45
        )
        assert first["status"] == "waiting"
        await app._pump
        task = app.tasks.get(first["task_id"])
        original_episode = tuple(task.episode_ids)
        second = await asyncio.wait_for(
            app.run("The letter r", task_id=task.id, source_id="clarification"), 45
        )
        assert second["status"] == "succeeded"
        assert second["task_id"] == task.id
        assert second["answer"] == "3"
        assert len(app.tasks.all()) == 1
        assert tuple(task.episode_ids) == original_episode
        assert task.source_ids == ["question", "clarification"]
        continuation = json.loads(provider.requests[2].prompt)
        assert continuation["task_id"] == task.id
        assert continuation["source_ids"] == ["question", "clarification"]
        assert continuation["incoming"]["source_id"] == "clarification"
        assert continuation["incoming"]["content"] == "The letter r"
        assert any(
            message.get("source_id") == "question"
            and message["content"] == "Count a letter in strawberry"
            for message in continuation["messages"]
        )
        assert len(provider.requests) == 4  # Framing is not repeated for the reply.


@pytest.mark.parametrize("results", [{}, {"report_format": None}])
def test_cog_05_unavailable_mandatory_check_prevents_task_success(results):
    """COG-05: deterministic gate; the check has no usable result, not a pass."""
    result = verification_result(("report_format",), results)
    assert result.status == "need_checks"
    assert result.missing_checks == ("report_format",)
    tasks = TaskStore()
    task = tasks.create_task("Return a checked report")
    tasks.assign_budget(task.id, {"active_time_minutes": 1}, 0, reason="Check report")
    with pytest.raises(ValueError, match="verified"):
        tasks.finish(
            task.id,
            "succeeded",
            reason="Looks correct",
            execution_stopped=True,
            verification=result,
        )
    assert not task.terminal


async def test_cog_05_unavailable_check_feedback_returns_task_to_waiting(tmp_path):
    """COG-05 orchestration: rejected verification is not changed into success."""
    reason = "Mandatory report_format check unavailable; no result has been obtained"
    provider = ScriptedProvider(
        [
            task_frame("Return a report", constraints=("report_format check is mandatory",)),
            decision("The report looks correct."),
            completed({"verified": False, "reason": reason}),
            decision("Waiting for the report format checker to become available", "waiting"),
        ]
    )
    async with component_app(
        tmp_path / "agent",
        provider=provider,
    ) as app:
        result = await asyncio.wait_for(app.run("Prepare and verify a report"), 45)
        task = app.tasks.get(result["task_id"])
        assert result["status"] == "waiting"
        assert not task.terminal
        assert reason in provider.requests[3].prompt
        assert app.learning.statistics("verified_task_rate")["observed_count"] == 0
        assert len(provider.requests) == 4
