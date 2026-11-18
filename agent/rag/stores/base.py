"""
base.py - the vector store contract.

A store keeps chunks as (id, vector, text, metadata) and finds the ones nearest to a query vector.
  add(records)                   insert or replace by id (never creates duplicates)
  delete(ids)                    remove ids; ids that are not there are ignored
  ids() / count()                what is stored
  query(vector, k, where=None)   up to k nearest records, best first; `where` is {field: value, ...}
                                 and means all of them must be equal
  get_meta() / set_meta(dict)    small facts about the index as a whole (the fingerprint, ...)
  reset()                        remove everything, including the meta

Score: higher is better. For "cosine" and "ip" it is the similarity; for "l2" it is minus the
squared distance. Metadata values must be text, whole numbers, decimals or true/false.
"""
from dataclasses import dataclass, field

from ..config import RagConfig


@dataclass(frozen=True)
class Record:
    chunk_id: str
    vector: list[float]
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Match:
    chunk_id: str
    score: float
    text: str
    metadata: dict


class Store:
    """Base class. The settings come from [store] in config/rag.toml."""

    def __init__(self, cfg: RagConfig, path=None):
        self.cfg = cfg
        # `path` lets tests point a store at a temporary folder; normally it is [store].path
        self.path = path if path is not None else cfg.root / cfg.store.path

    def add(self, records: list[Record]) -> None:
        raise NotImplementedError

    def delete(self, ids: list[str]) -> None:
        raise NotImplementedError

    def ids(self) -> list[str]:
        raise NotImplementedError

    def count(self) -> int:
        return len(self.ids())

    def query(self, vector: list[float], k: int, where: dict | None = None) -> list[Match]:
        raise NotImplementedError

    def get_meta(self) -> dict:
        raise NotImplementedError

    def set_meta(self, meta: dict) -> None:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError
