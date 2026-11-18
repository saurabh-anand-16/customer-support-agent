"""
main.py - the entry of the app. Run it with:  streamlit run app/main.py

This file runs on every interaction, before the page itself: it sets the layout, loads the one stylesheet, draws the demo
corner tag and the sidebar (so they are on every page), then runs the page chosen in the sidebar.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:               # `streamlit run app/main.py` puts app/ on the path, not the project folder
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(layout="wide", initial_sidebar_state="auto")

from app import components, state  # noqa: E402
from app.config import AppConfigError  # noqa: E402
from app.demo_db import DemoDbError  # noqa: E402

# Page title, file, address. These six names are used everywhere: sidebar, page heading and links.
PAGE_LIST = [("Home", "views/home.py", "home"), ("Customer chat", "views/chat.py", "customer-chat"),
             ("Manager queue", "views/manager.py", "manager-queue"), ("Developer trace", "views/developer.py", "developer-trace"),
             ("How it works", "views/how_it_works.py", "how-it-works"), ("Limits and assumptions", "views/limits.py", "limits-and-assumptions")]


def load_stylesheet() -> None:
    """The one stylesheet, put on the page once per run. (st.html removes the style block in this Streamlit version; st.markdown keeps it.)"""
    css_file = HERE / "styles.css"
    if css_file.is_file():
        st.markdown(f"<style>{css_file.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def sidebar(pages: dict, settings) -> None:
    with st.sidebar:
        st.html('<div class="app-name">customer-support-agent</div>')
        st.caption("Returns and refunds assistant.")
        st.markdown("**Pages**")
        for name, page in pages.items():
            st.page_link(page, label=name)
        cid = state.customer_id()
        if cid:
            from app.config import load_personas
            persona = next((p for p in load_personas() if p.customer_id == cid), None)
            st.html(components.now_playing_html(cid, persona.label if persona else None, persona.hint if persona else None))
            if st.button("Change customer", key="change-customer"):
                state.sign_out()
                st.switch_page(pages["Home"])
        st.button("Reset demo data", key="reset-demo", on_click=state.reset_demo)
        st.caption("Puts every order, return and review back as it was at the start. Your chat starts again.")
        st.caption(settings.fixed_date_line)


def main() -> None:
    load_stylesheet()
    try:
        settings = state.get_settings()
    except (AppConfigError, DemoDbError, OSError):
        st.error("The app could not start. Check the [app] section of config/agent.toml and that returns_agent.db exists.")
        return
    components.corner_tag(settings.corner_tag)
    notice = st.session_state.pop("notice", None)         # for example "Demo data was reset", shown once on whatever page the visitor is on
    if notice:
        st.info(notice)
    pages = {name: st.Page(path, title=name, url_path=url, default=(name == "Home")) for name, path, url in PAGE_LIST}
    sidebar(pages, settings)
    st.navigation(list(pages.values()), position="hidden").run()


main()
