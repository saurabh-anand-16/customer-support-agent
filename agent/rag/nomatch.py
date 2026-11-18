"""
nomatch.py - decides whether the results count as an answer at all.

Each strategy has its own rule, with thresholds from [no_match] in config/rag.toml:
  bm25     the best BM25 score must reach bm25_min_score (and a query word must have matched at all)
  vector   the best similarity must reach vector_min_score
  hybrid   both rules above are checked on each retriever's own best score; hybrid_require
           says whether "any" or "all" of them must pass
Fewer than min_hits results is always "no match". The thresholds in the starting config are
placeholders; phase 3d calibrates them.
"""
from dataclasses import dataclass

from .config import RagConfig


@dataclass(frozen=True)
class Decision:
    matched: bool
    reason: str


def _best(hits, retriever: str):
    """The highest score the named retriever gave to any hit, or None if it found nothing."""
    scores = [h.provenance["retrievers"][retriever]["score"] for h in hits if retriever in h.provenance["retrievers"]]
    return max(scores) if scores else None


class NoMatchRule:
    def __init__(self, cfg: RagConfig):
        self.cfg = cfg

    def decide(self, strategy: str, hits) -> Decision:
        n = self.cfg.no_match
        if len(hits) < n.min_hits:
            return Decision(False, "no result found (no meaningful query word matched, or nothing was retrieved)")
        bm25, vector = _best(hits, "bm25"), _best(hits, "vector")
        bm25_ok = bm25 is not None and bm25 >= n.bm25_min_score
        vector_ok = vector is not None and vector >= n.vector_min_score
        if strategy == "bm25":
            ok, why = bm25_ok, f"best bm25 score {bm25} is below {n.bm25_min_score}"
        elif strategy == "vector":
            ok, why = vector_ok, f"best similarity {vector} is below {n.vector_min_score}"
        else:   # hybrid, and any later strategy built from both
            ok = (bm25_ok and vector_ok) if n.hybrid_require == "all" else (bm25_ok or vector_ok)
            why = (f"hybrid_require = {n.hybrid_require}: bm25 {bm25} (needs {n.bm25_min_score}), "
                   f"vector {vector} (needs {n.vector_min_score})")
        return Decision(ok, "" if ok else why)
