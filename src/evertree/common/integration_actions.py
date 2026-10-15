"""Shared model-tool orchestration for immediate, checked graph operations."""

from evertree.core.semantics.actions import (  # noqa: F401 -- shared tool catalog
    CREATE_ACTIONS,
    INTEGRATION_TOOLS,
    WRITE_TOOLS,
    validate_action,
)


class SemanticTools:
    """Search/read assistance; write authority and persistent state remain in Core."""

    def __init__(self, *, search, describe, write, revision):
        self._search, self._describe, self._write, self._revision = (
            search,
            describe,
            write,
            revision,
        )
        self._searches = {}
        self._shown = {}
        self._sequence = 0
        self.writes = []

    @staticmethod
    def _candidate(node):
        result = {
            key: node.get(key)
            for key in ("id", "name", "kind", "description", "valid_from", "valid_until")
        }
        for key in ("valid_from", "valid_until"):
            value = result[key]
            if isinstance(value, dict) and set(value) == {"$datetime"}:
                result[key] = value["$datetime"]
        return result

    def _remember(self, result):
        nodes = [*result.get("items", []), *result.get("created", [])]
        if "subject" in result:
            nodes.append(result["subject"])
        for node in nodes:
            self._shown[node["id"]] = self._candidate(node)

    async def handle(self, name, arguments):
        self._sequence += 1
        operation_key = str(self._sequence)
        reads = []

        async def search(query, next_page=False):
            revision = await self._revision()
            key = query.strip().casefold()
            previous = self._searches.get(key)
            if previous is not None and previous[0] != revision:
                next_page = False
            result = await self._search(query, next_page)
            self._searches[key] = (revision, result)
            reads.append({"tool": "search", "query": query, "result": result})
            return result

        async def describe(subject):
            result = await self._describe(subject)
            reads.append({"tool": "describe", "query": subject, "result": result})
            if "subject" not in result:
                raise ValueError("Object could not be resolved; inspect the returned candidates")
            return result

        try:
            action = {**arguments, "action": name}
            validate_action(action)
            if name == "search":
                result = await search(action["query"], action["next_page"])
                self._remember(result)
                return result
            if name == "describe":
                result = await describe(action["subject"])
                self._remember(result)
                return result
            if name in CREATE_ACTIONS:
                query = action["name"].strip().casefold()
                previous = self._searches.get(query)
                if previous is None or previous[0] != await self._revision():
                    found = await search(action["name"])
                    # Refresh retrieval after graph changes, but do not make the model review
                    # the same unchanged cards again under every proposed new name.
                    unseen = [
                        node
                        for node in found.get("items", [])
                        if self._shown.get(node["id"]) != self._candidate(node)
                    ]
                    if unseen and found.get("status") == "complete":
                        raise ValueError(
                            "Review search candidates. They are possible matches, not a name "
                            "conflict. If one represents this object, use its ID. Otherwise "
                            "repeat this creation with the SAME name to proceed. Changing the "
                            "name starts another search and review."
                        )
                if self._searches[query][1].get("status") != "complete":
                    raise ValueError("Search is incomplete; retry later or omit this creation")
            subjects = []
            if name == "create_instance":
                subjects = [action["prototype"], "IDENTITY_TYPE"]
            elif name == "create_facet":
                subjects = [action["instance"], "STATE_IDENTITY"]
            elif name == "create_prototype" and action["parent"] is not None:
                subjects = [action["parent"], "SUBTYPE_OF"]
            elif name == "update":
                subjects = [action["object"]]
            elif name == "delete":
                subjects = action["objects"]
            if name == "relate":
                result = await describe(action["relation"])
                schema = result.get("schema", result["subject"])
                kinds = {slot["label"]: slot["value_type"] for slot in schema["signature"]}
                for argument in action["arguments"]:
                    if kinds.get(argument["role"]) in {
                        "node",
                        "concept",
                        "prototype",
                        "instance",
                        "facet",
                    }:
                        value = argument["value"]
                        subjects.extend(value if isinstance(value, list) else [value])
            for subject in dict.fromkeys(subjects):
                if subject is not None:
                    await describe(subject)
            result = await self._write(action, operation_key)
            if "error" not in result:
                self.writes.append(result)
                self._remember(result)
            return result
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            for read in reads:
                self._remember(read["result"])
            return {"error": str(exc), **({"reads": reads} if reads else {})}
