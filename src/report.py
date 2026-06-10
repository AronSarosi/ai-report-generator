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
from typing import Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.analysis import compute_battery
from src.config import get_chat_model, get_settings
from src.data_tool import profile_dataset
from src.obs import get_callbacks
from src.schemas import ChartSpec, KeyMessage, Report, ReportRequest, ReportSection


# --------------------------------------------------------------------------- #
# Number formatting (used for BOTH approved figures and chart labels)
# --------------------------------------------------------------------------- #
def money(x) -> str:
    if x is None:
        return "n/a"
    x = float(x)
    if x != x:  # NaN (NaN is the only value not equal to itself)
        return "n/a"
    ax = abs(x)
    if ax >= 1e12:
        return f"${x / 1e12:.2f}T"
    if ax >= 1e9:
        return f"${x / 1e9:.2f}B"
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


_SMALL_WORDS = {"a", "an", "the", "of", "for", "vs", "and", "or", "in", "on", "to",
                "by", "with", "at", "from", "as"}


def smart_title(text: str) -> str:
    """Title-case a user phrase but keep small words lowercase (never returns empty)."""
    words = (text or "").split()
    if not words:
        return "Business Review"
    return " ".join(w.lower() if (i and w.lower() in _SMALL_WORDS) else (w[:1].upper() + w[1:])
                    for i, w in enumerate(words))


def _fallback_title(table: Optional[str]) -> str:
    """A clean, data-derived title when the model doesn't give a good one."""
    name = (table or "data").replace("_", " ").strip()
    return smart_title(f"{name} Performance Review")


def _no_dashes(s: str) -> str:
    """Strip em/en dashes from model-written text (em-dashes are unwanted in the output)."""
    if not s:
        return s
    for a, b in ((" — ", ", "), (" – ", ", "), ("—", ", "), ("–", "-")):
        s = s.replace(a, b)
    return s


# --------------------------------------------------------------------------- #
# Structured-output drafts (the LLM fills ONLY text fields)
# --------------------------------------------------------------------------- #
class SectionDraft(BaseModel):
    action_title: str = Field(description="Full-sentence assertion <=15 words, active voice, "
                                          "includes a number")
    narrative: str = Field(description="2-4 sentence explanation grounded in the figures")
    bullets: list[str] = Field(default_factory=list, description="2-3 short supporting points")
    so_what: str = Field(description="One-sentence takeaway / implication")


class ExecDraft(BaseModel):
    title: str = Field(description="A concise, board-ready report title of 3-6 words that names "
                       "the subject and the angle (e.g. 'Monthly Sales Performance', "
                       "'Budget vs Actuals Review'). Do NOT copy the user's prompt verbatim.")
    governing_thought: str = Field(description="One sentence the whole report proves")
    key_messages: list[KeyMessage] = Field(description="3-5 assertions, each with a number and a status")


class RecsDraft(BaseModel):
    recommendations: list[str] = Field(description="3-4 specific, verb-first actions grounded "
                                                   "in the findings")


# --------------------------------------------------------------------------- #
# Plan: turn the battery into section specs (pure Python, no LLM)
# --------------------------------------------------------------------------- #
def _table_md(columns: list[str], rows: list[list], limit: int = 12) -> str:
    head = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows[:limit]]
    return "\n".join([head, sep, *body])


# A dataset can have many dimensions; one LLM-written section per dimension is the main
# cost driver (a 50-column upload would mean ~50 sections). Cap the report's breadth.
_MAX_DIMS = 6
# Bars per breakdown chart: more than this is unreadable on a slide (and the leader/
# concentration story lives in the top values anyway).
_MAX_BARS = 15


def _label(v) -> str:
    """Human label for a dimension value, mapping SQL NULL / blanks to a clear token
    instead of the literal 'None'."""
    if v is None:
        return "(blank)"
    s = str(v).strip()
    return s or "(blank)"


def _dim_facts(battery: dict, dim: str) -> dict:
    """Pull the notable facts for one dimension: leader, its share, biggest +/- movers."""
    bd = battery["dimensions"][dim]["breakdown"].rows      # [value, total] desc
    mv = battery["dimensions"][dim]["movers"].rows          # [value, cur, prev, delta] by |delta|
    total = battery["period_total"] or 0.0
    leader = bd[0] if bd else [None, 0]
    # Share is only meaningful with a positive total (avoid 5,000,000% when total<=0).
    leader_share = (leader[1] or 0) / total if total > 0 else None
    risers = [r for r in mv if (r[3] or 0) > 0]
    fallers = [r for r in mv if (r[3] or 0) < 0]
    top_riser = max(risers, key=lambda r: r[3]) if risers else None
    top_faller = min(fallers, key=lambda r: r[3]) if fallers else None
    return {
        "leader": leader, "leader_share": leader_share,
        "top_riser": top_riser, "top_faller": top_faller,
    }


def _plan_sections(battery: dict, profile) -> list[dict]:
    m = battery["primary_measure"]
    period, prior = battery["period"], battery["prior"]
    specs: list[dict] = []

    # --- Executive summary ---
    if battery["prior_total"] is not None:
        exec_lines = [f"Total {m}: {money(battery['period_total'])} in {period} "
                      f"(prior {prior}: {money(battery['prior_total'])}, "
                      f"change {pct(battery['delta_pct'])})."]
        approved = [money(battery["period_total"]), money(battery["prior_total"]),
                    pct(battery["delta_pct"]), signed_money(battery["delta"])]
    else:
        exec_lines = [f"Total {m}: {money(battery['period_total'])} across {period}."]
        approved = [money(battery["period_total"])]
    dims = profile.dimensions[:_MAX_DIMS]
    for dim in dims:
        f = _dim_facts(battery, dim)
        if f["leader"][0] is not None:
            share = (f"({pct(f['leader_share'], signed=False)} of total)"
                     if f["leader_share"] is not None else "")
            exec_lines.append(f"Top {dim}: {_label(f['leader'][0])} at {money(f['leader'][1])} {share}.")
            approved += [money(f["leader"][1]), pct(f["leader_share"], signed=False)]
        if f["top_faller"]:
            r = f["top_faller"]
            exec_lines.append(f"Biggest {dim} decline: {_label(r[0])} {signed_money(r[3])} vs prior.")
            approved.append(signed_money(r[3]))
    specs.append({
        "id": "exec", "kind": "exec", "kicker": "EXECUTIVE SUMMARY",
        "instruction": "Write a concise 3-6 word report title (name the subject and angle, do not "
                       "copy the user's prompt), a governing thought, and 3-5 key messages. "
                       "Each key message is an assertion that includes a figure; set status to "
                       "positive/negative/neutral.",
        "grounding": "\n".join(exec_lines), "approved": approved, "chart": None,
    })

    # --- Performance vs prior (trend line) — only when the data has a time axis ---
    trend = battery["trend"]
    if trend is not None and trend.rows:
        months = [_label(r[0]) for r in trend.rows]
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
            # Approve every figure the grounding table shows, not just the headline:
            # the model may legitimately cite any month from the trend it was given.
            "approved": [money(battery["period_total"]), money(battery["prior_total"]),
                         pct(battery["delta_pct"]), signed_money(battery["delta"]), money(peak_val),
                         *[money(t) for t in totals]],
            "chart": perf_chart,
        })

    # --- One insight slide per dimension (bar). Cap both the number of dimensions
    # (cost) and the bars per chart (readability — a 1000-value dimension is unreadable). ---
    for dim in dims:
        bd = battery["dimensions"][dim]["breakdown"]
        mv = battery["dimensions"][dim]["movers"]
        f = _dim_facts(battery, dim)
        x = [_label(r[0]) for r in bd.rows[:_MAX_BARS]]
        vals = [float(r[1] or 0) for r in bd.rows[:_MAX_BARS]]
        chart = ChartSpec(kind="bar", title=f"{m} by {dim} ({period})", x=x,
                          series={m: vals}, highlight=x[0] if x else None)
        approved = [money(f["leader"][1]), pct(f["leader_share"], signed=False)]
        if f["top_riser"]:
            approved += [signed_money(f["top_riser"][3])]
        if f["top_faller"]:
            approved += [signed_money(f["top_faller"][3])]
        # Every value shown in the grounding tables is a real SQL result, so the model
        # may cite it: approve the breakdown rows it sees (_table_md shows 12) ...
        approved += [money(r[1]) for r in bd.rows[:12]]
        grounding = f"{bd.title}\n{_table_md(bd.columns, bd.rows)}"
        instruction = f"Explain the {m} breakdown by {dim} for {period}: who leads and the concentration"
        if mv.rows:
            grounding += f"\n\n{mv.title}\n{_table_md(mv.columns, mv.rows, limit=6)}"
            instruction += ", plus the biggest mover versus the prior period."
            # ... and the mover rows (current, prior, delta for the 6 shown).
            for r in mv.rows[:6]:
                approved += [money(r[1]), money(r[2]), signed_money(r[3])]
        else:
            instruction += "."
        specs.append({
            "id": f"dim_{dim}", "kind": "insight", "kicker": f"{dim.upper()} BREAKDOWN",
            "instruction": instruction, "grounding": grounding,
            "approved": approved, "chart": chart,
        })

    # --- Recommendations ---
    # Approved set = the exec summary's (specs[0]): the grounding is the same exec_lines,
    # NOT the last dimension's loop-local `approved`.
    specs.append({
        "id": "reco", "kind": "reco", "kicker": "RECOMMENDATIONS",
        "instruction": "Given the findings, write 3-4 specific, prioritized, verb-first "
                       "recommendations a finance leader could act on next month.",
        "grounding": "\n".join(exec_lines), "approved": list(specs[0]["approved"]), "chart": None,
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
    "you, using those exact strings. Never invent or recompute any other number: no sums, "
    "differences, ratios, roundings, or percentages of your own. If the figure you want is not "
    "in the approved list, express the point in words without a number."
)

# A number must END on a digit ("\d(?:[\d,]*\d)?"), or the match would swallow a
# trailing comma in running text ("$1,591, and").
_FIG_RE = re.compile(
    r"[-+]?\$\s?\d(?:[\d,]*\d)?(?:\.\d+)?\s*[kKmMbB]?|[-+]?\d(?:[\d,]*\d)?(?:\.\d+)?\s*%")


def _norm(t: str) -> str:
    return t.replace("$", "").replace(",", "").replace(" ", "").replace("+", "").lower()


def _unapproved_figures(text: str, approved: list[str]) -> list[str]:
    ok = {_norm(a) for a in approved}
    # Prose legitimately moves a figure's sign into words ("declined by $10k" for the
    # approved "-$10k"), so an UNSIGNED citation also matches a signed approved figure.
    # An explicit "-" in the text still has to match exactly.
    ok |= {n.lstrip("-") for n in ok}
    return [t for t in _FIG_RE.findall(text) if _norm(t) not in ok]


def _draft(spec: dict, strict: str = "", config=None) -> Any:
    kind = spec["kind"]
    schema = {"exec": ExecDraft, "reco": RecsDraft}.get(kind, SectionDraft)
    llm = get_chat_model(temperature=0.3).with_structured_output(schema)
    user = (f"{spec['instruction']}\n\nGrounded data:\n{spec['grounding']}\n\n"
            f"Approved figures you may cite (use these exact strings, nothing else): "
            f"{spec['approved']}{strict}")
    return llm.invoke([{"role": "system", "content": _WRITER_SYS}, {"role": "user", "content": user}],
                      config=config)


def _section_from_draft(spec: dict, draft: SectionDraft) -> ReportSection:
    return ReportSection(
        kicker=spec["kicker"], action_title=_no_dashes(draft.action_title),
        narrative=_no_dashes(draft.narrative), bullets=[_no_dashes(b) for b in draft.bullets],
        so_what=_no_dashes(draft.so_what), chart=spec.get("chart"),
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


def node_write(state: GState, config=None) -> dict:
    sections: list[ReportSection] = []
    exec_draft, recs = None, []
    for spec in state["plan"]:
        draft = _draft(spec, config=config)
        if spec["kind"] == "exec":
            exec_draft = draft
        elif spec["kind"] == "reco":
            recs = draft.recommendations
        else:
            sections.append(_section_from_draft(spec, draft))
    return {"sections": sections, "exec_draft": exec_draft, "recs": recs}


_MAX_REGEN = 3


def _strict_note(bad: list[str]) -> str:
    return (f"\n\nA previous draft cited figures that are NOT in the approved list: {bad}. "
            f"These were computed or invented — that is forbidden. Rewrite using ONLY the "
            f"approved figures above, as exact strings. If a number you want is not approved, "
            f"omit it and describe the point in words instead.")


def _verify_section(spec: dict, sec: ReportSection, config=None) -> ReportSection:
    """Regenerate a section while it cites unapproved figures (bounded retries),
    re-checking each redraft — a redraft can invent new figures too."""
    for _ in range(_MAX_REGEN + 1):  # final iteration is a check without a regen budget
        text = " ".join([sec.action_title, sec.narrative, *sec.bullets, sec.so_what or ""])
        bad = _unapproved_figures(text, spec["approved"])
        if not bad:
            break
        sec = _section_from_draft(spec, _draft(spec, strict=_strict_note(bad), config=config))
    return sec


def node_verify(state: GState, config=None) -> dict:
    """Re-check everything the LLM wrote — sections AND the exec summary AND the
    recommendations — for figures outside the approved sets; regenerate offenders."""
    specs = {s["id"]: s for s in state["plan"]}
    fixed: list[ReportSection] = []
    for sec in state["sections"]:
        spec_id = sec.citations[0].split(":")[0] if sec.citations else None
        spec = specs.get(spec_id) or next(
            (s for s in state["plan"] if s["kicker"] == sec.kicker), None)
        fixed.append(_verify_section(spec, sec, config) if spec else sec)
    out: dict = {"sections": fixed}

    # Exec draft: title + governing thought + key messages.
    ed, exec_spec = state.get("exec_draft"), specs.get("exec")
    if ed and exec_spec:
        for _ in range(_MAX_REGEN + 1):
            text = " ".join([ed.title, ed.governing_thought, *[km.text for km in ed.key_messages]])
            bad = _unapproved_figures(text, exec_spec["approved"])
            if not bad:
                break
            ed = _draft(exec_spec, strict=_strict_note(bad), config=config)
        out["exec_draft"] = ed

    # Recommendations.
    recs, reco_spec = state.get("recs"), specs.get("reco")
    if recs and reco_spec:
        for _ in range(_MAX_REGEN + 1):
            bad = _unapproved_figures(" ".join(recs), reco_spec["approved"])
            if not bad:
                break
            recs = _draft(reco_spec, strict=_strict_note(bad), config=config).recommendations
        out["recs"] = recs

    return out


def node_assemble(state: GState) -> dict:
    b, profile = state["battery"], state["profile"]
    ed: ExecDraft = state["exec_draft"]
    # Prefer the model's concise title; fall back to a clean data-derived one. Guard against
    # the model echoing a long prompt (a title should be short).
    title = (ed.title or "").strip() if ed else ""
    if not title or len(title.split()) > 9:
        title = _fallback_title(b["table"])
    report = Report(
        title=_no_dashes(smart_title(title)),
        subtitle=f"Period {b['period']}  |  source table: {b['table']}",
        period=b["period"],
        governing_thought=_no_dashes(ed.governing_thought) if ed else "",
        key_messages=[km.model_copy(update={"text": _no_dashes(km.text)})
                      for km in ed.key_messages] if ed else [],
        sections=state["sections"],
        recommendations=[_no_dashes(r) for r in state.get("recs", [])],
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


# Human-readable label for each graph node, surfaced as live progress in the UI.
_STEP_LABELS = {
    "analyze": "Profiling the data and computing the analytics",
    "plan_sections": "Planning the report sections",
    "write": "Writing the narrative",
    "verify": "Verifying every figure against the data",
    "assemble": "Assembling the report",
}


def build_report(request: Optional[ReportRequest] = None,
                 progress: Optional[Callable[[str], None]] = None) -> Report:
    """Build the report. If `progress` is given, it is called with a human-readable label
    as each pipeline step (analyze->plan->write->verify->assemble) completes."""
    request = request or ReportRequest()
    # Pass the Langfuse callback so the whole analyze->plan->write->verify->assemble run
    # is captured as one trace (with every nested LLM call) in the Langfuse dashboard.
    cfg = {"callbacks": get_callbacks()}
    if progress is None:
        report = GRAPH.invoke({"request": request}, config=cfg)["report"]
    else:
        report = None
        # stream_mode="updates" yields {node_name: state_delta} after each node runs.
        for chunk in GRAPH.stream({"request": request}, config=cfg, stream_mode="updates"):
            for node, delta in chunk.items():
                if node in _STEP_LABELS:
                    progress(_STEP_LABELS[node])
                if isinstance(delta, dict) and "report" in delta:
                    report = delta["report"]
        if report is None:  # safety net if streaming didn't surface the assembled report
            report = GRAPH.invoke({"request": request}, config=cfg)["report"]
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
