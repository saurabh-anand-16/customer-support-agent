"""
local.py - embeddings computed on this computer with sentence-transformers (provider "local").

The model name comes from [embedding].model. The `sentence_transformers` package is optional
(see requirements-rag.txt) and is imported only when the first text is embedded. The model is
downloaded on first use. For tests, pass a `model` that has an `.encode(texts)` method.
"""
from ..registry import register
from .base import Embedder, MissingDependencyError


@register("embedder", "local")
class LocalEmbedder(Embedder):
    def __init__(self, cfg, model=None):
        super().__init__(cfg)
        self._model = model

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as err:
                raise MissingDependencyError(
                    "The 'sentence-transformers' package is not installed. "
                    "Install it (see requirements-rag.txt) or set provider = \"openai\" in config/rag.toml") from err
            self._model = SentenceTransformer(self.cfg.embedding.model)
        return self._model

    def _embed_batch(self, texts):
        encoded = self._get_model().encode(texts)
        return [[float(x) for x in row] for row in encoded]
