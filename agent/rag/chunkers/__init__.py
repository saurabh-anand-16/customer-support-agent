"""
chunkers: the swappable "split a page into chunks" parts. Importing this package registers
them; `get_chunker(cfg)` returns the one named in [chunking].strategy.
"""
from .. import registry
from ..config import RagConfig
from . import fixed, heading   # noqa: F401  (importing registers the chunkers)
from .base import Chunker


def get_chunker(cfg: RagConfig) -> Chunker:
    return registry.get("chunker", cfg.chunking.strategy)(cfg)


def chunk_documents(cfg: RagConfig, docs) -> list:
    """All chunks for all pages, using the configured strategy."""
    chunker = get_chunker(cfg)
    return [c for doc in docs for c in chunker.chunk(doc)]
