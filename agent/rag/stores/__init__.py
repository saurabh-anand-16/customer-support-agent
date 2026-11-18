"""
stores: the swappable "keep vectors and find the nearest" parts. Importing this package
registers them; `get_store(cfg)` returns the one named in [store].kind.
"""
from .. import registry
from ..config import RagConfig
from . import chroma, memory   # noqa: F401  (importing registers the stores; chromadb itself loads only when one is opened)
from .base import Match, Record, Store


def get_store(cfg: RagConfig, path=None) -> Store:
    """The store for cfg.store.kind. `path` overrides [store].path (tests use a temporary folder)."""
    return registry.get("store", cfg.store.kind)(cfg, path)
