import os

import pytest

from evertree.core.semantics.config import SemanticConfig
from evertree.core.semantics.index import OpenAIEmbeddings

pytestmark = pytest.mark.skipif(
    os.environ.get("EVERTREE_EMBEDDINGS_INTEGRATION") != "1",
    reason="Explicit paid embedding smoke opt-in required",
)


async def test_live_large_embedding_dimensions():
    vectors = await OpenAIEmbeddings(SemanticConfig()).embed(["кошка", "дочь Светланы"])
    assert len(vectors) == 2
    assert all(len(vector) == 3072 for vector in vectors)
