"""
filters.py - which chunks a search may return.

Two rules, applied before ranking so a filtered-out chunk never takes a place in the results:
  in_scope    unless the caller asks for out-of-scope pages (include_out_of_scope=True), only
              chunks from in-scope pages are searched
  page_type   if [retrieval].page_types lists any README sections, only those are searched
"""
from dataclasses import dataclass

from .config import RagConfig


@dataclass(frozen=True)
class Filter:
    in_scope_only: bool = True
    page_types: tuple = ()

    @classmethod
    def from_config(cls, cfg: RagConfig, include_out_of_scope: bool = False) -> "Filter":
        return cls(in_scope_only=not include_out_of_scope, page_types=tuple(cfg.retrieval.page_types))

    def allows(self, item) -> bool:
        """True if a chunk or hit (anything with .in_scope and .page_type) may be returned."""
        if self.in_scope_only and not item.in_scope:
            return False
        return not self.page_types or item.page_type in self.page_types

    def where(self) -> dict:
        """The part of the filter a store can apply itself (equality only); page types are applied afterwards."""
        return {"in_scope": True} if self.in_scope_only else {}
