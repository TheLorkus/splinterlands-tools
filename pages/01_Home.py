from __future__ import annotations

from core.config import render_footer, setup_page
from core.home import render_home


setup_page("Splinterlands Tools Hub")


def render_page() -> None:
    render_home()


if __name__ == "__main__":
    render_page()
    render_footer()
