"""
types.py - the plain data objects passed between stages.

Document: one policy page, after table-of-contents lines are removed.
Chunk:    one piece of a page, with the metadata that search and citations need.
Hit:      one search result: a chunk plus its score and the history of how it was found.
"""
from dataclasses import dataclass, field, fields, replace


@dataclass(frozen=True)
class Document:
    source_file: str    # file name, e.g. "refund-policy.md"
    page_title: str     # the page's "# " heading
    text: str           # page text with table-of-contents lines removed, nothing else changed
    copied_on: str      # date the page was copied, read from policy/README.md
    in_scope: bool      # False for pages on cases the agent does not handle
    page_type: str      # the README section the page is listed under


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_file: str
    page_title: str
    heading_path: str       # headings joined with the configured separator
    heading_level: int
    part_index: int         # 0 for the first piece of a section
    text: str
    char_count: int
    copied_on: str
    in_scope: bool
    page_type: str

    def to_row(self, field_names: list[str]) -> dict:
        """The chunk as a dict holding only the configured metadata fields, in that order."""
        return {name: getattr(self, name) for name in field_names}


CHUNK_FIELDS = [f.name for f in fields(Chunk)]


def new_provenance() -> dict:
    """The record of how a hit was found. Each stage fills in its part."""
    return {
        "retrievers": {},     # name -> {"rank": 1-based rank in that retriever's list, "score": its score}
        "fusion": None,       # name of the fuser, if the hit was merged from several lists
        "fused_score": None,
        "rerank": None,       # {"method", "position" (1-based, after reranking), "score", "status", "error"}
    }


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    source_file: str
    page_title: str
    heading_path: str
    text: str
    copied_on: str
    in_scope: bool
    page_type: str
    score: float                                   # the score of the last stage that scored it
    provenance: dict = field(default_factory=new_provenance)

    @classmethod
    def from_chunk(cls, chunk: "Chunk", score: float, provenance: dict) -> "Hit":
        return cls(chunk.chunk_id, chunk.source_file, chunk.page_title, chunk.heading_path, chunk.text,
                   chunk.copied_on, chunk.in_scope, chunk.page_type, score, provenance)

    def with_provenance(self, **changes) -> "Hit":
        """A copy with some provenance keys replaced (the original is not changed)."""
        return replace(self, provenance={**self.provenance, **changes})

    def to_result(self) -> dict:
        """The fixed per-result shape returned by search_policy."""
        return {
            "source_file": self.source_file,
            "heading_path": self.heading_path,
            "text": self.text,
            "score": round(self.score, 6),
            "copied_on": self.copied_on,
            "in_scope": self.in_scope,
            "provenance": {"chunk_id": self.chunk_id, **self.provenance},
        }
