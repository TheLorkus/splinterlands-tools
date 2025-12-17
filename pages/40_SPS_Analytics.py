from __future__ import annotations

import streamlit as st

from core.config import render_footer, setup_page


setup_page("SPS Analytics")


def render_page() -> None:
    st.title("SPS Analytics")
    st.info("Coming soon: deeper SPS insights, pricing history, and dashboarding.")


if __name__ == "__main__":
    render_page()
    render_footer()
