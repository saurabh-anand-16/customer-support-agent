"""
trace_view.py - the pieces of the Developer trace page (phase 9), as plain functions with no Streamlit calls.

Every value comes from a turn record of the trace file (agent/tracing.py). Nothing is worked out here that the record does not
hold, and nothing is invented: a field the record lacks is shown as "not recorded" (a turn written before phase 6c has no model calls,
no tool timing and no versions) and a price that is not set is shown as "not priced". Text from a customer, a model or a tool goes
through `esc` before it is put inside HTML.
"""
import base64
import html

from . import router_path

NOT_RECORDED = "not recorded"
NOT_PRICED = "not priced"
NOT_CAPTURED = "[not captured]"
TOOL_KINDS = ("tool_call", "retrieval", "write")


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pretty(code) -> str:
    return str(code).replace("_", " ") if code is not None else ""


# -- formatting ---------------------------------------------------------------------------------------------------------
def fmt_ms(ms) -> str:
    if not isinstance(ms, (int, float)) or isinstance(ms, bool):
        return NOT_RECORDED
    if ms >= 1000:
        return f"{ms / 1000:.1f} s"
    return f"{ms:.1f} ms" if ms < 10 else f"{ms:.0f} ms"


def fmt_score(score) -> str:
    return f"{score:.3f}".rstrip("0").rstrip(".") if isinstance(score, (int, float)) and not isinstance(score, bool) else NOT_RECORDED


def fmt_int(n) -> str:
    return f"{n:,}" if isinstance(n, int) and not isinstance(n, bool) else NOT_RECORDED


def fmt_cost(cost) -> str:
    """US dollars, or "not priced" when the record holds no cost (the price table in config/agent.toml has no price for the model)."""
    if not isinstance(cost, (int, float)) or isinstance(cost, bool):
        return NOT_PRICED
    return f"${cost:.4f}" if cost >= 0.0001 or cost == 0 else f"${cost:.6f}"


def has_detail(rec: dict) -> bool:
    """True for a record written by phase 6c or later (it has the model calls and the timeline)."""
    return isinstance(rec.get("model_calls"), list) and isinstance(rec.get("timeline"), list)


def text_captured(rec: dict) -> bool:
    return rec.get("capture_text") is not False


def shown_text(rec: dict, key: str) -> str:
    """The customer's message or the agent's reply as the record holds it. With capture_text off that is "[not captured]" and the length."""
    value = rec.get(key)
    if not text_captured(rec) or value == NOT_CAPTURED:
        n = rec.get(f"{key}_chars")
        return f"{NOT_CAPTURED} · {n} characters" if isinstance(n, int) else NOT_CAPTURED
    return str(value) if isinstance(value, str) else NOT_RECORDED


def route_text(rec: dict) -> str:
    route = rec.get("route") or {}
    label = route.get("router_label")
    return pretty(label) + (f" / {pretty(route['kind'])}" if route.get("kind") else "") if label else NOT_RECORDED


# -- the list and its totals ----------------------------------------------------------------------------------------------
def session_totals(turns: list) -> dict:
    """Totals over `turns`: how many, tokens in and out (only turns that recorded them), the cost, and how many turns pre-date phase 6c."""
    old = [t for t in turns if not has_detail(t)]
    new = [t for t in turns if has_detail(t)]
    costs = [t.get("total_cost_usd") for t in new]
    priced = [c for c in costs if isinstance(c, (int, float))]
    state = "none" if not new else "priced" if len(priced) == len(new) else "not_priced"
    return {"turns": len(turns), "input_tokens": sum(t.get("total_input_tokens") or 0 for t in new), "output_tokens": sum(t.get("total_output_tokens") or 0 for t in new),
            "cost": round(sum(priced), 8) if state == "priced" else None, "cost_state": state, "old_turns": len(old)}


def totals_line(totals: dict) -> str:
    parts = [f"{totals['turns']} turn{'' if totals['turns'] == 1 else 's'}"]
    if totals["turns"] == totals["old_turns"]:
        parts.append("no tokens or cost recorded (written before the richer trace)")
    else:
        parts.append(f"{fmt_int(totals['input_tokens'])} tokens in, {fmt_int(totals['output_tokens'])} out")
        parts.append(f"cost {fmt_cost(totals['cost'])}")
        if totals["old_turns"]:
            parts.append(f"{totals['old_turns']} older turn{'' if totals['old_turns'] == 1 else 's'} without usage")
    return " · ".join(parts)


def number_of(turns_newest_first: list, index: int) -> int:
    """The message number of the turn at `index` of a newest-first list: the oldest is 1."""
    return len(turns_newest_first) - index


# -- tables ---------------------------------------------------------------------------------------------------------------
def _table(head: list, rows: list, caption: str | None = None) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    cap = f'<div class="muted">{esc(caption)}</div>' if caption else ""
    return f'<div class="dev-scroll"><table class="dev-table"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>{cap}'


def model_calls_html(rec: dict) -> str:
    if not has_detail(rec):
        return f'<div class="muted">{NOT_RECORDED}: this turn was written before the richer trace.</div>'
    calls = rec["model_calls"]
    if not calls:
        return '<div class="muted">No model was called in this turn.</div>'
    rows = []
    for c in calls:
        status = "" if c.get("status") == "ok" else f' <span class="badge badge-declined">{esc(c.get("status"))}</span>'
        rows.append([f'<span class="nw">{esc(pretty(c.get("kind")))}</span>{status}', esc(c.get("model") or NOT_RECORDED), esc(fmt_int(c.get("input_tokens"))),
                     esc(fmt_int(c.get("output_tokens"))), esc(fmt_ms(c.get("latency_ms"))), esc(fmt_cost(c.get("cost_usd")))])
    rows.append(["<b>Total</b>", "", f'<b>{esc(fmt_int(rec.get("total_input_tokens")))}</b>', f'<b>{esc(fmt_int(rec.get("total_output_tokens")))}</b>', "",
                 f'<b>{esc(fmt_cost(rec.get("total_cost_usd")))}</b>'])
    note = ""
    if not rec.get("cost_complete", True):
        note = '<div class="muted">Prices are set in config/agent.toml, under [pricing]. A call with no price (or no usage) has no cost, and so has the total.</div>'
    if rec.get("usage_complete") is False:
        note += '<div class="muted">Some calls reported no token counts, so the token totals may be low.</div>'
    return _table(["Call", "Model used", "Tokens in", "Tokens out", "Time", "Cost"], rows) + note


def _ordered_tool_steps(rec: dict) -> list:
    steps = [(i, s) for i, s in enumerate(rec.get("steps") or []) if s.get("kind") in TOOL_KINDS]
    return [s for _, s in sorted(steps, key=lambda p: (p[1].get("seq") is None, p[1].get("seq") or 0, p[0]))]


def tool_calls_html(rec: dict) -> str:
    steps = _ordered_tool_steps(rec)
    if not steps:
        return '<div class="muted">No tool was called in this turn.</div>'
    hide_text = not text_captured(rec)
    rows = []
    for s in steps:
        out = s.get("output")
        if hide_text and s.get("kind") == "retrieval":         # a search result repeats the customer's words
            out = "not shown (message text is not captured)"
        time_text = fmt_ms(s.get("duration_ms")) if has_detail(rec) else NOT_RECORDED
        if s.get("kind") == "write":
            time_text = fmt_ms(s.get("duration_ms")) if s.get("duration_ms") is not None else "not timed"
        order = esc(s.get("seq")) if s.get("seq") is not None else ""
        rows.append([f'<span class="nw">{order}</span>', f'<span class="nw"><code>{esc(s.get("name"))}</code></span>' + (' <span class="badge">writes</span>' if s.get("kind") == "write" else ""),
                     esc(s.get("input") or ""), esc(out or ""), esc(time_text), esc(pretty(s.get("status")))])
    return _table(["#", "Tool", "Input", "Result", "Time", "Status"], rows,
                  "In the order the calls ran. The customer id is added by the app from the session; it is never one of the model's inputs.")


# -- policy passages --------------------------------------------------------------------------------------------------------
def _cited(rec: dict, source, heading) -> bool | None:
    for p in rec.get("passages") or []:
        if p.get("source_file") == source and (_heading(p.get("heading_path")) == _heading(heading)):
            return bool(p.get("cited"))
    return None


def _heading(path) -> str:
    return " > ".join(str(x) for x in path) if isinstance(path, (list, tuple)) else str(path or "")


def passages_html(rec: dict) -> str | None:
    """None when no policy search ran in this turn (the section is left out)."""
    searches, passages = rec.get("search") or [], rec.get("passages") or []
    if not searches and not passages and not rec.get("index_fingerprint"):
        return None
    out = []
    capture = text_captured(rec)
    for found in searches:
        rows = [("Profile", found.get("profile")), ("Strategy", found.get("strategy")), ("Policy index", found.get("index_fingerprint") or rec.get("index_fingerprint"))]
        if capture and found.get("query") is not None:
            if found.get("original_query") is not None and found.get("rewritten"):
                rows += [("Original question", found.get("original_query")), ("Rewritten question", found.get("query"))]
            else:
                rows.append(("Question searched", found.get("query")))
        elif not capture:
            rows.append(("Question searched", f"{NOT_CAPTURED} · {found.get('query_chars')} characters" if found.get("query_chars") is not None else NOT_CAPTURED))
        out.append("".join(f'<div class="kv"><span class="k">{esc(k)}</span><span class="v">{esc(v if v not in (None, "") else NOT_RECORDED)}</span></div>' for k, v in rows))
        if found.get("ok") is False:
            out.append(f'<div class="muted">The search failed: {esc(pretty(found.get("error_code")))}.</div>')
        elif found.get("no_match_fired"):
            out.append('<div class="amber-box"><b>No match.</b>The no-match rule fired: nothing in the policy pages counted as an answer, so the agent said so.</div>')
        limits = found.get("no_match_thresholds")
        if isinstance(limits, dict):
            line = ", ".join(f"{k} {v}" for k, v in limits.items() if k != "note")
            out.append(f'<div class="muted">No-match thresholds applied: {esc(line)}.</div>')
        results = found.get("results") or []
        if results:
            rows_ = []
            for r in results:
                cited = _cited(rec, r.get("source_file"), r.get("heading_path"))
                rows_.append([esc(r.get("rank")), f'{esc(r.get("source_file"))} › {esc(_heading(r.get("heading_path")))}', f'<span class="nw">{esc(fmt_score(r.get("score")))}</span>',
                              "yes" if r.get("in_scope", True) else "no", "yes" if cited else ("no" if cited is False else NOT_RECORDED)])
            out.append(_table(["#", "Page › section", "Score", "In scope", "Cited"], rows_))
    if not searches and passages:       # an older record: the passages are known, their scores are not
        rows_ = [[esc(p.get("number")), f'{esc(p.get("source_file"))} › {esc(_heading(p.get("heading_path")))}', NOT_RECORDED, "yes" if p.get("cited") else "no"] for p in passages]
        out.append(f'<div class="kv"><span class="k">Policy index</span><span class="v">{esc(rec.get("index_fingerprint") or NOT_RECORDED)}</span></div>')
        out.append(_table(["#", "Page › section", "Score", "Cited"], rows_))
    return "".join(out)


# -- the answer check ---------------------------------------------------------------------------------------------------------
def answer_check_html(rec: dict) -> str:
    if not has_detail(rec):
        return f'<div class="muted">{NOT_RECORDED}: this turn was written before the richer trace.</div>'
    detail = rec.get("answer_check")
    if not detail:
        return '<div class="muted">The answer check did not run: no model-written answer needed checking in this turn.</div>'
    out = [f'<div class="muted">{len(detail.get("attempts") or [])} attempt(s) · retried: {"yes" if detail.get("retried") else "no"} · '
           f'plain fallback used: {"yes" if detail.get("fallback_used") else "no"}</div>']
    for a in detail.get("attempts") or []:
        verdict = "passed" if a.get("passed") else "did not pass"
        counts = ", ".join(f"{a.get(k + '_found', 0)} {label} ({a.get(k + '_unsupported', 0)} not backed)" for k, label in (("numbers", "numbers"), ("dates", "dates"), ("files", "file names")))
        out.append(f'<div class="check-line"><b>{esc(pretty(a.get("attempt")))}</b> {esc(verdict)}: {esc(counts)}</div>')
        for kind in ("numbers", "dates", "files"):
            values = a.get(kind)
            if isinstance(values, list) and values:
                out.append('<div class="muted">' + ", ".join(f'{esc(v.get("text"))} ({"backed" if v.get("supported") else "not backed"})' for v in values) + "</div>")
    if not text_captured(rec):
        out.append('<div class="muted">The values read from the reply are not shown because message text is not captured.</div>')
    return "".join(out)


# -- versions and checks ------------------------------------------------------------------------------------------------------
def versions_html(rec: dict) -> str:
    v = rec.get("versions") if isinstance(rec.get("versions"), dict) else None
    if v is None:
        return f'<div class="muted">{NOT_RECORDED}: this turn was written before the richer trace.</div>'
    rows = [("Code version", f"git commit {v.get('git_commit')}" if v.get("git_commit") else None), ("Settings version", f"config hash {v.get('config_hash')}" if v.get("config_hash") else None),
            ("Prompt version", f"prompt hash {v.get('prompt_hash')}" if v.get("prompt_hash") else None), ("Policy index", v.get("index_fingerprint") or "no policy search in this turn"),
            ("Retries", rec.get("retry_count"))]
    errors = rec.get("errors") or []
    rows.append(("Errors", "none" if not errors else "; ".join(f"{e.get('where')}: {pretty(e.get('type'))}, {e.get('message')}" for e in errors)))
    return "".join(f'<div class="kv"><span class="k">{esc(k)}</span><span class="v">{esc(val if val not in (None, "") else NOT_RECORDED)}</span></div>' for k, val in rows)


def check_status(check: dict) -> str:
    """'blocked' for a check that held a write back by design, 'pass' or 'fail' otherwise. A blocked check is never counted as a failure."""
    if check.get("status") == "blocked_by_design":
        return "blocked"
    return "pass" if check.get("passed") else "fail"


STATUS_WORD = {"blocked": "Blocked by design", "pass": "Pass", "fail": "Fail"}
STATUS_CLASS = {"blocked": "badge", "pass": "badge-approved", "fail": "badge-declined"}


def checks_html(rec: dict) -> str:
    checks = [c for c in rec.get("checks") or [] if isinstance(c, dict)]
    if not checks:
        return '<div class="muted">No safety check ran in this turn.</div>'
    rows = []
    for c in checks:
        s = check_status(c)
        rows.append(f'<div class="check-row"><span class="badge {STATUS_CLASS[s]}">{STATUS_WORD[s]}</span> <b>{esc(pretty(c.get("name")))}</b> <span class="muted">{esc(c.get("reason"))}</span></div>')
    return "".join(rows)


def failed_check_count(rec: dict) -> int:
    return sum(1 for c in rec.get("checks") or [] if isinstance(c, dict) and check_status(c) == "fail")


# -- the conversation of a turn ------------------------------------------------------------------------------------------------
def bubble_html(side: str, who: str, text: str) -> str:
    """A chat bubble: side 'user' (blue, right) or 'agent' (green, left)."""
    return f'<div class="dev-row dev-{side}"><div class="dev-bubble dev-bubble-{side}"><div class="who">{esc(who)}</div><div class="plain-text">{esc(text)}</div></div></div>'


def turn_conversation_html(rec: dict) -> str:
    return bubble_html("user", f"Customer · {rec.get('customer_id') or NOT_RECORDED}", shown_text(rec, "message")) + bubble_html("agent", "Agent", shown_text(rec, "reply"))


def list_item_html(rec: dict, number: int, selected: bool) -> str:
    """One turn in the list: the two bubbles, then the route and the time."""
    duration = fmt_ms(rec.get("duration_ms"))
    return (f'<div class="dev-turn{" dev-turn-selected" if selected else ""}">' + bubble_html("user", "Customer", shown_text(rec, "message")) +
            bubble_html("agent", "Agent", shown_text(rec, "reply")) + f'<div class="muted dev-meta">Message {number} · {esc(route_text(rec))} · {esc(duration)}</div></div>')


def path_html(rec: dict) -> str:
    """The drawing as an image whose source is the SVG itself (a data address): Streamlit's HTML cleaner removes inline <svg>, and keeps this."""
    route = (rec.get("route") or {}).get("router_label")
    svg = router_path.path_svg(route)
    said = router_path.taken(route)
    alt = f"Path through the agent: {said} was taken." if said else "Path through the agent: the route is not recognised."
    source = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return (f'<img class="path-img" alt="{esc(alt)}" src="{source}"/>'
            f'<div class="muted">Route taken: <b>{esc(said or NOT_RECORDED)}</b>. The green line is the path this message took. Dashed grey lines were possible but not taken.</div>')
