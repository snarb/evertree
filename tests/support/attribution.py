"""Numeric populations built through the real source-backed semantic write boundary."""

from tests.support.semantics import recorded_experience, semantic_world, write_action


class Population:
    def __init__(self):
        self.world = semantic_world()
        self.sequence = 0
        self.domain = self.create("create_prototype", "Dog", parent=None)
        self.property = self.create(
            "create_property", "Body mass", unit="kg", applies_to=[self.domain]
        )

    def write(self, action, **fields):
        self.sequence += 1
        refs, metadata = recorded_experience(self.world, fields)
        result = write_action(
            self.world,
            refs,
            metadata,
            {"action": action, "sources": refs, **fields},
            key=str(self.sequence),
        )
        return result

    def create(self, action, name, **fields):
        result = self.write(action, name=name, description=None, **fields)
        assert "error" not in result, result
        return result["object"]

    def measurement(
        self, value, *, name=None, subject=None, unit="kg", prototype=None, conditions=None
    ):
        if subject is None:
            subject = self.create("create_instance", name, prototype=prototype or self.domain)
        result = self.write(
            "relate",
            relation=self.world.graph.find("HAS_NUMERIC_VALUE").id,
            arguments=[
                {"role": role, "value": item}
                for role, item in {
                    "entity": subject,
                    "property": self.property,
                    "value": value,
                    "unit": unit,
                }.items()
            ],
            conditions=[{"parameter": k, "value": v} for k, v in (conditions or {}).items()],
            description="Reported measurement, not independently verified",
        )
        assert "error" not in result, result
        return subject, result["object"]

    def reference(
        self,
        kind,
        *,
        name="Dog reference",
        boundaries=(),
        classes=(),
        samples=(),
        conditions=None,
        domain=None,
        unit="kg",
        **fields,
    ):
        return self.create(
            "create_property_reference",
            name,
            property=self.property,
            domain=self.domain if domain is None else domain,
            unit=unit,
            reference_kind=kind,
            boundaries=list(boundaries),
            classes=list(classes),
            samples=list(samples),
            conditions=conditions or {},
            **fields,
        )

    def report(self, *, domain=None, **args):
        return self.world.attribution.summarize_property(
            self.domain if domain is None else domain, self.property, **args
        )
