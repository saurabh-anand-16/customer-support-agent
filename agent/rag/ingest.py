"""
ingest.py - find and read the policy pages.

For each page it:
  - removes the table-of-contents lines (the label and the list of "#anchor" links);
    everything else stays exactly as Amazon wrote it
  - takes the page title from the first "# " heading
  - reads the copy date and the page type (the README section) from policy/README.md
  - marks the page in scope or not, from the out-of-scope list in the config
All patterns and file names come from config/rag.toml.
"""
import re
from pathlib import Path

from .config import RagConfig
from .types import Document


def remove_toc(text: str, cfg: RagConfig) -> str:
    """Drop the contents label and its link list; optionally collapse the blank lines left behind."""
    t = cfg.text
    if not t.remove_toc:
        return text
    item = re.compile(t.toc_item_pattern)
    kept = [line for line in text.split("\n")
            if line.strip() != t.toc_label and not item.match(line)]
    result = "\n".join(kept)
    if t.collapse_blank_lines:
        result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def read_readme(cfg: RagConfig, policy_dir: Path) -> tuple[str, dict[str, str]]:
    """Return (copy date, {file name: page type}) from the policy README."""
    s = cfg.sources
    text = (policy_dir / s.readme_file).read_text(encoding="utf-8")
    match = re.search(s.copy_date_pattern, text)
    if not match:
        raise ValueError(f"No copy date found in {s.readme_file} (pattern: {s.copy_date_pattern})")
    heading_prefix = "#" * s.page_type_heading_level + " "
    page_types: dict[str, str] = {}
    current = None
    for line in text.split("\n"):
        if line.startswith(heading_prefix):
            current = line[len(heading_prefix):].strip()
        elif current and line.startswith("|"):
            link = re.search(r"\]\(([^)#]+\.md)\)", line)
            if link:
                page_types[link.group(1)] = current
    return match.group(1), page_types


def load_documents(cfg: RagConfig) -> list[Document]:
    """Read every policy page named by [sources], in file-name order."""
    s = cfg.sources
    policy_dir = cfg.root / s.policy_dir
    copied_on, page_types = read_readme(cfg, policy_dir)
    docs = []
    for path in sorted(policy_dir.glob(s.include_glob)):
        if path.name in s.exclude_files:
            continue
        if path.name not in page_types:
            raise ValueError(f"{path.name} is not listed under a section in {s.readme_file}")
        text = remove_toc(path.read_text(encoding="utf-8"), cfg)
        title = next((ln[2:].strip() for ln in text.split("\n") if ln.startswith("# ")), path.stem)
        docs.append(Document(
            source_file=path.name,
            page_title=title,
            text=text,
            copied_on=copied_on,
            in_scope=path.name not in s.out_of_scope_files,
            page_type=page_types[path.name],
        ))
    return docs
