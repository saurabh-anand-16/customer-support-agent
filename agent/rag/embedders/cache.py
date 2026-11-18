"""
cache.py - remembers vectors on disk so a rebuild embeds only what changed.

Each entry is keyed by the embedder's name (provider, model), the requested size and a hash of
the text. The file is JSON lines: {"key": ..., "vector": [...]}. It holds hashes and numbers
only: not the text, and never the API key. A line that cannot be read is skipped.
"""
import hashlib
import json
from pathlib import Path

from .base import Embedder


class CachedEmbedder:
    """Wraps another embedder with the same interface; asks it only for texts it has not seen."""

    def __init__(self, inner: Embedder, path: str | Path):
        self.inner = inner
        self.path = Path(path)
        self.cache_hits = 0
        self._vectors: dict[str, list[float]] = {}
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                    self._vectors[entry["key"]] = entry["vector"]
                except (ValueError, KeyError, TypeError):
                    continue

    # same surface as Embedder
    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def embedded_count(self) -> int:
        return self.inner.embedded_count

    @property
    def dimension(self) -> int:
        return self.inner.dimension

    def _key(self, text: str) -> str:
        e = self.inner.cfg.embedding
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{self.inner.name}|{e.dimensions}|{e.normalize}|{digest}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [self._key(t) for t in texts]
        missing = list(dict.fromkeys(t for t, k in zip(texts, keys) if k not in self._vectors))
        self.cache_hits += sum(1 for k in keys if k in self._vectors)
        if missing:
            fresh = self.inner.embed(missing)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                for text, vector in zip(missing, fresh):
                    key = self._key(text)
                    self._vectors[key] = vector
                    f.write(json.dumps({"key": key, "vector": vector}) + "\n")
        return [self._vectors[k] for k in keys]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([self.inner.cfg.embedding.query_prefix + text])[0]
