from __future__ import annotations

import streamlit as st


def render_home() -> None:
    st.title("Splinterlands Tools Hub")
    st.caption("Pick a tool to jump in, or open a page from the sidebar.")

    st.markdown("### Featured tools")
    st.page_link("pages/10_Brawl_Dashboard.py", label="Brawl Dashboard", icon="🛡️")
    st.page_link("pages/20_Rewards_Tracker.py", label="Rewards Tracker", icon="🎓")

    # Keep a small list of known paths so renames do not silently break the home link.
    series_page_paths = [
        "pages/30_Tournament_Series.py",  # current
        "pages/30_Series_Hub.py",  # legacy
    ]
    for path in series_page_paths:
        try:
            st.page_link(path, label="Tournament Series", icon="🏆")
            break
        except Exception:
            continue

    st.markdown("### Coming soon")
    st.page_link("pages/40_SPS_Analytics.py", label="SPS Analytics", icon="📈")

    st.info("Use the sidebar to switch between pages at any time.")
