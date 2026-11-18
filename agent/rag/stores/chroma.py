"""
chroma.py - the real store: ChromaDB saved in a folder (kind "chroma").

The folder is [store].path and the collection name is [store].collection. The `chromadb`
package is imported only when the store is opened (see requirements-rag.txt).
"""
from ..registry import register
from .base import Match, Record, Store

_SPACES = {"cosine": "cosine", "ip": "ip", "l2": "l2"}


@register("store", "chroma")
class ChromaStore(Store):
    def __init__(self, cfg, path=None):
        super().__init__(cfg, path)
        try:
            import chromadb
        except ImportError as err:
            raise ImportError("The 'chromadb' package is not installed: pip install -r requirements-rag.txt") from err
        if cfg.store.distance not in _SPACES:
            raise ValueError(f"[store].distance must be one of {', '.join(_SPACES)}")
        self._chromadb = chromadb
        self._client = chromadb.PersistentClient(path=str(self.path))
        self._collection = self._open()

    def _open(self):
        return self._client.get_or_create_collection(
            self.cfg.store.collection, metadata={"hnsw:space": _SPACES[self.cfg.store.distance]})

    def add(self, records):
        if not records:
            return
        self._collection.upsert(
            ids=[r.chunk_id for r in records],
            embeddings=[list(r.vector) for r in records],
            documents=[r.text for r in records],
            metadatas=[r.metadata or None for r in records],
        )

    def delete(self, ids):
        if ids:
            self._collection.delete(ids=list(ids))

    def ids(self):
        return sorted(self._collection.get(include=[])["ids"])

    def count(self):
        return self._collection.count()

    def query(self, vector, k, where=None):
        total = self._collection.count()
        if total == 0 or k <= 0:
            return []
        clauses = [{key: value} for key, value in (where or {}).items()]
        found = self._collection.query(
            query_embeddings=[list(vector)], n_results=min(k, total),
            where=None if not clauses else clauses[0] if len(clauses) == 1 else {"$and": clauses},
            include=["documents", "metadatas", "distances"])
        matches = []
        for chunk_id, text, meta, distance in zip(found["ids"][0], found["documents"][0],
                                                  found["metadatas"][0], found["distances"][0]):
            score = -distance if self.cfg.store.distance == "l2" else 1.0 - distance
            matches.append(Match(chunk_id, float(score), text, dict(meta or {})))
        matches.sort(key=lambda m: (-m.score, m.chunk_id))          # ties broken by id: same query, same order
        return matches

    def get_meta(self):
        return {k: v for k, v in (self._collection.metadata or {}).items() if k != "hnsw:space"}

    def set_meta(self, meta):
        # The distance function cannot be changed after creation, so it is left out here.
        self._collection.modify(metadata=dict(meta))

    def reset(self):
        self._client.delete_collection(self.cfg.store.collection)
        self._collection = self._open()
