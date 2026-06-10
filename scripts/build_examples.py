"""Pre-build the Example Reports gallery: one polished deck per domain, rendered ONCE.

For each example dataset it: writes the source CSV, builds a real report (LLM), renders
PPTX + PDF, and exports each slide to a PNG via PyMuPDF. Outputs + a manifest land in
app/examples/, which the UI serves statically — so visitors view real reports instantly,
with zero wait and zero OpenAI tokens.

    python scripts/build_examples.py        (run once; makes real LLM calls)

PyMuPDF is only needed here (build time), not at runtime.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz  # PyMuPDF  # noqa: E402

from scripts.example_datasets import generate_marketing, generate_saas  # noqa: E402
from scripts.gen_budget_data import generate as generate_budget  # noqa: E402
from scripts.gen_sales_data import generate as generate_sales  # noqa: E402
from src.data_tool import drop_table, load_file_to_sqlite  # noqa: E402
from src.render import load_report, render_report  # noqa: E402
from src.report import build_report  # noqa: E402
from src.schemas import ReportRequest  # noqa: E402

# Reuse a previously-built report.json (skips the LLM) so styling can be re-rendered cheaply.
REUSE = os.environ.get("REUSE_EXAMPLES") == "1"

OUT = ROOT / "app" / "examples"
# The downloadable source CSV is sampled above this many rows (the report is still built
# on the full data); keeps bundled assets small without weakening the flagship report.
CSV_DOWNLOAD_LIMIT = 10_000

# Each example gets a distinct brand identity (accent + ink + fonts) so the gallery shows
# the SAME engine producing differently-styled decks — exactly what uploading a different
# brand template does. Fonts are standard on the (Windows) build machine and bake into the
# rendered images, so they show regardless of the deployment host's fonts.
EXAMPLES = [
    {"key": "retail_sales", "title": "Retail Sales Review",
     "domain": "Retail / Commerce",
     "description": "Two years of daily sales across regions, channels, categories and "
                    "products. The report finds the winning category, the laggard region, "
                    "and the channel shift.",
     "intent": "Monthly sales performance review highlighting the winning products, "
               "categories and regions, and any weak spots.",
     "gen": generate_sales,
     "brand": {"accent": "#2E6DB4", "ink": "#11243F",
               "font_head": "Georgia", "font_body": "Calibri", "cover": "dark"}},
    {"key": "fpa_budget", "title": "Budget vs Actuals (FP&A)",
     "domain": "Finance / FP&A",
     "description": "Monthly budget-vs-actuals by department. A completely different shape "
                    "from the sales data (no products/regions) — same engine, FP&A report.",
     "intent": "Budget vs actuals review: where are we over and under budget, and which "
               "departments are drifting?",
     "gen": generate_budget,
     "brand": {"accent": "#0E7C66", "ink": "#0C2E27",
               "font_head": "Cambria", "font_body": "Calibri", "cover": "light"}},
    {"key": "saas_metrics", "title": "SaaS Growth Metrics",
     "domain": "SaaS / Subscriptions",
     "description": "MRR, new and churned revenue, and active customers by plan and region. "
                    "Surfaces the plan driving growth and where churn concentrates.",
     "intent": "Monthly SaaS growth review: MRR by plan and region, what is driving new "
               "revenue, and where churn is concentrated.",
     "gen": generate_saas,
     "brand": {"accent": "#6C4BF0", "ink": "#211747",
               "font_head": "Trebuchet MS", "font_body": "Trebuchet MS", "cover": "dark"}},
    {"key": "marketing_analytics", "title": "Marketing Channel Performance",
     "domain": "Marketing / Web",
     "description": "Sessions, conversions, revenue and ad spend by channel. Shows the "
                    "efficient channels, the expensive ones, and what is declining.",
     "intent": "Monthly marketing performance review by channel: revenue, conversion and "
               "spend efficiency, and channel trends.",
     "gen": generate_marketing,
     "brand": {"accent": "#A61E4D", "ink": "#2E0E1E",
               "font_head": "Tahoma", "font_body": "Tahoma", "cover": "light"}},
]


def _slides_to_png(pdf_path: Path, dest: Path, dpi: int = 110) -> list[str]:
    """Render each PDF page to a PNG; return repo-relative paths."""
    out: list[str] = []
    doc = fitz.open(pdf_path)
    try:
        for i, page in enumerate(doc, 1):
            png = dest / f"slide_{i}.png"
            page.get_pixmap(dpi=dpi).save(str(png))
            out.append(str(png.relative_to(ROOT)).replace("\\", "/"))
    finally:
        doc.close()
    return out


def build_one(ex: dict) -> dict:
    key = ex["key"]
    dest = OUT / key
    # Preserve a prior report.json across the wipe so REUSE can re-render styling cheaply.
    cached = (dest / "report.json")
    cached_text = cached.read_text(encoding="utf-8") if (REUSE and cached.exists()) else None
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    df = ex["gen"]()
    report_json = dest / "report.json"

    # Build the report on the FULL dataset (best quality), or reuse a saved report.json so
    # styling can be re-rendered without another LLM call. The narrative does not change
    # with branding, only the visual theme passed to render_report.
    if cached_text is not None:
        report_json.write_text(cached_text, encoding="utf-8")
        report = load_report(report_json)
    else:
        full_csv = dest / "_full.csv"
        df.to_csv(full_csv, index=False)
        table = f"ex_{key}"
        load_file_to_sqlite(full_csv, table=table)
        try:
            report = build_report(ReportRequest(intent=ex["intent"], table=table))
            report_json.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        finally:
            drop_table(table)
            full_csv.unlink(missing_ok=True)

    n = len(df)
    # Clean cover subtitle (the default exposes the internal table name).
    report.subtitle = f"{ex['domain']} dataset  ·  {n:,} rows"
    paths = render_report(report, out_dir=dest, charts_dir=dest / "charts", brand=ex.get("brand"))
    shutil.rmtree(dest / "charts", ignore_errors=True)

    # Downloadable source CSV: sample large datasets so bundled assets stay small.
    csv_path = dest / "data.csv"
    sampled = len(df) > CSV_DOWNLOAD_LIMIT
    (df.sample(n=CSV_DOWNLOAD_LIMIT, random_state=0).sort_index() if sampled else df) \
        .to_csv(csv_path, index=False)

    thumbs = _slides_to_png(Path(paths["pdf"]), dest) if paths.get("pdf") else []
    rel = lambda p: str(Path(p).relative_to(ROOT)).replace("\\", "/")  # noqa: E731
    return {
        "key": key, "title": ex["title"], "domain": ex["domain"],
        "description": ex["description"], "rows": int(n), "cols": int(df.shape[1]),
        "columns": list(map(str, df.columns)),
        "title_text": report.title, "period": report.period,
        "n_sections": len(report.sections),
        "pdf": rel(paths["pdf"]) if paths.get("pdf") else "",
        "pptx": rel(paths["pptx"]), "csv": rel(csv_path), "csv_sampled": sampled,
        "thumbs": thumbs,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for ex in EXAMPLES:
        print(f"\n=== building {ex['key']} ===")
        rec = build_one(ex)
        print(f"  {rec['title']}  ({rec['rows']} rows x {rec['cols']} cols, "
              f"{rec['n_sections']} sections, {len(rec['thumbs'])} slides)")
        manifest.append(rec)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT / 'manifest.json'} with {len(manifest)} examples")


if __name__ == "__main__":
    main()
