"""Lossless, deterministic source sections for sequential knowledge acquisition."""

import json
import re

SECTION_CHARACTERS = 900
_PARAGRAPH_BREAK = re.compile(r"\r?\n[ \t\r]*\n")


def _size(value):
    return len(json.dumps(value, ensure_ascii=False))


def _boundaries(text):
    return [match.end() for match in re.finditer(r"\n\s*\n|\n|[.!?]\s+", text)]


def section_value(value, section):
    """Resolve a section against its immutable original source value."""
    for part in section["path"]:
        value = value[part]
    if "keys" in section:
        return {key: value[key] for key in section["keys"]}
    if "start" in section:
        return value[section["start"] : section["end"]]
    return value


def source_sections(value, *, limit=SECTION_CHARACTERS, path=()):
    """Partition without cutting JSON syntax or dropping any field, list item or character."""
    base = {"path": list(path)}
    if _size(value) <= limit or not isinstance(value, (str, list, dict)):
        return [base]
    if isinstance(value, str):
        result, start = [], 0
        boundaries = _boundaries(value)
        paragraphs = [match.end() for match in _PARAGRAPH_BREAK.finditer(value)]
        while start < len(value):
            end = min(start + limit, len(value))
            if end < len(value):
                candidates = [point for point in paragraphs if start < point <= end]
                if not candidates:
                    candidates = [point for point in boundaries if start < point <= end]
                if candidates:
                    end = candidates[-1]
                else:
                    whitespace = value.rfind(" ", start + limit // 2, end)
                    if whitespace != -1:
                        end = whitespace + 1
            result.append({**base, "start": start, "end": end})
            start = end
        return result
    result, group, cost = [], [], 0
    entries = value.items() if isinstance(value, dict) else enumerate(value)

    def flush():
        nonlocal group, cost
        if group:
            result.append(
                {**base, "keys": group}
                if isinstance(value, dict)
                else {**base, "start": group[0], "end": group[-1] + 1}
            )
            group, cost = [], 0

    for key, child in entries:
        size = _size(child) + _size(key)
        if size > limit:
            flush()
            result.extend(source_sections(child, limit=limit, path=(*path, key)))
        else:
            if cost + size > limit:
                flush()
            group.append(key)
            cost += size
    flush()
    return result


def bisect_section(value, section):
    """Split an exhausted unit at a source boundary; an indivisible assertion stays failed."""
    selected = section_value(value, section)
    if "keys" in section:
        keys = section["keys"]
        if len(keys) < 2:
            return bisect_section(value, {"path": [*section["path"], keys[0]]}) if keys else []
        middle = len(keys) // 2
        return [{**section, "keys": keys[:middle]}, {**section, "keys": keys[middle:]}]
    if isinstance(selected, (list, str)):
        if isinstance(selected, list) and len(selected) == 1:
            return bisect_section(value, {"path": [*section["path"], section.get("start", 0)]})
        middle = len(selected) // 2
        if isinstance(selected, str):
            boundaries = [
                match.end()
                for match in _PARAGRAPH_BREAK.finditer(selected)
                if match.end() < len(selected)
            ]
            if not boundaries:
                boundaries = [point for point in _boundaries(selected) if 0 < point < len(selected)]
            if not boundaries:
                return []
            middle = min(boundaries, key=lambda point: abs(point - middle))
        if middle == 0:
            return []
        start = section.get("start", 0)
        end = section.get("end", len(selected))
        return [
            {**section, "start": start, "end": start + middle},
            {**section, "start": start + middle, "end": end},
        ]
    if isinstance(selected, dict) and selected:
        return bisect_section(value, {**section, "keys": list(selected)})
    return []


def section_context(value, section):
    """Keep nearby source identifiers and boundaries available without repeating long bodies."""
    context, remaining = [], 2000

    def siblings(current, selected, path):
        nonlocal remaining
        nearby, omitted = {}, 0
        # Scalar identifiers and short headers survive before larger structured context.
        entries = sorted(current.items(), key=lambda item: _size({item[0]: item[1]}))
        for key, child in entries:
            if key in selected:
                continue
            size = _size({key: child})
            if size <= min(1000, remaining):
                nearby[key] = child
                remaining -= size
            else:
                omitted += 1
        if nearby:
            context.append({"path": path, "values": nearby})
        if omitted:
            context.append({"path": path, "other_context_fields": omitted})

    current = value
    for depth, part in enumerate(section["path"]):
        if isinstance(current, dict):
            siblings(current, {part}, section["path"][:depth])
        current = current[part]
    if isinstance(current, dict) and "keys" in section:
        siblings(current, set(section["keys"]), section["path"])
    if isinstance(current, str) and "start" in section:
        start, end = section["start"], section["end"]
        if start or end < len(current):
            left, right = max(0, start - 500), min(len(current), end + 500)
            # A character window can drop the subject at the start of an adjacent paragraph.
            boundaries = list(_PARAGRAPH_BREAK.finditer(current, max(0, left - 500), left))
            if boundaries:
                left = boundaries[-1].end()
            elif left < 500:
                left = 0
            boundary = _PARAGRAPH_BREAK.search(current, right, min(len(current), right + 500))
            if boundary is not None:
                right = boundary.start()
            elif len(current) - right < 500:
                right = len(current)
            context.append(
                {
                    "preceding_text": current[left:start],
                    "following_text": current[end:right],
                }
            )
    return context
