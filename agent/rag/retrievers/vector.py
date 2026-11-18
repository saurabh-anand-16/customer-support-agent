"""
vector.py - meaning-based search: embed the question, ask the vector store for the nearest chunks.

The store's `where` handles the in-scope rule. A page-type filter (several values) is applied
afterwards, so in that case the whole index is asked for and then trimmed to k. Chunk details
come from the chunk list; the store is used only for ranking.
"""
from ..registry import register
from .base import Retriever


@register("retriever", "vector")
class VectorRetriever(Retriever):
    name = "vector"
    uses_index = True

    def retrieve(self, query, k, flt):
        if self.store is None or self.embedder is None:
            raise ValueError("the vector retriever needs a store and an embedder")
        vector = self.embedder.embed_query(query)
        asked = self.store.count() if flt.page_types else k
        hits = []
        for match in self.store.query(vector, asked, flt.where() or None):
            chunk = self.by_id.get(match.chunk_id)
            if chunk is None or not flt.allows(chunk):
                continue
            hits.append(self.make_hit(chunk, len(hits) + 1, match.score))
            if len(hits) == k:
                break
        return hits
