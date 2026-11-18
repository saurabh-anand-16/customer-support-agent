"""
heading.py - split a page at its headings, then split long sections into parts.

Rules:
  - A new section starts at each heading of a configured level.
  - A section that fits in max_chars is one chunk.
  - A heading is never emitted alone when its section has body text: the first part holds the
    heading and the start of the body.
  - merge_empty_headings: a heading with no body of its own, directly followed by another
    heading, is folded into the first chunk of the next section.
  - A block too long for the room left is cut at the best boundary that fits, tried in order:
      1. between list items (a nested sub-list stays with its parent item)
      2. between any two lines
      3. after a sentence end
      4. at a space (last resort)
    So a list item is cut mid-sentence only if the item itself does not fit.
  - Tables: with table_handling "keep_whole" a table is never cut (a long one becomes one
    oversize chunk); with "split_rows" a long table is cut between rows and the header row
    is repeated on every part. A row is never cut in half.
  - Later parts of a section start with the section's heading line again if
    include_heading_in_text is on, so each chunk says what it is about.
  - overlap_chars > 0 starts each later part with the tail of the part before it.
"""
import re
from collections import deque

from ..registry import register
from .base import Chunker, parse_sections, slugify

_TABLE_SEPARATOR = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _is_table(block: str) -> bool:
    return all(line.lstrip().startswith("|") for line in block.split("\n") if line.strip())


def split_blocks(text: str) -> list[str]:
    """Paragraph-sized blocks. A blank line ends a block, and so does the edge of a table."""
    blocks, current = [], []
    for line in text.split("\n"):
        if not line.strip():
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        if current and line.lstrip().startswith("|") != current[-1].lstrip().startswith("|"):
            blocks.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


# Boundaries for cutting a long block, best first. Each pattern matches the gap to cut at.
_BOUNDARIES = [
    re.compile(r"\n(?=\S)"),             # 1. start of the next top-level list item or line
    re.compile(r"\n"),                   # 2. any line break (inside a nested sub-list)
    re.compile(r"(?<=[.!?])[ \t]+(?=\S)"),   # 3. after a sentence end
    re.compile(r" +"),                   # 4. any space
]


def _cut(block: str, limit: int) -> tuple[str, str]:
    """Split text into (head of at most `limit` characters, rest) at the best boundary."""
    for pattern in _BOUNDARIES:
        best = None
        for m in pattern.finditer(block):
            if m.start() > limit:
                break
            if m.start() > 0:
                best = m
        if best:
            return block[:best.start()].rstrip(), block[best.end():]
    return block[:limit], block[limit:]      # no boundary at all: one very long word


def _cut_table(block: str, limit: int) -> tuple[str, str]:
    """Split a table between rows. The header (and separator) row is repeated at the top of `rest`."""
    lines = block.split("\n")
    n_header = 2 if len(lines) > 1 and _TABLE_SEPARATOR.match(lines[1]) else 0
    header, rows = lines[:n_header], lines[n_header:]
    taken, size = list(header), len("\n".join(header))
    for i, row in enumerate(rows):
        added = size + (1 if taken else 0) + len(row)
        if i > 0 and added > limit:
            break
        taken.append(row)             # the first row is always taken, so every part makes progress
        size = added
    left = rows[len(taken) - n_header:]
    return "\n".join(taken), ("\n".join(header + left) if left else "")


def _tail(text: str, overlap: int) -> str:
    """The last `overlap` characters of `text`, starting at a word boundary."""
    tail = text[-overlap:]
    if len(text) > overlap and " " in tail:
        tail = tail.split(" ", 1)[1]
    return tail.strip()


@register("chunker", "heading")
class HeadingChunker(Chunker):
    def chunk(self, doc):
        c = self.cfg.chunking
        chunks, used_slugs = [], {}
        carried: list[str] = []      # heading lines with no body yet, waiting to join the next section
        sections = [s for s in parse_sections(doc.text, c.heading_levels) if doc.text[s.start:s.end].strip()]
        for position, section in enumerate(sections):
            text = doc.text[section.start:section.end]
            heading = section.heading_line
            body = text.split("\n", 1)[1] if heading and "\n" in text else ("" if heading else text)
            is_last = position == len(sections) - 1
            if heading and not body.strip() and c.merge_empty_headings and not is_last:
                carried.append(heading)
                continue
            slug = slugify(section.path[-1] if section.path else "intro")
            used_slugs[slug] = used_slugs.get(slug, 0) + 1
            if used_slugs[slug] > 1:                  # same heading twice on one page
                slug = f"{slug}-{used_slugs[slug]}"
            parts = self._split_section(body, heading, carried)
            carried = []
            for index, part in enumerate(parts):
                chunk_id = f"{doc.source_file.removesuffix('.md')}#{slug}-p{index}"
                chunks.append(self.make_chunk(doc, chunk_id, section.path, section.level, index, part))
        return chunks

    def _split_section(self, body: str, heading_line: str, carried: list[str]) -> list[str]:
        c = self.cfg.chunking
        split_rows = c.table_handling == "split_rows"
        repeat = heading_line if (c.include_heading_in_text and heading_line) else ""
        parts: list[str] = []
        elements: list[str] = []   # pieces of the part being built, joined by blank lines
        blocks_in_part = 0         # how many of them are body blocks
        previous_body = ""

        def start_part():
            nonlocal elements, blocks_in_part
            if parts:
                elements = [repeat] if repeat else []
                lead = _tail(previous_body, c.overlap_chars) if c.overlap_chars else ""
                if lead:
                    elements.append(lead)
            else:
                elements = carried + ([heading_line] if heading_line else [])
            blocks_in_part = 0

        def size():
            return sum(len(e) for e in elements) + 2 * max(len(elements) - 1, 0)

        def flush():
            nonlocal previous_body
            previous_body = "\n\n".join(elements[len(elements) - blocks_in_part:])
            parts.append("\n\n".join(elements))
            start_part()

        start_part()
        queue = deque(split_blocks(body))
        while queue:
            block = queue.popleft()
            gap = 2 if elements else 0
            if blocks_in_part and size() + gap + len(block) > c.max_chars:
                flush()
                queue.appendleft(block)
                continue
            room = c.max_chars - size() - gap
            if blocks_in_part == 0 and len(block) > room:
                if not _is_table(block):
                    head, rest = _cut(block, max(room, 1))
                elif split_rows:
                    head, rest = _cut_table(block, room)
                else:
                    head, rest = block, ""        # keep_whole: the table stays in one piece
                if rest:
                    queue.appendleft(rest)
                block = head
            elements.append(block)
            blocks_in_part += 1
        if blocks_in_part or not parts:
            parts.append("\n\n".join(elements))
        return parts
