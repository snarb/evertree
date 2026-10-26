"""Validate and atomically install the curated, symbolic starter ontology."""

from __future__ import annotations

import json
from pathlib import Path

from ..values import ContractError, json_value
from .matching import NODE_TYPES
from .store import GraphStore
from .types import (
    AccessView,
    Clause,
    GraphDelta,
    NodeUpdate,
    Predicate,
    Prototype,
    RelationInstance,
    RelationType,
    Slot,
    normalize_name,
)

TEMPLATE_DIRECTORY = Path(__file__).with_name("templates")
CORE_BINDINGS = {
    "sumo.process": "Process",
    "rel.subtype_of": "SUBTYPE_OF",
    "rel.identity_type": "IDENTITY_TYPE",
    "rel.state_identity": "STATE_IDENTITY",
    "rel.part_whole": "PART_WHOLE",
    "rel.has_numeric_value": "HAS_NUMERIC_VALUE",
    "rel.classified_as": "CLASSIFIED_AS",
    "rel.program_for_process": "PROGRAM_FOR_PROCESS",
    "rel.evidence_depends_on": "EVIDENCE_DEPENDS_ON",
}


def read_template(directory: Path | str = TEMPLATE_DIRECTORY) -> dict:
    """Read a manifest and its local modules; no graph state is changed."""
    directory = Path(directory)
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        modules = manifest["modules"]
        if not isinstance(modules, list) or not modules or len(modules) != len(set(modules)):
            raise ContractError("template requires distinct modules")
        nodes = []
        for filename in modules:
            if Path(filename).name != filename or not filename.endswith(".json"):
                raise ContractError("template modules must be local JSON files")
            path = directory / filename
            if path.is_symlink():
                raise ContractError("template modules cannot be symlinks")
            module = json.loads(path.read_text(encoding="utf-8"))
            if set(module) != {"nodes"} or not isinstance(module["nodes"], list):
                raise ContractError("template module requires a nodes array")
            nodes.extend(module["nodes"])
        package = {"manifest": manifest, "nodes": nodes}
        validate_template(package)
        return package
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ContractError(f"invalid template package: {error}") from error


def validate_template(package: dict) -> None:
    """Check dependency closure, taxonomy, relation contracts and source declarations.

    This validates recorded declarations, not empirical truth or LLM navigation quality.
    """
    try:
        _validate_template(package)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ContractError(f"invalid template package: {error}") from error


def _validate_template(package):
    manifest, records = package["manifest"], package["nodes"]
    if (
        type(manifest["format"]) is not int
        or manifest["format"] != 1
        or not manifest["version"]
        or manifest["core_bindings"] != CORE_BINDINGS
    ):
        raise ContractError("unsupported template format or core bindings")
    sources = manifest["sources"]
    for source in sources.values():
        for field in ("title", "url", "revision", "license", "use"):
            if not isinstance(source[field], str) or not source[field].strip():
                raise ContractError("sources require pinned provenance and usage terms")
    by_key, names = {}, set()
    for node in records:
        key, name = node["key"], normalize_name(node["name"])
        if not isinstance(key, str) or not key or key in by_key or not name or name in names:
            raise ContractError("template keys and canonical names must be unique")
        if node["kind"] not in {"prototype", "relation_type"}:
            raise ContractError("templates contain types, not running agent identities or facts")
        if not isinstance(node["definition"], str) or not node["definition"].strip():
            raise ContractError("every template type requires a definition")
        for language in ("en", "ru"):
            if not isinstance(node["aliases"][language], list) or any(
                not isinstance(alias, str) or not alias.strip()
                for alias in node["aliases"][language]
            ):
                raise ContractError("aliases must be nonempty strings in language arrays")
        for field in ("examples", "counterexamples", "links"):
            if not isinstance(node[field], list):
                raise ContractError(f"{field} must be an array")
        if any(
            not isinstance(text, str) or not text.strip()
            for field in ("examples", "counterexamples")
            for text in node[field]
        ):
            raise ContractError("examples and counterexamples must be nonempty text")
        source = node["source"]
        if not source["source_id"] or source["revision"] != sources[source["source"]]["revision"]:
            raise ContractError("node source must identify a pinned source revision")
        for coverage in node.get("coverage_sources", []):
            if coverage not in sources:
                raise ContractError("unknown coverage source")
        adaptation = node["adaptation"]
        if adaptation is not None:
            if (
                adaptation["kind"] not in {"single_parent", "semantic_correction", "navigation"}
                or not adaptation["reason"].strip()
            ):
                raise ContractError("adaptations require an explicit reason and category")
            if adaptation["kind"] == "navigation":
                _validate_navigation(adaptation["evidence"])
        by_key[key] = node
        names.add(name)
    root = manifest["root"]
    if root not in by_key or by_key[root]["kind"] != "prototype":
        raise ContractError("template requires a prototype root")
    for key, node in by_key.items():
        seen, current = set(), key
        while current != root:
            if current in seen:
                raise ContractError("template taxonomy has a cycle")
            seen.add(current)
            current = by_key[current]["parent"]
            if current not in by_key:
                raise ContractError("every accepted type must reach the root")
        if by_key[root]["parent"] is not None:
            raise ContractError("template root cannot have a parent")
        if (
            node["kind"] == "prototype"
            and node["parent"]
            and by_key[node["parent"]]["kind"] == "relation_type"
        ):
            raise ContractError("an abstract category cannot specialize a concrete predicate")
    for key, name in CORE_BINDINGS.items():
        if by_key[key]["name"] != name:
            raise ContractError("template changes a core binding")
    for node in records:
        _validate_relations(node, by_key)


def _validate_navigation(evidence):
    total = evidence["independent_intents"]
    before, after = evidence["baseline_failures"], evidence["candidate_failures"]
    if (
        any(type(value) is not int for value in (total, before, after))
        or not 0 <= after < before <= total
    ):
        raise ContractError("navigation comparison requires independent failure counts")
    if (
        (before - after) / before < 0.20
        or (before - after) / total < 0.03
        or not 0 < evidence["paired_ci95_lower"] <= 1
        or evidence["matched_conditions"] is not True
        or evidence["semantic_regressions"] != 0
        or evidence["priority_regressions"] != 0
        or not evidence["evaluation_ref"]
    ):
        raise ContractError("optional navigation adaptation fails the policy gate")


def _is_subtype(child, parent, by_key):
    while child is not None:
        if child == parent:
            return True
        child = by_key[child]["parent"]
    return False


def _view_from_record(record, signature, ids):
    fields = dict(record)
    if fields.get("constraints") is not None:
        slots = {slot["label"]: slot for slot in signature}

        def resolve(value):
            if isinstance(value, list):
                return [resolve(item) for item in value]
            return ids[value]

        clauses = []
        for raw in fields["constraints"]["all"]:
            clause = dict(raw)
            slot = slots.get(clause["field"])
            if slot and slot["value_type"] in NODE_TYPES and clause.get("value") is not None:
                clause["value"] = resolve(clause["value"])
            clauses.append(Clause(**clause))
        fields["constraints"] = Predicate(tuple(clauses))
    return AccessView(**fields)


def _validate_relations(node, by_key):
    seen_links = set()
    for link in node["links"]:
        pair = (link["relation"], link["target"])
        if pair in seen_links:
            raise ContractError("duplicate semantic link")
        seen_links.add(pair)
        relation = by_key[link["relation"]]
        if link["target"] not in by_key or relation["kind"] != "relation_type":
            raise ContractError("invalid semantic link")
        if [
            (slot["label"], slot["value_type"], slot["arity"]) for slot in relation["signature"]
        ] != [("source", "node", "one"), ("target", "node", "one")]:
            raise ContractError("template links require binary source/target node roles")
        for endpoint, key in (("source", node["key"]), ("target", link["target"])):
            semantic_type = next(
                slot["value_concept"] for slot in relation["signature"] if slot["label"] == endpoint
            )
            if not _is_subtype(key, semantic_type, by_key):
                raise ContractError("template link endpoint violates its semantic type")
    if node["kind"] != "relation_type":
        if any(field in node for field in ("signature", "views", "specialization", "subjects")):
            raise ContractError("abstract relation categories are ordinary Prototypes")
        return
    if not _is_subtype(node["key"], "sumo.relation", by_key):
        raise ContractError("concrete predicate must belong to the relation taxonomy")
    subjects = node["subjects"]
    if (
        not subjects
        or len(subjects) != len(set(subjects))
        or any(subject not in by_key for subject in subjects)
    ):
        raise ContractError("relations require existing, distinct subject concepts")
    if not node["views"]:
        raise ContractError("concrete predicates require declared read views")
    slots = []
    ids = {key: index + 1 for index, key in enumerate(by_key)}
    for slot in node["signature"]:
        for field in ("value_concept", "role_concept"):
            if by_key[slot[field]]["kind"] != "prototype":
                raise ContractError("role and semantic value types must reference Prototypes")
        if (
            not _is_subtype(slot["role_concept"], "local.role", by_key)
            or not slot["description"].strip()
        ):
            raise ContractError("each position requires an explained semantic role")
        slots.append(
            Slot(
                **{
                    **slot,
                    "value_concept": ids[slot["value_concept"]],
                    "role_concept": ids[slot["role_concept"]],
                }
            )
        )
    RelationType(
        1,
        node["name"],
        signature=tuple(slots),
        views=tuple(_view_from_record(view, node["signature"], ids) for view in node["views"]),
    )
    parent = by_key[node["parent"]]
    specialization = node.get("specialization")
    if parent["kind"] != "relation_type":
        if specialization is not None:
            raise ContractError("role projection requires a concrete predicate parent")
        return
    if (
        not specialization
        or specialization["parent"] != parent["key"]
        or not specialization["entailment"].strip()
    ):
        raise ContractError(
            "concrete predicate specialization requires explicit entailment and role mapping"
        )
    mapping = specialization["roles"]
    child_slots = {slot["label"]: slot for slot in node["signature"]}
    if set(mapping) != {slot["label"] for slot in parent["signature"]} or len(
        set(mapping.values())
    ) != len(mapping):
        raise ContractError("projection must map every parent role to a distinct child role")
    for parent_slot in parent["signature"]:
        child_slot = child_slots[mapping[parent_slot["label"]]]
        if (
            parent_slot["arity"] != child_slot["arity"]
            or parent_slot["value_type"] != child_slot["value_type"]
            or not _is_subtype(child_slot["value_concept"], parent_slot["value_concept"], by_key)
            or not _is_subtype(child_slot["role_concept"], parent_slot["role_concept"], by_key)
        ):
            raise ContractError("specialization widens or changes a parent argument contract")


def install_template(
    graph: GraphStore,
    *,
    provenance,
    directory: Path | str = TEMPLATE_DIRECTORY,
    package: dict | None = None,
) -> dict[str, int]:
    """Install on an empty/minimal graph in one rollback boundary, returning symbolic IDs.

    Existing application graphs are restored from snapshots, never upgraded here.
    """
    package = read_template(directory) if package is None else package
    validate_template(package)
    manifest, records = package["manifest"], package["nodes"]
    with graph.transaction():
        core = graph.bootstrap(provenance=provenance)
        if set(core) != set(CORE_BINDINGS.values()) or len(graph.nodes()) != len(core):
            raise ContractError("starter template requires an empty or minimal graph")
        ids = {key: core[name] for key, name in CORE_BINDINGS.items()}
        ids.update({node["key"]: graph.reserve_id() for node in records if node["key"] not in ids})
        creates, updates = [], []
        for record in records:
            props = {
                "aliases": record["aliases"],
                "examples": record["examples"],
                "counterexamples": record["counterexamples"],
                "template": {
                    "key": record["key"],
                    "version": manifest["version"],
                    "source": record["source"],
                    "source_terms": manifest["sources"][record["source"]["source"]],
                    "adaptation": record["adaptation"],
                    "coverage_sources": record.get("coverage_sources", []),
                },
            }
            fields = {
                "id": ids[record["key"]],
                "name": record["name"],
                "description": record["definition"],
                "properties": props,
            }
            if record["kind"] == "relation_type":
                fields["signature"] = tuple(
                    Slot(
                        **{
                            **slot,
                            "value_concept": ids[slot["value_concept"]],
                            "role_concept": ids[slot["role_concept"]],
                        }
                    )
                    for slot in record["signature"]
                )
                fields["views"] = tuple(
                    _view_from_record(view, record["signature"], ids) for view in record["views"]
                )
                if specialization := record.get("specialization"):
                    props["specialization"] = {
                        **specialization,
                        "parent": ids[specialization["parent"]],
                        "inference": "declaration_only",
                    }
                node = RelationType(**fields)
            else:
                node = Prototype(**fields)
            if record["key"] in CORE_BINDINGS:
                original = graph.get(node.id)
                if type(original) is not type(node):
                    raise ContractError("template conflicts with core representation")
                if isinstance(node, RelationType):
                    shape = lambda relation: [
                        (slot.label, slot.value_type, slot.arity) for slot in relation.signature
                    ]
                    if shape(node) != shape(original) or node.views != original.views:
                        raise ContractError("template conflicts with core relation contract")
                updates.append(
                    NodeUpdate(
                        node.id,
                        {
                            key: value
                            for key, value in json_value(node).items()
                            if key not in {"id", "kind"}
                        },
                    )
                )
            else:
                creates.append(node)

        def fact(relation, args):
            creates.append(
                RelationInstance(
                    graph.reserve_id(),
                    relation,
                    relation_type=ids[relation],
                    args=args,
                    properties={
                        "template_version": manifest["version"],
                        "template_key": record["key"],
                        "template_source": record["source"],
                    },
                )
            )

        for record in records:
            identity = ids[record["key"]]
            if record["parent"] is not None:
                fact("rel.subtype_of", {"type": identity, "supertype": ids[record["parent"]]})
            for subject in record.get("subjects", []):
                fact("rel.relation_subject", {"source": identity, "target": ids[subject]})
            for link in record["links"]:
                fact(link["relation"], {"source": identity, "target": ids[link["target"]]})
        graph.apply(
            GraphDelta(creates=tuple(creates), updates=tuple(updates)), provenance=provenance
        )
        return ids


if __name__ == "__main__":
    package = read_template()
    graph = GraphStore()
    symbols = install_template(graph, provenance="template-validation", package=package)
    print(
        f"Template {package['manifest']['version']}: {len(symbols)} types, "
        f"{len(graph.facts())} links; valid."
    )
