"""
types.py - the plain data objects passed between stages.

Document: one policy page, after table-of-contents lines are removed.
Chunk:    one piece of a page, with the metadata that search and citations need.
(A `Hit` class for search results is added in phase 3c.)
"""
from dataclasses import dataclass, fields


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
