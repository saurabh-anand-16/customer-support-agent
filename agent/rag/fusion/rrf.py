"""
rrf.py - reciprocal rank fusion.

A chunk's fused score is the sum, over every list it appears in, of 1 / (rrf_k + rank), where rank
starts at 1 and rrf_k is [fusion].rrf_k. Only ranks matter, so lists with different score scales
(BM25 and similarity) can be merged without adjusting them.
"""
from ..registry import register
from . import Fuser


@register("fuser", "rrf")
class RrfFuser(Fuser):
    name = "rrf"

    def scores(self, lists):
        k = self.cfg.fusion.rrf_k
        fused: dict[str, float] = {}
        for hits in lists.values():
            for position, hit in enumerate(hits, start=1):
                fused[hit.chunk_id] = fused.get(hit.chunk_id, 0.0) + 1.0 / (k + position)
        return fused
