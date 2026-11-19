"""
limits_view.py - the Limits and assumptions page (phase 13, part B), as plain functions with no Streamlit calls.

Two sources, both read-only: app/assumptions.toml (the entries of kind "our decision", each with its value read live from its config source;
see app/dev_assumptions.py) and app/limits.toml (the known gaps). A count in a known gap is read from data/evals/summary.json through the
entry's `summary_key`; the text never holds a number. A missing file is an empty state, and a missing field shows "not recorded".
"""
from pathlib import Path

from app import dev_assumptions
from app.dev_common import NOT_RECORDED, empty_box, get, pct
from app.trace_view import esc

OPENING = "This is a demonstration built on public policy pages and made-up data. It is not Amazon's system and it does not speak for Amazon."
HOW_TO_READ = ("An item on this page is something we chose or know is unfinished. It is not a hidden fault. "
               "Our decisions are listed with the value the code uses now, read from the file that holds it.")
MAX_LIMITS = 5


def limits(content) -> list:
    """The known gaps of app/limits.toml: dicts only, at most MAX_LIMITS."""
    items = content.get("limit") if isinstance(content, dict) else None
    return [e for e in items if isinstance(e, dict)][:MAX_LIMITS] if isinstance(items, list) else []


def our_decisions(content) -> list:
    return [e for e in dev_assumptions.entries(content) if e.get("kind") == "our decision"]


def _lookup(summary, key: str | None):
    """The value at a dotted path of the summary, or None. "{chosen}" is the chosen search profile."""
    if not key or not isinstance(summary, dict):
        return None
    chosen = get(summary, "retrieval", "chosen_profile")
    if "{chosen}" in key and not isinstance(chosen, str):
        return None
    return get(summary, *key.replace("{chosen}", chosen or "").split("."))


def count_text(entry: dict, summary) -> str | None:
    """"76 of 83 (91.6%)" for an entry with a summary_key, "not recorded" when the summary lacks it, None for an entry with no key."""
    if not entry.get("summary_key"):
        return None
    part, whole = _lookup(summary, entry.get("summary_key")), _lookup(summary, entry.get("summary_total_key"))
    return pct(part, whole)


def empty_state_html(what: str, state: str) -> str:
    why = {"missing": "is not there", "empty": "is empty", "broken": "could not be read"}.get(state, "could not be read")
    return empty_box(f"No {what}", f"The file {why}.")


def limit_html(entry: dict, summary) -> str:
    count = count_text(entry, summary)
    value = ""
    if count is not None:
        label = entry.get("summary_label")
        value = f'<div class="limit-value">{esc(label) + ": " if label else ""}{esc(count)}</div>'
    return (f'<div class="limit-item"><div class="limit-title">{esc(entry.get("title") or NOT_RECORDED)}</div>'
            f'<div class="limit-text">{esc(entry.get("text") or NOT_RECORDED)}</div>{value}</div>')


def limits_html(content, summary) -> str:
    items = limits(content)
    return "".join(limit_html(e, summary) for e in items)


def decisions_html(content, root: Path) -> str:
    return "".join(dev_assumptions.entry_html(e, root) for e in our_decisions(content))
