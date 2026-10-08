"""Opt-in external connectivity, independent of model/account integration."""

import os
import sys
import urllib.error
import urllib.request

import pytest

from evertree.core.sandbox.process import start_process

pytestmark = [
    pytest.mark.skipif(os.name != "nt" and sys.platform != "darwin", reason="Native sandbox"),
    pytest.mark.skipif(
        os.environ.get("EVERTREE_NETWORK_SMOKE") != "1", reason="External network smoke opt-in"
    ),
]


def test_native_worker_can_make_https_request(tmp_path):
    """A host control and real sandbox request distinguish isolation from network failure."""
    url = "https://example.com/"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            assert response.status == 200
    except (OSError, urllib.error.URLError) as error:
        pytest.skip(f"Host HTTPS control is unavailable: {error}")
    code = f"""
import urllib.request
with urllib.request.urlopen({url!r}, timeout=20) as response:
    assert response.status == 200
print('connected', flush=True)
"""
    with start_process(
        None,
        ["-I", "-c", code],
        workdir=tmp_path,
        readable=(),
        writable=(tmp_path,),
    ) as process:
        assert process.wait(timeout=30) == 0, process.stderr.read().decode(errors="replace")
        assert process.stdout.read().strip() == b"connected"
