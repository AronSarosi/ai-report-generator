"""Streamlit UI for the AI report generator.

One capability: Generate Report - data + a prompt -> a board-ready PPTX/PDF.

Run from the project root:
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

# Streamlit runs this file with app/ on sys.path, not the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from src.branding import extract_brand  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.data_tool import load_file_to_sqlite, profile_dataset  # noqa: E402
from src.legal import CONTACT_EMAIL, PRIVACY_MD, TERMS_MD  # noqa: E402
from src.limits import check, consume  # noqa: E402
from src.render import render_report  # noqa: E402
from src.report import build_report  # noqa: E402
from src.schemas import ReportRequest  # noqa: E402

_FAVICON = Path(__file__).parent / "favicon.png"
st.set_page_config(page_title="AI Report Generator",
                   page_icon=str(_FAVICON) if _FAVICON.exists() else None,
                   layout="wide", initial_sidebar_state="collapsed")
settings = get_settings()
UPLOAD_TYPES = ["csv", "tsv", "xlsx", "xlsm", "xls", "json"]

# Warm scheme shared across the portfolio tools (Contract Generator is the reference).
# Palette: base #F2ECE3, card #FBF8F2, ink #221E19, body #5B544B, muted #8A8175,
# line #E0D8CB, terracotta #B5532E, deep terracotta #99431F.
# Fonts: Newsreader (serif headings) + Inter (body).
# Minimum sizes: nothing below 10pt (~0.84rem); written text >= 11pt (~0.92rem).
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400;1,6..72,500&family=Inter:wght@400;500;600;700&display=swap');
/* Shared modular type scale (Perfect Fourth ~1.333), matched to theme.py across all tools. */
:root {
  --h1: clamp(2.5rem, 5vw, 3.75rem);
  --subhead: 1.15rem;
  --eyebrow: 0.8rem;
  --caption: 0.85rem;
}
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer, .stDeployButton {display:none !important;}
header[data-testid="stHeader"] {background:transparent;}
[data-testid="stAppViewContainer"] {background-color:#F2ECE3; background-image:linear-gradient(#221E1907 1px,transparent 1px),linear-gradient(90deg,#221E1907 1px,transparent 1px); background-size:88px 88px;}
html, body, [class*="css"], .stMarkdown, p, span, div, label {font-family:'Inter',-apple-system,Segoe UI,sans-serif;}
/* Modest top spacing: a centred hero that's not jammed to the top, no big empty gap. */
.block-container {padding-top:2.2rem; padding-bottom:2.5rem; max-width:1360px;}

/* Shared hero header */
.hero-head {text-align:center; max-width:900px; margin:0 auto 1.9rem auto;}
.eyebrow {font-family:'Inter',sans-serif; font-size:var(--eyebrow); font-weight:600; letter-spacing:.22em; text-transform:uppercase; color:#B5532E; margin-bottom:1.1rem;}
.app-title {font-family:'Newsreader',Georgia,serif; color:#221E19; font-weight:500; font-size:var(--h1); line-height:1.06; letter-spacing:-.02em; margin-bottom:.0rem; white-space:nowrap;}
@media (max-width:680px) {.app-title {white-space:normal;}}
.app-title .accent {color:#B5532E; font-style:italic;}
.app-sub {color:#5B544B; font-size:var(--subhead); max-width:620px; margin:1.4rem auto 0 auto; line-height:1.55;}

/* Trust chips (shared credibility cue, matched to theme.py .trust pattern). */
.trust {display:flex; flex-wrap:wrap; justify-content:center; gap:.6rem; margin:1.3rem auto 0; max-width:760px;}
.trust .chip {display:inline-flex; align-items:center; gap:.5rem; background:#FFFFFF; border:1px solid #E0D8CB; border-radius:999px; padding:.4rem .9rem; font-size:var(--caption); color:#5B544B; font-weight:500;}
.trust .chip::before {content:""; width:7px; height:7px; border-radius:50%; background:#B5532E; flex:none;}

.field-label {font-size:1.08rem; font-weight:600; color:#221E19; margin:.65rem 0 .3rem 0;}
.lede {color:#5B544B; font-size:1.2rem; line-height:1.5; margin:.7rem 0 .9rem 0;}
.hint {color:#8A8175; font-size:.95rem; margin:.3rem 0 .2rem 0;}
.datastatus {background:#FBF8F2; border:1px solid #E0D8CB; color:#221E19; padding:.6rem .85rem; border-radius:6px; font-size:.98rem; margin:.5rem 0 .6rem 0;}
.datachip {display:inline-block; background:#F2ECE3; border:1px solid #E0D8CB; color:#5B544B; border-radius:12px; padding:.1rem .65rem; font-size:.92rem; margin:.45rem .3rem 0 0;}

/* Browse files == Use sample data: identical width, identical right inset */
section[data-testid="stFileUploaderDropzone"] {padding-right:1rem;}
section[data-testid="stFileUploaderDropzone"] button {min-width:160px; width:160px; font-size:1.0rem;}
section[data-testid="stFileUploaderDropzone"] small {font-size:.92rem;}
div[class*="st-key-sample_"] .stButton {display:flex; justify-content:flex-end; padding-right:1rem;}
div[class*="st-key-sample_"] button {min-width:160px; width:160px; font-size:1.0rem;}
.st-key-gen_btn button {min-width:200px;}
.stTextArea textarea::placeholder, .stTextInput input::placeholder {font-style:italic; color:#8A8175;}

/* illustration: input  ->  arrow + prompt  ->  output.
   Fixed-width blocks + one uniform gap == identical space on BOTH sides of the middle. */
.hero {display:flex; align-items:center; justify-content:center; gap:3rem; flex-wrap:wrap; margin:1rem auto 2.6rem;}
.hero-col {flex:0 0 auto; width:340px; display:flex; flex-direction:column; align-items:center; text-align:center;}
.hero-cap {letter-spacing:.08em; font-size:.9rem; color:#8A8175; font-weight:700; margin-bottom:.55rem;}
.hero-mid {display:flex; flex-direction:column; align-items:center; gap:.7rem; flex:0 0 auto; width:210px;}
.hero-prompt {background:#FBF8F2; border:1px solid #E0D8CB; border-radius:11px; padding:.6rem .8rem; font-size:.92rem; color:#5B544B; text-align:left; line-height:1.42;}
.straight-arrow {line-height:0;}
.stack {position:relative; width:300px; height:240px; margin:0 auto;}
.filecard {position:absolute; left:50%; top:6px; width:288px; background:#fff; border:1px solid #E0D8CB; border-radius:9px; box-shadow:0 10px 26px rgba(34,30,25,.18); padding:.5rem .6rem .35rem .6rem;}
.filecard.back {transform:translate(-66%,30px) rotate(-5deg);}
.filecard.front {transform:translate(-50%,0);}
.fc-tag {display:inline-block; font-size:.88rem; font-weight:700; color:#fff; border-radius:3px; padding:.06rem .45rem; margin-bottom:.45rem;}
.tag-csv {background:#B5532E;} .tag-xlsx {background:transparent; color:#221E19; padding:0;}
.minitbl {width:100%; border-collapse:collapse; font-size:.86rem;}
.minitbl th {background:#221E19; color:#fff; padding:2px 5px; text-align:left;}
.minitbl td {border-bottom:1px solid #E0D8CB; padding:2px 5px; color:#5B544B;}
.report-thumb {width:300px; margin:0 auto; background:#fff; border:1px solid #E0D8CB; border-radius:9px; box-shadow:0 10px 26px rgba(34,30,25,.18); padding:.6rem; text-align:left;}
.rt-kicker {font-size:.86rem; color:#B5532E; font-weight:700; letter-spacing:.08em;}
.rt-title {font-family:'Newsreader',Georgia,serif; color:#221E19; font-weight:600; font-size:1.05rem; line-height:1.18; margin:.25rem 0 .65rem 0;}
.rt-bars {display:flex; align-items:flex-end; gap:3px; height:50px;}
.rt-bars span {flex:1; background:#E0D8CB; border-radius:2px 2px 0 0;}
.rt-bars span.hi {background:#B5532E;}
.rt-take {margin-top:.65rem; background:#F6EDE6; border-left:3px solid #B5532E; border-radius:3px; padding:.4rem .55rem; font-size:.72rem; color:#221E19; line-height:1.32;}
.rt-take b {font-size:.64rem; letter-spacing:.06em; color:#B5532E;}
/* subtle footer links + the standalone privacy/terms pages */
.footlink {color:#8A8175 !important; text-decoration:none !important; font-size:.85rem; margin:0 .55rem;}
.footlink:hover {color:#B5532E !important; text-decoration:none !important;}
.footsep {color:#B7AD9E;}
.policy-title {text-align:center; font-family:'Newsreader',Georgia,serif; color:#221E19; font-weight:500; font-size:2.4rem; margin:.6rem 0 .3rem 0;}
.policy-back {color:#8A8175; text-decoration:none; font-size:.95rem;}
.policy-back:hover {color:#B5532E; text-decoration:underline;}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Routing: ?page=privacy and ?page=terms render as their own themed pages.
# (Opened in a new tab from the footer; same background + brand as the main app.)
# --------------------------------------------------------------------------- #
_page = st.query_params.get("page")
if _page in ("privacy", "terms"):
    _title = "Privacy" if _page == "privacy" else "Terms of Use"
    _body = PRIVACY_MD if _page == "privacy" else TERMS_MD
    _lcol, _mcol, _rcol = st.columns([1, 3, 1])
    with _mcol:
        st.markdown(f"<div class='policy-title'>{_title}</div>", unsafe_allow_html=True)
        st.markdown("<div style='text-align:center; margin-bottom:1.4rem;'>"
                    "<a class='policy-back' href='?'>&larr; Back to the app</a></div>",
                    unsafe_allow_html=True)
        st.markdown(_body)
    st.stop()


def field_label(text: str) -> None:
    st.markdown(f"<div class='field-label'>{text}</div>", unsafe_allow_html=True)


def hint(text: str) -> None:
    st.markdown(f"<div class='hint'>{text}</div>", unsafe_allow_html=True)


# Project root (used for the bundled sample dataset and favicon paths).
_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Fair-use limits (lead-magnet gating; the OpenAI spend cap is the hard backstop)
# --------------------------------------------------------------------------- #
def _client_id() -> str:
    """Stable id for fair-use limits: the client IP if the host exposes it, else a session id."""
    try:
        h = st.context.headers
        fwd = (h.get("X-Forwarded-For") or h.get("X-Real-Ip") or "") if h else ""
        ip = fwd.split(",")[0].strip()
        if ip:
            return ip
    except Exception:  # noqa: BLE001
        pass
    if "_cid" not in st.session_state:
        import uuid
        st.session_state["_cid"] = "sess-" + uuid.uuid4().hex[:12]
    return st.session_state["_cid"]


def _limit_msg(reason: str) -> str:
    return (f"{reason} This is a free demo. If you'd like to use it for real, or have a custom "
            f"version built for your team, get in touch: {CONTACT_EMAIL}.")


# --------------------------------------------------------------------------- #
# Shared data handling (the uploaded or sample dataset, via session_state)
# --------------------------------------------------------------------------- #
# The bundled demo dataset (Dockerfile runs scripts/gen_sales_data.py at build).
_SAMPLE_CSV = _ROOT / "data" / "out" / "sales_sample.csv"


def _safe_table(name: str) -> str:
    t = re.sub(r"[^a-z0-9_]", "_", Path(name).stem.lower()).strip("_") or "data"
    return "t_" + t if t[0].isdigit() else t


def _unique_table(base: str, taken) -> str:
    """Give each distinct upload its own table name. If the filename stem already maps to a
    loaded table, suffix a counter (base_2, base_3, ...) so two files with the same stem
    don't silently clobber one another (load_file_to_sqlite uses if_exists="replace")."""
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


def _process_uploads(files) -> None:
    st.session_state.setdefault("tables", {})
    st.session_state.setdefault("processed", set())
    for f in files:
        sig = (f.name, f.size)
        if sig in st.session_state["processed"]:
            continue
        # `processed` already stops a re-upload of the same file re-entering here, so each
        # new file gets a fresh, non-clobbering table name.
        table = _unique_table(_safe_table(f.name), st.session_state["tables"])
        tmp = Path(tempfile.gettempdir()) / f"upload_{table}{Path(f.name).suffix}"
        tmp.write_bytes(f.getvalue())
        try:
            n = load_file_to_sqlite(tmp, table=table)
            st.session_state["tables"][table] = {"rows": n, "file": f.name}
            st.session_state["processed"].add(sig)
            st.session_state["active_table"] = table
        except Exception as e:  # noqa: BLE001
            st.error(f"Couldn't load {f.name}: {e}")
        finally:
            # The raw upload isn't needed once it's in SQLite, so delete it right away.
            try:
                tmp.unlink()
            except OSError:
                pass


def _load_sample() -> bool:
    """Load the bundled sample sales dataset into SQLite, the same path uploads take.

    Generated at build time (scripts/gen_sales_data.py); if it's missing locally,
    generate it on the fly so the button still works. Returns True on success.
    """
    if not _SAMPLE_CSV.exists():
        try:
            from scripts.gen_sales_data import main as _gen_sales
            _gen_sales()
        except Exception as e:  # noqa: BLE001
            st.error(f"Couldn't prepare the sample data: {e}")
            return False
    table = _safe_table(_SAMPLE_CSV.name)
    try:
        n = load_file_to_sqlite(_SAMPLE_CSV, table=table)
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't load the sample data: {e}")
        return False
    st.session_state.setdefault("tables", {})
    st.session_state["tables"][table] = {"rows": n, "file": _SAMPLE_CSV.name}
    st.session_state["active_table"] = table
    return True


def _no_numeric_measure(table: str) -> bool:
    """True when the active table has no numeric measure for the report to headline. Caught
    early so all-text datasets get a friendly note instead of a mid-pipeline error. If the
    profile can't be read here, fall through (False) and let the pipeline surface its own
    clean message rather than blocking on a profiling hiccup."""
    try:
        return not profile_dataset(table=table).measures
    except Exception:  # noqa: BLE001
        return False


def data_uploader(suffix: str) -> None:
    """Just the data drag-and-drop. Status + picker are rendered by data_status()."""
    field_label("Upload your data (CSV or Excel, one or more files)")
    files = st.file_uploader("data", type=UPLOAD_TYPES, accept_multiple_files=True,
                             key=f"up_{suffix}", label_visibility="collapsed")
    if files:
        _process_uploads(files)
    # Sit beside the uploader's Browse button (CSS keys off st-key-sample_).
    if st.button("Use sample data", key=f"sample_{suffix}"):
        if _load_sample():
            st.rerun()


def data_status(suffix: str) -> str | None:
    """Shared status + active-dataset picker for the loaded data. Returns the active table."""
    tables = st.session_state.get("tables", {})
    if not tables:
        hint("Upload a CSV or Excel file to begin.")
        return None

    names = list(tables.keys())
    msg = "Your data is loaded and ready."
    chips = "".join(f"<span class='datachip'>{tables[t]['file']} · {tables[t]['rows']:,} rows</span>"
                    for t in names)
    st.markdown(f"<div class='datastatus'>&#10003; {msg}<br>{chips}</div>", unsafe_allow_html=True)

    if len(names) > 1:
        hint("Each file loads as its own dataset. Pick which one to use. (Cross-file joins are coming.)")
        cur = st.session_state.get("active_table", names[0])
        active = st.selectbox("Active dataset", names,
                              index=names.index(cur) if cur in names else 0, key=f"act_{suffix}",
                              format_func=lambda t: tables[t]["file"])
        st.session_state["active_table"] = active
        return active
    return names[0]


def brand_uploader() -> None:
    """The optional brand-template drag-and-drop (+ its own status). Sets st.session_state['brand']."""
    field_label("Brand template (optional)")
    tmpl = st.file_uploader("template", type=["pptx", "potx"], key="tmpl_gen",
                            label_visibility="collapsed",
                            help="Upload a PowerPoint template or a past report and the deck adopts "
                                 "its brand colors and fonts. Leave empty for the default style.")
    if tmpl is not None:
        sig = (tmpl.name, tmpl.size)
        if st.session_state.get("_brand_sig") != sig:
            tpath = Path(tempfile.gettempdir()) / "template_upload.pptx"
            tpath.write_bytes(tmpl.getvalue())
            st.session_state["brand"] = extract_brand(tpath)
            st.session_state["_brand_sig"] = sig
            try:
                tpath.unlink()
            except OSError:
                pass
        brand = st.session_state.get("brand") or {}
        if brand:
            st.markdown(
                f"<div class='datastatus'>&#10003; Brand picked up from <b>{tmpl.name}</b>, accent "
                f"<b>{brand.get('accent', 'n/a')}</b>, fonts <b>{brand.get('font_head', 'n/a')}</b> / "
                f"<b>{brand.get('font_body', 'n/a')}</b>. Your deck will use these.</div>",
                unsafe_allow_html=True)
        else:
            hint("Couldn't read a theme from that file, so the deck will use the default style.")
    else:
        st.session_state.pop("brand", None)
        st.session_state.pop("_brand_sig", None)
        hint("Optional: give the deck your brand. Without a template it uses the clean default style.")


# --------------------------------------------------------------------------- #
# "How it works" illustrations (one per capability)
# --------------------------------------------------------------------------- #
_DATA_CARDS = """
  <div class="hero-col">
    <div class="hero-cap">YOUR DATA &middot; CSV / EXCEL</div>
    <div class="stack">
      <div class="filecard back">
        <span class="fc-tag tag-csv">sales.csv</span>
        <table class="minitbl"><tr><th>date</th><th>region</th><th>channel</th><th>revenue</th></tr>
        <tr><td>2026-05</td><td>US</td><td>Online</td><td>257k</td></tr>
        <tr><td>2026-05</td><td>EMEA</td><td>Store</td><td>184k</td></tr>
        <tr><td>2026-05</td><td>APAC</td><td>Online</td><td>229k</td></tr>
        <tr><td>2026-04</td><td>LATAM</td><td>Store</td><td>112k</td></tr>
        <tr><td>2026-04</td><td>US</td><td>Online</td><td>246k</td></tr></table>
      </div>
      <div class="filecard front">
        <span class="fc-tag tag-xlsx">budget.xlsx</span>
        <table class="minitbl"><tr><th>dept</th><th>budget</th><th>actual</th><th>var</th></tr>
        <tr><td>Sales</td><td>120k</td><td>131k</td><td>+11k</td></tr>
        <tr><td>Mktg</td><td>80k</td><td>74k</td><td>-6k</td></tr>
        <tr><td>R&amp;D</td><td>60k</td><td>58k</td><td>-2k</td></tr>
        <tr><td>Ops</td><td>95k</td><td>99k</td><td>+4k</td></tr>
        <tr><td>G&amp;A</td><td>40k</td><td>38k</td><td>-2k</td></tr></table>
      </div>
    </div>
  </div>
"""

_BARS = ("".join(f'<span style="height:{h}%"></span>' for h in
                 (38, 52, 60, 48, 70, 82, 64)) +
         '<span class="hi" style="height:100%"></span>' +
         "".join(f'<span style="height:{h}%"></span>' for h in (74, 58, 46)))

# One clean, straight arrow pointing input -> output. Nothing overlaps it.
STRAIGHT_ARROW = ('<svg class="straight-arrow" width="150" height="30" viewBox="0 0 150 30" '
                  'fill="none" stroke="#B5532E" stroke-width="5" stroke-linecap="round" '
                  'stroke-linejoin="round"><path d="M6 15 L132 15"/>'
                  '<path d="M132 15 L116 6"/><path d="M132 15 L116 24"/></svg>')

HERO_GENERATE = f"""
<div class="hero">
  {_DATA_CARDS}
  <div class="hero-mid">
    <div class="hero-prompt">&ldquo;Generate a monthly sales report, highlighting the winning
    products and regions.&rdquo;</div>
    {STRAIGHT_ARROW}
  </div>
  <div class="hero-col">
    <div class="hero-cap">FINISHED REPORT</div>
    <div class="report-thumb">
      <div class="rt-kicker">FINANCIAL PERFORMANCE</div>
      <div class="rt-title">Revenue grew 5.1% to $1.01M, led by Beauty &amp; Wellness</div>
      <div class="rt-bars">{_BARS}</div>
      <div class="rt-take"><b>KEY TAKEAWAY</b><br>Beauty &amp; Wellness up 157%; LATAM down 28%. Shift budget to the winners.</div>
    </div>
  </div>
</div>
"""

# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.markdown(
    '<div class="hero-head">'
    '<div class="eyebrow">AI Report Generator</div>'
    '<div class="app-title">Drop the data. <span class="accent">Get the report.</span></div>'
    '<div class="app-sub">Upload your raw data, describe the report you want, and get a board-ready '
    'deck back - every figure computed from your data, never invented.</div>'
    '</div>'
    '<div class="trust">'
    '<span class="chip">Every figure from your data</span>'
    '<span class="chip">No invented numbers</span>'
    '<span class="chip">Board-ready in minutes</span>'
    '</div>',
    unsafe_allow_html=True)

# Hero illustration: input -> quoted prompt + arrow -> finished report. Matches the
# compact three-column "how it works" illustration used by the other portfolio tools.
st.markdown(HERO_GENERATE, unsafe_allow_html=True)

st.markdown("<div style='margin-top:0.4rem'></div>", unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Generate Report
# --------------------------------------------------------------------------- #
# Data and brand-template uploaders side by side: drop your data on the left, an
# optional brand template on the right. The data confirmation/picker spans below.
up_data, up_brand = st.columns(2)
with up_data:
    data_uploader("gen")
with up_brand:
    brand_uploader()
active = data_status("gen")

field_label("What report do you want?")
prompt = st.text_area(
    "prompt", key="gen_prompt", label_visibility="collapsed",
    placeholder="Example: Generate a monthly sales report highlighting the winning products and regions.",
    height=68,
    help="Describe the report in plain English. Mention a month (e.g. 'for May 2026') to pin the "
         "period, and what to focus on (winning products, weak regions, channel shifts).",
)
if st.button("Generate report", type="primary", key="gen_btn"):
    cid = _client_id()
    allowed, reason = check(cid, "report")
    if not active:
        st.warning('Upload a data file or click "Use sample data" first.')
    elif not prompt.strip():
        st.warning("Describe the report you want (see the example in the box).")
    elif not allowed:
        st.warning(_limit_msg(reason))
    elif _no_numeric_measure(active):
        st.warning("This dataset has no numeric measure to report on - add a numeric column "
                   "or try the sample data.")
    else:
        # Live, step-by-step progress so the wait is transparent and engaging.
        status = st.status("Generating your report… (usually 20-40 seconds)", expanded=True)
        try:
            report = build_report(ReportRequest(intent=prompt, table=active),
                                  progress=lambda label: status.write(f"✓ {label}"))
            status.write("✓ Rendering the slides and PDF")
            paths = render_report(report, brand=st.session_state.get("brand"))
            consume(cid, "report")  # only count a successful generation
            status.update(label=f"Report ready for period {report.period}.",
                          state="complete", expanded=False)
            st.session_state["gen_result"] = {
                "pptx": str(paths["pptx"]),
                "pdf": str(paths["pdf"]) if paths.get("pdf") else None,
                "period": report.period,
            }
        except ValueError as e:  # intentional guardrails -> show the clean message
            status.update(label="Couldn't generate the report", state="error")
            st.session_state.pop("gen_result", None)
            st.error(str(e))
        except Exception as e:  # noqa: BLE001
            status.update(label="Something went wrong", state="error")
            st.session_state.pop("gen_result", None)
            st.error(f"Something went wrong: {e}")

# Download buttons live outside the click branch so they survive the rerun a download
# triggers (otherwise downloading the PPTX would make the PDF button vanish).
res = st.session_state.get("gen_result")
if res:
    st.success(f"Your report for period {res['period']} is ready. Open it to view the full deck.")
    d1, d2 = st.columns(2)
    d1.download_button("Download PPTX", Path(res["pptx"]).read_bytes(), "report.pptx",
                       "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    if res["pdf"]:
        d2.download_button("Download PDF", Path(res["pdf"]).read_bytes(),
                           "report.pdf", "application/pdf")

# --------------------------------------------------------------------------- #
# Footer: subtle, centered Privacy / Terms links (each opens its own themed page)
# --------------------------------------------------------------------------- #
st.markdown(
    "<div style='text-align:center; margin-top:9rem;'>"
    "<a class='footlink' href='?page=privacy' target='_blank'>Privacy</a>"
    "<span class='footsep'>&middot;</span>"
    "<a class='footlink' href='?page=terms' target='_blank'>Terms of Use</a>"
    "</div>", unsafe_allow_html=True)
