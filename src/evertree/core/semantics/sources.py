"""Exact graph provenance and bounded source reads without similarity ranking."""

import json
from collections import deque
from dataclasses import dataclass, field

from ..memory.types import TraceOutputRef, _ref
from ..tokens import count_tokens, current_read_context, read_budget
from ..values import ContractError, json_value


def _reference(value):
    if (
        not isinstance(value, dict)
        or set(value) - {"event_ref", "output_path"}
        or type(value.get("event_ref")) is not int
        or value["event_ref"] <= 0
        or not isinstance(value.get("output_path", []), (list, tuple))
        or any(
            type(part) not in {str, int} or type(part) is int and part < 0
            for part in value.get("output_path", [])
        )
    ):
        raise ContractError("Invalid retained source reference")
    return TraceOutputRef(value["event_ref"], tuple(value.get("output_path", ())))


@dataclass
class _Selection:
    revision: int
    value: object
    events: dict = field(default_factory=dict)
    offset: int = 0
    exhausted: bool = False


class SourceReads:
    def __init__(self, graph, memory, config):
        self.graph, self.memory, self.config = graph, memory, config
        self._selections = {}
        self._latest = {}

    def release(self, task_id):
        """Discard exact source continuations belonging to a finished task."""
        self._selections = {k: v for k, v in self._selections.items() if k[0] != task_id}
        self._latest = {k: v for k, v in self._latest.items() if k[0] != task_id}

    def _event(self, identity, events):
        try:
            event = self.memory.get_event(identity)
        except KeyError:
            events[identity] = None
            return None
        events[identity] = event
        return event

    def _material(self, ref, events):
        """Resolve an exact fragment while retaining every forwarding event for validation."""
        original, seen = ref, set()
        while ref not in seen:
            seen.add(ref)
            if self._event(ref.event_ref, events) is None:
                return {
                    "reference": json_value(original),
                    "status": "unavailable",
                    "reason": "Source event is unavailable",
                }
            try:
                value = self.memory._raw_resolve(ref)
                forwarded = _ref(value)
                if forwarded is not None:
                    ref = forwarded
                    continue
                producer = ref
                event = self._event(producer.event_ref, events)
                run = self.memory.get_run(event.program_run)
            except (KeyError, ValueError, TypeError, IndexError) as exc:
                return {
                    "reference": json_value(original),
                    "status": "unavailable",
                    "reason": str(exc),
                }
            return {
                "reference": json_value(original),
                "resolved_reference": json_value(producer),
                "context_reference": json_value(TraceOutputRef(producer.event_ref)),
                "status": "available",
                "origin": {
                    "program": run.program,
                    "operator": event.operator,
                    "run_mode": run.run_mode,
                    "occurred_at": event.occurred_at.isoformat(),
                    "kind": event.operator
                    if event.operator
                    in {"user_input", "observation", "analytical_note", "experience_fragment"}
                    else "recorded_result",
                },
                "content": json_value(value),
            }
        raise ContractError("Cyclic source reference")

    def _sources(self, subjects):
        """Keep historical write bindings and explicit evidence dependencies, not run context."""
        events, items, unavailable = {}, {}, []
        for subject in subjects:
            changes = self.graph.changes_of(subject)
            if not changes:
                unavailable.append({"subject": subject, "status": "not_found"})
                continue
            for change in reversed(changes):
                before, after = change.before.get(subject), change.after.get(subject)
                previous, current = json_value(before), json_value(after)
                fields = sorted(
                    k
                    for k in set(previous or {}) | set(current or {})
                    if (previous or {}).get(k) != (current or {}).get(k)
                )
                binding = {
                    "subject": subject,
                    "change_seq": change.seq,
                    "changed_at": change.at.isoformat(),
                    "operation": "create"
                    if before is None
                    else "delete"
                    if after is None
                    else "update",
                    "changed_fields": fields,
                    "latest_change": change.seq == changes[-1].seq,
                }
                try:
                    root = _reference(json_value(change.provenance))
                except ValueError:
                    unavailable.append(
                        {
                            **binding,
                            "status": "not_addressable",
                            "reason": "Graph change has no retained source reference",
                        }
                    )
                    continue
                binding["change_reference"] = json_value(root)
                pending, visited = deque([(root, None, True)]), set()
                while pending:
                    ref, parent, direct = pending.popleft()
                    material = self._material(ref, events)
                    event = self._event(ref.event_ref, events)
                    technical = (
                        event is not None
                        and event.operator == "graph_delta"
                        and self.memory.get_run(event.program_run).program == "GraphMutation"
                    )
                    if not technical:
                        key = (ref.event_ref, ref.output_path)
                        item = items.setdefault(
                            key, {k: v for k, v in material.items() if k != "content"}
                        )
                        origin = {**binding, "direct": direct}
                        if parent is not None:
                            origin["via"] = json_value(parent)
                        if origin not in item.setdefault("bindings", []):
                            item["bindings"].append(origin)
                    if ref in visited:
                        continue
                    visited.add(ref)
                    if event is not None:
                        pending.extend(
                            (
                                dependency,
                                parent if technical else ref,
                                direct if technical else False,
                            )
                            for dependency in event.dependencies
                        )
                        resolved = material.get("resolved_reference")
                        if resolved and resolved != json_value(ref):
                            pending.append((_reference(resolved), ref, False))
                    if technical and not event.dependencies:
                        unavailable.append(
                            {
                                **binding,
                                "status": "not_addressable",
                                "reason": "Graph mutation records no source dependencies",
                            }
                        )
        return _Selection(self.graph.revision, [*items.values(), *unavailable], events)

    def _check(self, selection, graph):
        if graph and selection.revision != self.graph.revision:
            raise ContractError("Graph changed; repeat source selection with next_page=false")
        for identity, original in selection.events.items():
            try:
                current = self.memory.get_event(identity)
            except KeyError:
                current = None
            if current != original:
                raise ContractError("Source availability changed; repeat with next_page=false")

    def read(self, method, payload, *, task_id):
        """Read or continue a task-scoped exact source selection within the model context."""
        payload = dict(payload)
        context = payload.pop("_read_context", None) or current_read_context.get()
        budget = read_budget(context, self.config.context_fraction)
        model = context["model"]
        next_page = payload.pop("next_page", False)
        next_page = False if next_page is None else next_page
        if type(next_page) is not bool:
            raise ContractError("next_page must be boolean")
        if method == "memory.read_source" and "max_items" in payload:
            raise ContractError("read_source does not accept max_items")
        maximum = payload.pop("max_items", self.config.max_items)
        maximum = self.config.max_items if maximum is None else maximum
        if type(maximum) is not int or maximum < 1:
            raise ContractError("max_items must be positive")
        field = "subjects" if method == "graph.sources" else "reference"
        if method not in {"graph.sources", "memory.read_source"} or set(payload) - {field}:
            raise ContractError("Unknown source read or unexpected fields")
        argument = payload.get(field)
        if argument is not None:
            if field == "subjects":
                if (
                    not isinstance(argument, list)
                    or not argument
                    or any(type(n) is not int or n <= 0 for n in argument)
                ):
                    raise ContractError("subjects must be a nonempty list of positive integer IDs")
                argument = sorted(set(argument))
            else:
                argument = json_value(_reference(argument))
        scope = (task_id, method)
        key = (
            (*scope, json.dumps(argument, sort_keys=True))
            if argument is not None
            else self._latest.get(scope)
        )
        if next_page:
            if key not in self._selections:
                raise ContractError("No saved source selection; start the read first")
            selection = self._selections[key]
            self._check(selection, field == "subjects")
            if selection.exhausted:
                raise ContractError("Source selection is exhausted")
        else:
            if argument is None:
                raise ContractError(f"{field} is required for a new source read")
            if field == "subjects":
                selection = self._sources(argument)
            else:
                events = {}
                material = self._material(_reference(argument), events)
                if material["status"] == "available":
                    content = material.pop("content")
                    material["format"] = "text" if isinstance(content, str) else "json"
                    material["content"] = (
                        content
                        if isinstance(content, str)
                        else json.dumps(
                            content, ensure_ascii=False, sort_keys=True, allow_nan=False
                        )
                    )
                selection = _Selection(self.graph.revision, material, events)
            self._selections[key] = selection
        self._latest[scope] = key
        if field == "subjects":
            result = self._list_page(selection, maximum, budget, model)
        else:
            result = self._content_page(selection, budget, model)
        return result

    def _fits(self, value, budget, model):
        return count_tokens(value, model, self.config.token_encoding) <= budget

    def _list_page(self, selection, maximum, budget, model):
        remaining = selection.value[selection.offset : selection.offset + maximum]
        result = {
            "scope": "recorded_history",
            "total": len(selection.value),
            "returned": 0,
            "has_more": selection.offset < len(selection.value),
            "items": [],
        }
        for item in remaining:
            candidate = {
                **result,
                "items": [*result["items"], item],
                "returned": result["returned"] + 1,
                "has_more": selection.offset + result["returned"] + 1 < len(selection.value),
            }
            if not self._fits(candidate, budget, model):
                break
            result = candidate
        if remaining and not result["returned"]:
            result["error"] = (
                "One source record exceeds the token budget; increase available context or select fewer subjects"
            )
        if not self._fits(result, budget, model):
            raise ContractError("Insufficient model context for source metadata")
        selection.offset += result["returned"]
        selection.exhausted = not result["has_more"]
        return result

    def _content_page(self, selection, budget, model):
        material = selection.value
        if material["status"] != "available":
            result = {**material, "has_more": False}
            if not self._fits(result, budget, model):
                raise ContractError("Insufficient model context for source status")
            selection.exhausted = True
            return result
        text = material["content"]
        start = selection.offset

        def page(end):
            return {
                **material,
                "content": text[start:end],
                "start": start,
                "end": end,
                "total_characters": len(text),
                "has_more": end < len(text),
            }

        low, high = start, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if self._fits(page(middle), budget, model):
                low = middle
            else:
                high = middle - 1
        result = page(low)
        if not self._fits(result, budget, model) or low == start and start < len(text):
            raise ContractError("Insufficient model context for source content")
        selection.offset = low
        selection.exhausted = not result["has_more"]
        return result
