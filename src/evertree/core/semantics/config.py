"""Independent model profiles; credentials stay in the core environment."""

import math
import os
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
class JevConfig:
    enabled: bool = False
    model: str = "jev-1.13.0"
    threshold: float = 0.05
    api_key_env: str = "TYPESAFE_API_KEY"

    def __post_init__(self):
        if (
            type(self.enabled) is not bool
            or not isinstance(self.model, str)
            or not self.model.strip()
            or type(self.threshold) not in {int, float}
            or not math.isfinite(self.threshold)
            or not 0 <= self.threshold <= 1
            or not isinstance(self.api_key_env, str)
            or not self.api_key_env.strip()
        ):
            raise ValueError("Invalid Jev search configuration")


@dataclass(frozen=True)
class SearchConfig:
    bm25_candidates: int = 64
    vector_candidates: int = 64
    chunk_tokens: int = 768
    chunk_overlap: int = 128

    def __post_init__(self):
        if (
            any(
                type(n) is not int or not 1 <= n <= 1000
                for n in (self.bm25_candidates, self.vector_candidates)
            )
            or type(self.chunk_tokens) is not int
            or not 64 <= self.chunk_tokens <= 4096
            or type(self.chunk_overlap) is not int
            or not 0 <= self.chunk_overlap < self.chunk_tokens
        ):
            raise ValueError("Invalid semantic search configuration")


@dataclass(frozen=True)
class SemanticConfig:
    remember: ModelProfile = field(default_factory=lambda: ModelProfile(effort="high"))
    read: ReadConfig = field(default_factory=ReadConfig)
    jev: JevConfig = field(default_factory=JevConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    redis_url_env: str = "EVERTREE_REDIS_URL"
    openai_key_env: str = "OPENAI_API_KEY"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 3072

    def __post_init__(self):
        if type(self.embedding_dimensions) is not int or self.embedding_dimensions < 1:
            raise ValueError("Invalid semantic search configuration")

    @classmethod
    def load(cls, home: Path):
        """Load semantic model, search and read-budget settings from an optional agent configuration file."""
        path = home / "evertree.toml"
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8")).get("semantics", {})
        for key in ("remember",):
            if key in data:
                data[key] = ModelProfile(**data[key])
        if "read" in data:
            data["read"] = ReadConfig(**data["read"])
        if "jev" in data:
            data["jev"] = JevConfig(**data["jev"])
        if "search" in data:
            data["search"] = SearchConfig(**data["search"])
        return cls(**data)


def load_search_environment(home: Path, config: SemanticConfig):
    """Load allowlisted host secrets from .env without replacing existing environment values."""
    from dotenv import dotenv_values

    path = home / ".env"
    if path.is_file():
        values = dotenv_values(path, interpolate=False)
        for name in (config.redis_url_env, config.openai_key_env, config.jev.api_key_env):
            if values.get(name):
                os.environ.setdefault(name, values[name])
