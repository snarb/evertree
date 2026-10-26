"""The live evaluation bridge supports both production LLM calling conventions."""

import pytest

from evertree.common.structured import ask
from evertree.core.provider import LLMEvent, ToolDefinition
from tests.support.live_semantics import (
    RecordedProvider,
    conscious_question,
    native_semantic_context,
)
from tests.support.semantics import EmptyIndex, semantic_world


@pytest.mark.parametrize("boundaries", [[6, 9], [10, 20], [2, 4], [1]])
@pytest.mark.parametrize("inclusive", [True, False])
def test_live_guide_oracle_checks_exact_inclusive_endpoints(boundaries, inclusive):
    from tests.live.test_attribution_learning import _assert_inclusive_bands
    from tests.support.attribution import Population

    data = Population()
    classes = [
        data.create("create_concept", name)
        for name in ("Small", "Medium", "Large")[: len(boundaries) + 1]
    ]
    data.reference(
        "bands",
        unit="g",
        boundaries=[value * 1000 for value in boundaries],
        classes=classes,
        boundary_inclusive=[inclusive, *([True] * (len(boundaries) - 1))],
    )
    report = data.report(value=boundaries[0], unit="kg")
    reference = report["references"][0]
    assert reference["interpretation"]["class"]["id"] == classes[0 if inclusive else 1]
    if inclusive:
        _assert_inclusive_bands(report, reference, data.world, boundaries)
    else:
        with pytest.raises(AssertionError, match="exact boundary to the lower class"):
            _assert_inclusive_bands(report, reference, data.world, boundaries)


@pytest.mark.parametrize("category", [None, "unknown", "small", "medium", "large"])
def test_grouped_interval_oracle_accepts_unknown_but_rejects_invented_categories(category):
    from tests.live.test_attribution_learning import _assert_extended_reports
    from tests.support.attribution import Population

    data = Population()
    data.reference(
        "distribution",
        samples=[
            {"lower": 1, "upper": 3, "count": 1},
            {"lower": 5, "upper": 7, "count": 1},
            {"lower": 9, "upper": 11, "count": 3},
        ],
    )
    report = data.report(value=6, unit="kg")
    answer = {
        "mean_kg": 7.6,
        "mean_bounds_kg": [6.6, 8.6],
        "mean_is_approximate": True,
        "sample_count": 5,
        "classifications": [] if category is None else [{"value_kg": 6, "class": category}],
    }
    arguments = ({"id": "grouped_interval_report"}, [report], answer, data.world, {})
    if category in {None, "unknown"}:
        _assert_extended_reports(*arguments)
    else:
        with pytest.raises(AssertionError, match="no declared categorical criterion"):
            _assert_extended_reports(*arguments)


@pytest.mark.parametrize("extra_dog", [None, "domain", "subtype"])
def test_selection_oracle_counts_dog_subtypes_but_not_contextual_facilities(extra_dog):
    from tests.live.test_attribution_learning import _assert_extended_reports
    from tests.support.attribution import Population

    data = Population()
    breed = data.create("create_prototype", "Hound", parent=data.domain)
    shelter = data.create("create_prototype", "Shelter", parent=None)
    data.create("create_instance", "Animal shelter", prototype=shelter)
    classes = [data.create("create_concept", name) for name in ("Small", "Medium", "Large")]
    data.reference("bands", boundaries=[10, 20], classes=classes)
    data.measurement(7, name="Roni")
    data.measurement(15, name="Vesta")
    large, _ = data.measurement(28, name="Grom", prototype=breed)
    data.create("create_instance", "Tuman", prototype=breed)
    if extra_dog:
        data.create(
            "create_instance",
            "Extra dog",
            prototype=data.domain if extra_dog == "domain" else breed,
        )
    reports = [data.report(value=value, unit="kg") for value in (7, 15, 28, 25)]
    answer = {
        "mean_kg": 50 / 3,
        "sample_count": 3,
        "large_choice": large,
        "nearest_choice": large,
        "classifications": [
            {"value_kg": value, "class": label}
            for value, label in ((7, "small"), (15, "medium"), (28, "large"), (None, "unknown"))
        ],
    }
    arguments = ({"id": "choose_large_and_nearest"}, reports, answer, data.world, {})
    if extra_dog:
        with pytest.raises(AssertionError, match="exactly four dogs"):
            _assert_extended_reports(*arguments)
    else:
        _assert_extended_reports(*arguments)


async def test_structured_assessment_and_native_tools_share_provider_and_transcript(tmp_path):
    class RecordingProvider:
        def __init__(self):
            self.requests = []

        async def run(self, request_id, request, *, tool_handler=None):
            self.requests.append(request)
            if request.tools:
                assert await tool_handler("read", {}) == {"count": 3}
                result = {"text": "Native read completed"}
            else:
                assert request.output_schema["required"] == ["assessed"]
                assert request.mode == "model"
                result = {"parsed": {"assessed": True}}
            yield LLMEvent("completed", result)

    provider, transcript = RecordingProvider(), []
    async with native_semantic_context(semantic_world(), provider, tmp_path, transcript) as ctx:
        structured = await ask(
            ctx,
            instructions="Assess the retained evidence.",
            data={"sources": ["An owner reports this measurement."]},
            schema={
                "type": "object",
                "properties": {"assessed": {"type": "boolean"}},
                "required": ["assessed"],
            },
        )
        assert structured["result"] == {"assessed": True}

        async def read(name, arguments):
            assert name == "read" and arguments == {}
            return {"count": 3}

        native = await ctx.llm(
            {"prompt": "Read observations", "instructions": "Use the supplied tool."},
            tools=[ToolDefinition("read", "Read observations", {"type": "object"}, read_only=True)],
            tool_handler=read,
        )
        assert native["text"] == "Native read completed"
    assert len(provider.requests) == 2
    invocations = [item for item in transcript if "events" in item]
    assert len(invocations) == 2
    assert invocations[0]["events"] == [
        {"kind": "completed", "data": {"parsed": {"assessed": True}}}
    ]
    assert any(item.get("tool_history") for item in transcript)


async def test_conscious_question_uses_scoped_application_writes_and_normal_integration(tmp_path):
    from evertree._application.prompts import CONSCIOUSNESS_INSTRUCTIONS
    from evertree.core.values import json_value
    from tests.support.application import IntegrationScriptedProvider, completed, decision
    from tests.support.component import component_app

    class ConsciousProvider(IntegrationScriptedProvider):
        async def run(self, request_id, request, **kwargs):
            if request.instructions != CONSCIOUSNESS_INSTRUCTIONS:
                async for event in super().run(request_id, request, **kwargs):
                    yield event
                return
            assert request.mode == "exec"
            assert any(group.name == "graph_write_tools" for group in request.tool_sets)
            handler = kwargs["tool_handler"]
            reference = await handler(
                "record_analysis", {"text": "Relative size compares members of a retained sample."}
            )
            result = await handler(
                "graph.create_concept",
                {
                    "name": "Relative size",
                    "description": "A conditional comparison",
                    "sources": [reference],
                },
            )
            assert "error" not in result, result
            value = decision("Relative comparison recorded")[0].data["parsed"]
            value["analysis"]["source_refs"] = [reference]
            for event in completed(value):
                yield event

    transcript = []
    async with component_app(
        tmp_path / "app",
        provider=RecordedProvider(ConsciousProvider([]), transcript),
        search_index=EmptyIndex(),
    ) as app:
        run = app.memory.start_run("UserInput", "revision", {})
        event = app.memory.record(run, "user_input", output="Compare retained sizes.")
        app.memory.finish_run(run)
        outcome = await conscious_question(
            app, "Compare retained sizes.", json_value(app.memory.output_ref(event))
        )
        assert app.graph.find("Relative size") is not None
        assert outcome["task"]["step_state"]["integrated"]
        assert len(outcome["task"]["program_run_ids"]) >= 2
        assert not [event for event in app.memory.events if event.operator == "integration_error"]
    assert transcript[0]["request"]["mode"] == "exec"
    from evertree.processes.self_semantic_processing.self_knowledge_integration._exec import (
        INSTRUCTIONS,
    )

    assert any(item["request"]["instructions"] == INSTRUCTIONS for item in transcript)
