"""
Limits and assumptions (phase 13): a read-only page. It reads app/assumptions.toml, app/limits.toml and data/evals/summary.json through
app/data.py, never calls the agent, a model or the database, and never writes. The pieces are in app/limits_view.py. Tests give their
own files through st.session_state["_dev_sources"] (keys: root, assumptions, limits, summary).
"""
import streamlit as st

from app import data, limits_view as lv


def source(name: str, default):
    return (st.session_state.get("_dev_sources") or {}).get(name) or default


root = source("root", data.project_root())

st.markdown("# Limits and assumptions")
st.write(lv.OPENING)

st.markdown("## Our decisions, not Amazon's")
assumptions, a_state = data.read_file(source("assumptions", root / "app" / "assumptions.toml"), "toml")
if a_state != "ok" or not lv.our_decisions(assumptions):
    st.html(lv.empty_state_html("list of decisions", a_state if a_state != "ok" else "empty"))
else:
    st.html(lv.decisions_html(assumptions, root))

st.markdown("## Known gaps")
gaps, g_state = data.read_file(source("limits", root / "app" / "limits.toml"), "toml")
summary, s_state = data.read_file(source("summary", root / "data" / "evals" / "summary.json"), "json")
if g_state != "ok" or not lv.limits(gaps):
    st.html(lv.empty_state_html("list of known gaps", g_state if g_state != "ok" else "empty"))
else:
    st.html(lv.limits_html(gaps, summary if s_state == "ok" else None))

st.markdown("## How to read this page")
st.write(lv.HOW_TO_READ)
st.write("The full evaluation tables are on the Developer page, in the Evaluation tab.")
st.page_link("views/developer.py", label="Open Developer trace")
