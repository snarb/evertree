"""Shared model-tool orchestration for immediate, checked graph operations."""

import logging

from evertree.core.semantics.tools import CREATE_ACTIONS, TOOLS_BY_NAME, validate_action

_log = logging.getLogger(__name__)

# Relation value types whose values are graph object IDs the model must have seen.
_NODE_VALUE_TYPES = frozenset({"node", "concept", "prototype", "instance", "facet"})


class SemanticTools:
    """Search/read assistance; write authority and persistent state remain in Core."""

    def __init__(self, *, search, describe, write, read=None):
        self._search_port = search
        self._describe_port = describe
        self._write_port = write
        self._read_port = read
        # casefolded query -> last search result in this model invocation
        self._searches = {}
        # object id -> card as last shown to the model
        self._shown_candidates = {}
        self._sequence = 0
        self.writes = []

    @staticmethod
    def _candidate_card(node):
        """Comparable card of an object, normalized so cards from any path match."""
        card = {
            key: node.get(key)
            for key in ("id", "name", "kind", "description", "valid_from", "valid_until")
        }
        # Model-facing projections omit empty descriptions.
        card["description"] = card["description"] or None
        for key in ("valid_from", "valid_until"):
            value = card[key]
            if isinstance(value, dict) and set(value) == {"$datetime"}:
                card[key] = value["$datetime"]
        return card

    def _track_shown_candidates(self, result):
        """Record the cards the model has now seen.

        A creation is only blocked for candidates not recorded here: once the model was shown
        the possible matches and repeats the creation, that is treated as a deliberate choice.
        """
        nodes = [
            *result.get("nodes", []),
            *result.get("items", []),
            *result.get("created", []),
            *result.get("updated", []),
        ]
        if "subject" in result:
            nodes.append(result["subject"])
        for node in nodes:
            if "id" not in node or "kind" not in node:
                continue
            self._shown_candidates[node["id"]] = self._candidate_card(node)

    def remember_read(self, name, arguments, result):
        """Share explicit consciousness reads with the creation review gate."""
        self._track_shown_candidates(result)
        if (
            name == "search"
            and isinstance(arguments.get("query"), str)
            and not arguments.get("kind")
        ):
            self._searches[arguments["query"].strip().casefold()] = result

    async def _search(self, query, reads):
        key = query.strip().casefold()
        result = await self._search_port(query)
        self._searches[key] = result
        reads.append({"tool": "search", "query": query, "result": result})
        return result

    async def _describe(self, subject, reads):
        result = await self._describe_port(subject)
        reads.append({"tool": "describe", "query": subject, "result": result})
        if "subject" not in result:
            raise ValueError("Object could not be resolved; inspect the returned candidates")
        return result

    async def _require_reviewed_search(self, action, reads):
        """Gate for creations: the name needs a complete and reviewed search.

        Unseen candidates reject the first attempt; repeating the same name afterwards means
        the model reviewed them and chose to create anyway.
        """
        name = action["name"]
        key = name.strip().casefold()
        previous = self._searches.get(key)
        if previous is None:
            found = await self._search(name, reads)
            # A new name still needs a search, but already shown candidates need no review.
            unseen = [
                node
                for node in found.get("items", [])
                if self._shown_candidates.get(node["id"]) != self._candidate_card(node)
            ]
            if unseen and found.get("status") == "complete":
                raise ValueError(
                    "Review search candidates. They are possible matches, not a name "
                    "conflict. If one represents this object, use its ID. Otherwise "
                    "repeat this creation with the SAME name to proceed. Changing the "
                    "name starts another search and review."
                )
        if self._searches[key].get("status") != "complete":
            raise ValueError("Search is incomplete; retry later or omit this creation")

    async def _describe_referenced(self, action, reads):
        """Describe every object the write depends on, so bad IDs fail before the write."""
        name = action["action"]
        subjects = []
        if name == "create_instance":
            subjects = [action["prototype"], "IDENTITY_TYPE"]
        elif name == "create_facet":
            subjects = [action["instance"], "STATE_IDENTITY"]
        elif name == "create_prototype" and action["parent"] is not None:
            subjects = [action["parent"], "SUBTYPE_OF"]
        elif name == "create_property":
            subjects = [
                *action["applies_to"],
                *action.get("classes", []),
                action.get("program"),
                action.get("relation_type"),
            ]
        elif name == "create_property_reference":
            subjects = [action["property"], action["domain"], *action["classes"]]
        elif name in {"create_qualitative_property", "revise_property_norm"}:
            subjects = [
                action["property"],
                action["domain"],
                *action["classes"],
                action.get("reference"),
                action.get("object"),
            ]
        elif name == "save_property_result":
            subjects = [action["subject"], action["property"]]
        elif name == "update":
            subjects = [action["object"]]
        elif name == "delete":
            subjects = action["objects"]
        elif name == "relate":
            subjects = [action.get("criterion")]
            result = await self._describe(action["relation"], reads)
            schema = result.get("schema", result["subject"])
            kinds = {slot["label"]: slot["value_type"] for slot in schema["signature"]}
            for argument in action["arguments"]:
                if kinds.get(argument["role"]) in _NODE_VALUE_TYPES:
                    value = argument["value"]
                    subjects.extend(value if isinstance(value, list) else [value])
        for subject in dict.fromkeys(subjects):
            if subject is not None:
                await self._describe(subject, reads)

    async def _checked_write(self, action, operation_key, reads):
        if action["action"] in CREATE_ACTIONS:
            await self._require_reviewed_search(action, reads)
        await self._describe_referenced(action, reads)
        return await self._write_port(action, operation_key)

    @staticmethod
    def _subject(action):
        """Short human label of what an action targets, for logs."""
        for key in ("name", "object", "objects", "relation"):
            if key in action:
                return action[key]
        return ""

    async def handle(self, name, arguments):
        """Run one model tool call.

        Correctable failures come back as `{"error": ..., "reads": [...]}` for the model to
        retry instead of raising; `reads` are what this call looked up before failing.
        """
        self._sequence += 1
        operation_key = str(self._sequence)
        reads = []
        action = {}
        try:
            action = {**arguments, "action": name}
            validate_action(action)
            if name == "search":
                result = await self._search(action["query"], reads)
            elif name == "describe" and not any(
                arguments.get(k) is not None for k in ("focus", "at")
            ):
                result = await self._describe(action["subject"], reads)
            elif TOOLS_BY_NAME[name].read_only:
                if self._read_port is None:
                    raise ValueError("This invocation has no graph read port")
                result = await self._read_port(name, arguments)
            else:
                result = await self._checked_write(action, operation_key, reads)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            for read in reads:
                self._track_shown_candidates(read["result"])
            _log.info("LLM %s %r rejected: %s", name, self._subject(action), exc)
            return {"error": str(exc), **({"reads": reads} if reads else {})}

        if TOOLS_BY_NAME[name].read_only:
            self._track_shown_candidates(result)
            _log.debug("LLM %s %r", name, self._subject(action))
        elif "error" in result:
            _log.info("LLM %s %r failed: %s", name, self._subject(action), result["error"])
        else:
            self.writes.append(result)
            self._track_shown_candidates(result)
            _log.info(
                "LLM %s %r -> object %s (created %d, revision %s)",
                name,
                self._subject(action),
                result.get("object"),
                len(result.get("created", [])),
                result.get("revision"),
            )
        return result
