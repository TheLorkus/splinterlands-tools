from __future__ import annotations

import streamlit as st

from core.config import render_footer, setup_page
try:
    from scholar_helper.services.storage import refresh_tournament_ingest_all, get_last_supabase_error
except ImportError:
    # Fallback to avoid app crash if the helper isn't available in the runtime.
    def refresh_tournament_ingest_all(max_age_days: int = 3) -> bool:  # type: ignore
        return False

    def get_last_supabase_error() -> str:  # type: ignore
        return "Helper not available"
from series import leaderboard, tournament


setup_page("Tournament Series")


def render_page() -> None:
    st.title("Tournament Series")
    st.caption("Series Leaderboard and Tournament Configurator.")
    with st.sidebar:
        st.markdown(
            """
            <style>
            [data-testid="stSidebar"] button[data-testid="stButton"][data-key="leaderboard-update"] {
                background-color: #6cc070 !important;
                border-color: #6cc070 !important;
                color: #0f1b0b !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Leaderboard Update", type="primary", key="leaderboard-update"):
            with st.spinner("Refreshing organizer tournaments (3 days)..."):
                ok = refresh_tournament_ingest_all(max_age_days=3)
            if ok:
                st.success("Tournament data refresh kicked off.")
            else:
                st.error(f"Failed to trigger refresh: {get_last_supabase_error() or 'Unknown error'}")
        st.caption("Refreshes the last 3 days of organizer tournaments into the database.")

    view = st.session_state.get("__series_view", "leaderboard")
    view = st.radio(
        "Pick a view",
        options=["leaderboard", "tournament"],
        format_func=lambda v: "Series Leaderboard" if v == "leaderboard" else "Tournament Configurator (organizers)",
        horizontal=True,
        index=0 if view == "leaderboard" else 1,
        key="__series_view",
    )

    st.divider()

    if view == "leaderboard":
        leaderboard.render_page(embed_mode=True)
    else:
        st.header("Tournament Configurator (organizers)", divider="gray")
        tournament.render_page(embed_mode=True)

        st.divider()
        st.subheader("Docs: Tournament Series")
        try:
            with open("Tournament_Series.md", "r", encoding="utf-8") as f:
                doc_text = f.read()
            st.markdown(doc_text)
        except Exception as exc:  # pragma: no cover - best-effort embed
            st.error(f"Failed to load Tournament_Series.md: {exc}")


if __name__ == "__main__":
    render_page()
    render_footer()
