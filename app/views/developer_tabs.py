"""
The four read-only tabs of the Developer page (phase 11): Evaluation, Tests, Policy explorer and Assumptions.

This file only draws. The logic is in app/dev_eval.py, app/dev_policy.py and app/dev_assumptions.py (no Streamlit calls there),
and the files are read through app/data.py. A tab never writes, never calls the agent, a model or an embedding service, never touches the
database and never runs a test or a script. A missing, empty or broken file is an empty state, never a traceback.

Tests give their own files through st.session_state["_dev_sources"] (a dict of name -> path; "root" is the project folder).
"""
import streamlit as st

from app import data, dev_assumptions, dev_eval, dev_policy
from app.trace_view import esc


def source(name: str, default):
    """A test's own file for `name`, else the default."""
    return (st.session_state.get("_dev_sources") or {}).get(name) or default


def root():
    return source("root", data.project_root())


def html(body: str) -> None:
    st.html(body)


def section(title: str, body: str) -> None:
    st.html(f'<div class="detail-h">{esc(title)}</div>{body}')


# -- Evaluation -----------------------------------------------------------------------------------------------------------
def draw_evaluation() -> None:
    summary, state = data.read_file(source("summary", root() / "data" / "evals" / "summary.json"), "json")
    if state != "ok" or not isinstance(summary, dict):
        with st.container(key="dev_eval_empty"):
            html(dev_eval.empty_state_html(state if state != "ok" else "broken"))
        return
    rows, _ = data.read_file(source("router_messages", root() / "data" / "evals" / "router_messages.csv"), "csv")
    lookup = dev_eval.router_lookup(rows)
    html(dev_eval.header_html(summary))
    html(dev_eval.how_to_read_html())
    section("Rows reviewed", dev_eval.reviewed_html(summary))
    section("Search: settings", dev_eval.search_settings_html(summary))
    section("Search: profiles", dev_eval.profiles_html(summary))
    section("Search: by category", dev_eval.category_html(summary))
    section("Search: skipped profiles", dev_eval.skipped_html(summary))
    section("Router", dev_eval.router_html(summary, lookup))
    section("Scenarios", dev_eval.scenarios_html(summary))
    section("Known weak spots", dev_eval.weak_spots_html(summary))
    section("Cost", dev_eval.cost_html(summary))


# -- Policy explorer --------------------------------------------------------------------------------------------------------
def draw_policy() -> None:
    base = root()
    config, _ = data.read_file(source("rag_config", base / "config" / "rag.toml"), "toml")
    settings = dev_policy.scope_settings(config)
    export = source("chunks", base / (settings["export_path"] or "data/clean/policy_chunks.csv"))
    policy_dir = source("policy_dir", base / (settings["policy_dir"] or "policy"))
    rows, state = data.read_file(export, "csv")
    found = {"Chunk export": (str(export.relative_to(base)) if str(export).startswith(str(base)) else export.name, export.is_file()),
             "Scope settings": ("config/rag.toml", isinstance(config, dict)),
             "Policy pages": (policy_dir.name + "/", policy_dir.is_dir())}
    if state != "ok" or not rows:
        with st.container(key="dev_policy_empty"):
            html(dev_policy.empty_state_html(state if state != "ok" else "empty"))
            html(dev_policy.sources_html(found))
        return
    files = sorted(p.name for p in policy_dir.glob("*.md")) if policy_dir.is_dir() else []
    items = dev_policy.pages(rows, settings, files)
    html(dev_policy.copy_date_html(items))
    html(dev_policy.notes_html_box())
    section("Policy pages", dev_policy.pages_html(items))
    names = [p["file"] for p in items]
    chosen = st.selectbox("Choose a page to see its chunks", names, key="dev_policy_page")
    page = next(p for p in items if p["file"] == chosen)
    section(f"Chunks of {chosen}", dev_policy.chunks_html(dev_policy.chunk_rows(rows, chosen), page))
    section("Source files", dev_policy.sources_html(found))


# -- Assumptions ------------------------------------------------------------------------------------------------------------
def draw_assumptions() -> None:
    content, state = data.read_file(source("assumptions", data.project_root() / "app" / "assumptions.toml"), "toml")
    items = dev_assumptions.entries(content)
    if state != "ok" or not items:
        with st.container(key="dev_assumptions_empty"):
            html(dev_assumptions.empty_state_html(state if state != "ok" else "empty"))
        return
    base = root()
    html("<div class=\"note-box\"><b>What is ours and not Amazon's</b>Each value below is read now from the file it names. "
         "It is not typed into the text. A source that cannot be found says so.</div>")
    for kind, group in dev_assumptions.grouped(items):
        section(f"{kind.capitalize()} ({len(group)})", "".join(dev_assumptions.entry_html(e, base) for e in group))
