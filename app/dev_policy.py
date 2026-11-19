"""
dev_policy.py - the Policy explorer tab of the Developer page (phase 11), as plain functions with no Streamlit calls.

It shows what the agent can read. Sources, all read as data and never changed: the chunk export (data/clean/policy_chunks.csv, or
[chunking].export_path of config/rag.toml), the scope settings of config/rag.toml ([sources].out_of_scope_files and [[scope.rules]]) and the
file names in the policy folder. There is no search box: a search would call an embedding model, and these pages never call a model.
A field the files lack is "not recorded".
"""
from app.dev_common import NOT_RECORDED, badge, empty_box, lines, table, text_or_missing
from app.trace_view import esc

COMMAND = "python scripts/05_chunk_policy.py"
NOTE = "This page shows what the agent can read. It is a copy of Amazon.in pages, with some sections hidden by our decision."


def _parse_bool(value):
    return {"true": True, "false": False}.get(str(value).strip().lower())


def _parse_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def scope_settings(config) -> dict:
    """{"out_of_scope_files": [...], "rules": [{"file", "heading", "reason"}], "exclude_files": [...], "export_path", "policy_dir"} from config/rag.toml."""
    config = config if isinstance(config, dict) else {}
    sources = config.get("sources") if isinstance(config.get("sources"), dict) else {}
    chunking = config.get("chunking") if isinstance(config.get("chunking"), dict) else {}
    scope = config.get("scope") if isinstance(config.get("scope"), dict) else {}
    rules = [r for r in scope.get("rules", []) if isinstance(r, dict)] if isinstance(scope.get("rules"), list) else []
    return {"out_of_scope_files": list(sources.get("out_of_scope_files") or []), "rules": rules,
            "exclude_files": list(sources.get("exclude_files") or []), "policy_dir": sources.get("policy_dir"),
            "export_path": chunking.get("export_path") or (config.get("metadata") or {}).get("export_path")}


def empty_state_html(state: str) -> str:
    why = {"missing": "The chunk export is not there.", "empty": "The chunk export is empty.", "broken": "The chunk export could not be read."}.get(state, "")
    return empty_box("No policy export", f"{why} Create it with: {COMMAND}. This page never rebuilds it.")


def sources_html(found: dict) -> str:
    """found: {label: (path text, exists)}. Says which source files are in the repo."""
    rows = [[esc(label), f'<span class="nw">{esc(path)}</span>', "found" if ok else "not found"] for label, (path, ok) in found.items()]
    return table(["Source", "File", "State"], rows)


def pages(rows: list, settings: dict, policy_files: list) -> list:
    """One entry per page: every page of the export, plus any policy page file that is not in the export (0 chunks). Sorted by file name."""
    by_file = {}
    for r in rows:
        by_file.setdefault(r.get("source_file") or NOT_RECORDED, []).append(r)
    skip = set(settings["exclude_files"])
    for name in policy_files:
        if name not in skip:
            by_file.setdefault(name, [])
    out_pages = set(settings["out_of_scope_files"])
    result = []
    for name in sorted(by_file):
        chunks = by_file[name]
        first = chunks[0] if chunks else {}
        hidden = [r for r in settings["rules"] if r.get("file") == name]
        flags = [_parse_bool(c.get("in_scope")) for c in chunks]
        if name in out_pages:
            status, reason = "out", "the page is listed in [sources].out_of_scope_files of config/rag.toml (our decision, not Amazon's)"
        elif hidden or False in flags:
            status = "partial"
            reason = "; ".join(f"hidden section \"{r.get('heading')}\": {r.get('reason') or NOT_RECORDED}" for r in hidden) or "some sections are marked out of scope"
        else:
            status, reason = "in", None
        result.append({"file": name, "title": first.get("page_title") or None, "type": first.get("page_type") or None, "chunks": len(chunks),
                       "hidden": sum(1 for f in flags if f is False), "copied_on": first.get("copied_on") or None, "status": status, "reason": reason,
                       "in_export": bool(chunks)})
    return result


STATUS_TEXT = {"in": ("In scope", "badge-approved"), "partial": ("In scope, some sections hidden", "badge-busy"), "out": ("Out of scope", "badge-declined")}


def pages_html(items: list) -> str:
    if not items:
        return f'<div class="muted">Pages: {NOT_RECORDED}</div>'
    rows = []
    for p in items:
        word, cls = STATUS_TEXT[p["status"]]
        chunks = esc(p["chunks"]) if p["in_export"] else "0 (not in the export)"
        reason = esc(p["reason"]) if p["reason"] else ""
        rows.append([f'<span class="nw">{esc(p["file"])}</span>', text_or_missing(p["title"]), text_or_missing(p["type"]), chunks, badge(word, cls) + (f"<div class=\"muted\">{reason}</div>" if reason else "")])
    return table(["File", "Page title", "Page type", "Chunks", "Scope"], rows)


def copy_date_html(items: list) -> str:
    dates = sorted({p["copied_on"] for p in items if p["copied_on"]})
    text = ", ".join(dates) if dates else NOT_RECORDED
    return f'<div class="muted">Copied from Amazon.in on: {esc(text)}.</div>'


def chunk_rows(rows: list, file: str) -> list:
    return [r for r in rows if r.get("source_file") == file]


def chunk_scope(chunk: dict, page: dict) -> tuple:
    """(in scope True/False/None, reason text) for one chunk. The reason is the one recorded on the chunk, else the page's reason for an out-of-scope page."""
    flag = _parse_bool(chunk.get("in_scope"))
    if flag is not False:
        return flag, None
    return flag, chunk.get("scope_reason") or (page["reason"] if page and page["status"] == "out" else NOT_RECORDED)


def chunks_html(chunks: list, page: dict) -> str:
    """The chunk table (heading path, size, scope, reason) and each chunk's text in a collapsed block."""
    if not chunks:
        return empty_box("No chunks for this page", "The page is not in the chunk export. " + f"Create the export with: {COMMAND}.")
    head_rows, blocks = [], []
    for i, c in enumerate(chunks, 1):
        flag, reason = chunk_scope(c, page)
        size = _parse_int(c.get("char_count"))
        scope = {True: badge("in scope", "badge-approved"), False: badge("out of scope", "badge-declined"), None: NOT_RECORDED}[flag]
        path = text_or_missing(c.get("heading_path"))
        head_rows.append([str(i), path, esc(f"{size:,}") if size is not None else NOT_RECORDED, scope, esc(reason) if reason else ""])
        blocks.append(f'<details class="passage"><summary>{i}. {path}</summary><div class="dev-text">{text_or_missing(c.get("text"))}</div></details>')
    return table(["#", "Heading path", "Size (characters)", "Scope", "Reason"], head_rows) + '<div class="detail-h">Chunk text</div>' + "".join(blocks)


def notes_html_box() -> str:
    return '<div class="note-box"><b>About this page</b>' + _notes() + "</div>"


def _notes() -> str:
    return lines([NOTE, "There is no search box here: a search would call an embedding model, and these pages never call a model.",
                  "Which sections are hidden is our decision (config/rag.toml); the category-to-policy mapping is also ours, not Amazon's."])
