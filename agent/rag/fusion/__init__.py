"""
fusion: ways to merge several ranked lists into one. Importing this package registers `rrf` and
`weighted`; `get_fuser(cfg)` returns the one named in [fusion].method.

Contract: fuse({"bm25": [...hits], "vector": [...hits]}) returns one list of Hits, best first,
holding every chunk found by any list once. Each Hit's score becomes the fused score, and its
provenance keeps every retriever's rank and score plus the fuser's name and the fused score.
Ties are broken by chunk id so the order never varies.
"""
from dataclasses import replace

from .. import registry
from ..config import RagConfig
from ..types import Hit


class Fuser:
    name = ""

    def __init__(self, cfg: RagConfig):
        self.cfg = cfg

    def scores(self, lists: dict[str, list[Hit]]) -> dict[str, float]:
        """{chunk_id: fused score}. Each fuser implements this."""
        raise NotImplementedError

    def fuse(self, lists: dict[str, list[Hit]]) -> list[Hit]:
        fused = self.scores(lists)
        first_seen: dict[str, Hit] = {}
        retrievers: dict[str, dict] = {}
        for hits in lists.values():
            for hit in hits:
                first_seen.setdefault(hit.chunk_id, hit)
                retrievers.setdefault(hit.chunk_id, {}).update(hit.provenance["retrievers"])
        out = []
        for cid, hit in first_seen.items():
            hit = hit.with_provenance(retrievers=retrievers[cid], fusion=self.name, fused_score=fused[cid])
            out.append(replace(hit, score=fused[cid]))
        return sorted(out, key=lambda h: (-h.score, h.chunk_id))


def get_fuser(cfg: RagConfig) -> Fuser:
    if cfg.fusion.method == "none":
        raise ValueError('hybrid retrieval needs [fusion].method to be "rrf" or "weighted", not "none"')
    return registry.get("fuser", cfg.fusion.method)(cfg)


from . import rrf, weighted   # noqa: E402,F401  (importing registers them)
