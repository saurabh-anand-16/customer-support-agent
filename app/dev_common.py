"""
dev_common.py - small pieces shared by the four read-only Developer tabs of phase 11 (Evaluation, Tests, Policy explorer, Assumptions).

Plain functions, no Streamlit calls. Text goes through `esc` before it is put inside HTML. A value the source file lacks is "not recorded".
"""
from app.trace_view import esc

NOT_RECORDED = "not recorded"


def is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def num(value) -> str:
    """An integer with thousands separators; a float as it is; anything else "not recorded"."""
    if is_int(value):
        return f"{value:,}"
    return f"{value}" if is_num(value) else NOT_RECORDED


def pct(part, whole) -> str:
    """"46 of 76 (60.5%)": the count first, then the percentage. "not recorded" when either number is missing; no percentage for a zero whole."""
    if not (is_int(part) and is_int(whole)):
        return NOT_RECORDED
    if whole == 0:
        return f"{part:,} of 0"
    return f"{part:,} of {whole:,} ({part / whole * 100:.1f}%)"


def get(d, *keys):
    """d[k1][k2]... or None when a step is missing or not a dict."""
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def text_or_missing(value) -> str:
    return esc(value) if value not in (None, "") else NOT_RECORDED


def table(head: list, rows: list, caption: str | None = None) -> str:
    """A table in the page's table style. Cells are HTML that the caller already escaped."""
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    cap = f'<div class="muted">{esc(caption)}</div>' if caption else ""
    return f'<div class="dev-scroll"><table class="dev-table"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>{cap}'


def empty_box(title: str, body: str) -> str:
    return f'<div class="empty-box"><div class="empty-title">{esc(title)}</div>{esc(body)}</div>'


def box(title: str, body_html: str) -> str:
    return f'<div class="note-box"><b>{esc(title)}</b>{body_html}</div>'


def badge(text: str, kind: str = "") -> str:
    return f'<span class="badge {kind}">{esc(text)}</span>'


def heading(text: str) -> str:
    return f'<div class="detail-h">{esc(text)}</div>'


def lines(items: list) -> str:
    """A bulleted list; items are plain text."""
    return '<ul class="dev-list">' + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"
