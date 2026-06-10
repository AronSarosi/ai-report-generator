"""Capture screenshots of the running Streamlit app for a visual UX review.

    python scripts/ui_shots.py [base_url]

Saves PNGs to data/ui_shots/.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8599"
OUT = Path(__file__).resolve().parents[1] / "data" / "ui_shots"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(BASE, wait_until="networkidle", timeout=60000)
        page.wait_for_selector('[data-baseweb="tab"]', timeout=45000)
        page.wait_for_selector('text=See what it produces', timeout=45000)
        page.wait_for_timeout(3500)
        page.screenshot(path=str(OUT / "gen_top.png"))  # viewport: form
        # scroll to the showcase
        page.get_by_text("See what it produces").scroll_into_view_if_needed()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "gen_showcase.png"))
        browser.close()
    print("done")


if __name__ == "__main__":
    main()
