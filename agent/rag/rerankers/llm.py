"""
llm.py - reorders hits by asking an OpenAI chat model how well each passage answers the question
(method "llm").

The model is [rerank].llm_model (no model name is written here). It is asked for one score from
0 to 10 per passage, as JSON. The key is read the same way as for embeddings: the variable named
in [embedding].api_key_env, then the env file [embedding].env_file. The key is used only to build
the client and is removed from any error message. For tests, pass a `client` with the same
`.chat.completions.create(...)` method as the OpenAI client.
"""
import json

from ..embedders.base import MissingDependencyError, MissingKeyError, read_secret, scrub
from ..registry import register
from .base import Reranker, RerankerError

_INSTRUCTIONS = (
    "You rate how well passages from a returns and refunds help page answer a customer question. "
    "Give each passage a score from 0 (irrelevant) to 10 (answers the question directly). "
    "Use only the passage text. Reply with JSON only, with one entry for every passage id: "
    "{\"scores\": [{\"id\": 0, \"score\": 7}, {\"id\": 1, \"score\": 2}, ...]}."
)


@register("reranker", "llm")
class LlmReranker(Reranker):
    name = "llm"

    def __init__(self, cfg, client=None, **backend):
        super().__init__(cfg)
        self._client = client
        self._key: str | None = None

    def _get_client(self):
        if self._client is None:
            e = self.cfg.embedding
            self._key = read_secret(e.api_key_env, self.cfg.root / e.env_file)
            if not self._key:
                raise MissingKeyError(f"No API key: set {e.api_key_env} in the environment or in {e.env_file}")
            try:
                import openai
            except ImportError as err:
                raise MissingDependencyError(
                    "The 'openai' package is not installed: pip install -r requirements-rag.txt") from err
            self._client = openai.OpenAI(api_key=self._key)
        return self._client

    def rerank(self, query, hits):
        if not hits:
            return []
        r = self.cfg.rerank
        passages = "\n\n".join(f"[{i}] {hit.text[:r.llm_max_chars]}" for i, hit in enumerate(hits))
        messages = [{"role": "system", "content": _INSTRUCTIONS},
                    {"role": "user", "content": f"Question: {query}\n\nThere are {len(hits)} passages, "
                                                f"with ids 0 to {len(hits) - 1}.\n\nPassages:\n{passages}"}]
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=r.llm_model, messages=messages, temperature=0, response_format={"type": "json_object"})
            rated = {int(item["id"]): float(item["score"])
                     for item in json.loads(response.choices[0].message.content)["scores"]}
        except (MissingKeyError, MissingDependencyError):
            raise                      # these messages name the variable or package, never the key
        except Exception as err:   # the kind of failure, never the key
            raise RerankerError(f"LLM rerank failed ({type(err).__name__}): {scrub(str(err), self._key)}") from None
        if set(rated) != set(range(len(hits))):
            raise RerankerError(f"LLM rerank rated {len(rated)} of {len(hits)} passages (ids {sorted(set(range(len(hits))) - set(rated))} missing)")
        scores = [rated[i] for i in range(len(hits))]
        order = sorted(range(len(hits)), key=lambda i: (-scores[i], i))      # ties keep the fused order
        return [(hits[i], scores[i]) for i in order]
