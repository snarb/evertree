"""Slot queries and breadth-first walks over facts, with bounded model output."""

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from uuid import uuid4

from ..graph.matching import NODE_TYPES, match_fact, node_ids, prepare
from ..graph.types import Facet, RelationType
from ..tokens import count_tokens, current_read_context, read_budget
from ..values import ContractError, json_value, timestamp
from .actions import validate_action
from .reading import card, describe, resolve

_WORK_LIMIT = 10_000
_FIELDS = {"description", "properties", "schema"}


@dataclass
class _Query:
    task: str
    revision: int
    method: str
    arguments: dict
    iterator: object
    node_result: bool
    items: dict = field(default_factory=dict)
    complete: bool = False
    ordered: list = field(default_factory=list)

    def advance(self):
        """Consume a bounded traversal batch, merging duplicate nodes before ordering completed results."""
        for _ in range(_WORK_LIMIT):
            try:
                entry = next(self.iterator)
            except StopIteration:
                self.complete = True
                self.ordered = sorted(
                    self.items.values(), key=lambda item: (item.get("depth", 0), item["id"])
                )
                return
            if entry is None:
                continue
            previous = self.items.get(entry["id"])
            if previous is None:
                self.items[entry["id"]] = entry
            else:
                previous["facts"].update(entry["facts"])
                if "depth" in entry:
                    previous["depth"] = min(previous["depth"], entry["depth"])
                if entry["status"] == "applicable":
                    previous["status"] = "applicable"


class GraphQueries:
    def __init__(self, graph, attribution, config):
        self.graph, self.attribution, self.config = graph, attribution, config
        self._pages = {}
        self._progress = {}
        self._continuations = {}
        self._latest = {}

    def release(self, task_id):
        """Discard all private pagination and traversal state owned by a task."""
        self._pages = {k: v for k, v in self._pages.items() if v[0].task != task_id}
        self._progress = {k: v for k, v in self._progress.items() if k in self._pages}
        self._continuations = {k: v for k, v in self._continuations.items() if k[0] != task_id}
        self._latest = {k: v for k, v in self._latest.items() if k[0] != task_id}

    def _resolve(self, value, *, relation=False):
        node = resolve(self.graph, value)
        if isinstance(node, dict):
            return node
        if relation and not isinstance(node, RelationType):
            raise ContractError("relation must identify a RelationType")
        return node

    def _prepare(self, method, arguments, task_id):
        """Validate query or walk selections and construct their incremental traversal iterator."""
        args = {key: value for key, value in arguments.items() if value is not None}
        fields = args.setdefault("fields", ["description"])
        if not isinstance(fields, list) or any(f not in _FIELDS for f in fields):
            raise ContractError("fields must select description, properties or schema")
        args["at"] = timestamp(args["at"]) if args.get("at") else None
        relation = None
        if args.get("relation") is not None:
            relation = self._resolve(args["relation"], relation=True)
            if isinstance(relation, dict):
                return relation
            args["relation"] = relation.id
        if method == "walk":
            if relation is None or "start" not in args:
                raise ContractError("walk requires start and relation")
            start = self._resolve(args["start"])
            if isinstance(start, dict):
                return start
            args["start"] = start.id
            slots = {slot.label: slot for slot in relation.signature}
            for role in ("from_slot", "to_slot"):
                if args.get(role) not in slots or slots[args[role]].value_type not in NODE_TYPES:
                    raise ContractError(f"{role} must name a node-valued slot")
            if args["from_slot"] == args["to_slot"]:
                raise ContractError("walk requires different from_slot and to_slot")
            depth = arguments.get("max_depth", 1)
            if depth is not None and (type(depth) is not int or depth < 1):
                raise ContractError("max_depth must be a positive integer or null for all levels")
            args["max_depth"] = depth
            result = args.setdefault("result", "nodes")
            if result not in {"nodes", "count_nodes", "exists"}:
                raise ContractError("walk result must be nodes, count_nodes or exists")
            clauses = prepare(self.graph, relation, {}, args.get("where", []))
            iterator = self._walk(args, relation, clauses)
            node_result = True
        else:
            subject = args.get("subject")
            if subject is not None:
                subject = self._resolve(subject)
                if isinstance(subject, dict):
                    return subject
                args["subject"] = subject.id
            if relation is None and subject is None:
                raise ContractError("query requires relation or subject")
            if relation is None and any(args.get(k) for k in ("bindings", "where", "select")):
                raise ContractError("bindings, where and select require a relation")
            result = args.setdefault("result", "matches")
            if result not in {"matches", "nodes", "count_matches", "count_nodes", "exists"}:
                raise ContractError("Unknown query result mode")
            bindings = {}
            for binding in args.get("bindings", []):
                if set(binding) != {"slot", "value"} or binding["slot"] in bindings:
                    raise ContractError("bindings require unique slot/value entries")
                value = binding["value"]
                bindings[binding["slot"]] = tuple(value) if isinstance(value, list) else value
            clauses = (
                prepare(self.graph, relation, bindings, args.get("where", [])) if relation else ()
            )
            selected = args.get("select", [])
            slots = {slot.label: slot for slot in relation.signature} if relation else {}
            if len(selected) != len(set(selected)) or any(label not in slots for label in selected):
                raise ContractError("select must name unique declared slots")
            node_result = result in {"nodes", "count_nodes"}
            if node_result and (
                len(selected) != 1 or slots[selected[0]].value_type not in NODE_TYPES
            ):
                raise ContractError("nodes and count_nodes require one node-valued select slot")
            iterator = self._query(args, relation, bindings, clauses, node_result)
        return _Query(task_id, self.graph.revision, method, args, iterator, node_result)

    def _query(self, args, relation, bindings, clauses, nodes):
        """Yield matching facts or selected participants, including scan markers for bounded work accounting."""
        for fact in self.graph.facts(relation.id if relation else None):
            schema = relation or self.graph.get(fact.relation_type)
            status = match_fact(self.graph, fact, schema, bindings, clauses, valid_at=args["at"])
            if status is None or (
                args.get("subject") is not None and args["subject"] not in node_ids(fact, schema)
            ):
                yield None
                continue
            if nodes:
                values = fact.args.get(args["select"][0])
                values = (
                    values
                    if isinstance(values, (list, tuple))
                    else (() if values is None else (values,))
                )
                for identity in values:
                    yield {"id": identity, "status": status, "facts": {fact.id: None}}
                if not values:
                    yield None
            else:
                yield {"id": fact.id, "status": status, "facts": {fact.id: None}}

    def _walk(self, args, relation, clauses):
        """Traverse relation neighbors with depth and temporal applicability tracking."""
        adjacency = defaultdict(list)
        for fact in self.graph.facts(relation.id):
            status = match_fact(self.graph, fact, relation, {}, clauses, valid_at=args["at"])
            if status is not None:
                sources = fact.args.get(args["from_slot"])
                sources = (
                    sources
                    if isinstance(sources, (list, tuple))
                    else (() if sources is None else (sources,))
                )
                for source in sources:
                    adjacency[source].append((fact, status))
            yield None
        pending = deque([(args["start"], 0, "applicable")])
        # An applicable path may reach a node after a shorter uncertain path.
        visited = {(args["start"], "applicable")}
        while pending:
            source, depth, path_status = pending.popleft()
            if args["max_depth"] is not None and depth >= args["max_depth"]:
                continue
            for fact, status in adjacency[source]:
                combined = "unknown" if "unknown" in (path_status, status) else "applicable"
                targets = fact.args.get(args["to_slot"])
                targets = (
                    targets
                    if isinstance(targets, (list, tuple))
                    else (() if targets is None else (targets,))
                )
                for target in targets:
                    if target == args["start"]:
                        yield None
                        continue
                    yield {
                        "id": target,
                        "depth": depth + 1,
                        "status": combined,
                        "facts": {fact.id: source},
                    }
                    key = (target, combined)
                    if key not in visited:
                        visited.add(key)
                        pending.append((target, depth + 1, combined))

    def _card(self, identity, fields, at):
        node = self.graph.get(identity)
        item = {"id": node.id, "name": node.name, "kind": node.kind}
        if "description" in fields and node.description:
            item["description"] = node.description
        if isinstance(node, Facet):
            item.update({k: v for k, v in card(node).items() if k.startswith("valid_")})
            if at is not None:
                item["temporal_status"] = node.applicability(at)
        if "properties" in fields:
            properties = describe(
                self.graph, self.attribution, identity, focus="properties", at=at
            )["properties"]
            if properties:
                item["properties"] = [
                    {
                        key: value
                        for key, value in prop.items()
                        if not (key == "description" and value is None)
                        and not (key == "required_parameters" and value == [])
                    }
                    for prop in properties
                ]
        if "schema" in fields and isinstance(node, RelationType):
            item["signature"] = [
                {key: value for key, value in slot.items() if value is not None}
                for slot in json_value(node.signature)
            ]
        return item

    def _fact(self, identity, at):
        fact = self.graph.get(identity)
        relation = self.graph.get(fact.relation_type)
        item = {
            "id": fact.id,
            "relation": relation.name,
            "relation_type": relation.id,
            "args": self._arguments(fact),
        }
        if fact.description:
            item["description"] = fact.description
        if fact.properties:
            item["properties"] = json_value(fact.properties)
        if at is not None:
            item["temporal_status"] = self.graph.fact_applicability(fact, at)
        return item

    def _arguments(self, fact):
        values = json_value(fact.args)
        for slot in self.graph.get(fact.relation_type).signature:
            if slot.value_type in NODE_TYPES and values.get(slot.label) is not None:
                value = values[slot.label]
                values[slot.label] = (
                    [{"node": identity} for identity in value]
                    if isinstance(value, list)
                    else {"node": value}
                )
        return values

    def _render(self, query, entries, next_cursor):
        """Project selected graph results into model-facing node and fact records."""
        unknown = sum(item["status"] == "unknown" for item in query.items.values())
        response = {
            "total" if query.complete else "total_at_least": len(query.items),
            "returned": len(entries),
            "has_more": next_cursor is not None,
        }
        if unknown:
            response["applicable"] = len(query.items) - unknown
            response["unknown"] = unknown
        if next_cursor:
            response["next_cursor"] = next_cursor
        if not query.complete:
            response["status"] = "scanning"
        if query.method == "walk":
            response["max_depth"] = query.arguments["max_depth"]
        result = query.arguments["result"]
        if result in {"count_matches", "count_nodes", "exists"}:
            if result == "exists":
                response["exists"] = (
                    True
                    if len(query.items) > unknown
                    else (None if unknown or not query.complete else False)
                )
            return response
        nodes, facts, items = {}, {}, []
        at, fields = query.arguments["at"], query.arguments["fields"]
        for entry in entries:
            if query.node_result:
                item = {"node": entry["id"], "source_facts": list(entry["facts"])}
                nodes[entry["id"]] = self._card(entry["id"], fields, at)
                if "depth" in entry:
                    item["depth"] = entry["depth"]
                    item["via"] = [
                        {"fact": fact, "from": source} for fact, source in entry["facts"].items()
                    ]
            else:
                fact = self.graph.get(entry["id"])
                selected = query.arguments.get("select") or fact.args.keys()
                arguments = self._arguments(fact)
                item = {
                    "source_fact": fact.id,
                    "values": {label: arguments.get(label) for label in selected},
                }
                for slot in self.graph.get(fact.relation_type).signature:
                    if slot.label in selected and slot.value_type in NODE_TYPES:
                        value = fact.args.get(slot.label)
                        for identity in (
                            value
                            if isinstance(value, (list, tuple))
                            else (() if value is None else (value,))
                        ):
                            nodes[identity] = self._card(identity, fields, at)
            if at is not None:
                item["temporal_status"] = entry["status"]
            for identity in entry["facts"]:
                facts[identity] = self._fact(identity, at)
                fact = self.graph.get(identity)
                for participant in node_ids(fact, self.graph.get(fact.relation_type)):
                    if participant not in nodes:
                        nodes[participant] = self._card(participant, [], at)
            items.append(item)
        response["items"] = items
        if nodes:
            response["nodes"] = list(nodes.values())
        if facts:
            response["facts"] = list(facts.values())
        return response

    def read(self, method, payload, *, task_id):
        """Execute or continue an exact graph query within task scope and model output budgets."""
        payload = dict(payload)
        context = payload.pop("_read_context", None) or current_read_context.get()
        validate_action({"action": method, **payload})
        next_page = payload.pop("next_page", False)
        selection = {k: v for k, v in payload.items() if k != "max_items" and v is not None}
        # Explicit null depth means all levels, whereas omitted depth means one.
        if method == "walk" and selection and "max_depth" in payload:
            selection["max_depth"] = payload["max_depth"]
        scope = (task_id, method)
        key = (*scope, json.dumps(selection, sort_keys=True, ensure_ascii=False))
        if next_page:
            if not selection:
                key = self._latest.get(scope)
            if key not in self._continuations:
                raise ContractError("No saved selection for next_page; start the query first")
            cursor = self._continuations[key]
            if cursor is None:
                raise ContractError("No next page; this selection is exhausted")
            payload = {"cursor": cursor, "max_items": payload.get("max_items")}
        response = self._read_page(method, payload, task_id=task_id, context=context)
        response = dict(response)
        cursor = response.pop("next_cursor", None)
        if "returned" in response:
            self._continuations[key] = cursor
            self._latest[scope] = key
        return response

    def _read_page(self, method, payload, *, task_id, context):
        """Pack a continuation page within both item and serialized model-token limits."""
        payload = dict(payload)
        budget = read_budget(context, self.config.context_fraction)
        model = context["model"]
        maximum = payload.pop("max_items", None)
        maximum = self.config.max_items if maximum is None else maximum
        if type(maximum) is not int or maximum < 1:
            raise ContractError("max_items must be a positive integer")
        cursor = payload.pop("cursor", None)
        if cursor:
            if cursor not in self._pages:
                raise ContractError("Unknown or expired cursor; repeat the query")
            query, offset = self._pages[cursor]
            if query.task != task_id or query.method != method:
                raise ContractError("Cursor belongs to another task or operation")
            if query.revision != self.graph.revision:
                raise ContractError("Graph changed; repeat the query with next_page=false")
            if any(value is not None for value in payload.values()):
                raise ContractError("Continue with cursor and optional max_items only")
            if cursor in self._progress:
                response = self._progress[cursor]
                if count_tokens(response, model, self.config.token_encoding) > budget:
                    raise ContractError("Insufficient model context for graph statistics")
                return response
        else:
            query = self._prepare(method, payload, task_id)
            if isinstance(query, dict):
                candidates = query.get("candidates", [])
                query = {**query, "candidates_total": len(candidates)}
                while (
                    count_tokens(query, model, self.config.token_encoding) > budget and candidates
                ):
                    candidates.pop()
                    query["candidates_truncated"] = True
                if count_tokens(query, model, self.config.token_encoding) > budget:
                    raise ContractError("Insufficient model context for graph resolution")
                return query
            offset = 0
        if not query.complete:
            query.advance()
        next_cursor = uuid4().hex
        if not query.complete:
            response = self._render(query, [], next_cursor)
            self._pages[next_cursor] = (query, offset)
        else:
            remaining = query.ordered[offset : offset + maximum]
            if query.arguments["result"] in {"count_matches", "count_nodes", "exists"}:
                remaining = []
                response = self._render(query, [], None)
            else:
                # Count the same JSON serialization sent to the model, including
                # metadata, participant cards and the continuation token.
                low, high = 0, len(remaining)
                while low < high:
                    middle = (low + high + 1) // 2
                    token = next_cursor if offset + middle < len(query.ordered) else None
                    candidate = self._render(query, remaining[:middle], token)
                    if count_tokens(candidate, model, self.config.token_encoding) <= budget:
                        low = middle
                    else:
                        high = middle - 1
                token = next_cursor if offset + low < len(query.ordered) else None
                response = self._render(query, remaining[:low], token)
                if not low and remaining:
                    response["error"] = (
                        "One complete item exceeds the token budget; request fewer fields or narrow the query"
                    )
                    response["object"] = remaining[0]["id"]
                if token:
                    self._pages[token] = (query, offset + low)
        if count_tokens(response, model, self.config.token_encoding) > budget:
            raise ContractError(
                "Insufficient model context for a graph result; compact context before reading"
            )
        if cursor and response.get("status") == "scanning":
            self._progress[cursor] = response
        return response
