"""
base.py - the retriever contract.

A retriever is built with the config, the chunks (from phase 3a) and, if it needs them, the
vector store and an embedder. `retrieve(query, k, flt)` returns up to k Hits, best first, only
from chunks the filter allows. Each Hit's provenance records this retriever's rank and score.
For the same query and settings it must always return the same hits in the same order.
`uses_index` says whether it reads the vector index (so search must check the index is current).
"""
from ..config import RagConfig
from ..filters import Filter
from ..types import Hit, new_provenance


class Retriever:
    name = ""
    uses_index = False

    def __init__(self, cfg: RagConfig, chunks, store=None, embedder=None):
        self.cfg = cfg
        self.chunks = list(chunks)
        self.by_id = {c.chunk_id: c for c in self.chunks}
        self.store = store
        self.embedder = embedder

    def retrieve(self, query: str, k: int, flt: Filter) -> list[Hit]:
        raise NotImplementedError

    def make_hit(self, chunk, rank: int, score: float) -> Hit:
        provenance = new_provenance()
        provenance["retrievers"] = {self.name: {"rank": rank, "score": float(score)}}
        return Hit.from_chunk(chunk, float(score), provenance)
