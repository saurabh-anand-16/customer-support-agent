"""
weighted.py - weighted sum of scores.

Each list's scores are first scaled to 0 to 1 (the best in the list becomes 1, the worst 0; a
list whose scores are all equal gives every hit 1). A chunk's fused score is then the sum, over
the lists it appears in, of weight x scaled score. The weight for a list called "bm25" is
[fusion].weight_bm25, for "vector" it is [fusion].weight_vector.
"""
from ..registry import register
from . import Fuser


@register("fuser", "weighted")
class WeightedFuser(Fuser):
    name = "weighted"

    def scores(self, lists):
        fused: dict[str, float] = {}
        for name, hits in lists.items():
            if not hits:
                continue
            weight = getattr(self.cfg.fusion, f"weight_{name}", None)
            if weight is None:
                raise ValueError(f"no weight_{name} in [fusion] for the '{name}' list")
            low, high = min(h.score for h in hits), max(h.score for h in hits)
            for hit in hits:
                scaled = (hit.score - low) / (high - low) if high > low else 1.0
                fused[hit.chunk_id] = fused.get(hit.chunk_id, 0.0) + weight * scaled
        return fused
