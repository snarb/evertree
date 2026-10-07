import pytest

from evertree.core.runtime import ProgramSpec, Runtime
from tests.support.runtime import TestProcess, commit_programs


@pytest.mark.parametrize(
    "text",
    ["Подготовь краткий отчёт на русском.", "中文 🚦 café e\u0301"],
    ids=["cyrillic-request", "mixed-unicode"],
)
async def test_cog_01_unicode_arguments_gateway_and_durable_result(tmp_path, text):
    """A non-ASCII run must be admitted before any gateway call, then round trip."""
    repository = tmp_path / "programs"
    revision = commit_programs(
        repository,
        {
            "echo.py": """
async def run(ctx, text):
    echoed = await ctx.step('echo', {'text': text})
    return {'result': echoed, 'feedback': text}
""",
        },
    )
    program = ProgramSpec("unicode-echo", "echo.py", revision)
    calls, traces = [], []

    async def gateway(method, payload):
        assert method == "echo"
        calls.append(payload["text"])
        return {"echoed": payload["text"], "reply": "Готово ✅"}

    async def trace(event):
        traces.append(event)

    runtime = Runtime(tmp_path / "runtime", repository, gateway, trace, process_factory=TestProcess)
    try:
        result = await runtime.execute(
            "unicode-task", program, {"text": text}, run_id="unicode-roundtrip", timeout=30
        )
        assert result.result == {"echoed": text, "reply": "Готово ✅"}
        assert result.feedback == text
        started = [event for event in traces if event["type"] == "run_started"]
        assert len(started) == 1
        assert started[0]["arguments"] == {"text": text}
        assert calls == [text]
        replayed = await runtime.execute(
            "unicode-task", program, {"text": text}, run_id="unicode-roundtrip", timeout=30
        )
        assert replayed == result
        assert calls == [text]
    finally:
        await runtime.close()
