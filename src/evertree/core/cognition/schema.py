"""Closed response schemas; Python defaults remain useful to internal callers."""

from pydantic.json_schema import GenerateJsonSchema


class ResponseSchema(GenerateJsonSchema):
    def generate(self, schema, mode="validation"):
        result = super().generate(schema, mode=mode)

        def close(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    if value.get("additionalProperties") not in (None, False):
                        raise ValueError(
                            "Response objects need explicit fields, not arbitrary maps"
                        )
                    value["additionalProperties"] = False
                    value["required"] = list(value.get("properties", {}))
                value.pop("default", None)
                for child in value.values():
                    close(child)
            elif isinstance(value, list):
                for child in value:
                    close(child)

        close(result)
        return result
