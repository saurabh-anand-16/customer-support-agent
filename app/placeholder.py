"""placeholder.py - the short page for a part of the app that a later phase builds."""
import streamlit as st


def coming_soon(name: str, phase: int, description: str) -> None:
    st.markdown(f"# {name}")
    st.info(f"Coming in phase {phase}. {description}")
    st.page_link("views/home.py", label="Home")
