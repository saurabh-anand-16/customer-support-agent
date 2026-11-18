"""
rerankers: the swappable "put the best passages first" parts. Importing this package registers
them (no heavy package is loaded); `get_reranker(cfg)` returns the one named in [rerank].method.
"""
from .. import registry
from ..config import RagConfig
from . import cross_encoder, llm, none   # noqa: F401
from .base import Reranker, RerankerError


def get_reranker(cfg: RagConfig, **backend) -> Reranker:
    """`backend` is passed to the reranker (tests give a fake `model=` or `client=`)."""
    return registry.get("reranker", cfg.rerank.method)(cfg, **backend)
