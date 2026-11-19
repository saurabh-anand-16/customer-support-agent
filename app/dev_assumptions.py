"""
dev_assumptions.py - the Assumptions tab of the Developer page (phase 11), as plain functions with no Streamlit calls.

The list is app/assumptions.toml. Each entry names a `source`: "path" or "path#key" under the project folder. The value shown on the page is
READ LIVE from that source (a key of a .toml file, a fact of data/clean/policy_facts.csv, the row count of a .csv, or the fact that a file exists).
It is never typed into the text. A source that cannot be found shows "source not found".
"""
from pathlib import Path

from app import data
from app.dev_common import NOT_RECORDED, badge, empty_box, text_or_missing
from app.trace_view import esc

KINDS = ["our decision", "policy gap", "data", "evaluation"]
NOT_FOUND = "source not found"


def empty_state_html(state: str) -> str:
    why = {"missing": "app/assumptions.toml is not there.", "empty": "app/assumptions.toml is empty.", "broken": "app/assumptions.toml could not be read."}.get(state, "")
    return empty_box("No assumptions list", why)


def entries(content) -> list:
    """The entries of the file: a list of dicts. Anything that is not a table is left out."""
    items = content.get("assumption") if isinstance(content, dict) else None
    return [e for e in items if isinstance(e, dict)] if isinstance(items, list) else []


def sources_of(entry: dict) -> list:
    src = entry.get("source")
    if isinstance(src, str):
        return [src] if src.strip() else []
    return [s for s in src if isinstance(s, str) and s.strip()] if isinstance(src, list) else []


def _show(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) if value else "(empty list)"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _under_root(root: Path, relative: str) -> Path | None:
    """The file a source names, only when it is inside the project folder (a path that climbs out of it is not found)."""
    try:
        path = (Path(root) / relative).resolve()
        path.relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return None
    return path if path.is_file() else None


def resolve(source: str, root: Path) -> tuple:
    """(found, text): the live value of one source. found is False when the file or the key does not exist."""
    name, _, key = source.partition("#")
    path = _under_root(root, name.strip())
    if path is None:
        return False, NOT_FOUND
    key = key.strip()
    suffix = path.suffix.lower()
    if not key:
        if suffix == ".csv":
            rows, state = data.read_file(path, "csv")
            return (True, f"{len(rows):,} rows") if state == "ok" else (True, "file exists")
        return True, "file exists"
    if suffix in (".toml", ".json"):
        content, state = data.read_file(path, "toml" if suffix == ".toml" else "json")
        if state != "ok":
            return False, NOT_FOUND
        for part in key.split("."):
            if not isinstance(content, dict) or part not in content:
                return False, NOT_FOUND
            content = content[part]
        return True, f"{key} = {_show(content)}"
    if suffix == ".csv":
        rows, state = data.read_file(path, "csv")
        if state != "ok":
            return False, NOT_FOUND
        row = next((r for r in rows if r.get("fact_key") == key), None)
        if row is None:
            return False, NOT_FOUND
        value, unit = (row.get("fact_value") or "").strip(), (row.get("unit") or "").strip()
        return True, f"{key} = " + (f"{value}{' ' + unit if unit else ''}" if value else "blank in the file (no value is stated)")
    return False, NOT_FOUND


def resolve_entry(entry: dict, root: Path) -> list:
    """[(source text, found, value text)] for every source of an entry; an entry with no source gives one unresolved line."""
    srcs = sources_of(entry)
    if not srcs:
        return [("", False, NOT_FOUND)]
    return [(s, *resolve(s, root)) for s in srcs]


def unresolved(items: list, root: Path) -> list:
    """The ids of entries with at least one source that cannot be found."""
    return [e.get("id") for e in items if not all(found for _, found, _ in resolve_entry(e, root))]


def entry_html(entry: dict, root: Path) -> str:
    lines = []
    for source, found, value in resolve_entry(entry, root):
        if found:
            lines.append(f'<div class="kv"><div class="k">Value now</div><div class="v">{esc(value)}</div></div>'
                         f'<div class="kv"><div class="k">Source</div><div class="v"><span class="nw">{esc(source)}</span></div></div>')
        else:
            lines.append(f'<div class="kv"><div class="k">Value now</div><div class="v">{badge(NOT_FOUND, "badge-declined")}</div></div>'
                         f'<div class="kv"><div class="k">Source</div><div class="v"><span class="nw">{text_or_missing(source)}</span></div></div>')
    return (f'<div class="assumption"><div class="assumption-title">{text_or_missing(entry.get("title"))}</div>'
            f'<div class="assumption-text">{text_or_missing(entry.get("text"))}</div>{"".join(lines)}</div>')


def grouped(items: list) -> list:
    """[(kind, [entries])] in the order of KINDS, then any other kind the file uses, then entries with no kind."""
    kinds = list(KINDS) + [k for k in dict.fromkeys(e.get("kind") for e in items) if k not in KINDS and k]
    out = [(k, [e for e in items if e.get("kind") == k]) for k in kinds]
    out = [(k, es) for k, es in out if es]
    rest = [e for e in items if not e.get("kind")]
    return out + ([(NOT_RECORDED, rest)] if rest else [])
