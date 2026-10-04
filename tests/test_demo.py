from __future__ import annotations

import os
from pathlib import Path

import pytest

from evertree.demo import run_demo


@pytest.mark.skipif(os.name != "nt", reason="Lifecycle demonstration uses native Windows workers")
async def test_full_program_improvement_and_restart_demo(tmp_path, monkeypatch):
    from evertree.core import runtime, sandbox

    cache = Path(__file__).resolve().parents[1] / ".state" / "test-demo-python"
    monkeypatch.setattr(runtime, "prepare_python", lambda _: sandbox.prepare_python(cache))
    result = await run_demo(tmp_path / "demo")
    assert result["provider"] == "demo-scripted"
    assert result["incident"] == [1, 3]
    assert len(result["stages"]) == 2
    first, second = result["stages"]
    assert first["revision"] != second["revision"]
    assert first["dataset"] != second["dataset"]
    assert result["restart"]["revision"] == second["revision"]
    assert result["restart"]["answer"] == "[1, 3, 3]"
    assert result["restart"]["retained_events"] > 0
    assert result["learning"]["observed_count"] == 3
    for operation in ("develop_candidate", "evaluate_candidate", "choose_candidate"):
        assert result["tool_calls"].count(operation) == 2
    assert result["tool_calls"].count("create_candidate") == 1
    assert result["tool_calls"].count("run_program") == 4
