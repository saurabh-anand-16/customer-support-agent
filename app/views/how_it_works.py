"""How it works (phase 13): a read-only page. It reads no file and calls no agent, model or database; the content is in app/how_view.py."""
import streamlit as st

from app import how_view as hv

st.markdown("# How it works")
st.write(hv.OPENING)

st.markdown("## The whole project at a glance")
st.html(hv.diagram_image_html())
st.html(hv.diagram_text_html())

st.markdown("## Seven steps")
st.html(hv.steps_html())

st.markdown("## Four rules that do not bend")
st.html(hv.rules_html())

st.markdown("## See it on a real turn")
st.write("Every message the agent handles is recorded: the route it took, the tools it called, the passages it used and the checks it passed.")
st.page_link("views/developer.py", label="Open Developer trace")
