"""
base.py - the embedder contract, and the small helper that reads the API key.

Contract: an embedder turns a list of texts into a list of vectors, in the same order.
  embed(texts)        -> one vector per text, in order (batching is done here)
  embed_query(text)   -> one vector for a search query ([embedding].query_prefix is put in front)
  name                -> "<provider>:<model>", used in cache keys and index records
  dimension           -> length of a vector
  embedded_count      -> how many texts have really been sent to the model (not counting cache hits)
Which provider and model run comes from [embedding] in config/rag.toml; nothing here names one.
"""
import math
import os
from pathlib import Path

from ..config import RagConfig


class EmbedderError(RuntimeError):
    """An embedder could not do its job. The message never contains the API key."""


class MissingDependencyError(EmbedderError):
    """A package needed by this provider is not installed (see requirements-rag.txt)."""


class MissingKeyError(EmbedderError):
    """The API key was not found in the environment or the env file."""


# --- the API key --------------------------------------------------------------------------
def read_secret(name: str, env_file: str | Path | None = None) -> str | None:
    """
    Find the value of `name`: the environment first, then the env file (lines like NAME=value).
    A small loader of our own instead of python-dotenv: this is all we need, and it adds no
    package. It does not copy anything into os.environ, and the value is never printed or stored.
    """
    if os.environ.get(name):
        return os.environ[name]
    if not env_file or not Path(env_file).is_file():
        return None
    for line in Path(env_file).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        if key == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value or None
    return None


def scrub(message: str, secret: str | None) -> str:
    """Remove the secret from a message before it is shown or logged."""
    return message.replace(secret, "[key hidden]") if secret else message


# --- the contract -------------------------------------------------------------------------
class Embedder:
    """Base class. Subclasses set `provider` (via the registry) and implement `_embed_batch`."""

    def __init__(self, cfg: RagConfig):
        self.cfg = cfg
        self._sent = 0              # texts sent to the model so far
        self._dimension: int | None = None

    # -- to implement
    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    # -- provided
    @property
    def name(self) -> str:
        e = self.cfg.embedding
        return f"{e.provider}:{e.model}"

    @property
    def embedded_count(self) -> int:
        return self._sent

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._dimension = len(self.embed(["dimension check"])[0])
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Vectors for `texts`, in the same order. Sent to the model `batch_size` texts at a time."""
        size = self.cfg.embedding.batch_size
        out: list[list[float]] = []
        for start in range(0, len(texts), size):
            batch = texts[start:start + size]
            vectors = self._embed_batch(batch)
            if len(vectors) != len(batch):
                raise EmbedderError(f"{self.name} returned {len(vectors)} vectors for {len(batch)} texts")
            self._sent += len(batch)
            out.extend(_unit(v) if self.cfg.embedding.normalize else [float(x) for x in v] for v in vectors)
        if out:
            self._check_dimensions(out)
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed([self.cfg.embedding.query_prefix + text])[0]

    def _check_dimensions(self, vectors: list[list[float]]) -> None:
        sizes = {len(v) for v in vectors}
        wanted = self.cfg.embedding.dimensions
        if len(sizes) != 1 or (wanted and sizes != {wanted}) or (self._dimension and sizes != {self._dimension}):
            raise EmbedderError(
                f"{self.name} gave vectors of size {sorted(sizes)}, expected {wanted or self._dimension or 'one size'}")
        self._dimension = sizes.pop()


def _unit(vector) -> list[float]:
    """Scale a vector to length 1 (a zero vector is returned unchanged)."""
    values = [float(x) for x in vector]
    norm = math.sqrt(sum(x * x for x in values))
    return [x / norm for x in values] if norm else values
