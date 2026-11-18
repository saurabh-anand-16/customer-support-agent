"""
policy_search.py - the front door to policy search: PolicySearch.search_policy(...).

It returns one fixed shape, whichever retriever, fuser and reranker the profile uses:

  {"ok": True, "query": ..., "profile": ..., "index_fingerprint": ...,
   "results": [{"source_file", "heading_path", "text", "score", "copied_on", "in_scope", "provenance"}, ...]}
  blank query            -> ok False, error_code "empty_query"
  index of other settings -> ok False, error_code "index_out_of_date" (the old index is never searched)
  nothing counts as an answer (no-match rule) -> ok True, results [], and a "note"; the caller must
                           then say the policy pages do not cover this, or escalate. It never guesses.

Policy search gives explanations and citations only. It never works out eligibility, windows or
refund times, and it does not read order data.

Every setting comes from config/rag.toml and the chosen profile (argument, RAG_PROFILE, or the
file's default). Retrieval by BM25 alone needs no index and no extra package; the vector and
hybrid strategies need the index built by scripts/06_build_policy_index.py and refuse a stale one.
"""
from .rag.chunkers import chunk_documents
from .rag.config import RagConfig, load_config
from .rag.embedders import get_embedder
from .rag.filters import Filter
from .rag.index import index_status
from .rag.ingest import load_documents
from .rag.pipeline import Pipeline
from .rag.retrievers import uses_index
from .rag.stores import get_store


def format_citation(cfg: RagConfig, result: dict) -> str:
    """A short citation for one result, laid out by [citations] in the config."""
    c = cfg.citations
    text = c.format.format(heading_path=result["heading_path"], source_file=result["source_file"],
                           copied_on=result["copied_on"])
    return text + c.copied_on_suffix.format(copied_on=result["copied_on"]) if c.show_copied_on else text


class PolicySearch:
    def __init__(self, profile: str | None = None, cfg: RagConfig | None = None, config_path=None,
                 store=None, embedder=None, reranker=None, chunks=None):
        """
        profile / config_path choose the settings (or pass a ready `cfg`). `store`, `embedder`,
        `reranker` and `chunks` are made from the config when not given; tests give fakes.
        """
        self.cfg = cfg or load_config(profile, path=config_path)
        self._store, self._embedder, self._reranker, self._chunks = store, embedder, reranker, chunks
        self._pipeline: Pipeline | None = None

    # -- helpers ---------------------------------------------------------------------------
    def _base(self, query: str, fingerprint: str) -> dict:
        return {"ok": True, "query": query, "profile": self.cfg.profile, "index_fingerprint": fingerprint,
                "results": []}

    def _get_pipeline(self) -> Pipeline:
        if self._pipeline is None:
            if self._chunks is None:
                self._chunks = chunk_documents(self.cfg, load_documents(self.cfg))
            self._pipeline = Pipeline.build(self.cfg, self._chunks, self._store, self._embedder, self._reranker)
        return self._pipeline

    def citation(self, result: dict) -> str:
        return format_citation(self.cfg, result)

    # -- the front door --------------------------------------------------------------------
    def search_policy(self, query, top_k=None, include_out_of_scope=False) -> dict:
        text = query.strip() if isinstance(query, str) else ""
        fingerprint = self.cfg.fingerprint       # BM25 is built from the current settings, so it is never stale
        if not text:
            return {**self._base("", fingerprint), "ok": False, "error_code": "empty_query",
                    "error": "The question is empty."}

        if uses_index(self.cfg):
            if self._store is None:
                self._store = get_store(self.cfg)
            status, message = index_status(self.cfg, self._store)
            fingerprint = self._store.get_meta().get("fingerprint") or fingerprint
            if status != "ok":
                return {**self._base(text, fingerprint), "ok": False, "error_code": "index_out_of_date",
                        "error": message}
            if self._embedder is None:
                self._embedder = get_embedder(self.cfg)

        try:
            k = max(1, int(top_k)) if top_k is not None else self.cfg.retrieval.top_k
        except (TypeError, ValueError):
            k = self.cfg.retrieval.top_k
        outcome = self._get_pipeline().run(text, k, Filter.from_config(self.cfg, bool(include_out_of_scope)))

        result = self._base(text, fingerprint)
        if not outcome.matched:
            result["note"] = self.cfg.no_match.note
        else:
            result["results"] = [hit.to_result() for hit in outcome.hits]
        return result
