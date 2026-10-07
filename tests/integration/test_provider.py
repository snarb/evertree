import json


def test_launcher_drops_host_permissions_and_secrets(monkeypatch):
    """A real interpreter proves the SDK launcher removes host environment authority."""
    import subprocess
    import sys

    from evertree.core.codex.configuration import _LAUNCHER

    monkeypatch.setenv("CODEX_PERMISSION_PROFILE", ":danger-full-access")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    output = subprocess.check_output(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            _LAUNCHER,
            sys.executable,
            "-I",
            "-S",
            "-c",
            "import os,json; print(json.dumps(sorted(os.environ)))",
        ],
        text=True,
        input="\n",
    )
    names = json.loads(output)
    assert "CODEX_PERMISSION_PROFILE" not in names
    assert "OPENAI_API_KEY" not in names
