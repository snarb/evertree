"""Core semantic gateway: identities, bounded search and checked writes."""

import hashlib
import json

from ..graph.types import RelationInstance, node_from_dict
from ..memory.types import TraceOutputRef, _references
from ..values import ContractError, json_value
from .compile import compile_action
from .queries import GraphQueries
from .reading import card
from .tools import CREATE_ACTIONS, validate_action


class SemanticService:
    def __init__(self, graph, memory, attribution, config, index, operations):
        self.graph, self.memory, self.attribution = graph, memory, attribution
        self.config, self.index, self.operations = config, index, operations
        self._index_reads = {}
        self.queries = GraphQueries(graph, attribution, config.read)

    def release(self, task_id):
        """Discard a task's transient query continuations and index-read state."""
        self.queries.release(task_id)
        self._index_reads.pop(task_id, None)

    def lookup(self, query, kind=None, limit=20, *, task_id, scope):
        """Serve exact graph matches, returning None when text needs non-exact search."""
        kind = kind.strip().casefold() if kind is not None else None
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ContractError("limit must be between 1 and 20")
        matches = self.graph.lookup(query, kind=kind)
        if matches or isinstance(query, int):
            return self.results(
                query, kind, [card(n) for n in matches], [], limit, task_id, scope=scope, exact=True
            )
        if not query.strip():
            raise ContractError("Search query cannot be empty")
        return None

    def results(self, query, kind, items, errors, limit, task_id, *, scope, exact=False):
        """Record invocation-scoped search results for candidate review and report channel completeness."""
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ContractError("limit must be between 1 and 20")
        key = [task_id, scope, str(query).strip().casefold()]
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

    def _search_confirmation(self, key):
        # Core records both complete and incomplete results so replay cannot revive
        # an earlier approval after a failed explicit search.
        for event in reversed(self.memory.events):
            if event.operator != "search_review":
                continue
            run = self.memory.get_run(event.program_run)
            if run.program == "SemanticSearchReview" and list(run.arguments.get("key", ())) == key:
                return event.output["complete"]
        return None

    def _check_search(self, action, metadata):
        if action["action"] not in CREATE_ACTIONS:
            return
        query = action["name"].strip().casefold()
        key = [metadata["task_id"], metadata["semantic_scope"], query]
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
                refs = list(action.get("sources", []))
                if action["action"] == "save_note" and action["source"] not in refs:
                    refs.append(action["source"])
                sources = tuple(dict.fromkeys(self._reference(ref) for ref in refs))
                if not sources:
                    raise ContractError("Graph writes require sources")
                for ref in sources:
                    if not any(self._contains(parent, ref) for parent in inputs):
                        raise ContractError("Write source is outside supplied experience")
                material = self.sources(json_value(sources), metadata=metadata)
                self._check_search(action, metadata)
                delta, identity = compile_action(self.graph, action, material)
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
        if method in {"graph.query", "graph.walk"}:
            return self.queries.read(method.removeprefix("graph."), payload, task_id=task_id)
        if method == "semantic.lookup":
            self._index_reads.setdefault(task_id, {}).pop(metadata["run_id"], None)
            return self.lookup(**payload, task_id=task_id, scope=metadata["semantic_scope"])
        if method in {"semantic.bm25", "semantic.vector"}:
            nodes = [card(n) for n in self.graph.nodes()]
            operation = self.index.lexical if method == "semantic.bm25" else self.index.vector
            result = await operation(nodes, payload["query"], payload.get("kind"))
            key = metadata["run_id"]
            self._index_reads.setdefault(task_id, {}).setdefault(key, {})[method] = (
                payload["query"],
                payload.get("kind"),
            )
            return result
        if method == "semantic.results":
            errors = list(payload["errors"])
            key = metadata["run_id"]
            completed = self._index_reads.get(task_id, {}).pop(key, {})
            if not errors and completed != {
                method: (payload["query"], payload.get("kind"))
                for method in ("semantic.bm25", "semantic.vector")
            }:
                errors.append({"channel": "search", "error": "Search needs completed index reads"})
            items = payload["items"]
            checked = []
            for item in items:
                node = self.graph.get(item["id"])
                if payload.get("kind") is not None and node.kind != payload["kind"]:
                    raise ContractError("Search result violates kind filter")
                channels = list(item.get("channels", []))
                if not channels or set(channels) - {"bm25", "vector"}:
                    raise ContractError("Search result has an unknown index channel")
                checked.append({**card(node), "channels": channels, "source_facts": []})
            return self.results(
                payload["query"],
                payload.get("kind"),
                checked,
                errors,
                payload["limit"],
                task_id,
                scope=metadata["semantic_scope"],
            )
        if method == "semantic.sources":
            return self.sources(**payload, metadata=metadata)
        if method == "semantic.write":
            return self.write(payload, metadata)
        raise ValueError("Unknown semantic operation")
