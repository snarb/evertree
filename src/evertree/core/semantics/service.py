"""Core semantic gateway: identities, snapshots, pagination and checked writes."""

import hashlib
import json
from uuid import uuid4

from ..graph.store import GraphStore
from ..graph.types import GraphDelta, RelationInstance, RelationType, node_from_dict
from ..memory.types import TraceOutputRef, _references
from ..values import ContractError, json_value
from .reading import card


class SemanticService:
    def __init__(self, graph, memory, attribution, config, index, operations):
        self.graph, self.memory, self.attribution = graph, memory, attribution
        self.config, self.index, self.operations = config, index, operations
        self._pages = {}
        self._searches = {}
        self._index_reads = {}

    def release(self, task_id):
        self._pages = {key: page for key, page in self._pages.items() if page["task_id"] != task_id}
        self._searches.pop(task_id, None)
        self._index_reads.pop(task_id, None)

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
        self._searches.setdefault(task_id, {})[str(query).strip().casefold()] = {
            "revision": self.graph.revision,
            "complete": not errors,
            "items": items,
        }
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

    @staticmethod
    def _authorize(metadata):
        if (
            metadata.get("knowledge_integration_authorized") is not True
            or metadata.get("program", {}).get("role") != "exec"
            or not metadata.get("program", {}).get("revision")
            or not metadata.get("integration_operation_id")
        ):
            raise PermissionError("Semantic writes require admitted KnowledgeIntegration execution")

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

    @staticmethod
    def _fingerprint(experience, context):
        stable_context = json_value(context)
        if isinstance(stable_context.get("task"), dict):
            for field in (
                "remaining_active_time_minutes",
                "self_improvement_remaining",
                "remaining",
            ):
                stable_context["task"].pop(field, None)
        return hashlib.sha256(
            json.dumps(
                [[item["reference"] for item in experience], stable_context],
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def _receipt(self, metadata, fingerprint):
        key = [metadata["task_id"], metadata["integration_operation_id"]]
        for event in reversed(self.memory.events):
            if (
                event.operator != "semantic_commit"
                or self.memory.get_run(event.program_run).program != "KnowledgeIntegrationReceipt"
                or list(event.arguments.get("key", ())) != key
            ):
                continue
            if event.arguments.get("fingerprint") != fingerprint:
                raise ContractError(
                    "Integration operation cannot be reused with different experience or context"
                )
            if event.output["complete"]:
                return {
                    **json_value(event.output),
                    "receipt_ref": json_value(self.memory.output_ref(event)),
                }
        return None

    def sources(self, experience_refs, focus=None, *, metadata):
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
        context = json_value(metadata.get("integration_context", {}))
        intents = {item["id"]: item for item in context.get("preservation_intents", [])}

        def preserve(value, reference):
            if isinstance(value, dict):
                if value.get("preserve") is True and isinstance(value.get("text"), str):
                    identity = (
                        str(reference["event_ref"]) + ":" + json.dumps(reference["output_path"])
                    )
                    intents[identity] = {
                        "id": identity,
                        "source_ref": reference,
                        "text": value["text"],
                    }
                for key, child in value.items():
                    preserve(child, {**reference, "output_path": [*reference["output_path"], key]})
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    preserve(
                        child, {**reference, "output_path": [*reference["output_path"], index]}
                    )

        for item in values:
            event = self.memory.get_event(item["reference"]["event_ref"])
            analytical = event.operator == "analytical_note" and event.output_type.endswith(
                ".AnalyticalNote"
            )
            if event.operator == "experience_fragment" and isinstance(item["content"], dict):
                original = item["content"].get("source_ref")
                if original is not None:
                    source_event = self.memory.get_event(self._reference(original).event_ref)
                    analytical = (
                        self.memory.get_run(event.program_run).program == "ExperienceFragments"
                        and source_event.operator == "analytical_note"
                        and source_event.output_type.endswith(".AnalyticalNote")
                    )
            if analytical:
                preserve(item["content"], item["reference"])
        context["preservation_intents"] = list(intents.values())
        fingerprint = self._fingerprint(values, context)
        return {
            "experience": values,
            "focus": focus,
            "context": context,
            "receipt": self._receipt(metadata, fingerprint),
        }

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
            if item.get("kind") == "facet" and not item.get("valid_from"):
                raise ContractError("Facet requires explicit world-time valid_from")
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

    @staticmethod
    def _contains(parent, child):
        return (
            parent.event_ref == child.event_ref
            and child.output_path[: len(parent.output_path)] == parent.output_path
        )

    def _decisions(self, payload, material, delta):
        inputs = tuple(self._reference(item["reference"]) for item in material["experience"])
        decisions = payload.get("decisions")
        if not isinstance(decisions, list) or not decisions:
            raise ContractError("Integration requires explicit decisions covering its experience")
        local_ids = {
            item["id"]: node.id
            for item, node in zip(
                payload["proposal"].get("creates", []), delta.creates, strict=True
            )
        }
        changed = {n.id for n in delta.creates} | {n.id for n in delta.updates} | set(delta.deletes)
        covered, attributed, sources, normalized, preserved = set(), set(), [], [], set()
        intents = {item["id"]: item for item in material["context"].get("preservation_intents", [])}
        for decision in decisions:
            disposition = decision.get("disposition")
            if disposition not in {"materialize", "reuse", "trace_only", "unresolved"}:
                raise ContractError("Unknown integration disposition")
            if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
                raise ContractError("Every integration decision requires a reason")
            refs = tuple(self._reference(ref) for ref in decision.get("source_refs", []))
            if not refs:
                raise ContractError("Every decision requires source_refs")
            for ref in refs:
                self.memory.resolve(ref)
                parents = {i for i, parent in enumerate(inputs) if self._contains(parent, ref)}
                if not parents:
                    raise ContractError("Decision source is outside supplied experience")
                covered.update(parents)
            ids = [
                local_ids.get(identity, identity) for identity in decision.get("affected_ids", [])
            ]
            if any(type(identity) is not int for identity in ids):
                raise ContractError("Decision affected_ids must be graph identities")
            if disposition == "materialize":
                if not ids or not set(ids) <= changed:
                    raise ContractError("Materialization must identify its graph changes")
                attributed.update(ids)
                sources.extend(refs)
            elif disposition == "reuse":
                if not ids:
                    raise ContractError("Reuse requires existing identities")
                if set(ids) & set(delta.deletes):
                    raise ContractError("Cannot reuse an object deleted by this integration")
                for identity in ids:
                    self.graph.get(identity)
            elif ids:
                raise ContractError("Trace-only and unresolved decisions cannot change graph nodes")
            preservation_ids = decision.get("preservation_ids", [])
            if not isinstance(preservation_ids, list) or set(preservation_ids) - intents.keys():
                raise ContractError("Unknown preservation intent")
            if disposition in {"materialize", "reuse"}:
                if preservation_ids and not set(ids) - set(delta.deletes):
                    raise ContractError(
                        "Preservation requires a representation that remains in the graph"
                    )
                for identity in preservation_ids:
                    intent_ref = intents[identity].get("source_ref")
                    if intent_ref and not any(
                        self._contains(ref, TraceOutputRef(**intent_ref))
                        or self._contains(TraceOutputRef(**intent_ref), ref)
                        for ref in refs
                    ):
                        raise ContractError("Preservation decision must cite its analytical source")
                preserved.update(preservation_ids)
            normalized.append(
                {
                    "disposition": disposition,
                    "reason": decision["reason"],
                    "source_refs": json_value(refs),
                    "affected_ids": ids,
                    "preservation_ids": preservation_ids,
                }
            )
        if len(covered) != len(inputs):
            raise ContractError("Integration decisions leave unreviewed experience")
        if attributed != changed:
            raise ContractError("Every graph change needs an attributed materialization decision")
        for embedded in _references(json_value(delta)):
            if not any(self._contains(source, embedded) for source in sources):
                raise ContractError("Embedded provenance must belong to materialized candidates")
        return normalized, tuple(dict.fromkeys(sources)), sorted(intents.keys() - preserved)

    def _check_searches(self, proposal, metadata):
        searches = self._searches.get(metadata["task_id"], {})
        for item in proposal.get("creates", []):
            if item.get("kind", "concept") in {"relation_instance", "note"}:
                continue
            query = item.get("name", "").strip().casefold()
            search = searches.get(query)
            if not search or not search["complete"] or search["revision"] != self.graph.revision:
                raise ContractError(
                    "Creating an identity requires a complete current search for " + query
                )

    def commit(self, payload, metadata):
        self._authorize(metadata)
        try:
            material = self.sources(payload["experience_refs"], metadata=metadata)
            if material["receipt"] is not None:
                return material["receipt"]
            delta = self._proposal(payload["proposal"])
            decisions, refs, pending = self._decisions(payload, material, delta)
            self._check_searches(payload["proposal"], metadata)
            changed = bool(delta.creates or delta.updates or delta.deletes)
            receipt = {
                "operation_id": metadata["integration_operation_id"],
                "status": "blocked" if pending else "complete",
                "complete": not pending,
                "decisions": decisions,
                "pending_preservation_ids": pending,
                "created": [] if pending else [card(n) for n in delta.creates],
                "updated": [],
                "deleted": [] if pending else list(delta.deletes),
                "revision": self.graph.revision,
            }
            with self.graph.transaction(), self.memory.transaction():
                # A blocked packet is retried as a whole. Partial writes would force
                # a new interpretation of temporary identities during recovery.
                if changed and not pending:
                    result = self.operations.apply_delta(
                        delta,
                        task_id=metadata["task_id"],
                        revision=metadata["program"]["revision"],
                        run_mode=metadata.get("run_mode", "live"),
                        source_refs=refs,
                        integration_operation_id=metadata["integration_operation_id"],
                        integration_decisions=[
                            item for item in decisions if item["disposition"] == "materialize"
                        ],
                    )
                    receipt["revision"] = result.seq
                    receipt["updated"] = [card(self.graph.get(n.id)) for n in delta.updates]
                run = self.memory.start_run(
                    "KnowledgeIntegrationReceipt",
                    metadata["program"]["revision"],
                    {},
                    run_mode=metadata.get("run_mode", "live"),
                )
                event = self.memory.record(
                    run,
                    "semantic_commit",
                    arguments={
                        "key": [metadata["task_id"], metadata["integration_operation_id"]],
                        "fingerprint": self._fingerprint(
                            material["experience"], material["context"]
                        ),
                    },
                    output=receipt,
                )
                self.memory.finish_run(run)
                receipt["receipt_ref"] = json_value(self.memory.output_ref(event))
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
            key = (payload["query"], payload.get("kind"), payload["revision"])
            self._index_reads.setdefault(task_id, {}).setdefault(key, set()).add(method)
            return result
        if method == "semantic.results":
            errors = list(payload["errors"])
            key = (payload["query"], payload.get("kind"), payload["revision"])
            completed = self._index_reads.get(task_id, {}).get(key, set())
            if not errors and completed != {"semantic.bm25", "semantic.vector"}:
                errors.append({"channel": "search", "error": "Search needs completed index reads"})
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
            return self.sources(**payload, metadata=metadata)
        if method == "semantic.commit":
            return self.commit(payload, metadata)
        raise ValueError("Unknown semantic operation")
