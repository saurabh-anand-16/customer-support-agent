"""
bm25.py - keyword search with the BM25 formula, in plain Python (no package).

The corpus is the chunks' text. Words are found with [retrieval].token_pattern after lower-casing;
stopwords are dropped; with bm25_stem a plural "s" is stripped (refunds -> refund). Only chunks
that contain at least one meaningful query word are scored. The statistics (document counts and
lengths) always come from the whole corpus, so a filter changes which chunks can be returned but
never their scores.
"""
import math
import re
from collections import Counter

from ..registry import register
from .base import Retriever


def tokenize(text: str, cfg) -> list[str]:
    r = cfg.retrieval
    stop = set(r.stopwords)
    words = [w for w in re.findall(r.token_pattern, text.lower()) if w not in stop]
    if r.bm25_stem:
        words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")) else w for w in words]
    return words


@register("retriever", "bm25")
class Bm25Retriever(Retriever):
    name = "bm25"

    def __init__(self, cfg, chunks, store=None, embedder=None):
        super().__init__(cfg, chunks, store, embedder)
        self.counts = {c.chunk_id: Counter(tokenize(c.text, cfg)) for c in self.chunks}
        self.lengths = {cid: sum(c.values()) for cid, c in self.counts.items()}
        self.avg_length = (sum(self.lengths.values()) / len(self.lengths)) if self.lengths else 0.0
        self.doc_freq = Counter(term for counts in self.counts.values() for term in counts)

    def retrieve(self, query, k, flt):
        r = self.cfg.retrieval
        terms = list(dict.fromkeys(tokenize(query, self.cfg)))      # unique, in order
        n_docs = len(self.chunks)
        scores: dict[str, float] = {}
        for term in terms:
            df = self.doc_freq.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            for cid, counts in self.counts.items():
                tf = counts.get(term, 0)
                if tf:
                    norm = tf + r.bm25_k1 * (1 - r.bm25_b + r.bm25_b * self.lengths[cid] / self.avg_length)
                    scores[cid] = scores.get(cid, 0.0) + idf * tf * (r.bm25_k1 + 1) / norm
        ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))      # ties: by id, so order is fixed
        hits = []
        for cid, score in ranked:
            chunk = self.by_id[cid]
            if flt.allows(chunk):
                hits.append(self.make_hit(chunk, len(hits) + 1, score))
                if len(hits) == k:
                    break
        return hits
