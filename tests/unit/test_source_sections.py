"""Source partitions preserve content and split only real structured or text boundaries."""

import pytest

from evertree.common.source_sections import (
    bisect_section,
    section_context,
    section_value,
    source_sections,
)


def test_large_structured_source_keeps_metadata_and_exact_text_without_broken_json():
    text = "First qualification applies only on Tuesday.\n\n" * 12 + "Last exception."
    source = {
        "title": "Offers",
        "article": {"url": "https://example.test/a", "body": text},
        "count": 7,
    }
    sections = source_sections(source, limit=100)
    body = [section for section in sections if section["path"] == ["article", "body"]]
    assert "".join(section_value(source, section) for section in body) == text
    assert all(len(section_value(source, section)) <= 100 for section in body)
    assert [section["start"] for section in body] == [0] + [section["end"] for section in body[:-1]]
    metadata = [section_value(source, section) for section in sections if "keys" in section]
    assert {key for item in metadata for key in item} == {"title", "url", "count"}
    context = section_context(source, body[1])
    assert any(item.get("values", {}).get("url") == source["article"]["url"] for item in context)
    assert any(item.get("preceding_text") for item in context)


def test_adaptive_bisection_preserves_ranges_and_does_not_cut_indivisible_assertion():
    text = "A supplies B. C supplies D. E supplies F."
    section = {"path": [], "start": 14, "end": len(text)}
    children = bisect_section(text, section)
    assert "".join(section_value(text, child) for child in children) == text[14:]
    assert children[0]["start"] == 14 and children[-1]["end"] == len(text)
    assert bisect_section("A supplies B", {"path": []}) == []
    records = [{"index": index, "value": "x" * 20} for index in range(8)]
    chunks = source_sections(records, limit=90)
    assert [row for section in chunks for row in section_value(records, section)] == records


def test_sections_keep_table_headers_and_bisect_single_child_wrappers():
    table = {"columns": ["city", "temperature_C"], "rows": [["Kyiv", i] for i in range(1000)]}
    section = next(unit for unit in source_sections(table) if unit["path"] == ["rows"])
    context = section_context(table, section)
    assert any(row.get("values", {}).get("columns") == table["columns"] for row in context)
    text = "A supplies B. B supplies C. C powers D."
    for source in ({"body": text}, [text]):
        children = bisect_section(source, {"path": []})
        assert len(children) == 2
        assert "".join(section_value(source, child) for child in children) == text


def test_key_groups_keep_current_dictionary_identity_and_table_metadata():
    table = {
        "entity": "Pump P1",
        "columns": ["reading", "temperature_C"],
        "first": ["x" * 100] * 12,
        "second": ["y" * 100] * 12,
    }
    for source, path in ((table, []), ({"measurements": table}, ["measurements"])):
        sections = source_sections(source, limit=1800)
        section = next(unit for unit in sections if unit.get("keys") == ["second"])
        context = section_context(source, section)
        values = next(
            row["values"] for row in context if row.get("path") == path and "values" in row
        )
        assert values["entity"] == "Pump P1"
        assert values["columns"] == table["columns"]


@pytest.mark.parametrize("paragraph_length", [520, 730, 900])
@pytest.mark.parametrize("separator", ["\n\n", "\r\n \r\n"])
def test_boundary_context_keeps_short_adjacent_paragraphs_with_their_subject(
    paragraph_length, separator
):
    owner = "Station Cedar measures only this device. "
    preceding = owner + "x" * (paragraph_length - len(owner))
    following = "An independent qualification follows. " + "y" * paragraph_length
    prefix = "Earlier unrelated material. " * 80 + separator
    selected = "Its threshold is 12 kg."
    text = prefix + preceding + separator + selected + separator + following + separator + "End."
    start = len(prefix + preceding + separator)
    section = {"path": [], "start": start, "end": start + len(selected)}
    context = section_context(text, section)[-1]
    assert context["preceding_text"] == preceding + separator
    assert context["following_text"] == separator + following
    assert section_value(text, section) == selected
    assert all(len(value) <= 1000 for value in context.values())


def test_boundary_context_stays_bounded_when_no_nearby_paragraph_is_available():
    text = "x" * 5000
    section = {"path": [], "start": 2000, "end": 2100}
    context = section_context(text, section)[-1]
    assert context == {"preceding_text": text[1500:2000], "following_text": text[2100:2600]}
    assert section_context("A short text.", {"path": [], "start": 2, "end": 7})[-1] == {
        "preceding_text": "A ",
        "following_text": " text.",
    }


@pytest.mark.parametrize("separator", ["\n\n", "\r\n \r\n"])
def test_short_report_paragraph_keeps_its_timestamp_and_continuation_together(separator):
    paragraphs = [
        "Earlier section. Earlier observation. Earlier condition.",
        "10:00 — Station Cedar reports a pressure change. Its output is now 12 bar.",
        "11:00 — Station Birch reports a different measurement. Its output is 8 bar.",
    ]
    text = separator.join(paragraphs)
    sections = source_sections(text, limit=115)
    parts = [section_value(text, section) for section in sections]
    assert "".join(parts) == text
    assert all(any(paragraph in part for part in parts) for paragraph in paragraphs)
    assert all(len(part) <= 115 for part in parts)


def test_oversized_paragraph_falls_back_to_sentences_without_losing_text():
    text = "A long observation remains sourced. " * 20
    parts = [section_value(text, section) for section in source_sections(text, limit=100)]
    assert "".join(parts) == text
    assert all(0 < len(part) <= 100 for part in parts)


def test_adaptive_split_prefers_paragraphs_before_breaking_a_short_report():
    first = "10:00 — Station Cedar reports a change. "
    second = "11:00 — Station Birch reports a change. " + "Its output is 8 bar. " * 5
    text = first + "\n\n" + second
    children = bisect_section(text, {"path": []})
    assert [section_value(text, child) for child in children] == [first + "\n\n", second]
