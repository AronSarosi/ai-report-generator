"""Capture screenshots of the running Streamlit app for a visual UX review.

    python scripts/ui_shots.py [base_url]

Drives the app with Playwright: landing (Generate tab), Ask Your Data tab, a desktop
and a mobile width. Saves PNGs to data/ui_shots/.
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

        # --- Desktop: lands on Example Reports tab ---
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE, wait_until="networkidle", timeout=60000)
        page.wait_for_selector('[data-baseweb="tab"]', timeout=45000)
        page.wait_for_timeout(3500)
        page.screenshot(path=str(OUT / "01_examples_tab.png"), full_page=True)

        # Generate tab
        try:
            page.get_by_role("tab", name="Generate Report").click()
            page.wait_for_timeout(2500)
            page.screenshot(path=str(OUT / "02_generate_tab.png"), full_page=True)
        except Exception as e:  # noqa: BLE001
            print("generate tab:", e)

        # Ask Your Data tab
        try:
            page.get_by_role("tab", name="Ask Your Data").click()
            page.wait_for_timeout(2500)
            page.screenshot(path=str(OUT / "03_chat_tab.png"), full_page=True)
        except Exception as e:  # noqa: BLE001
            print("chat tab:", e)

        browser.close()
    print(f"shots in {OUT}")
    for f in sorted(OUT.glob("*.png")):
        print(" ", f.name)


if __name__ == "__main__":
    main()
