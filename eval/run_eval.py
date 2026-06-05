"""Run evaluation over the QA pairs and prove Talk2Data's numbers are correct.

For each known-answer question we compute the *ground truth* directly from the database,
then run the question through Talk2Data (LLM-generated read-only SQL) and check the answer
matches. Outputs a pass-rate and writes eval/REPORT.md. This is the automated trust signal:
proof that the system's numbers are right, not hallucinated.

Run from the project root:
    python eval/run_eval.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.data_tool import answer_data_question, run_select


def _is_num(x) -> bool:
    try:
        float(str(x).replace(",", "").replace("$", "").strip())
        return True
    except (ValueError, TypeError):
        return False


def _num(x) -> float:
    return float(str(x).replace(",", "").replace("$", "").strip())


def _matches(truth, rows) -> bool:
    """Is the ground-truth value present in the LLM's result (numeric tolerance / substring)?"""
    cells = [c for row in rows for c in row if c is not None]
    if _is_num(truth):
        t = _num(truth)
        return any(_is_num(c) and abs(_num(c) - t) <= max(1.0, abs(t) * 0.01) for c in cells)
    ts = str(truth).strip().lower()
    return any(ts in str(c).strip().lower() for c in cells)


def main() -> None:
    here = Path(__file__).parent
    pairs = yaml.safe_load((here / "qa_pairs.yaml").read_text(encoding="utf-8"))["qa_pairs"]

    results = []
    for p in pairs:
        truth_res = run_select(p["truth_sql"])
        truth = truth_res.rows[0][0] if truth_res.rows else None
        llm = answer_data_question(p["question"])
        ok = (not llm.error) and _matches(truth, llm.rows)
        got = llm.rows[0][0] if llm.rows else (llm.error or "(no rows)")
        results.append({"q": p["question"], "truth": truth, "got": got, "pass": ok})

    n = len(results)
    n_pass = sum(r["pass"] for r in results)
    print(f"\nTalk2Data accuracy: {n_pass}/{n} ({n_pass / n:.0%})\n")
    for r in results:
        print(f"  [{'PASS' if r['pass'] else 'FAIL'}] {r['q']}")
        print(f"         expected ~ {r['truth']}    got ~ {r['got']}")

    lines = [
        "# Evaluation Report", "",
        "Each question is answered by **Talk2Data** (LLM-generated read-only SQL); the answer "
        "is checked against the **ground truth** computed directly from the database. This is the "
        "automated proof that the numbers are correct, not hallucinated.", "",
        f"**Talk2Data accuracy: {n_pass}/{n} ({n_pass / n:.0%})**", "",
        "| # | Question | Expected | Got | Result |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"| {i} | {r['q']} | {r['truth']} | {r['got']} | {'✅' if r['pass'] else '❌'} |")
    (here / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nWrote eval/REPORT.md")


if __name__ == "__main__":
    main()
