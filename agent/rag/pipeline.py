"""
pipeline.py - builds the search stages from the config (and so from a profile) and runs them.

  retrieve (bm25, vector or hybrid)  ->  no-match rule  ->  rerank  ->  cut to top_k

The profile decides every part: [retrieval].strategy, [fusion].method, [rerank].method and the
thresholds in [no_match]. Nothing is chosen here by name. A reranker that fails never fails the
search: the fused order is kept and each hit's provenance says what went wrong.
"""
from dataclasses import dataclass, field, replace

from .chunkers import chunk_documents
from .config import RagConfig
from .embedders import get_embedder
from .filters import Filter
from .ingest import load_documents
from .nomatch import NoMatchRule
from .rerankers import get_reranker
from .retrievers import get_retriever, uses_index
from .stores import get_store
from .types import Hit


@dataclass
class PipelineResult:
    hits: list[Hit] = field(default_factory=list)
    matched: bool = True
    reason: str = ""             # why nothing counted as an answer (empty when something did)
    rerank_status: str = "ok"    # "ok", or "failed: ..." when the fused order was kept


class Pipeline:
    def __init__(self, cfg: RagConfig, retriever, reranker, rule: NoMatchRule):
        self.cfg, self.retriever, self.reranker, self.rule = cfg, retriever, reranker, rule

    @classmethod
    def build(cls, cfg: RagConfig, chunks=None, store=None, embedder=None, reranker=None) -> "Pipeline":
        """
        The stages for cfg's profile. `chunks`, `store`, `embedder` and `reranker` can be given
        (tests do); otherwise they are made from the config, and only the parts the profile needs.
        """
        if chunks is None:
            chunks = chunk_documents(cfg, load_documents(cfg))
        if uses_index(cfg):
            store = store or get_store(cfg)
            embedder = embedder or get_embedder(cfg)
        retriever = get_retriever(cfg, chunks, store, embedder)
        return cls(cfg, retriever, reranker or get_reranker(cfg), NoMatchRule(cfg))

    def run(self, query: str, top_k: int, flt: Filter) -> PipelineResult:
        hits = self.retriever.retrieve(query, self.cfg.retrieval.candidate_k, flt)

        decision = self.rule.decide(self.cfg.retrieval.strategy, hits)
        if not decision.matched:
            return PipelineResult([], False, decision.reason)

        pool = hits[:self.cfg.rerank.candidates]
        method = self.cfg.rerank.method
        try:
            ranked = self.reranker.rerank(query, pool)
            status, error = "ok", None
        except Exception as err:       # a reranker must never fail the search
            ranked = [(hit, None) for hit in pool]
            status, error = "failed", f"{type(err).__name__}: {str(err)[:300]}"
        if status == "ok" and self.reranker.limits_output:
            ranked = ranked[:self.cfg.rerank.top_n]
        ranked = ranked[:top_k]

        final = []
        for position, (hit, score) in enumerate(ranked, start=1):
            info = {"method": method, "position": position, "score": score, "status": status, "error": error}
            final.append(replace(hit.with_provenance(rerank=info), score=score if score is not None else hit.score))
        return PipelineResult(final, True, "", "ok" if status == "ok" else f"failed: {error}")
