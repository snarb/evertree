"""On-demand Redis Search index derived from authoritative graph content."""

import asyncio
import hashlib
import json
import os
import re
import urllib.request
from array import array
from dataclasses import asdict

import tiktoken

from ..graph.types import normalize_name
from .searching import search_kinds


class OpenAIEmbeddings:
    def __init__(self, config):
        self.config = config

    async def embed(self, texts):
        """Request configured OpenAI embeddings using host credentials and preserve input order."""
        key = os.environ.get(self.config.openai_key_env)
        if not key:
            raise RuntimeError("OpenAI embedding credentials are not configured")
        payload = json.dumps(
            {
                "model": self.config.embedding_model,
                "input": texts,
                "dimensions": self.config.embedding_dimensions,
            }
        ).encode()

        def send():
            request = urllib.request.Request(
                "https://api.openai.com/v1/embeddings",
                payload,
                {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.load(response)
            return [item["embedding"] for item in sorted(result["data"], key=lambda i: i["index"])]

        return await asyncio.to_thread(send)


class RedisSearchIndex:
    def __init__(self, config, namespace, *, client=None, embeddings=None):
        self.config = config
        self.namespace = "evertree:" + hashlib.sha256(str(namespace).encode()).hexdigest()[:24]
        self.client = client
        self.embeddings = embeddings or OpenAIEmbeddings(config)
        self._prepare_lock = asyncio.Lock()
        self._vectors_lock = asyncio.Lock()
        self._current = None
        self._ready = set()
        self._vectors_ready = set()
        self.last_error = None
        self._documents_key = None
        self._documents_cache = []

    def _redis(self):
        if self.client is None:
            from redis.asyncio import Redis

            url = os.environ.get(self.config.redis_url_env)
            if not url:
                raise RuntimeError("Redis Search URL is not configured")
            self.client = Redis.from_url(url, socket_connect_timeout=10, socket_timeout=None)
        return self.client

    def _generation(self, nodes):
        data = [
            4,
            self.config.embedding_model,
            self.config.embedding_dimensions,
            asdict(self.config.search),
            nodes,
        ]
        digest = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return self.namespace + ":" + digest

    async def _collect_generations(self):
        # Runtime finishes the preceding search before a different graph can be indexed.
        client = self._redis()
        for raw in await client.execute_command("FT._LIST"):
            index = raw.decode() if isinstance(raw, bytes) else raw
            if not index.startswith(self.namespace + ":") or index in {
                self._current,
                self._current + ":vectors",
            }:
                continue
            await client.execute_command("FT.DROPINDEX", index, "DD")
            self._ready.discard(index)
            self._vectors_ready.discard(index)

    @staticmethod
    def _text(node):
        text = node["name"] + " " + (node.get("description") or "")
        fields = {
            key: node[key]
            for key in (
                "relation",
                "relation_description",
                "args",
                "signature",
                "semantic_signature",
                "semantic_links",
                "properties",
                "valid_from",
                "valid_until",
            )
            if key in node
        }

        def named(reference):
            return {
                key: reference[key] for key in ("name", "kind", "description") if key in reference
            }

        if "semantic_signature" in fields:
            fields["semantic_signature"] = [
                {
                    **slot,
                    **{
                        key: named(slot[key]) if slot.get(key) else None
                        for key in ("value_concept", "role_concept")
                    },
                }
                for slot in fields["semantic_signature"]
            ]
            fields["signature"] = [
                {
                    key: value
                    for key, value in slot.items()
                    if key not in {"value_concept", "role_concept"}
                }
                for slot in fields.get("signature", [])
            ]
        if "semantic_links" in fields:
            fields["semantic_links"] = [
                {**link, "target": named(link["target"])} for link in fields["semantic_links"]
            ]
        if "args" in fields:
            fields["args"] = dict(fields["args"])
            for slot in node.get("signature", []):
                if slot["value_type"] not in {"node", "concept", "prototype", "instance", "facet"}:
                    continue
                value = fields["args"].get(slot["label"])

                # Reference IDs must not masquerade as measured numbers. Opaque data stays intact.
                if isinstance(value, list):
                    fields["args"][slot["label"]] = [named(reference) for reference in value]
                elif value is not None:
                    fields["args"][slot["label"]] = named(value)
        return text + (
            "\n" + json.dumps(fields, ensure_ascii=False, sort_keys=True) if fields else ""
        )

    def _documents(self, nodes):
        key = self._generation(nodes)
        if key != self._documents_key:
            encoder = tiktoken.get_encoding("cl100k_base")
            size, overlap = self.config.search.chunk_tokens, self.config.search.chunk_overlap
            documents = []
            for node in nodes:
                text = self._text(node)
                tokens = encoder.encode(text, disallowed_special=())
                _, offsets = encoder.decode_with_offsets(tokens)
                for position, start in enumerate(range(0, len(tokens), size - overlap)):
                    end = min(start + size, len(tokens))
                    documents.append(
                        {
                            "id": node["id"],
                            "key": f"{node['id']}:{position}",
                            "kind": node["kind"],
                            "text": text[
                                offsets[start] : offsets[end] if end < len(tokens) else len(text)
                            ],
                        }
                    )
                    if start + size >= len(tokens):
                        break
            self._documents_key, self._documents_cache = key, documents
        return self._documents_cache

    @staticmethod
    def _algorithm(count):
        return "FLAT" if count < 10000 else "HNSW"

    async def _indexed(self, index, count):
        while True:
            raw = await self._redis().execute_command("FT.INFO", index)
            info = dict(zip(raw[::2], raw[1::2]))
            if int(info.get(b"hash_indexing_failures", 0)):
                raise RuntimeError("Redis rejected indexed documents")
            if not int(info.get(b"indexing", 0)) and int(info.get(b"num_docs", 0)) == count:
                return
            await asyncio.sleep(0.01)

    async def _ensure(self, nodes):
        """Publish a complete lexical generation for a graph snapshot before exposing it to readers."""
        client = self._redis()
        index = self._generation(nodes)
        documents = self._documents(nodes)
        async with self._prepare_lock:
            from redis.exceptions import ResponseError

            if index in self._ready:
                try:
                    raw = await client.execute_command("FT.INFO", index)
                    info = dict(zip(raw[::2], raw[1::2]))
                    if int(info.get(b"num_docs", 0)) != len(documents):
                        self._ready.discard(index)
                        self._vectors_ready.discard(index)
                except ResponseError as exc:
                    if not any(
                        text in str(exc).casefold()
                        for text in ("unknown index", "no such index", "index not found")
                    ):
                        raise
                    self._ready.discard(index)
                    self._vectors_ready.discard(index)
            if index not in self._ready:
                try:
                    await client.execute_command(
                        "FT.CREATE",
                        index,
                        "ON",
                        "HASH",
                        "PREFIX",
                        1,
                        index + ":node:",
                        "STOPWORDS",
                        0,
                        "SCHEMA",
                        "text",
                        "TEXT",
                        "kind",
                        "TAG",
                    )
                except ResponseError as exc:
                    if "Index already exists" not in str(exc):
                        raise
                pipe = client.pipeline(transaction=False)
                for node in documents:
                    pipe.hset(
                        index + ":node:" + node["key"],
                        mapping={
                            "text": normalize_name(node["text"]),
                            "kind": node["kind"],
                            "identity": node["id"],
                        },
                    )
                await pipe.execute()
                await self._indexed(index, len(documents))
                self._ready.add(index)
            self._current = index
            try:
                await self._collect_generations()
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 -- cache cleanup cannot reject a completed index
                self.last_error = type(exc).__name__
        return index

    async def _ensure_vectors(self, index, nodes):
        """Populate missing embeddings for a current index."""
        client = self._redis()
        async with self._vectors_lock:
            from redis.exceptions import ResponseError

            documents = self._documents(nodes)
            vector_index = index + ":vectors"
            if index in self._vectors_ready:
                try:
                    raw = await client.execute_command("FT.INFO", vector_index)
                    info = dict(zip(raw[::2], raw[1::2]))
                    if int(info.get(b"num_docs", 0)) == len(documents):
                        return
                except ResponseError as exc:
                    if not any(
                        text in str(exc).casefold()
                        for text in ("unknown index", "no such index", "index not found")
                    ):
                        raise
                self._vectors_ready.discard(index)
            try:
                await client.execute_command(
                    "FT.CREATE",
                    vector_index,
                    "ON",
                    "HASH",
                    "PREFIX",
                    1,
                    vector_index + ":node:",
                    "SCHEMA",
                    "kind",
                    "TAG",
                    "vector",
                    "VECTOR",
                    self._algorithm(len(documents)),
                    6,
                    "TYPE",
                    "FLOAT32",
                    "DIM",
                    self.config.embedding_dimensions,
                    "DISTANCE_METRIC",
                    "COSINE",
                )
            except ResponseError as exc:
                if "Index already exists" not in str(exc):
                    raise
            self._ready.add(vector_index)
            for start in range(0, len(documents), 32):
                batch = documents[start : start + 32]
                texts = [n["text"] for n in batch]
                keys = [
                    self.namespace
                    + ":embedding:"
                    + hashlib.sha256(
                        json.dumps(
                            [self.config.embedding_model, self.config.embedding_dimensions, t]
                        ).encode()
                    ).hexdigest()
                    for t in texts
                ]
                cached_values = await client.mget(keys)
                cached = dict(zip(keys, cached_values, strict=True))
                missing = {
                    key: text
                    for key, text in zip(keys, texts, strict=True)
                    if cached[key] is None
                    or len(cached[key]) != 4 * self.config.embedding_dimensions
                }
                if missing:
                    vectors = await self.embeddings.embed(list(missing.values()))
                    if len(vectors) != len(missing):
                        raise ValueError("Embedding response count mismatch")
                    for key, vector in zip(missing, vectors, strict=True):
                        if len(vector) != self.config.embedding_dimensions:
                            raise ValueError("Embedding dimensions mismatch")
                        cached[key] = array("f", vector).tobytes()
                pipe = client.pipeline(transaction=False)
                for node, key in zip(batch, keys, strict=True):
                    vector = cached[key]
                    pipe.set(key, vector, ex=30 * 24 * 60 * 60)
                    pipe.hset(
                        vector_index + ":node:" + node["key"],
                        mapping={"kind": node["kind"], "identity": node["id"], "vector": vector},
                    )
                await pipe.execute()
            await self._indexed(vector_index, len(documents))
            self._vectors_ready.add(index)

    @staticmethod
    def _ids(result, *, lexical=False):
        best = {}
        for position in range(1, len(result), 3 if lexical else 2):
            raw = result[position + (2 if lexical else 1)]
            fields = dict(zip(raw[::2], raw[1::2], strict=True))
            identity = int(fields.get(b"identity", fields.get("identity")))
            score = (
                float(result[position + 1])
                if lexical
                else -float(fields.get(b"distance", fields.get("distance", 0)))
            )
            best[identity] = max(score, best.get(identity, -float("inf")))
        # Equal passage scores must not make object ranks depend on Redis insertion order.
        return sorted(best, key=lambda identity: (-best[identity], identity))

    def _fetch_count(self, nodes, quota):
        # One object's matching passages must not consume another object's quota.
        counts = {}
        for document in self._documents(nodes):
            identity = document["id"]
            counts[identity] = counts.get(identity, 0) + 1
        return min(len(self._documents_cache), quota * max(counts.values(), default=1))

    @staticmethod
    def _kinds(kinds):
        kinds = search_kinds(kinds)
        if kinds is None:
            return "*"
        return "@kind:{" + "|".join(re.sub(r"([^\w])", r"\\\1", kind) for kind in kinds) + "}"

    async def _ranked(self, commands):
        pipe = self._redis().pipeline(transaction=False)
        for command in commands:
            pipe.execute_command(*command)
        replies = await pipe.execute(raise_on_error=False)
        return [
            {"ids": [], "error": str(reply)}
            if isinstance(reply, Exception)
            else {"ids": self._ids(reply, lexical="WITHSCORES" in command)}
            for command, reply in zip(commands, replies, strict=True)
        ]

    async def lexical(self, nodes, queries, kinds=None):
        """Retrieve distinct objects by their best lexical passage in one pipeline."""
        kinds = search_kinds(kinds)
        if not queries:
            return []
        index = await self._ensure(nodes)
        quota = self.config.search.bm25_candidates
        fetch = self._fetch_count(nodes, quota)
        commands, positions = [], []
        rows = [{"ids": []} for _ in queries]
        for position, query in enumerate(queries):
            terms = re.findall(r"\w+", normalize_name(query), flags=re.UNICODE)
            if not terms:
                continue
            text_query = "@text:(" + "|".join(terms) + ")"
            if kinds is not None:
                text_query = self._kinds(kinds) + " " + text_query
            positions.append(position)
            commands.append(
                (
                    "FT.SEARCH",
                    index,
                    text_query,
                    "WITHSCORES",
                    "SCORER",
                    "BM25STD",
                    "RETURN",
                    1,
                    "identity",
                    "LIMIT",
                    0,
                    fetch,
                    "TIMEOUT",
                    0,
                    "DIALECT",
                    2,
                )
            )
        if commands:
            for position, row in zip(positions, await self._ranked(commands), strict=True):
                rows[position] = {**row, "ids": row["ids"][:quota]}
        return rows

    async def vector(self, nodes, queries, kinds=None):
        """Retrieve distinct objects by nearest passage using batched query embeddings."""
        kinds = search_kinds(kinds)
        if not queries:
            return []
        index = await self._ensure(nodes)
        quota = self.config.search.vector_candidates
        fetch = self._fetch_count(nodes, quota)
        runtime = (
            f" EF_RUNTIME {max(200, fetch)}"
            if self._algorithm(len(self._documents_cache)) == "HNSW"
            else ""
        )
        embeddings_task = asyncio.create_task(self.embeddings.embed(queries))
        try:
            await self._ensure_vectors(index, nodes)
            vectors = await embeddings_task
            if len(vectors) != len(queries) or any(
                len(vector) != self.config.embedding_dimensions for vector in vectors
            ):
                raise ValueError("Query embedding count or dimensions mismatch")
            commands = [
                (
                    "FT.SEARCH",
                    index + ":vectors",
                    "("
                    + self._kinds(kinds)
                    + f")=>[KNN {fetch} @vector $query{runtime} AS distance]",
                    "PARAMS",
                    2,
                    "query",
                    array("f", vector).tobytes(),
                    "SORTBY",
                    "distance",
                    "RETURN",
                    2,
                    "identity",
                    "distance",
                    "LIMIT",
                    0,
                    fetch,
                    "TIMEOUT",
                    0,
                    "DIALECT",
                    2,
                )
                for vector in vectors
            ]
            return [{**row, "ids": row["ids"][:quota]} for row in await self._ranked(commands)]
        finally:
            if not embeddings_task.done():
                embeddings_task.cancel()
            await asyncio.gather(embeddings_task, return_exceptions=True)

    async def close(self):
        """Close the derived index connection."""
        if self.client is not None:
            await self.client.aclose()
