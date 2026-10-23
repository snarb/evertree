"""Core semantic gateway: identities, bounded search and checked writes."""

import hashlib
import json
import math

from ..graph.types import RelationInstance, node_from_dict
from ..memory.types import TraceOutputRef, _references
from ..values import ContractError, json_value
from .compile import compile_action
from .fragments import authorized_fragment, prepare_sections
from .jev import JevFilter
from .queries import GraphQueries
from .reading import card, search_card
from .searching import query_key, search_kinds, search_limit, search_queries
from .sources import SourceReads
from .tools import CREATE_ACTIONS, validate_action


class SemanticService:
    def __init__(self, graph, memory, attribution, config, index, operations):
        self.graph, self.memory, self.attribution = graph, memory, attribution
        self.config, self.index, self.operations = config, index, operations
        self._index_reads = {}
        self.jev = JevFilter(config.jev)
        self.queries = GraphQueries(graph, attribution, config.read)
        self.source_reads = SourceReads(graph, memory, config.read)

    def release(self, task_id):
        """Discard a task's transient query continuations and index-read state."""
        self.queries.release(task_id)
        self.source_reads.release(task_id)
        self._index_reads.pop(task_id, None)

    def _exact(self, query, kinds):
        matches = (
            self.graph.lookup(query)
            if kinds is None
            else sorted(
                (node for kind in kinds for node in self.graph.lookup(query, kind=kind)),
                key=lambda node: node.id,
            )
        )
        return (
            [search_card(self.graph, node) for node in matches]
            if matches or type(query) is int
            else None
        )

    def lookup(self, queries, kinds=None, limit=10, *, task_id, scope):
        """Return a merged batch only when every query resolves without external retrieval."""
        queries = search_queries(queries)
        search_limit(limit)
        kinds = search_kinds(kinds)
        matches = [self._exact(query, kinds) for query in queries]
        if any(items is None for items in matches):
            return None
        rows = [
            self.results(query, kinds, items, [], limit, task_id, scope=scope, exact=True)
            for query, items in zip(queries, matches, strict=True)
        ]
        return self._merge(queries, rows, total_ids={n["id"] for row in matches for n in row})

    def results(self, query, kinds, items, errors, limit, task_id, *, scope, exact=False):
        """Record Core's invocation-scoped completeness confirmation for one query."""
        search_limit(limit)
        key = [
            task_id,
            scope,
            query if type(query) is int else query_key(query),
            search_kinds(kinds),
        ]
        complete = not errors
        if self._search_confirmation(key) != complete:
            with self.memory.transaction():
                run = self.memory.start_run("SemanticSearchReview", "core", {"key": key})
                event = self.memory.record(run, "search_review", output={"complete": complete})
                self.memory.finish_run(run)
                self.memory.retain(self.memory.output_ref(event), "task:" + task_id)
        return {
            "status": "incomplete" if errors else "complete",
            "items": items[:limit],
            "errors": errors,
            "total": len(items),
            "exact": exact,
        }

    @staticmethod
    def _merge(queries, rows, *, scores=None, total_ids=None, warnings=()):
        scores = scores or {}
        items, exact_ids, summaries, errors = {}, set(), [], []
        for position, (query, row) in enumerate(zip(queries, rows, strict=True)):
            summaries.append(
                {
                    "query": query,
                    **{k: row[k] for k in ("status", "exact", "total")},
                    "ids": [n["id"] for n in row["items"]],
                }
            )
            errors.extend({**error, "query_index": position} for error in row["errors"])
            for node in row["items"]:
                identity = node["id"]
                if row["exact"]:
                    exact_ids.add(identity)
                if identity not in items:
                    items[identity] = {**node, "query_indices": []}
                items[identity]["query_indices"].append(position)
                channels = set(items[identity].get("channels", [])) | set(node.get("channels", []))
                if channels:
                    items[identity]["channels"] = sorted(channels)
        ordered = sorted(items, key=lambda i: (i not in exact_ids, -scores.get(i, 0), i))
        return {
            "status": "incomplete" if errors else "complete",
            "queries": summaries,
            "items": [items[i] for i in ordered],
            "errors": errors,
            "warnings": list(warnings),
            "total": len(total_ids if total_ids is not None else items),
            "exact": all(row["exact"] for row in rows),
        }

    def failed_search(self, queries, errors, *, kinds=None, limit=10, task_id, scope):
        """Revoke unresolved queries after runtime failure while preserving exact matches."""
        queries = search_queries(queries)
        search_limit(limit)
        kinds = search_kinds(kinds)
        rows = []
        for query in queries:
            exact = self._exact(query, kinds)
            rows.append(
                self.results(
                    query,
                    kinds,
                    exact or [],
                    errors if exact is None else [],
                    limit,
                    task_id,
                    scope=scope,
                    exact=exact is not None,
                )
            )
        return self._merge(queries, rows)

    async def _search_results(self, payload, metadata):
        queries = search_queries(payload["queries"])
        kinds = search_kinds(payload.get("kinds"))
        limit = search_limit(payload["limit"])
        rankings = payload["rankings"]
        if len(rankings) != len(queries):
            raise ContractError("Search ranking count mismatch")
        completed = self._index_reads.get(metadata["task_id"], {}).pop(metadata["run_id"], {})
        candidates, rows, scores, exact_ids = {}, [], {}, set()
        for position, (query, ranking) in enumerate(zip(queries, rankings, strict=True)):
            exact = self._exact(query, kinds)
            if exact is not None:
                exact_ids.update(node["id"] for node in exact)
                rows.append((exact, [], True))
                continue
            errors = list(ranking["errors"])
            for method in ("semantic.bm25", "semantic.vector"):
                read = completed.get(method)
                if read is None or read[0] != (queries, kinds):
                    error = "Search needs completed index reads"
                else:
                    error = read[1][position].get("error")
                if error and not any(e["channel"] == method.split(".")[1] for e in errors):
                    errors.append({"channel": method.split(".")[1], "error": error})
            checked, seen = [], set()
            for item in ranking["items"]:
                node = self.graph.get(item["id"])
                if kinds is not None and node.kind not in kinds:
                    raise ContractError("Search result violates kinds filter")
                channels = list(item.get("channels", []))
                if not channels or set(channels) - {"bm25", "vector"}:
                    raise ContractError("Search result has an unknown index channel")
                score = item["score"]
                if type(score) not in {int, float} or not math.isfinite(score) or score < 0:
                    raise ContractError("Invalid fused search score")
                if node.id in seen:
                    continue
                seen.add(node.id)
                rendered = {
                    **search_card(self.graph, node),
                    "channels": channels,
                    "source_facts": [],
                }
                checked.append(rendered)
                candidates[node.id] = search_card(self.graph, node)
                scores[node.id] = scores.get(node.id, 0) + score
            rows.append((checked, errors, False))
        kept, warnings = await self.jev.filter(
            queries, [node for identity, node in candidates.items() if identity not in exact_ids]
        )
        kept.update(exact_ids)
        rendered, total_ids = [], set()
        for query, (items, errors, exact) in zip(queries, rows, strict=True):
            if not exact:
                items = [node for node in items if node["id"] in kept]
            total_ids.update(node["id"] for node in items)
            rendered.append(
                self.results(
                    query,
                    kinds,
                    items,
                    errors,
                    limit,
                    metadata["task_id"],
                    scope=metadata["semantic_scope"],
                    exact=exact,
                )
            )
        return self._merge(queries, rendered, scores=scores, total_ids=total_ids, warnings=warnings)

    @staticmethod
    def _authorize(metadata):
        if (
            not (
                metadata.get("knowledge_integration_authorized") is True
                or metadata.get("consciousness_graph_authorized") is True
            )
            or metadata.get("program", {}).get("role") != "exec"
            or not metadata.get("program", {}).get("revision")
            or not metadata.get("integration_operation_id")
        ):
            raise PermissionError("Semantic writes require admitted graph execution")

    @staticmethod
    def _reference(value):
        if (
            not isinstance(value, dict)
            or set(value) - {"event_ref", "output_path"}
            or type(value.get("event_ref")) is not int
            or not isinstance(value.get("output_path", []), (list, tuple))
            or any(
                type(part) not in {int, str} or (type(part) is int and part < 0)
                for part in value.get("output_path", [])
            )
        ):
            raise ContractError("Invalid retained experience reference")
        return TraceOutputRef(**value)

    def sources(self, experience_refs, focus=None, *, metadata):
        """Authorize integration and resolve retained experience with its producer provenance."""
        self._authorize(metadata)
        if not isinstance(experience_refs, list) or not experience_refs:
            raise ContractError("Integration requires nonempty retained experience_refs")
        if focus is not None and not isinstance(focus, str):
            raise ContractError("Integration focus must be text")
        values = []
        for source in experience_refs:
            ref = self._reference(source)
            producer = self.memory.producer_of(ref)
            event = self.memory.get_event(producer.event_ref)
            run = self.memory.get_run(event.program_run)
            values.append(
                {
                    "reference": json_value(ref),
                    "content": json_value(self.memory.resolve(ref)),
                    "origin": {
                        "program": run.program,
                        "revision": run.base_commit_sha,
                        "run_mode": run.run_mode,
                        "operator": event.operator,
                        "output_type": event.output_type,
                        "analyst": run.arguments.get("producer_program")
                        if run.program == "AnalyticalNote"
                        else None,
                    },
                }
            )
        return {
            "experience": values,
            "focus": focus,
            "context": json_value(metadata.get("integration_context", {})),
        }

    @staticmethod
    def _contains(parent, child):
        return (
            parent.event_ref == child.event_ref
            and child.output_path[: len(parent.output_path)] == parent.output_path
        )

    def prepare_sources(self, experience_refs, sections, focus=None, *, metadata):
        """Retain exact sections while preserving the original integration authority."""
        material = self.sources(experience_refs, focus, metadata=metadata)
        return prepare_sections(self.memory, material, sections, metadata)

    def _search_confirmation(self, key):
        # Core records both complete and incomplete results so replay cannot revive
        # an earlier approval after a failed explicit search.
        for event in reversed(self.memory.events):
            if event.operator != "search_review":
                continue
            run = self.memory.get_run(event.program_run)
            if (
                run.program == "SemanticSearchReview"
                and json_value(run.arguments.get("key", ())) == key
            ):
                return event.output["complete"]
        return None

    def _check_search(self, action, metadata):
        if action["action"] not in CREATE_ACTIONS:
            return
        query = query_key(action["name"])
        # A scoped search cannot establish that an identity is absent from the whole graph.
        key = [metadata["task_id"], metadata["semantic_scope"], query, None]
        if self._search_confirmation(key) is not True:
            raise ContractError("Creating an identity requires a complete search for " + query)

    def write(self, payload, metadata):
        """Validate and persist one source-backed semantic operation, deduplicating durable callback retries."""
        self._authorize(metadata)
        try:
            action = payload["action"]
            validate_action(action)
            operation_key = payload["operation_key"]
            if not isinstance(operation_key, str) or not operation_key.strip():
                raise ContractError("Graph writes require a runtime operation key")
            key = [metadata["task_id"], metadata["integration_operation_id"], operation_key]
            fingerprint = hashlib.sha256(
                json.dumps(
                    action,
                    sort_keys=True,
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            with self.graph.transaction(), self.memory.transaction():
                # The durable callback may repeat after the mutation but before its acknowledgement.
                for event in reversed(self.memory.events):
                    if (
                        event.operator == "semantic_write"
                        and self.memory.get_run(event.program_run).program == "SemanticWrite"
                        and list(event.arguments.get("key", ())) == key
                    ):
                        if event.arguments.get("fingerprint") != fingerprint:
                            raise ContractError(
                                "A graph operation key cannot be reused with different arguments"
                            )
                        return json_value(event.output)
                inputs = tuple(self._reference(ref) for ref in payload["experience_refs"])
                producers = tuple(self.memory.producer_of(ref) for ref in inputs)
                refs = list(action.get("sources", []))
                if action["action"] == "save_note" and action["source"] not in refs:
                    refs.append(action["source"])
                sources = tuple(dict.fromkeys(self._reference(ref) for ref in refs))
                if not sources:
                    raise ContractError("Graph writes require sources")
                for ref in sources:
                    resolved = self.memory.producer_of(ref)
                    declared = any(self._contains(parent, ref) for parent in (*inputs, *producers))
                    retained = any(self._contains(parent, resolved) for parent in producers)
                    fragment = authorized_fragment(self.memory, ref, producers, metadata)
                    if not (declared and retained or fragment):
                        raise ContractError(
                            "Write source is outside supplied experience. Choose a supplied "
                            "experience reference or its actual nested part and retry; a supplied "
                            "reading or analytical note already retains its earlier source dependencies."
                        )
                material = self.sources(json_value(sources), metadata=metadata)
                self._check_search(action, metadata)
                delta, identity = compile_action(
                    self.graph, action, material, attribution=self.attribution
                )
                for embedded in _references(json_value(delta)):
                    if not any(self._contains(source, embedded) for source in sources):
                        raise ContractError(
                            "Embedded provenance must belong to this operation's sources"
                        )
                changed_ids = {update.id for update in delta.updates} | set(delta.deletes)

                def fact_key(fact):
                    return (
                        fact.relation_type,
                        json.dumps(json_value(fact.args), sort_keys=True),
                        json.dumps(json_value(fact.properties), sort_keys=True),
                    )

                known = {
                    fact_key(fact) for fact in self.graph.facts() if fact.id not in changed_ids
                }
                updated = [
                    node_from_dict(
                        {**json_value(self.graph.get(update.id)), **json_value(update.changes)}
                    )
                    for update in delta.updates
                ]
                for node in (*delta.creates, *updated):
                    if isinstance(node, RelationInstance):
                        signature = fact_key(node)
                        if signature in known:
                            raise ContractError("Fact already exists; use its existing identity")
                        known.add(signature)
                change = self.operations.apply_delta(
                    delta,
                    task_id=metadata["task_id"],
                    revision=metadata["program"]["revision"],
                    run_mode=metadata.get("run_mode", "live"),
                    source_refs=sources,
                    integration_operation_id=metadata["integration_operation_id"],
                )
                result = {
                    **({"object": identity} if identity is not None else {}),
                    "created": [card(node) for node in delta.creates],
                    "updated": [card(self.graph.get(update.id)) for update in delta.updates],
                    "deleted": list(delta.deletes),
                    "revision": change.seq,
                }
                run = self.memory.start_run(
                    "SemanticWrite",
                    metadata["program"]["revision"],
                    {},
                    run_mode=metadata.get("run_mode", "live"),
                )
                event = self.memory.record(
                    run,
                    "semantic_write",
                    arguments={"key": key, "fingerprint": fingerprint},
                    output=result,
                )
                self.memory.finish_run(run)
                self.memory.retain(self.memory.output_ref(event), "task:" + metadata["task_id"])
                return result
        except (ValueError, KeyError, TypeError, AttributeError, PermissionError) as exc:
            return {"error": str(exc)}

    async def execute(self, method, payload, metadata):
        """Dispatch task-scoped graph reads, index queries and checked semantic writes."""
        task_id = metadata["task_id"]
        if method in {"graph.sources", "memory.read_source"}:
            return self.source_reads.read(method, payload, task_id=task_id)
        if method in {"graph.query", "graph.walk"}:
            return self.queries.read(method.removeprefix("graph."), payload, task_id=task_id)
        if method == "semantic.lookup":
            self._index_reads.setdefault(task_id, {}).pop(metadata["run_id"], None)
            return self.lookup(**payload, task_id=task_id, scope=metadata["semantic_scope"])
        if method in {"semantic.bm25", "semantic.vector"}:
            queries = search_queries(payload["queries"])
            kinds = search_kinds(payload.get("kinds"))
            unresolved = [
                position
                for position, query in enumerate(queries)
                if self._exact(query, kinds) is None
            ]
            operation = self.index.lexical if method == "semantic.bm25" else self.index.vector
            ranked = await operation(
                [search_card(self.graph, n) for n in self.graph.nodes()],
                [queries[i] for i in unresolved],
                kinds,
            )
            if len(ranked) != len(unresolved):
                raise ContractError("Search channel response count mismatch")
            result = [{"ids": []} for _ in queries]
            for position, row in zip(unresolved, ranked, strict=True):
                result[position] = row
            self._index_reads.setdefault(task_id, {}).setdefault(metadata["run_id"], {})[method] = (
                (queries, kinds),
                result,
            )
            return result
        if method == "semantic.results":
            return await self._search_results(payload, metadata)
        if method == "semantic.sources":
            return self.sources(**payload, metadata=metadata)
        if method == "semantic.prepare_sources":
            return self.prepare_sources(**payload, metadata=metadata)
        if method == "semantic.write":
            return self.write(payload, metadata)
        raise ValueError("Unknown semantic operation")
