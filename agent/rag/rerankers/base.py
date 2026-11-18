"""
base.py - the reranker contract.

A reranker takes the question and the fused hits (best guess first) and returns them as
(hit, score) pairs in a new order. The score is None when the reranker gives none (method
"none"). It may raise RerankerError; the pipeline then keeps the fused order and records the
failure in each hit's provenance, so a reranker can never make a search fail.
`limits_output` is False for a reranker that only passes hits through, so [rerank].top_n does
not cut its output.
"""
from ..config import RagConfig
from ..types import Hit


class RerankerError(RuntimeError):
    """A reranker could not do its job. The message never contains an API key."""


class Reranker:
    name = ""
    limits_output = True

    def __init__(self, cfg: RagConfig, **backend):
        self.cfg = cfg

    def rerank(self, query: str, hits: list[Hit]) -> list[tuple[Hit, float | None]]:
        raise NotImplementedError
