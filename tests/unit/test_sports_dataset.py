"""Check that the committed evaluation fixture retains its tree and evidence."""

import pickle
from pathlib import Path


def test_sports_taxonomy_fixture_is_self_contained_and_consistent():
    path = Path(__file__).resolve().parents[1] / "data" / "sports_taxonomy.pkl"
    with path.open("rb") as stream:
        dataset = pickle.load(stream)

    nodes = {node["id"]: node for node in dataset["tree"]["nodes"]}
    articles = dataset["articles"]
    questions = dataset["questions"]
    assert len(nodes) == len(dataset["tree"]["nodes"]) == 1369
    assert len(articles) == 211
    assert len(questions) == 609
    assert dataset["tree"]["root_id"] == 0
    assert dataset["pilot_question_indices"] == [28, 87, 148, 181, 184, 216, 225, 264, 270, 411]

    roots = [node for node in nodes.values() if node["parent_id"] is None]
    assert len(roots) == 1 and roots[0]["id"] == dataset["tree"]["root_id"]
    visited = set()
    pending = [roots[0]["id"]]
    while pending:
        identity = pending.pop()
        assert identity not in visited
        visited.add(identity)
        pending.extend(nodes[identity]["children_ids"])
    assert visited == nodes.keys()
    for node in nodes.values():
        parent = node["parent_id"]
        if parent is not None:
            assert node["id"] in nodes[parent]["children_ids"]
        assert all(nodes[child]["parent_id"] == node["id"] for child in node["children_ids"])
        if node["text_id"] is not None:
            assert node["text"] == articles[int(node["text_id"])]["body"]

    urls = {article["url"] for article in articles}
    assert all(
        evidence["url"] in urls for question in questions for evidence in question["evidence_list"]
    )
