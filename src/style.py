"""Single source of truth for the visual system (MBB/Big-4 design spec).

Both the PowerPoint renderer and the matplotlib charts import these constants so the
deck and the charts never drift. See docs/report_design_spec.md for the rationale.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Color palette (hex) - gray is context, accent is rationed for emphasis
# --------------------------------------------------------------------------- #
INK = "#1F2A44"        # near-black navy: titles, totals, primary bars
ACCENT = "#2E6DB4"     # corporate blue: the ONE highlight
GRAY_900 = "#3C4450"   # body text dark
GRAY_500 = "#7A828C"   # secondary text, source line, context bars
GRAY_300 = "#C0C5C9"   # muted bars/lines
GRAY_100 = "#E6E8EB"   # gridlines, table rules, callout fill
POSITIVE = "#2E8B6F"   # favorable variance / up
NEGATIVE = "#C0392B"   # unfavorable variance / down
AMBER = "#E0A53B"      # RAG amber
PAPER = "#FFFFFF"

# --------------------------------------------------------------------------- #
# Typography
# --------------------------------------------------------------------------- #
FONT_HEAD = "Georgia"  # serif titles (MBB-credible)
FONT_BODY = "Arial"    # universal; identical in LibreOffice

# point sizes (bumped up - small text reads as cheap; consulting decks run large)
SZ_DECK_TITLE = 46
SZ_KICKER = 13
SZ_TITLE = 30
SZ_SUB = 17
SZ_BODY = 15
SZ_SOURCE = 9

# --------------------------------------------------------------------------- #
# Slide geometry (16:9 = 13.333 x 7.5 in). Tuples are (left, top, width, height)
# in inches; the renderer wraps them in pptx.util.Inches.
# --------------------------------------------------------------------------- #
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5
MARGIN_IN = 0.5
CONTENT_W_IN = SLIDE_W_IN - 2 * MARGIN_IN  # 12.333

KICKER_BOX = (0.5, 0.32, CONTENT_W_IN, 0.30)
TITLE_BOX = (0.5, 0.64, CONTENT_W_IN, 1.10)
RULE_Y_IN = 1.74
BODY_BOX = (0.5, 1.92, CONTENT_W_IN, 4.20)
SOURCE_BOX = (0.5, 7.08, CONTENT_W_IN, 0.30)


def apply_mpl_style() -> None:
    """Apply the global matplotlib rcParams so charts match the deck (Tufte data-ink)."""
    import matplotlib as mpl

    mpl.use("Agg")  # headless: no GUI backend
    mpl.rcParams.update({
        "figure.dpi": 200, "savefig.dpi": 200, "figure.facecolor": PAPER,
        "savefig.facecolor": PAPER,
        "font.family": FONT_BODY, "font.size": 10,
        "axes.edgecolor": GRAY_500, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y",
        "grid.color": GRAY_100, "grid.linewidth": 0.8,
        "axes.titlesize": 11, "axes.titlelocation": "left", "axes.titlecolor": INK,
        "axes.labelcolor": GRAY_900, "xtick.color": GRAY_500, "ytick.color": GRAY_500,
        "xtick.bottom": True, "ytick.left": False,
        "axes.prop_cycle": mpl.cycler(color=[GRAY_300, GRAY_500, ACCENT, INK]),
        "legend.frameon": False,
    })
