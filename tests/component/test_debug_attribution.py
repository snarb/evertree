"""The IDE harness learns through real Core tools and answers from retained state."""

import json

import pytest

from evertree.core.values import UNKNOWN
from evertree.debug_attribution import AttributionSession
from tests.support.application import completed
from tests.support.semantics import EmptyIndex

OBSERVATIONS = ("Jack weighs 8 kg.", "Luna weighs 5 kg.", "Rex weighs 10 kg.")
QUESTION = "Compare our dogs by relative mass, including a hypothetical 7 kg dog."


class Index(EmptyIndex):
    closed = False

    async def close(self):
        self.closed = True


class Provider:
    """Script semantic choices while all writes, fits and evidence updates remain real."""

    def __init__(self):
        self.requests, self.subjects, self.questions = [], [], []
        self.domain = self.numeric = self.norm = None
        self.closed = self.reader_write_rejected = False

    async def run(self, request_id, request, *, tool_handler=None):
        self.requests.append(request)
        data = json.loads(request.prompt)

        async def tool(tool_name, **arguments):
            result = await tool_handler(tool_name, arguments)
            assert "error" not in result, result
            return result

        async def create(action, name, sources, **fields):
            return (await tool(action, name=name, description=None, sources=sources, **fields))[
                "object"
            ]

        if "material" in data:
            source = next(
                item
                for item in data["material"]["experience"]
                if item.get("content") in OBSERVATIONS
            )
            sources = [source["reference"]]
            name, _, value, _ = source["content"].split()
            if self.domain is None:
                self.domain = await create("create_prototype", "Dog", sources, parent=None)
                self.numeric = await create(
                    "create_property", "Body mass", sources, unit="kg", applies_to=[self.domain]
                )
            subject = await create("create_instance", name, sources, prototype=self.domain)
            relation = (await tool("describe", subject="HAS_NUMERIC_VALUE"))["subject"]["id"]
            await tool(
                "relate",
                relation=relation,
                arguments=[
                    {"role": role, "value": item}
                    for role, item in {
                        "entity": subject,
                        "property": self.numeric,
                        "value": float(value),
                        "unit": "kg",
                    }.items()
                ],
                conditions=[],
                description="Reported mass",
                sources=sources,
            )
            self.subjects.append(subject)
            answer = {}
        elif "targets" in data:
            answer = {
                "targets": [
                    {
                        "element": item["element"],
                        "prior": None,
                        "evidence": [],
                        "unresolved": None,
                    }
                    for item in data["targets"]
                ],
                "origins": [],
                "scopes": [],
            }
        elif "questions" in data:
            answer = {
                "scopes": [
                    {
                        "scope": item["scope"],
                        "evidence": [
                            {
                                "source": source["key"],
                                "stances": [
                                    {
                                        "class": label["id"],
                                        "stance": "supports"
                                        if label["id"]
                                        == item["conditional_interpretation"]["class"]
                                        else "opposes",
                                    }
                                    for label in item["classes"]
                                ],
                                "repeats": None,
                                "reason": "Reported mass under the retained criterion",
                            }
                            for source in item["sources"]
                            if source["role"] == "measurement"
                        ],
                    }
                    for item in data["questions"]
                ]
            }
        else:
            assert data["question"] == QUESTION
            self.questions.append(request)
            assert all(observation not in request.prompt for observation in OBSERVATIONS)
            if "source_refs" in data:
                classes = [
                    await create("create_concept", name, data["source_refs"])
                    for name in ("Small", "Medium", "Large")
                ]
                self.norm = await create(
                    "create_qualitative_property",
                    "Relative mass",
                    data["source_refs"],
                    property=self.numeric,
                    domain=self.domain,
                    classes=classes,
                    conditions={},
                )
                answer = {"answer": "Prepared a relative scale from the retained measurements."}
            else:
                assert all(item.read_only for item in request.tools)
                with pytest.raises(PermissionError, match="Tool was not declared"):
                    await tool_handler(
                        "create_concept", {"name": "Forbidden", "description": None, "sources": []}
                    )
                self.reader_write_rejected = True
                for subject in self.subjects:
                    reading = await tool("read_property", subject=subject, property=self.norm)
                    assert reading["belief_data"]["profile"]
                    assert reading["belief_data"]["stats"]["evidence_count"] == 1
                summary = await tool(
                    "summarize_property", domain=self.domain, property=self.numeric
                )
                assert summary["observations"]["count"] == 3
                assert summary["observations"]["mean"] == pytest.approx(23 / 3)
                answer = {"answer": "Three assessed dogs; the hypothetical dog is conditional."}
        if any(item.name == "finish_section" for item in request.tools):
            await tool("finish_section", complete=True, remaining="")
        for event in completed(answer):
            yield event

    async def close(self):
        self.closed = True


def session_with_services(tmp_path):
    session = AttributionSession(tmp_path, observations=OBSERVATIONS, question=QUESTION)
    session.index = session.service.index = Index()
    session.provider = Provider()
    return session


async def test_observations_question_assessment_and_fresh_reader_use_retained_state(
    tmp_path, monkeypatch
):
    session = session_with_services(tmp_path)
    monkeypatch.setenv(session.config.redis_url_env, "unused-scripted-index")
    monkeypatch.setenv(session.config.openai_key_env, "unused-scripted-provider")
    assert await session.run() == "Three assessed dogs; the hypothetical dog is conditional."
    assert session.provider.reader_write_rejected
    assert session.provider.closed and session.index.closed
    assert len(session.stages) == 4
    assert len(session.provider.questions) == 2
    preparation, answer = session.provider.questions
    assert preparation.mode == "exec" and answer.mode == "model"
    assert set(json.loads(answer.prompt)) == {"question"}
    assert session.graph.find("Forbidden") is None
    for index in range(1, 4):
        saved = json.loads((tmp_path / f"observation-{index}" / "properties.json").read_text())
        numeric = next(item for item in saved if item["property"]["id"] == session.provider.numeric)
        assert len(numeric["readings"]) == index
    for name in ("graph", "beliefs", "attribution"):
        learned = json.loads((tmp_path / "learned" / f"{name}.json").read_text())
        assert learned == json.loads((tmp_path / "final" / f"{name}.json").read_text())
    assert json.loads((tmp_path / "answer.json").read_text())["answer"] == session.answer
    assert list(tmp_path.glob("model-*.json"))
    for subject in session.provider.subjects:
        assert (
            session.operations.attribution.read_property(subject, session.provider.norm)
            is not UNKNOWN
        )
    before = (
        session.graph.snapshot(),
        session.operations.beliefs.snapshot(),
        session.operations.attribution.snapshot(),
        session.memory.snapshot(),
    )
    session.checkpoint("inspected")
    assert before == (
        session.graph.snapshot(),
        session.operations.beliefs.snapshot(),
        session.operations.attribution.snapshot(),
        session.memory.snapshot(),
    )


async def test_missing_configuration_preserves_inputs_and_final_state_before_any_model_call(
    tmp_path, monkeypatch
):
    session = session_with_services(tmp_path)
    monkeypatch.delenv(session.config.redis_url_env, raising=False)
    monkeypatch.delenv(session.config.openai_key_env, raising=False)
    with pytest.raises(RuntimeError, match="Для поиска задайте"):
        await session.run()
    assert not session.provider.requests
    assert session.provider.closed and session.index.closed
    assert not list(tmp_path.glob("model-*.json"))
    assert json.loads((tmp_path / "inputs.json").read_text()) == {
        "observations": list(OBSERVATIONS),
        "question": QUESTION,
    }
    assert json.loads((tmp_path / "stages.json").read_text()) == []
    assert json.loads((tmp_path / "answer.json").read_text()) == {
        "preparation": None,
        "answer": None,
    }
    assert json.loads((tmp_path / "final" / "graph.json").read_text()) == session.graph.snapshot()
