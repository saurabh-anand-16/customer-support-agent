"""
base.py - the chunker contract and helpers shared by the chunkers.

Contract: a chunker is built with the config and has `chunk(document) -> list[Chunk]`.
For the same document and config it must always return the same chunks in the same order.
"""
import re
from dataclasses import dataclass

from ..config import RagConfig
from ..types import Chunk, Document


class Chunker:
    """Base class. Subclasses implement `chunk`."""

    def __init__(self, cfg: RagConfig):
        self.cfg = cfg

    def chunk(self, doc: Document) -> list[Chunk]:
        raise NotImplementedError

    def make_chunk(self, doc: Document, chunk_id: str, path: list[str], level: int,
                   part_index: int, text: str) -> Chunk:
        """Build a Chunk, filling the page-level metadata from the document."""
        return Chunk(
            chunk_id=chunk_id,
            source_file=doc.source_file,
            page_title=doc.page_title,
            heading_path=self.cfg.metadata.heading_path_separator.join(path),
            heading_level=level,
            part_index=part_index,
            text=text,
            char_count=len(text),
            copied_on=doc.copied_on,
            in_scope=doc.in_scope,
            page_type=doc.page_type,
        )


@dataclass(frozen=True)
class Section:
    start: int          # offset in the page text where the section's heading line begins
    end: int            # offset where the next section begins (or the end of the text)
    level: int          # number of "#" in the heading; 0 for text before the first heading
    path: list[str]     # headings from the page title down to this one
    heading_line: str   # the heading as written, e.g. "## Refund Timelines"


def parse_sections(text: str, heading_levels: list[int]) -> list[Section]:
    """
    Split page text at headings of the configured levels. The sections cover the whole text,
    one after another. Lines inside ``` code fences are never treated as headings.
    """
    starts = []   # (offset, level, heading text, heading line)
    offset, in_fence = 0, False
    for line in text.split("\n"):
        if line.startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else re.match(r"(#{1,6}) +(.*?)\s*$", line)
        if match and len(match.group(1)) in heading_levels:
            starts.append((offset, len(match.group(1)), match.group(2), line))
        offset += len(line) + 1

    if not starts or starts[0][0] > 0:
        starts.insert(0, (0, 0, "", ""))   # text before the first heading

    sections, stack = [], []   # stack holds (level, heading text) of the headings above
    for i, (pos, level, title, line) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if level > 0:
            stack.append((level, title))
        sections.append(Section(pos, end, level, [t for _, t in stack], line))
    return sections


def slugify(text: str) -> str:
    """Lowercase, with runs of non-letters/digits turned into single hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
