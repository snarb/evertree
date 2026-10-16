"""Redis Search generations derived entirely from authoritative graph content."""

import asyncio
import hashlib
import json
import os
import re
import urllib.request
from array import array
from contextlib import asynccontextmanager

from ..graph.types import normalize_name


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
        self._locks = {}
        self._generation_guard = asyncio.Lock()
        self._active = {}
        self._current = None
        self._ready = set()
        self._vectors_ready = set()
        self._unsubscribe = None
        self._refresh_task = None
        self._pending = None
        self.indexed_revision = None
        self.last_error = None

    def attach(self, graph):
        """Subscribe to committed graph changes and schedule derived-index refreshes."""
        if self._unsubscribe:
            self._unsubscribe()
        self.indexed_revision = None

        def changed(_=None):
            from .reading import card

            self._pending = (graph.revision, [card(n) for n in graph.nodes()])
            if not os.environ.get(self.config.redis_url_env) and self.client is None:
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            if self._refresh_task is None or self._refresh_task.done():
                self._refresh_task = loop.create_task(self._refresh())

        self._unsubscribe = graph.on_change(changed)
        changed()

    async def _refresh(self):
        while self._pending is not None:
            revision, nodes = self._pending
            self._pending = None
            try:
                async with self._generation_lease(nodes) as index:
                    await self._ensure_vectors(index, nodes)
                self.indexed_revision = {"revision": revision, "generation": index}
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 -- derived index failures cannot reject graph commits
                # An unavailable derived index must never roll back semantic writes.
                self.last_error = type(exc).__name__

    def _redis(self):
        if self.client is None:
            from redis.asyncio import Redis

            url = os.environ.get(self.config.redis_url_env)
            if not url:
                raise RuntimeError("Redis Search URL is not configured")
            self.client = Redis.from_url(url, socket_connect_timeout=10, socket_timeout=None)
        return self.client

    def _generation(self, nodes):
        data = [self.config.embedding_model, self.config.embedding_dimensions, nodes]
        digest = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return self.namespace + ":" + digest

    @asynccontextmanager
    async def _generation_lease(self, nodes):
        index = self._generation(nodes)
        async with self._generation_guard:
            self._active[index] = self._active.get(index, 0) + 1
            self._current = index
        try:
            await self._ensure(nodes)
            yield index
        finally:
            async with self._generation_guard:
                self._active[index] -= 1
                if not self._active[index]:
                    del self._active[index]
                try:
                    await self._collect_generations()
                except Exception as exc:  # noqa: BLE001 -- cache cleanup cannot invalidate a read
                    self.last_error = type(exc).__name__

    async def _collect_generations(self):
        # Keep in-flight snapshots, but do not retain a full index per graph edit.
        client = self._redis()
        for raw in await client.execute_command("FT._LIST"):
            index = raw.decode() if isinstance(raw, bytes) else raw
            if (
                not index.startswith(self.namespace + ":")
                or index == self._current
                or index in self._active
            ):
                continue
            await client.execute_command("FT.DROPINDEX", index, "DD")
            self._ready.discard(index)
            self._vectors_ready.discard(index)
            self._locks.pop(index, None)
            self._locks.pop(index + ":vectors", None)

    @staticmethod
    def _text(node):
        return node["name"] + " " + (node.get("description") or "")

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
        async with self._locks.setdefault(index, asyncio.Lock()):
            from redis.exceptions import ResponseError

            if index in self._ready:
                try:
                    raw = await client.execute_command("FT.INFO", index)
                    info = dict(zip(raw[::2], raw[1::2]))
                    if int(info.get(b"num_docs", 0)) != len(nodes):
                        self._ready.discard(index)
                        self._vectors_ready.discard(index)
                except ResponseError as exc:
                    if "Unknown index" not in str(exc) and "no such index" not in str(exc):
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
                        "vector",
                        "VECTOR",
                        "HNSW",
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
                pipe = client.pipeline(transaction=False)
                for node in nodes:
                    pipe.hset(
                        index + ":node:" + str(node["id"]),
                        mapping={
                            "text": normalize_name(self._text(node)),
                            "kind": node["kind"],
                            "identity": node["id"],
                        },
                    )
                await pipe.execute()
                await self._indexed(index, len(nodes))
                self._ready.add(index)
        return index

    async def _ensure_vectors(self, index, nodes):
        """Populate missing embeddings for a leased generation without mixing graph snapshots."""
        client = self._redis()
        async with self._locks.setdefault(index + ":vectors", asyncio.Lock()):
            if index in self._vectors_ready:
                return
            for start in range(0, len(nodes), 32):
                batch = nodes[start : start + 32]
                texts = [self._text(n) for n in batch]
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
                    pipe.hset(index + ":node:" + str(node["id"]), "vector", vector)
                await pipe.execute()
            self._vectors_ready.add(index)

    @staticmethod
    def _ids(result):
        return [
            int(
                result[i].decode().rsplit(":", 1)[1]
                if isinstance(result[i], bytes)
                else result[i].rsplit(":", 1)[1]
            )
            for i in range(1, len(result), 2)
        ]

    @staticmethod
    def _kind(kind):
        if kind is None:
            return "*"
        return "@kind:{" + re.sub(r"([^\w])", r"\\\1", kind.strip().casefold()) + "}"

    async def lexical(self, nodes, query, kind=None):
        """Rank up to seven graph identities by Redis BM25 over the leased graph snapshot."""
        async with self._generation_lease(nodes) as index:
            terms = re.findall(r"\w+", normalize_name(query), flags=re.UNICODE)
            if not terms:
                return []
            text_query = "@text:(" + "|".join(terms) + ")"
            if kind is not None:
                text_query = self._kind(kind) + " " + text_query
            result = await self._redis().execute_command(
                "FT.SEARCH",
                index,
                text_query,
                "SCORER",
                "BM25STD",
                "RETURN",
                1,
                "identity",
                "LIMIT",
                0,
                7,
                "TIMEOUT",
                0,
                "DIALECT",
                2,
            )
            return self._ids(result)

    async def vector(self, nodes, query, kind=None):
        """Rank up to twelve graph identities by embedding distance over the leased snapshot."""
        async with self._generation_lease(nodes) as index:
            embeddings_task = asyncio.create_task(self.embeddings.embed([query]))
            try:
                await self._ensure_vectors(index, nodes)
                vector = (await embeddings_task)[0]
                if len(vector) != self.config.embedding_dimensions:
                    raise ValueError("Query embedding dimensions mismatch")
                blob = array("f", vector).tobytes()
                result = await self._redis().execute_command(
                    "FT.SEARCH",
                    index,
                    "(" + self._kind(kind) + ")=>[KNN 12 @vector $query AS distance]",
                    "PARAMS",
                    2,
                    "query",
                    blob,
                    "SORTBY",
                    "distance",
                    "RETURN",
                    1,
                    "identity",
                    "LIMIT",
                    0,
                    12,
                    "TIMEOUT",
                    0,
                    "DIALECT",
                    2,
                )
                return self._ids(result)
            finally:
                if not embeddings_task.done():
                    embeddings_task.cancel()
                await asyncio.gather(embeddings_task, return_exceptions=True)

    async def close(self):
        """Detach graph listeners, stop index refreshes and close the Redis connection."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        if self._refresh_task:
            self._refresh_task.cancel()
            await asyncio.gather(self._refresh_task, return_exceptions=True)
        if self.client is not None:
            await self.client.aclose()
