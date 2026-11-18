"""
openai.py - embeddings from the OpenAI API (provider "openai").

The model name comes from [embedding].model. The key is read with read_secret() from the
environment variable named in [embedding].api_key_env, or from the env file. The key is used
only to build the client: it is never printed, logged or written anywhere, and error messages
have it removed. The `openai` package is imported only when a request is made.

For tests, pass a `client` that has the same `.embeddings.create(...)` method.
"""
from ..registry import register
from .base import Embedder, EmbedderError, MissingDependencyError, MissingKeyError, read_secret, scrub


@register("embedder", "openai")
class OpenAIEmbedder(Embedder):
    def __init__(self, cfg, client=None):
        super().__init__(cfg)
        self._client = client
        self._key: str | None = None

    def _get_client(self):
        if self._client is None:
            e = self.cfg.embedding
            self._key = read_secret(e.api_key_env, self.cfg.root / e.env_file)
            if not self._key:
                raise MissingKeyError(
                    f"No API key: set {e.api_key_env} in the environment or in {e.env_file}")
            try:
                import openai
            except ImportError as err:
                raise MissingDependencyError(
                    "The 'openai' package is not installed: pip install -r requirements-rag.txt") from err
            self._client = openai.OpenAI(api_key=self._key)
        return self._client

    def _embed_batch(self, texts):
        e = self.cfg.embedding
        request = {"model": e.model, "input": texts}
        if e.dimensions > 0:
            request["dimensions"] = e.dimensions
        client = self._get_client()
        try:
            response = client.embeddings.create(**request)
        except Exception as err:   # report the kind of failure, never the key
            raise EmbedderError(
                f"OpenAI embedding request failed ({type(err).__name__}): {scrub(str(err), self._key)}") from None
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
