"""
fixed.py - cut the page into equal-size windows, ignoring headings.

It exists as a baseline so phase 3d can measure whether heading-aware chunking is better.
Windows are max_chars long and each starts (max_chars - overlap_chars) after the one before.
Each chunk still gets the heading path of the section where its window begins.
"""
from ..registry import register
from .base import Chunker, parse_sections


@register("chunker", "fixed")
class FixedChunker(Chunker):
    def chunk(self, doc):
        c = self.cfg.chunking
        sections = parse_sections(doc.text, c.heading_levels)
        step = c.max_chars - c.overlap_chars
        chunks, start, index = [], 0, 0
        stem = doc.source_file.removesuffix(".md")
        while start < len(doc.text):
            text = doc.text[start:start + c.max_chars]
            if text.strip():
                section = next(s for s in sections if s.start <= start < s.end)
                chunks.append(self.make_chunk(
                    doc, f"{stem}#fixed-{index}", section.path, section.level, index, text))
                index += 1
            if start + c.max_chars >= len(doc.text):
                break
            start += step
        return chunks
