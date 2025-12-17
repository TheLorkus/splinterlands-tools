from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Splinterlands Tools")
st.markdown(
    """
    <meta property="og:title" content="Splinterlands Tools">
    <meta property="og:description" content="Optimization tools for Splinterlands">
    <meta property="og:image" content="https://images.hive.blog/DQmPVy7cZdqVrpSCGnnMcPdPZQPvV8UGPS6nRP9jYhYn7m4/spl-tools-starburst.png">
    """,
    unsafe_allow_html=True,
)

from core.config import setup_page
from core.home import render_home


setup_page("Splinterlands Tools Hub")


def main() -> None:
    """Entry point for the multipage Streamlit hub."""
    try:
        # Route to the ordered Home page so the sidebar keeps the multipage order.
        st.switch_page("pages/01_Home.py")
        return
    except Exception:
        # Fallback for environments without switch_page support.
        render_home()


if __name__ == "__main__":
    main()
