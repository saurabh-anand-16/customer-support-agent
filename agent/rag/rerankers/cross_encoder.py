"""
cross_encoder.py - reorders hits with a cross-encoder model that reads the question and each
passage together (method "cross_encoder").

The model name is [rerank].cross_encoder_model. The `sentence_transformers` package is optional
(see requirements-rag.txt) and is imported only when the first search is reranked; the model is
downloaded on first use. For tests, pass a `model` with a `.predict(pairs)` method.
"""
from ..embedders.base import MissingDependencyError
from ..registry import register
from .base import Reranker


@register("reranker", "cross_encoder")
class CrossEncoderReranker(Reranker):
    name = "cross_encoder"

    def __init__(self, cfg, model=None, **backend):
        super().__init__(cfg)
        self._model = model

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as err:
                raise MissingDependencyError(
                    "The 'sentence-transformers' package is not installed (see requirements-rag.txt), "
                    "so the cross-encoder reranker cannot run") from err
            self._model = CrossEncoder(self.cfg.rerank.cross_encoder_model)
        return self._model

    def rerank(self, query, hits):
        if not hits:
            return []
        scores = [float(s) for s in self._get_model().predict([[query, hit.text] for hit in hits])]
        if len(scores) != len(hits):
            raise ValueError(f"the model gave {len(scores)} scores for {len(hits)} passages")
        order = sorted(range(len(hits)), key=lambda i: (-scores[i], i))      # ties keep the fused order
        return [(hits[i], scores[i]) for i in order]
