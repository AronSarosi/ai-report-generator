"""Run the complete evaluation suite and write the combined eval/REPORT.md.

    python eval/run_all.py        (from the project root; makes real LLM calls)

Covers both trust surfaces:
  - Talk2Data: golden-QA accuracy of LLM-generated SQL (eval/run_eval.py)
  - Report pipeline: figure grounding + structure of full generated reports
    (eval/run_report_eval.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import run_eval  # noqa: E402
import run_report_eval  # noqa: E402


def main() -> None:
    t2d = run_eval.run_talk2data()
    rep = run_report_eval.run_report_eval()

    print(f"\nTalk2Data accuracy:  {t2d['n_pass']}/{t2d['n']} ({t2d['n_pass'] / t2d['n']:.0%})")
    print(f"Report pipeline:     {rep['n_pass']}/{rep['n']} datasets pass")
    for r in rep["results"]:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  [{status}] {r['name']}: {len(r['unapproved'])} unapproved figures")

    lines = ["# Evaluation Report", "",
             *run_eval.section_md(t2d), "",
             *run_report_eval.section_md(rep)]
    (Path(__file__).parent / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nWrote eval/REPORT.md")


if __name__ == "__main__":
    main()
