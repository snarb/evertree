"""Core semantic gateway: identities, snapshots, pagination and checked writes."""

import hashlib
import json
from uuid import uuid4

from ..graph.store import GraphStore
from ..graph.types import GraphDelta, RelationInstance, RelationType, node_from_dict
from ..memory.types import TraceOutputRef
from ..values import ContractError, json_value
from .reading import card


class SemanticService:
    def __init__(self, graph, memory, attribution, config, index, operations):
        self.graph, self.memory, self.attribution = graph, memory, attribution
        self.config, self.index, self.operations = config, index, operations
        self._pages = {}

    def release(self, task_id):
        self._pages = {key: page for key, page in self._pages.items() if page["task_id"] != task_id}

    def lookup(self, query, kind=None, limit=20, cursor=None, *, task_id):
        kind = kind.strip().casefold() if kind is not None else None
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ContractError("limit must be between 1 and 100")
        if cursor:
            page = self._pages.get(cursor)
            if (
                page is None
                or page["task_id"] != task_id
                or page["query"] != query
                or page["kind"] != kind
            ):
                raise ContractError("Invalid search cursor for this task/query")
            self._check_revision(page["revision"])
            return self._page(page, limit)
        matches = self.graph.lookup(query, kind=kind)
        if matches or isinstance(query, int):
            return self.results(
                query, kind, [card(n) for n in matches], [], limit, task_id, exact=True
            )
        if not query.strip():
            raise ContractError("Search query cannot be empty")
        return None

    def _page(self, page, limit):
        offset = page.get("offset", 0)
        items = page["items"][offset : offset + limit]
        cursor = None
        if offset + limit < len(page["items"]):
            cursor = f"{page['page_id']}:{offset + limit}"
            self._pages[cursor] = {**page, "offset": offset + limit}
        return {
            "status": "incomplete" if page["errors"] else "complete",
            "items": items,
            "errors": page["errors"],
            "cursor": cursor,
            "total": len(page["items"]),
            "exact": page.get("exact", False),
        }

    def results(self, query, kind, items, errors, limit, task_id, exact=False):
        return self._page(
            {
                "query": query,
                "page_id": uuid4().hex,
                "revision": self.graph.revision,
                "kind": kind.strip().casefold() if kind is not None else None,
                "items": items,
                "errors": errors,
                "task_id": task_id,
                "exact": exact,
            },
            limit,
        )

    def _check_revision(self, revision):
        if revision != self.graph.revision:
            raise ContractError("Graph changed during search; repeat the query")

    def sources(self, statements, sources, context=None):
        if (
            not isinstance(statements, list)
            or not statements
            or any(not isinstance(s, str) or not s.strip() for s in statements)
        ):
            raise ContractError("statements must be a nonempty list of text")
        if not isinstance(sources, list) or not sources:
            raise ContractError("remember requires retained source references")
        values = []
        for source in sources:
            ref = TraceOutputRef(**source)
            values.append({"reference": source, "content": json_value(self.memory.resolve(ref))})
        return {"statements": statements, "sources": values, "context": context}

    def _proposal(self, proposal):
        if not isinstance(proposal, dict) or set(proposal) - {"creates", "updates", "deletes"}:
            raise ContractError("Expected GraphDelta creates/updates/deletes")
        proposal = json.loads(json.dumps(proposal))
        creates = proposal.get("creates", [])
        local = [item["id"] for item in creates]
        if any(type(i) is not int or i >= 0 for i in local) or len(set(local)) != len(local):
            raise ContractError("New nodes require unique negative temporary IDs")
        staged = GraphStore.from_snapshot(self.graph.snapshot())
        identities = {i: staged.reserve_id() for i in local}

        def ref(value):
            return identities.get(value, value) if isinstance(value, int) else value

        types = {n.id: n for n in staged.nodes() if isinstance(n, RelationType)}
        for item in creates:
            item["id"] = ref(item["id"])
            if item.get("kind") == "relation_type":
                for slot in item.get("signature", []):
                    if slot.get("concept") is not None:
                        slot["concept"] = ref(slot["concept"])
                types[item["id"]] = node_from_dict(item)
        # Resolve the final schema before remapping arguments: a delta may both
        # change a relation signature and create facts using that signature.
        for update in proposal.get("updates", []):
            previous = staged.get(update["id"])
            changes = update["changes"]
            if isinstance(previous, RelationType):
                for slot in changes.get("signature", []):
                    if slot.get("concept") is not None:
                        slot["concept"] = ref(slot["concept"])
                types[previous.id] = node_from_dict({**json_value(previous), **changes})

        def remap(item, previous=None):
            binding = item.get("properties", {}).get("attribution")
            if binding is not None:
                for field in ("applies_to", "classes"):
                    if field in binding:
                        binding[field] = [ref(i) for i in binding[field]]
                if "relation_type" in binding:
                    binding["relation_type"] = ref(binding["relation_type"])
            if item.get("belief_target") or previous is not None and "belief_target" in item:
                raise ContractError("Belief changes require evidence assessment")
            if (
                isinstance(previous, RelationInstance)
                and previous.belief_target
                and set(item) & {"args", "relation_type", "properties"}
            ):
                raise ContractError("Changing assessed evidence requires evidence assessment")
            if item.get("kind") != "relation_instance" and not isinstance(
                previous, RelationInstance
            ):
                return
            if "relation_type" in item:
                item["relation_type"] = ref(item["relation_type"])
            relation = types.get(
                item.get("relation_type", getattr(previous, "relation_type", None))
            )
            if relation is None:
                raise ContractError("Unknown relation type")
            if "args" in item:
                for slot in relation.signature:
                    if slot.value_type in {"node", "concept", "prototype", "instance", "facet"}:
                        value = item["args"].get(slot.label)
                        if value is not None:
                            item["args"][slot.label] = (
                                [ref(v) for v in value] if isinstance(value, list) else ref(value)
                            )
            if previous is None:
                item.setdefault("name", relation.name)

        for item in creates:
            remap(item)
        for update in proposal.get("updates", []):
            remap(update["changes"], staged.get(update["id"]))
        delta = GraphDelta.from_dict(proposal)
        # Validation must not reserve live identities or partially write on failure.
        staged.apply(delta, provenance="proposal-validation")

        def fact_key(fact):
            return (
                fact.relation_type,
                json.dumps(json_value(fact.args), sort_keys=True),
                json.dumps(json_value(fact.properties), sort_keys=True),
            )

        changed_ids = {u.id for u in delta.updates} | set(delta.deletes)
        seen_facts = {fact_key(f) for f in self.graph.facts() if f.id not in changed_ids}
        for node in (*delta.creates, *(staged.get(u.id) for u in delta.updates)):
            if isinstance(node, RelationInstance):
                signature = fact_key(node)
                if signature in seen_facts:
                    raise ContractError(
                        "Fact already exists; reuse it instead of duplicating evidence"
                    )
                seen_facts.add(signature)
        return delta

    def commit(self, payload, metadata):
        try:
            self.sources(payload["statements"], payload["sources"], payload.get("context"))
            key = hashlib.sha256(
                json.dumps([metadata["run_id"], payload], sort_keys=True).encode()
            ).hexdigest()
            for event in self.memory.events:
                if event.operator == "semantic_commit" and event.arguments.get("key") == key:
                    return json_value(event.output)
            delta = self._proposal(payload["proposal"])

            refs = tuple(TraceOutputRef(**source) for source in payload["sources"])
            changed = bool(delta.creates or delta.updates or delta.deletes)
            result = (
                self.operations.apply_delta(
                    delta,
                    task_id=metadata["task_id"],
                    revision=metadata["program"]["revision"],
                    run_mode=metadata.get("run_mode", "live"),
                    source_refs=refs,
                )
                if changed
                else None
            )
            receipt = {
                "status": "saved" if changed else "reused",
                "created": [card(n) for n in delta.creates],
                "updated": [card(self.graph.get(n.id)) for n in delta.updates],
                "deleted": list(delta.deletes),
                "revision": result.seq if result else self.graph.revision,
            }
            run = self.memory.start_run(
                "KnowledgeRememberingReceipt", metadata["program"]["revision"], {}
            )
            self.memory.record(
                run, "semantic_commit", arguments={"key": key}, output=receipt, dependencies=refs
            )
            self.memory.finish_run(run)
            return receipt
        except (ValueError, KeyError, TypeError, AttributeError, PermissionError) as exc:
            return {"status": "invalid", "error": str(exc)}

    async def execute(self, method, payload, metadata):
        task_id = metadata["task_id"]
        if method == "semantic.lookup":
            return self.lookup(**payload, task_id=task_id)
        if method == "semantic.revision":
            return self.graph.revision
        if method in {"semantic.bm25", "semantic.vector"}:
            self._check_revision(payload["revision"])
            nodes = [card(n) for n in self.graph.nodes()]
            operation = self.index.lexical if method == "semantic.bm25" else self.index.vector
            result = await operation(nodes, payload["query"], payload.get("kind"))
            self._check_revision(payload["revision"])
            return result
        if method == "semantic.results":
            errors = list(payload["errors"])
            if payload["revision"] != self.graph.revision:
                errors.append({"channel": "graph", "error": "Graph changed; repeat search"})
            items = payload["items"] if payload["revision"] == self.graph.revision else []
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
                payload["query"], payload.get("kind"), checked, errors, payload["limit"], task_id
            )
        if method == "semantic.sources":
            return self.sources(**payload)
        if method == "semantic.commit":
            return self.commit(payload, metadata)
        raise ValueError("Unknown semantic operation")
