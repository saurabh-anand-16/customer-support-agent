"""
hybrid.py - runs the bm25 and vector retrievers and merges their lists with the configured fuser.

The merged list holds every chunk either retriever found, best first; each Hit's provenance
shows both retrievers' ranks and scores and the fused score.
"""
from .. import registry
from ..fusion import get_fuser
from ..registry import register
from .base import Retriever


@register("retriever", "hybrid")
class HybridRetriever(Retriever):
    name = "hybrid"
    uses_index = True

    def __init__(self, cfg, chunks, store=None, embedder=None, fuser=None):
        super().__init__(cfg, chunks, store, embedder)
        self.parts = {name: registry.get("retriever", name)(cfg, chunks, store, embedder) for name in ("bm25", "vector")}
        self.fuser = fuser or get_fuser(cfg)

    def retrieve(self, query, k, flt):
        lists = {name: part.retrieve(query, k, flt) for name, part in self.parts.items()}
        return self.fuser.fuse(lists)
