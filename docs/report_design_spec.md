# Consulting-Grade Finance Report Generator - Design Spec

A data-agnostic spec for the automated PowerPoint (`python-pptx`) + PDF (LibreOffice
headless) generator, derived from MBB/Big-4 deck conventions (Minto Pyramid, BCG action
titles), Tufte's data-ink principle, and IBCS business-charting standards. All values are
opinionated defaults - implement these as-is; they live in one `src/style.py` constants
module so the deck and the charts never drift.

> Source of truth for Step A6 (default report template / narrative rules) and Step A7
> (renderer). Produced from background research; see Sources at the bottom.

## 1. Structure & Narrative

**Governing rule - Pyramid Principle (Minto):** lead with the answer, then support it.
Top-down: governing thought -> 3 key messages -> evidence.

- **Governing thought:** one sentence the whole deck proves (e.g. "Q2 results are on plan;
  margin pressure in Region B is the one risk to manage").
- **Executive summary = key messages**, not a table of contents. 3-5 bullets, each a full
  assertion (the "so what"), each mapping to a downstream section. Reading only these = the
  whole story.
- **Action titles (BCG):** every content-slide title is a complete sentence stating the
  takeaway, NOT a topic. Hard limits: <=15 words, <=2 lines, active voice, include the number.
  - Good: "Revenue grew 12% YoY, driven entirely by the Enterprise segment"
  - Bad: "Revenue Overview"
- **Horizontal flow test:** reading titles top-to-bottom should read like the exec summary.
  **So-what test:** if a title could caption any month's data, it fails.
- **MECE:** section groupings are mutually exclusive, collectively exhaustive.

**Default monthly finance-review sequence:**
1. Title slide
2. Executive summary / key messages (verdict: on-track? top wins? decisions needed?)
3. Section divider -> **Financial Performance** (revenue, margin, P&L bridge vs plan)
4. Section divider -> **Operational / Segment Drivers** (what moved the numbers)
5. Section divider -> **Risks & Outlook** (forecast, RAG status)
6. **Recommendations / decisions requested**
7. Appendix + **Sources** slide

## 2. Slide Anatomy (16:9 = 13.333 x 7.5 in)

Zones for a standard content slide (top->bottom). EMU at 914,400/in; full slide =
12,192,000 x 6,858,000 EMU.

| Zone | Top (in) | Height (in) | Content |
|---|---|---|---|
| Kicker / section label | 0.30 | 0.25 | ALL-CAPS, accent color, 11pt (e.g. "FINANCIAL PERFORMANCE") |
| Action title | 0.55 | 0.85 | The assertion, 24pt bold, dark navy, left-aligned, <=2 lines |
| Hairline rule | 1.45 | - | 1pt accent line under title, full content width |
| Body | 1.65 | 4.55 | Single chart OR table OR content block |
| So-what callout box | right ~30% of body OR bottom-right | - | Tinted box, accent border, 1-2 sentence takeaway / key number |
| Source / footnote line | 7.05 | 0.25 | 8pt gray, left ("Source: ..."); page # right |

- Side margins: 0.5 in (content width 12.333 in / 11,277,600 EMU). Title/body/source all
  left-align to this 0.5 in gridline.
- One message per slide. If two charts are needed, they share one action title.

## 3. Chart Design (Tufte data-ink + IBCS)

- No top/right spines. No vertical gridlines. Drop the y-axis line+ticks, keep faint
  horizontal gridlines (#E6E8EB) OR direct-label every point and drop gridlines entirely.
- Direct labeling, not legends. Legends only at 4+ series.
- No 3D, shadows, rounded bars, background fill, or data-table dumps.
- Restrained color: everything gray; ONE accent color highlights the one bar/line the
  action title is about. Color = meaning, never decoration.
- One message per chart.

**Chart selection (IBCS):**
| Use case | Chart |
|---|---|
| Value across categories | Horizontal bar (sorted descending) |
| Value over time | Line (<=4 series) or column (<=8 periods) |
| Composition over time | Stacked column (<=5 series) |
| Variance: budget-vs-actual, YoY bridge, P&L walk | **WATERFALL / bridge** (signature MBB variance chart) |

**Waterfall convention (IBCS):** start total -> +/- contributions -> end total. Positive =
green, negative = red, totals = dark navy. Label positives above the bar, negatives below.

## 4. Visual System

**Color palette - named constants (hex):**
```
INK        = "#1F2A44"   # near-black navy - titles, totals, primary bars
ACCENT     = "#2E6DB4"   # corporate blue - the ONE highlight (kicker, rule, emphasis)
GRAY_900   = "#3C4450"   # body text dark
GRAY_500   = "#7A828C"   # secondary text, source line, context bars
GRAY_300   = "#C0C5C9"   # muted bars/lines
GRAY_100   = "#E6E8EB"   # gridlines, table rules, callout box fill
POSITIVE   = "#2E8B6F"   # green - favorable variance / up
NEGATIVE   = "#C0392B"   # red - unfavorable variance / down
PAPER      = "#FFFFFF"
```
RAG status chips: POSITIVE / "#E0A53B" (amber) / NEGATIVE.

**Typography (safe in PowerPoint + LibreOffice):**
- Headings/titles: **Georgia** (serif, MBB-credible) - or Arial Bold for a single-family look.
- Body/charts: **Arial** (universal; renders identically in LibreOffice).
- Pairing: Georgia titles + Arial body (McKinsey-style default).
- Sizes: kicker 11pt / action title 24pt bold / subhead 13pt / body 11pt / chart labels
  9-10pt / source 8pt.

**Whitespace/grid:** consistent 0.5 in margins, left-aligned to one gridline, generous
gutters. Two fonts max, <=4 colors per slide.

## 5. python-pptx + matplotlib Mapping

### Reusable constants
```python
from pptx.util import Inches, Pt

# Canvas (16:9 widescreen)
SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.5)
CONTENT_W = Inches(12.333)          # SLIDE_W - 2*MARGIN

# Zone geometry (left, top, width, height) in inches
KICKER_BOX  = (Inches(0.5), Inches(0.30), CONTENT_W, Inches(0.25))
TITLE_BOX   = (Inches(0.5), Inches(0.55), CONTENT_W, Inches(0.85))
RULE_Y      = Inches(1.45)          # 1pt ACCENT hairline
BODY_BOX    = (Inches(0.5), Inches(1.65), CONTENT_W, Inches(4.55))
SOURCE_BOX  = (Inches(0.5), Inches(7.05), CONTENT_W, Inches(0.25))

FONT_HEAD, FONT_BODY = "Georgia", "Arial"
SZ_KICKER, SZ_TITLE, SZ_SUB, SZ_BODY, SZ_SOURCE = Pt(11), Pt(24), Pt(13), Pt(11), Pt(8)
```
Charts: matplotlib -> PNG at DPI 200 -> inserted into BODY_BOX (not native PPT charts;
matplotlib gives full Tufte control and identical PDF output).

### Slide-type templates
| Type | Contents |
|---|---|
| (a) Title | Deck title (Georgia 40pt INK), subtitle (Arial 18pt GRAY_500), client/date/confidentiality, thin ACCENT rule. No kicker. |
| (b) Exec summary / key messages | Kicker "EXECUTIVE SUMMARY"; action title = governing thought; body = 3-5 assertion bullets each with a POSITIVE/NEGATIVE RAG chip; no chart. |
| (c) Section divider | INK full-bleed (or left ACCENT band); section number + name centered, Georgia 32pt white; no source line. |
| (d) Single-chart insight | Kicker + action title + hairline; matplotlib chart in left ~68% of BODY_BOX; so-what callout box (GRAY_100 fill, ACCENT left border, Arial 11pt) in right ~30%; source line. The workhorse slide. |
| (e) Breakdown / table | Action title; banded table - header row INK fill/white text, body rows alternating PAPER/GRAY_100, 1pt GRAY_300 rules, right-align numbers, no vertical borders; variance column colored POSITIVE/NEGATIVE. |
| (f) Recommendations | Kicker "RECOMMENDATIONS"; numbered imperative actions (verb-first), each with owner + timeframe; optional priority chips. |
| (g) Sources | Action title "Sources & methodology"; Arial 9pt reference list; data-as-of date and assumptions. |

### matplotlib styling (global rcParams so charts match the deck)
```python
import matplotlib as mpl
mpl.rcParams.update({
    "figure.dpi": 200, "savefig.dpi": 200, "figure.facecolor": "white",
    "font.family": "Arial", "font.size": 10,
    "axes.edgecolor": "#7A828C", "axes.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.spines.left": False,
    "axes.grid": True, "axes.grid.axis": "y",
    "grid.color": "#E6E8EB", "grid.linewidth": 0.8,
    "axes.titlesize": 11, "axes.titlelocation": "left", "axes.titlecolor": "#1F2A44",
    "axes.labelcolor": "#3C4450", "xtick.color": "#7A828C", "ytick.color": "#7A828C",
    "xtick.bottom": True, "ytick.left": False,
    "axes.prop_cycle": mpl.cycler(color=["#C0C5C9","#C0C5C9","#C0C5C9","#C0C5C9"]),
    "legend.frameon": False,
})
```
Per-chart: direct-label series, format axes (`,.0f` / `0.0%`), recolor only the highlighted
series to ACCENT/POSITIVE/NEGATIVE, `fig.tight_layout()`, white background for byte-stable
PDF export.

### Implementation notes
1. Render all charts in matplotlib -> PNG (not native PPT charts) for Tufte control and
   stable PDF output.
2. Every content slide is built from the same 6-zone skeleton with only the body swapped.
3. Palette + fonts + matplotlib rcParams live in one `src/style.py`.
4. The action-title generator must enforce the <=15-word / <=2-line / contains-a-number rule
   at generation time.

## Sources
- Barbara Minto, *The Pyramid Principle* (think-cell, Slideworks summaries)
- Edward Tufte, *The Visual Display of Quantitative Information* (data-ink ratio, chartjunk)
- BCG action titles & MBB slide standards (Deckary, Slideworks)
- IBCS business-charting (variance/waterfall, positive/negative color)
- Datawrapper data-vis color discipline; McKinsey brand blue #24477f
- 16:9 widescreen 13.333x7.5 in (Microsoft); EMU = 914,400/in (python-pptx docs)
