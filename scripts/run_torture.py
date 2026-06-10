"""Run the full pipeline on every torture dataset and save the decks for human review.

For each dataset it loads the data, builds a report, renders the PPTX/PDF, and records
whether it crashed, how many LLM-cited figures were ungrounded (should be 0), and basic
structure. Outputs land in data/torture/out/ with an index.md summary.

    python scripts/run_torture.py        (makes real LLM calls — costs API money)
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.torture_datasets import DATASETS, INTENTS, OUT  # noqa: E402
from scripts.torture_datasets import main as gen_datasets  # noqa: E402
from src.analysis import compute_battery  # noqa: E402
from src.data_tool import drop_table, load_file_to_sqlite, profile_dataset  # noqa: E402
from src.render import render_report  # noqa: E402
from src.report import _plan_sections, _unapproved_figures, build_report  # noqa: E402
from src.schemas import ReportRequest  # noqa: E402

OUTDIR = OUT / "out"


def _ungrounded(report, table: str) -> list[str]:
    """Re-derive approved figures deterministically and flag any $/% the report cites
    outside them (the same grounding check the eval uses)."""
    try:
        profile = profile_dataset(table=table)
        battery = compute_battery(profile)
        specs = _plan_sections(battery, profile)
    except Exception:  # noqa: BLE001
        return []  # if we can't rebuild, don't claim a violation
    union = sorted({fig for s in specs for fig in s["approved"]})
    by_kicker = {s["kicker"]: s for s in specs}
    bad: list[str] = []
    for sec in report.sections:
        spec = by_kicker.get(sec.kicker)
        approved = spec["approved"] if spec else union
        text = " ".join([sec.action_title, sec.narrative, *sec.bullets, sec.so_what or ""])
        bad += _unapproved_figures(text, approved)
    gtext = " ".join([report.title, report.governing_thought,
                      *[km.text for km in report.key_messages], *report.recommendations])
    bad += _unapproved_figures(gtext, union)
    return bad


def run_one(name: str) -> dict:
    table = f"torture_{name}"
    csv = OUT / f"{name}.csv"
    rec: dict = {"name": name, "status": "ok", "detail": "", "rows": 0,
                 "sections": 0, "ungrounded": 0, "pptx": "", "pdf": ""}
    try:
        rec["rows"] = load_file_to_sqlite(csv, table=table)
        report = build_report(ReportRequest(intent=INTENTS[name], table=table))
        paths = render_report(report, out_dir=OUTDIR / name, charts_dir=OUTDIR / name / "charts")
        bad = _ungrounded(report, table)
        rec.update(sections=len(report.sections), ungrounded=len(bad),
                   title=report.title, period=report.period,
                   pptx=str(paths["pptx"]), pdf=str(paths.get("pdf") or ""))
        if bad:
            rec["status"] = "ungrounded"
            rec["detail"] = "; ".join(bad[:6])
    except ValueError as e:               # intentional guardrail (e.g. no numeric measure)
        rec["status"] = "rejected"
        rec["detail"] = str(e)
    except Exception as e:                # noqa: BLE001 — capture crashes, don't stop the run
        rec["status"] = "CRASH"
        rec["detail"] = f"{type(e).__name__}: {e}"
        rec["trace"] = traceback.format_exc()
    finally:
        try:
            drop_table(table)
        except Exception:  # noqa: BLE001
            pass
    return rec


def main() -> None:
    gen_datasets()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    results = []
    for name in DATASETS:
        t0 = time.monotonic()
        print(f"\n=== {name} ===")
        rec = run_one(name)
        rec["secs"] = round(time.monotonic() - t0, 1)
        flag = {"ok": "OK", "rejected": "REJECTED (clean)", "ungrounded": "UNGROUNDED",
                "CRASH": "CRASH"}[rec["status"]]
        print(f"  -> {flag}  rows={rec['rows']} sections={rec['sections']} "
              f"ungrounded={rec['ungrounded']} {rec['secs']}s")
        if rec["detail"]:
            print(f"     {rec['detail']}")
        results.append(rec)

    # index.md summary
    lines = ["# Torture-test results", "",
             "Each dataset is run end-to-end (load -> profile -> battery -> report -> render). "
             "`ungrounded` counts $/% figures the report cited that are not in the database-derived "
             "approved set (should be 0). `rejected (clean)` means an intentional guardrail fired "
             "with a clear message (not a crash).", "",
             "| Dataset | Status | Rows | Sections | Ungrounded | Time | Title / detail |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        title = r.get("title", "") or r["detail"]
        lines.append(f"| {r['name']} | {r['status']} | {r['rows']} | {r['sections']} | "
                     f"{r['ungrounded']} | {r['secs']}s | {title} |")
    n_crash = sum(r["status"] == "CRASH" for r in results)
    n_bad = sum(r["ungrounded"] for r in results)
    lines += ["", f"**Crashes: {n_crash}/{len(results)}  ·  total ungrounded figures: {n_bad}**", ""]
    for r in results:
        if r.get("trace"):
            lines += [f"### {r['name']} traceback", "```", r["trace"].strip(), "```", ""]
    (OUTDIR / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {OUTDIR / 'index.md'}  (decks saved per dataset under {OUTDIR})")
    print(f"Crashes: {n_crash}/{len(results)}   total ungrounded figures: {n_bad}")


if __name__ == "__main__":
    main()
