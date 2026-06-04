"""The report engine: a LangGraph state machine that builds a grounded Report.

Flow:  analyze -> plan -> write -> verify -> assemble

Design principle that makes it trustworthy: the MODEL writes prose; the SYSTEM owns the
numbers. Charts are built from the real analytical battery (never the LLM), and the writer
is given an explicit list of "approved figures" it is allowed to cite. The verify node
then checks that no $ or % figure outside that approved set appears in the text, and
regenerates a section once if it finds one.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.analysis import compute_battery
from src.config import get_chat_model, get_settings
from src.data_tool import profile_dataset
from src.schemas import (ChartSpec, KeyMessage, Report, ReportRequest, ReportSection)


# --------------------------------------------------------------------------- #
# Number formatting (used for BOTH approved figures and chart labels)
# --------------------------------------------------------------------------- #
def money(x) -> str:
    if x is None:
        return "n/a"
    x = float(x)
    ax = abs(x)
    if ax >= 1e6:
        return f"${x / 1e6:.2f}M"
    if ax >= 1e3:
        return f"${x / 1e3:.0f}k"
    return f"${x:,.0f}"


def signed_money(x) -> str:
    if x is None:
        return "n/a"
    return ("+" if x >= 0 else "-") + money(abs(x))


def pct(frac: Optional[float], signed: bool = True) -> str:
    if frac is None:
        return "n/a"
    return f"{frac * 100:+.1f}%" if signed else f"{frac * 100:.1f}%"


# --------------------------------------------------------------------------- #
# Structured-output drafts (the LLM fills ONLY text fields)
# --------------------------------------------------------------------------- #
class SectionDraft(BaseModel):
    action_title: str = Field(description="Full-sentence assertion <=15 words, active voice, includes a number")
    narrative: str = Field(description="2-4 sentence explanation grounded in the figures")
    bullets: list[str] = Field(default_factory=list, description="2-3 short supporting points")
    so_what: str = Field(description="One-sentence takeaway / implication")


class ExecDraft(BaseModel):
    governing_thought: str = Field(description="One sentence the whole report proves")
    key_messages: list[KeyMessage] = Field(description="3-5 assertions, each with a number and a status")


class RecsDraft(BaseModel):
    recommendations: list[str] = Field(description="3-4 specific, verb-first actions grounded in the findings")


# --------------------------------------------------------------------------- #
# Plan: turn the battery into section specs (pure Python, no LLM)
# --------------------------------------------------------------------------- #
def _table_md(columns: list[str], rows: list[list], limit: int = 12) -> str:
    head = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows[:limit]]
    return "\n".join([head, sep, *body])


def _dim_facts(battery: dict, dim: str) -> dict:
    """Pull the notable facts for one dimension: leader, its share, biggest +/- movers."""
    bd = battery["dimensions"][dim]["breakdown"].rows      # [value, total] desc
    mv = battery["dimensions"][dim]["movers"].rows          # [value, cur, prev, delta] by |delta|
    total = battery["period_total"] or 1.0
    leader = bd[0] if bd else [None, 0]
    risers = [r for r in mv if (r[3] or 0) > 0]
    fallers = [r for r in mv if (r[3] or 0) < 0]
    top_riser = max(risers, key=lambda r: r[3]) if risers else None
    top_faller = min(fallers, key=lambda r: r[3]) if fallers else None
    return {
        "leader": leader, "leader_share": (leader[1] or 0) / total,
        "top_riser": top_riser, "top_faller": top_faller,
    }


def _plan_sections(battery: dict, profile) -> list[dict]:
    m = battery["primary_measure"]
    period, prior = battery["period"], battery["prior"]
    specs: list[dict] = []

    # --- Executive summary ---
    if battery["prior_total"] is not None:
        exec_lines = [f"Total {m}: {money(battery['period_total'])} in {period} "
                      f"(prior {prior}: {money(battery['prior_total'])}, change {pct(battery['delta_pct'])})."]
        approved = [money(battery["period_total"]), money(battery["prior_total"]),
                    pct(battery["delta_pct"]), signed_money(battery["delta"])]
    else:
        exec_lines = [f"Total {m}: {money(battery['period_total'])} across {period}."]
        approved = [money(battery["period_total"])]
    for dim in profile.dimensions:
        f = _dim_facts(battery, dim)
        if f["leader"][0] is not None:
            exec_lines.append(f"Top {dim}: {f['leader'][0]} at {money(f['leader'][1])} "
                              f"({pct(f['leader_share'], signed=False)} of total).")
            approved += [money(f["leader"][1]), pct(f["leader_share"], signed=False)]
        if f["top_faller"]:
            r = f["top_faller"]
            exec_lines.append(f"Biggest {dim} decline: {r[0]} {signed_money(r[3])} vs prior.")
            approved.append(signed_money(r[3]))
    specs.append({
        "id": "exec", "kind": "exec", "kicker": "EXECUTIVE SUMMARY",
        "instruction": "Write the executive summary as a governing thought plus 3-5 key messages. "
                       "Each key message is an assertion that includes a figure; set status to "
                       "positive/negative/neutral.",
        "grounding": "\n".join(exec_lines), "approved": approved, "chart": None,
    })

    # --- Performance vs prior (trend line) — only when the data has a time axis ---
    trend = battery["trend"]
    if trend is not None and trend.rows:
        months = [r[0] for r in trend.rows]
        totals = [float(r[1] or 0) for r in trend.rows]
        peak_val = max(totals) if totals else 0
        perf_chart = ChartSpec(kind="line", title=f"Monthly {m}", x=months,
                               series={m: totals}, highlight=months[-1] if months else None)
        specs.append({
            "id": "performance", "kind": "insight", "kicker": "FINANCIAL PERFORMANCE",
            "instruction": f"Describe how {m} performed in {period} versus the prior month and the "
                           f"recent trend (note any seasonal peak).",
            "grounding": (f"Total {m} {period}: {money(battery['period_total'])} vs {prior}: "
                          f"{money(battery['prior_total'])} ({pct(battery['delta_pct'])}). Peak month "
                          f"{money(peak_val)}.\n\n{trend.title}\n{_table_md(trend.columns, trend.rows)}"),
            "approved": [money(battery["period_total"]), money(battery["prior_total"]),
                         pct(battery["delta_pct"]), signed_money(battery["delta"]), money(peak_val)],
            "chart": perf_chart,
        })

    # --- One insight slide per dimension (bar) ---
    for dim in profile.dimensions:
        bd = battery["dimensions"][dim]["breakdown"]
        mv = battery["dimensions"][dim]["movers"]
        f = _dim_facts(battery, dim)
        x = [str(r[0]) for r in bd.rows]
        vals = [float(r[1] or 0) for r in bd.rows]
        chart = ChartSpec(kind="bar", title=f"{m} by {dim} ({period})", x=x,
                          series={m: vals}, highlight=x[0] if x else None)
        approved = [money(f["leader"][1]), pct(f["leader_share"], signed=False)]
        if f["top_riser"]:
            approved += [signed_money(f["top_riser"][3])]
        if f["top_faller"]:
            approved += [signed_money(f["top_faller"][3])]
        grounding = f"{bd.title}\n{_table_md(bd.columns, bd.rows)}"
        instruction = f"Explain the {m} breakdown by {dim} for {period}: who leads and the concentration"
        if mv.rows:
            grounding += f"\n\n{mv.title}\n{_table_md(mv.columns, mv.rows, limit=6)}"
            instruction += ", plus the biggest mover versus the prior period."
        else:
            instruction += "."
        specs.append({
            "id": f"dim_{dim}", "kind": "insight", "kicker": f"{dim.upper()} BREAKDOWN",
            "instruction": instruction, "grounding": grounding,
            "approved": approved, "chart": chart,
        })

    # --- Recommendations ---
    specs.append({
        "id": "reco", "kind": "reco", "kicker": "RECOMMENDATIONS",
        "instruction": "Given the findings, write 3-4 specific, prioritized, verb-first "
                       "recommendations a finance leader could act on next month.",
        "grounding": "\n".join(exec_lines), "approved": approved, "chart": None,
    })
    return specs


# --------------------------------------------------------------------------- #
# Write + verify
# --------------------------------------------------------------------------- #
_WRITER_SYS = (
    "You are a management consultant writing a board-ready finance report in the McKinsey/BCG "
    "style. The action title is the most important element: state the single key INSIGHT or its "
    "implication as a full-sentence assertion (<=15 words, active voice, include the key number) "
    "-- never a topic label like 'Revenue overview'. A reader skimming only the titles slide "
    "after slide should get the whole story, so prefer 'why it matters' over 'what it is'. "
    "Refer to the metric by the exact name used in the data (for example actual, spend, budget, "
    "units); do NOT call it revenue unless that is genuinely its name. "
    "Write in crisp, executive prose. CRITICAL: you may cite ONLY the approved figures given to "
    "you, using those exact strings. Never invent or recompute any other number."
)

_FIG_RE = re.compile(r"[-+]?\$\s?\d[\d,]*(?:\.\d+)?\s*[kKmMbB]?|[-+]?\d[\d,]*(?:\.\d+)?\s*%")


def _norm(t: str) -> str:
    return t.replace("$", "").replace(",", "").replace(" ", "").replace("+", "").lower()


def _unapproved_figures(text: str, approved: list[str]) -> list[str]:
    ok = {_norm(a) for a in approved}
    return [t for t in _FIG_RE.findall(text) if _norm(t) not in ok]


def _draft(spec: dict, model: str = None, strict: str = "") -> Any:
    kind = spec["kind"]
    schema = {"exec": ExecDraft, "reco": RecsDraft}.get(kind, SectionDraft)
    llm = get_chat_model(temperature=0.3).with_structured_output(schema)
    user = (f"{spec['instruction']}\n\nGrounded data:\n{spec['grounding']}\n\n"
            f"Approved figures you may cite (use these exact strings, nothing else): "
            f"{spec['approved']}{strict}")
    return llm.invoke([{"role": "system", "content": _WRITER_SYS}, {"role": "user", "content": user}])


def _section_from_draft(spec: dict, draft: SectionDraft) -> ReportSection:
    return ReportSection(
        kicker=spec["kicker"], action_title=draft.action_title, narrative=draft.narrative,
        bullets=draft.bullets, so_what=draft.so_what, chart=spec.get("chart"),
        citations=[f'{spec["id"]}: {spec["chart"].title}'] if spec.get("chart") else [],
    )


# --------------------------------------------------------------------------- #
# LangGraph nodes
# --------------------------------------------------------------------------- #
class GState(TypedDict, total=False):
    request: ReportRequest
    profile: Any
    battery: dict
    plan: list[dict]
    exec_draft: ExecDraft
    recs: list[str]
    sections: list[ReportSection]
    report: Report


_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _period_from_intent(intent: Optional[str]) -> Optional[str]:
    """Pull an explicit 'YYYY-MM' or 'Month YYYY' out of the prompt; else None (=latest)."""
    t = (intent or "").lower()
    m = re.search(r"(20\d\d)[-/ ](0[1-9]|1[0-2])\b", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(20\d\d)\b", t)
    if m:
        return f"{m.group(2)}-{_MONTHS[m.group(1)]:02d}"
    return None


def node_analyze(state: GState) -> dict:
    req = state["request"]
    profile = profile_dataset(table=req.table)
    period = req.period or _period_from_intent(req.intent)
    battery = compute_battery(profile, period=period)
    return {"profile": profile, "battery": battery}


def node_plan(state: GState) -> dict:
    return {"plan": _plan_sections(state["battery"], state["profile"])}


def node_write(state: GState) -> dict:
    sections: list[ReportSection] = []
    exec_draft, recs = None, []
    for spec in state["plan"]:
        draft = _draft(spec)
        if spec["kind"] == "exec":
            exec_draft = draft
        elif spec["kind"] == "reco":
            recs = draft.recommendations
        else:
            sections.append(_section_from_draft(spec, draft))
    return {"sections": sections, "exec_draft": exec_draft, "recs": recs}


def node_verify(state: GState) -> dict:
    """Re-check each written section for figures outside its approved set; regenerate once."""
    specs = {s["id"]: s for s in state["plan"]}
    fixed: list[ReportSection] = []
    for sec in state["sections"]:
        spec_id = sec.citations[0].split(":")[0] if sec.citations else None
        spec = specs.get(spec_id) or next(
            (s for s in state["plan"] if s["kicker"] == sec.kicker), None)
        if not spec:
            fixed.append(sec)
            continue
        text = " ".join([sec.action_title, sec.narrative, *sec.bullets, sec.so_what or ""])
        bad = _unapproved_figures(text, spec["approved"])
        if bad:
            strict = (f"\n\nA previous draft invented these figures: {bad}. Rewrite using ONLY "
                      f"the approved figures above.")
            sec = _section_from_draft(spec, _draft(spec, strict=strict))
        fixed.append(sec)
    return {"sections": fixed}


def node_assemble(state: GState) -> dict:
    b, profile, req = state["battery"], state["profile"], state["request"]
    ed: ExecDraft = state["exec_draft"]
    report = Report(
        title=req.intent.title() if req.intent else "Business Review",
        subtitle=f"Period {b['period']}  |  source table: {b['table']}",
        period=b["period"],
        governing_thought=ed.governing_thought if ed else "",
        key_messages=ed.key_messages if ed else [],
        sections=state["sections"],
        recommendations=state.get("recs", []),
        sources=[f"{b['table']} ({profile.n_rows:,} rows), measure: {b['primary_measure']}, "
                 f"period {b['period']} vs {b['prior']}; figures verified against the database."],
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    return {"report": report}


def _build_graph():
    g = StateGraph(GState)
    g.add_node("analyze", node_analyze)
    g.add_node("plan_sections", node_plan)
    g.add_node("write", node_write)
    g.add_node("verify", node_verify)
    g.add_node("assemble", node_assemble)
    g.add_edge(START, "analyze")
    g.add_edge("analyze", "plan_sections")
    g.add_edge("plan_sections", "write")
    g.add_edge("write", "verify")
    g.add_edge("verify", "assemble")
    g.add_edge("assemble", END)
    return g.compile()


GRAPH = _build_graph()


def build_report(request: Optional[ReportRequest] = None) -> Report:
    request = request or ReportRequest()
    final = GRAPH.invoke({"request": request})
    report = final["report"]
    try:  # persist for the UI/API and for cheap design iteration (render without re-LLM)
        out = Path(get_settings().out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    except Exception:
        pass
    return report


if __name__ == "__main__":
    rep = build_report(ReportRequest(intent="Monthly sales review", table="sales"))
    print(f"# {rep.title}")
    print(f"{rep.subtitle}\n")
    print(f"Governing thought: {rep.governing_thought}\n")
    print("Key messages:")
    for km in rep.key_messages:
        print(f"  [{km.status}] {km.text}")
    print("\nSections:")
    for s in rep.sections:
        chart = f"  (chart: {s.chart.kind})" if s.chart else ""
        print(f"  - {s.action_title}{chart}")
        print(f"      so what: {s.so_what}")
    print("\nRecommendations:")
    for r in rep.recommendations:
        print(f"  - {r}")
    print("\nSources:", rep.sources[0])
