"""Evaluate the FULL report pipeline: build a real report and prove it is grounded.

For each sample dataset this runs the whole LangGraph pipeline (analyze -> plan -> write ->
verify -> assemble), then re-derives the approved figures *deterministically* (profile ->
battery -> plan are pure given the data) and checks:

  1. Figure grounding — every $ / % figure anywhere in the report text exists in the
     approved set computed from the database. Insight sections are checked against their
     own section's approved figures (same rule the runtime verify node enforces); the
     title, governing thought, key messages and recommendations are checked against the
     union of all approved figures — the runtime verify node does NOT cover those, so
     this eval closes that gap.
  2. Structure — the report has the shape the renderer expects (title length, key-message
     count and statuses, sections with non-empty charts, recommendation count, sources).

Run from the project root (makes real LLM calls — costs API money):
    python eval/run_report_eval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis import compute_battery  # noqa: E402
from src.data_tool import load_file_to_sqlite, profile_dataset  # noqa: E402
from src.report import _plan_sections, _unapproved_figures, build_report  # noqa: E402
from src.schemas import Report, ReportRequest  # noqa: E402

DATASETS = [
    {"name": "sales", "table": "sales", "intent": "Monthly sales review"},
    {"name": "budget", "table": "budget", "intent": "Budget vs actuals review",
     "csv": ROOT / "data" / "out" / "budget_vs_actuals.csv"},
]

VALID_STATUSES = {"positive", "negative", "neutral"}


def _ensure_data() -> None:
    """Regenerate the sample datasets if they are missing."""
    if not (ROOT / "data" / "db" / "sales.sqlite").exists():
        from scripts.gen_sales_data import main as gen_sales
        gen_sales()
    if not (ROOT / "data" / "out" / "budget_vs_actuals.csv").exists():
        from scripts.gen_budget_data import main as gen_budget
        gen_budget()


def _spec_for(section, specs: list[dict]):
    """Match a written section back to its plan spec (same logic as node_verify)."""
    by_id = {s["id"]: s for s in specs}
    spec_id = section.citations[0].split(":")[0] if section.citations else None
    return by_id.get(spec_id) or next((s for s in specs if s["kicker"] == section.kicker), None)


def evaluate_report(report: Report, table: str) -> dict:
    """Grounding + structural checks; deterministic given the report and the database."""
    profile = profile_dataset(table=table)
    battery = compute_battery(profile)
    specs = _plan_sections(battery, profile)
    union_approved = sorted({fig for s in specs for fig in s["approved"]})

    # --- 1. figure grounding ---
    unapproved: list[str] = []
    for sec in report.sections:
        spec = _spec_for(sec, specs)
        approved = spec["approved"] if spec else union_approved
        text = " ".join([sec.action_title, sec.narrative, *sec.bullets, sec.so_what or ""])
        unapproved += [f"{sec.kicker}: {fig}" for fig in _unapproved_figures(text, approved)]
    global_text = " ".join([report.title, report.governing_thought,
                            *[km.text for km in report.key_messages],
                            *report.recommendations])
    unapproved += [f"global: {fig}" for fig in _unapproved_figures(global_text, union_approved)]

    # --- 2. structure ---
    structure = [
        ("title 1-9 words", 1 <= len(report.title.split()) <= 9),
        ("3-5 key messages", 3 <= len(report.key_messages) <= 5),
        ("key message statuses valid", all(km.status in VALID_STATUSES
                                           for km in report.key_messages)),
        ("governing thought present", bool(report.governing_thought.strip())),
        (">=2 sections", len(report.sections) >= 2),
        ("every chart has data", all(s.chart.x and next(iter(s.chart.series.values()), [])
                                     for s in report.sections if s.chart)),
        ("3-4 recommendations", 3 <= len(report.recommendations) <= 4),
        ("sources present", bool(report.sources)),
    ]
    return {
        "table": table,
        "n_approved": sum(len(s["approved"]) for s in specs),
        "unapproved": unapproved,
        "structure": structure,
        "grounding_pass": not unapproved,
        "structure_pass": all(ok for _, ok in structure),
    }


def run_report_eval() -> dict:
    """Build a real report per dataset and evaluate it. Returns {results, n, n_pass}."""
    _ensure_data()
    results = []
    for ds in DATASETS:
        if "csv" in ds:
            load_file_to_sqlite(ds["csv"], table=ds["table"])
        report = build_report(ReportRequest(intent=ds["intent"], table=ds["table"]))
        res = evaluate_report(report, ds["table"])
        res["name"] = ds["name"]
        res["title"] = report.title
        res["pass"] = res["grounding_pass"] and res["structure_pass"]
        results.append(res)
    return {"results": results, "n": len(results), "n_pass": sum(r["pass"] for r in results)}


def section_md(res: dict) -> list[str]:
    """Markdown section for the combined eval report."""
    lines = [
        "## Report pipeline (figure grounding + structure)", "",
        "Each report is generated end-to-end by the LangGraph pipeline, then every quoted "
        "$ / % figure is checked against the approved set recomputed from the database "
        "(including the title, key messages and recommendations, which the runtime verify "
        "node does not cover).", "",
        "| Dataset | Report title | Unapproved figures | Structure | Result |",
        "|---|---|---|---|---|",
    ]
    for r in res["results"]:
        bad = ", ".join(r["unapproved"]) if r["unapproved"] else "none"
        struct = "; ".join(name for name, ok in r["structure"] if not ok) or "all checks pass"
        lines.append(f"| {r['name']} | {r['title']} | {bad} | {struct} | "
                     f"{'✅' if r['pass'] else '❌'} |")
    return lines


def main() -> None:
    res = run_report_eval()
    print(f"\nReport pipeline: {res['n_pass']}/{res['n']} datasets fully grounded + structural\n")
    for r in res["results"]:
        print(f"  [{'PASS' if r['pass'] else 'FAIL'}] {r['name']}: \"{r['title']}\"")
        for fig in r["unapproved"]:
            print(f"         unapproved figure: {fig}")
        for name, ok in r["structure"]:
            if not ok:
                print(f"         structure: {name}")


if __name__ == "__main__":
    main()
