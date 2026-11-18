"""
retrievers: the swappable "question -> ranked chunks" parts. Importing this package registers
them; `get_retriever(cfg, ...)` returns the one named in [retrieval].strategy.
"""
from .. import registry
from ..config import RagConfig
from . import bm25, hybrid, vector   # noqa: F401  (importing registers them; no heavy package is loaded)
from .base import Retriever


def get_retriever(cfg: RagConfig, chunks, store=None, embedder=None, **parts) -> Retriever:
    return registry.get("retriever", cfg.retrieval.strategy)(cfg, chunks, store, embedder, **parts)


def uses_index(cfg: RagConfig) -> bool:
    """Whether the configured strategy reads the vector index."""
    return registry.get("retriever", cfg.retrieval.strategy).uses_index
