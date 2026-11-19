"""
dev_eval.py - the Evaluation tab of the Developer page (phase 11), as plain functions with no Streamlit calls.

Source: data/evals/summary.json (written by scripts/20_write_summary.py; this module only reads what is given to it). Every number comes
from that file: nothing is computed here except a percentage next to a count. A field the file lacks is "not recorded". A cost is shown
only when the file holds one. Router messages and expected routes come from data/evals/router_messages.csv (repo data, not customer data).
"""
from app.dev_common import NOT_RECORDED, badge, empty_box, get, heading, lines, num, pct, table, text_or_missing
from app.trace_view import esc

SUMMARY_COMMAND = "python scripts/20_write_summary.py"

HOW_TO_READ = [
    ("hit@1, hit@3, hit@5", "For a question the policy pages answer, did the right page and section come back first (hit@1), in the first three (hit@3) "
                            "or in the first five (hit@5)? Counts are of the answerable questions."),
    ("MRR", "Mean reciprocal rank. 1 means the right passage is always first; lower means it comes further down."),
    ("No match", "Some questions the pages do not answer (off-topic ones, for example). Search should return nothing for them. "
                 "\"No-match correct\" counts the rows where search did the right thing."),
    ("Router", "The router picks one route for each message. The number is how many of the reviewed messages got the route we expected."),
    ("Scenarios", "Whole conversations run through the real agent on a copy of the database. Each has an expected decision from the eligibility code."),
]
KEY_NOTE = "The answer keys are ours, reviewed by one person, on synthetic data. The numbers come from small sets and are a guide, not a guarantee."


def how_to_read_html() -> str:
    items = "".join(f"<li><b>{esc(t)}.</b> {esc(d)}</li>" for t, d in HOW_TO_READ)
    return f'<div class="note-box"><b>How to read this</b><ul class="dev-list">{items}</ul><div>{esc(KEY_NOTE)}</div></div>'


def empty_state_html(state: str) -> str:
    why = {"missing": "The summary file is not there.", "empty": "The summary file is empty.", "broken": "The summary file could not be read."}.get(state, "")
    return empty_box("No evaluation summary", f"{why} Create it with: {SUMMARY_COMMAND}")


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def header_html(summary: dict) -> str:
    return f'<div class="muted">Summary written {text_or_missing(summary.get("date"))} from commit {text_or_missing(summary.get("git_commit"))}.</div>'


def reviewed_html(summary: dict) -> str:
    rows = []
    for key, label in (("retrieval_questions", "Retrieval questions (policy search)"), ("router_messages", "Router messages")):
        block = get(summary, "reviewed_rows", key)
        rows.append([esc(label), esc(num(get(block, "reviewed"))), esc(num(get(block, "not_reviewed")))])
    return table(["Answer key", "Reviewed", "Not reviewed"], rows)


# -- search ---------------------------------------------------------------------------------------------------------------
def search_settings_html(summary: dict) -> str:
    r = _dict(summary.get("retrieval"))
    th = _dict(r.get("thresholds"))
    rows = [["Chosen profile", text_or_missing(r.get("chosen_profile"))],
            ["Embedding model", text_or_missing(r.get("embedding_model"))],
            ["Chunk size (characters)", esc(num(r.get("chunk_max_chars")))],
            ["Vector threshold", text_or_missing(th.get("vector_min_score"))],
            ["Keyword (BM25) threshold", text_or_missing(th.get("bm25_min_score"))],
            ["Hybrid needs", text_or_missing(th.get("hybrid_require"))]]
    return table(["Setting", "Value"], rows)


def profiles_html(summary: dict) -> str:
    r = _dict(summary.get("retrieval"))
    profiles = _dict(r.get("profiles"))
    chosen = r.get("chosen_profile")
    if not profiles:
        return f'<div class="muted">Profiles: {NOT_RECORDED}</div>'
    rows = []
    for name, p in profiles.items():
        p = _dict(p)
        mark = " " + badge("default", "badge-approved") if name == chosen else ""
        ans, tot, mrr = p.get("answerable_rows"), p.get("rows"), p.get("mrr")
        rows.append([f"<b>{esc(name)}</b>{mark}", esc(num(tot)), esc(pct(p.get("hit_at_1"), ans)), esc(pct(p.get("hit_at_3"), ans)),
                     esc(pct(p.get("hit_at_5"), ans)), esc(mrr if mrr is not None else NOT_RECORDED), esc(pct(p.get("no_match_ok"), tot))])
    return table(["Profile", "Rows", "Hit@1", "Hit@3", "Hit@5", "MRR", "No-match correct"], rows,
                 "Hit counts are of the answerable questions; no-match correct is of all rows.")


def category_html(summary: dict) -> str:
    r = _dict(summary.get("retrieval"))
    chosen = r.get("chosen_profile")
    cats = get(r, "profiles", chosen, "by_category")
    if not isinstance(cats, dict) or not cats:
        return f'<div class="muted">By category: {NOT_RECORDED}</div>'
    rows = []
    for name, c in cats.items():
        c = _dict(c)
        ans, tot = c.get("answerable"), c.get("rows")
        if ans == 0:                                          # a category with no answerable question has no hits to count
            hits = ["no answerable rows"] * 3
        else:
            hits = [pct(c.get("hit1"), ans), pct(c.get("hit3"), ans), pct(c.get("hit5"), ans)]
        rows.append([esc(name), esc(num(tot)), esc(num(ans))] + [esc(h) for h in hits] + [esc(pct(c.get("nomatch_ok"), tot))])
    return table(["Category", "Rows", "Answerable", "Hit@1", "Hit@3", "Hit@5", "No-match correct"], rows,
                 f"Profile: {chosen}. Hit counts are of the answerable rows of the category.")


def skipped_html(summary: dict) -> str:
    skipped = get(summary, "retrieval", "skipped")
    if skipped is None:
        return f'<div class="muted">Skipped profiles: {NOT_RECORDED}</div>'
    if not isinstance(skipped, dict) or not skipped:
        return '<div class="muted">No profile was skipped.</div>'
    return table(["Skipped profile", "Reason"], [[esc(k), esc(v)] for k, v in skipped.items()])


# -- router ---------------------------------------------------------------------------------------------------------------
def router_lookup(rows) -> dict:
    """{id: (message, expected_route)} from the rows of data/evals/router_messages.csv."""
    return {r.get("id"): (r.get("message"), r.get("expected_route")) for r in rows or [] if r.get("id")}


def _id_list(title: str, ids, lookup: dict) -> str:
    if not isinstance(ids, list):
        return f'<div class="muted">{esc(title)}: {NOT_RECORDED}</div>'
    if not ids:
        return f'<div class="muted">{esc(title)} (0): none.</div>'
    rows = []
    for i in ids:
        message, route = lookup.get(i, (None, None))
        rows.append([f'<span class="nw">{esc(i)}</span>', text_or_missing(message), text_or_missing(route)])
    return heading(f"{title} ({len(ids)})") + table(["Id", "Message", "Expected route"], rows)


def router_html(summary: dict, lookup: dict) -> str:
    r = _dict(summary.get("router"))
    if not r:
        return f'<div class="muted">Router: {NOT_RECORDED}</div>'
    before, after = r.get("before"), r.get("after")
    out = [f'<div>Model: <b>{text_or_missing(r.get("model"))}</b></div>']
    out.append(table(["", "Correct"], [["Before", esc(pct(get(before, "correct"), get(before, "rows")))],
                                       ["After", esc(pct(get(after, "correct"), get(after, "rows")))]]))
    bb, ab = get(before, "by_category"), get(after, "by_category")
    names = list(dict.fromkeys(list(_dict(bb)) + list(_dict(ab))))
    if names:
        rows = [[esc(n), esc(pct(get(bb, n, "correct"), get(bb, n, "total"))), esc(pct(get(ab, n, "correct"), get(ab, n, "total")))] for n in names]
        out.append(table(["Category", "Before", "After"], rows))
    out.append(_id_list("Got better", r.get("got_better"), lookup))
    out.append(_id_list("Got worse", r.get("got_worse"), lookup))
    out.append(_id_list("Still wrong", get(after, "wrong_ids"), lookup))
    return "".join(out)


# -- scenarios and cost ----------------------------------------------------------------------------------------------
def _id_text(ids) -> str:
    if not isinstance(ids, list):
        return NOT_RECORDED
    return ", ".join(str(i) for i in ids) if ids else "none"


def scenarios_html(summary: dict) -> str:
    s = summary.get("scenarios")
    if not isinstance(s, dict):
        return f'<div class="muted">Scenarios: {NOT_RECORDED}</div>'
    unchanged = {True: "yes", False: "NO"}.get(s.get("real_database_unchanged"), NOT_RECORDED)
    rows = [["Passed", esc(pct(s.get("passed"), s.get("scenarios")))], ["Failed ids", esc(_id_text(s.get("failed_ids")))],
            ["Model calls", esc(num(s.get("model_calls")))], ["Tokens in", esc(num(s.get("input_tokens")))],
            ["Tokens out", esc(num(s.get("output_tokens")))], ["Real database unchanged", esc(unchanged)]]
    return table(["Scenario run", "Value"], rows)


def weak_spots_html(summary: dict) -> str:
    r = _dict(summary.get("retrieval"))
    cats = get(r, "profiles", r.get("chosen_profile"), "by_category")
    items = []
    for key, label in (("unanswerable_related", "Questions that are related but unanswerable"), ("scope_guard", "Scope-guard questions")):
        c = get(cats, key)
        fact = f" ({pct(get(c, 'nomatch_ok'), get(c, 'rows'))} correctly returned nothing)" if c else ""
        items.append(f"{label} still get passages{fact}.")
    items.append("The numbers come from small sets, so one row moves a percentage a lot.")
    items.append("Real-model runs are not exactly repeatable: the same run can differ by a row or two.")
    return lines(items)


def cost_html(summary: dict) -> str:
    cost = summary.get("cost_usd", summary.get("cost"))
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        return f"<div>${cost:.4f} (as recorded in the summary file)</div>"
    return f"<div>Cost: {NOT_RECORDED}.</div>"
