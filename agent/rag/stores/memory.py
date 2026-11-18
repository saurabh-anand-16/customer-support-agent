"""
memory.py - a store that keeps everything in memory (kind "memory").

It follows the same contract as the ChromaDB store and is used by tests, so they run fast and
need no extra package. Nothing is saved to disk.
"""
import numpy as np

from ..registry import register
from .base import Match, Record, Store


@register("store", "memory")
class MemoryStore(Store):
    def __init__(self, cfg, path=None):
        super().__init__(cfg, path)
        self._records: dict[str, Record] = {}
        self._meta: dict = {}

    def add(self, records):
        for r in records:
            if self._records and len(r.vector) != len(next(iter(self._records.values())).vector):
                raise ValueError("vector size does not match the vectors already stored")
            self._records[r.chunk_id] = r

    def delete(self, ids):
        for chunk_id in ids:
            self._records.pop(chunk_id, None)

    def ids(self):
        return sorted(self._records)

    def query(self, vector, k, where=None):
        q = np.array(vector, dtype=float)
        scored = []
        for r in self._records.values():
            if where and any(r.metadata.get(key) != value for key, value in where.items()):
                continue
            v = np.array(r.vector, dtype=float)
            scored.append((self._score(q, v), r))
        scored.sort(key=lambda pair: (-pair[0], pair[1].chunk_id))     # ties broken by id: same query, same order
        return [Match(r.chunk_id, float(s), r.text, dict(r.metadata)) for s, r in scored[:k]]

    def _score(self, q, v) -> float:
        distance = self.cfg.store.distance
        if distance == "l2":
            return -float(np.sum((q - v) ** 2))
        if distance == "ip":
            return float(q @ v)
        denom = float(np.linalg.norm(q) * np.linalg.norm(v))        # "cosine"
        return float(q @ v) / denom if denom else 0.0

    def get_meta(self):
        return dict(self._meta)

    def set_meta(self, meta):
        self._meta = dict(meta)

    def reset(self):
        self._records, self._meta = {}, {}
