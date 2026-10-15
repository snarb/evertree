"""Independent model profiles; credentials stay in the core environment."""

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ModelProfile:
    model: str = "gpt-6-luna"
    effort: str = "low"

    def __post_init__(self):
        if (
            not isinstance(self.model, str)
            or not self.model.strip()
            or self.effort not in {"none", "low", "medium", "high", "xhigh", "max"}
        ):
            raise ValueError("Invalid semantic model profile")


@dataclass(frozen=True)
class ReadConfig:
    context_fraction: float = 0.6
    max_items: int = 600
    token_encoding: str = "o200k_base"

    def __post_init__(self):
        if (
            type(self.context_fraction) not in {int, float}
            or not math.isfinite(self.context_fraction)
            or not 0 < self.context_fraction <= 1
            or type(self.max_items) is not int
            or self.max_items < 1
            or not isinstance(self.token_encoding, str)
            or not self.token_encoding
        ):
            raise ValueError("Invalid semantic read configuration")


@dataclass(frozen=True)
class SemanticConfig:
    remember: ModelProfile = field(default_factory=lambda: ModelProfile(effort="high"))
    read: ReadConfig = field(default_factory=ReadConfig)
    redis_url_env: str = "EVERTREE_REDIS_URL"
    openai_key_env: str = "OPENAI_API_KEY"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072

    def __post_init__(self):
        if type(self.embedding_dimensions) is not int or self.embedding_dimensions < 1:
            raise ValueError("Invalid semantic search configuration")

    @classmethod
    def load(cls, home: Path):
        path = home / "evertree.toml"
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8")).get("semantics", {})
        for key in ("remember",):
            if key in data:
                data[key] = ModelProfile(**data[key])
        if "read" in data:
            data["read"] = ReadConfig(**data["read"])
        return cls(**data)
