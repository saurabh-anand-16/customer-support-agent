"""
embedders: the swappable "text -> vector" parts. Importing this package registers them;
`get_embedder(cfg)` returns the one named in [embedding].provider, wrapped in the on-disk
cache unless [embedding].cache_path is empty.
"""
from .. import registry
from ..config import RagConfig
from . import local, openai   # noqa: F401  (importing registers the embedders; no heavy package is loaded)
from .base import Embedder, EmbedderError, MissingDependencyError, MissingKeyError, read_secret
from .cache import CachedEmbedder


def get_embedder(cfg: RagConfig, use_cache: bool = True, **backend):
    """
    The embedder for cfg.embedding.provider. `backend` is passed to its constructor
    (tests give a fake `client=` or `model=`). The cache file is [embedding].cache_path
    relative to the project root.
    """
    embedder = registry.get("embedder", cfg.embedding.provider)(cfg, **backend)
    if use_cache and cfg.embedding.cache_path:
        return CachedEmbedder(embedder, cfg.root / cfg.embedding.cache_path)
    return embedder
