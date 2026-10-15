"""A real, small BPE vocabulary keeps offline tests independent of downloads."""

import pytest
import tiktoken


@pytest.fixture(autouse=True)
def offline_tokenizer(monkeypatch):
    ranks = {bytes([i]): i for i in range(256)}
    for value in (b"  ", b'{"', b'":', b", "):
        ranks[value] = len(ranks)
    encoder = tiktoken.Encoding(
        name="test_bpe", pat_str=r"(?s).+", mergeable_ranks=ranks, special_tokens={}
    )
    monkeypatch.setattr("evertree.core.tokens.encoding", lambda *args: encoder)
