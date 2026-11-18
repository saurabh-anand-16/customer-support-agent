"""
none.py - no reranking: the fused order is kept as it is.
"""
from ..registry import register
from .base import Reranker


@register("reranker", "none")
class NoReranker(Reranker):
    name = "none"
    limits_output = False

    def rerank(self, query, hits):
        return [(hit, None) for hit in hits]
