"""Streamlit UI for the AI report generator.

Two clearly separated capabilities, sharing one uploaded dataset:
  - Generate Report: data + a prompt -> a board-ready PPTX/PDF.
  - Ask Your Data:    natural-language questions answered with safe SQL (Talk2Data).

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

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src.branding import extract_brand  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.data_tool import answer_data_question, load_file_to_sqlite, profile_dataset  # noqa: E402
from src.legal import CONTACT_EMAIL, PRIVACY_MD, TERMS_MD  # noqa: E402
from src.limits import LABEL, LIMITS, consume, remaining  # noqa: E402
from src.render import render_report  # noqa: E402
from src.report import build_report  # noqa: E402
from src.schemas import ReportRequest  # noqa: E402

_FAVICON = Path(__file__).parent / "favicon.png"
st.set_page_config(page_title="AI Report Generator",
                   page_icon=str(_FAVICON) if _FAVICON.exists() else None,
                   layout="wide", initial_sidebar_state="collapsed")
settings = get_settings()
UPLOAD_TYPES = ["csv", "tsv", "xlsx", "xlsm", "xls", "json"]

# Pre-filled prompts so clicking "Use sample data" lets the user run immediately.
SAMPLE_GEN_PROMPT = "Generate a monthly sales report highlighting the winning products and regions."
SAMPLE_CHAT_Q = "Which region declined the most last month?"

# Minimum sizes: nothing below 10pt (~0.84rem); written text >= 11pt (~0.92rem).
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Lato:wght@700;900&display=swap');
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer, .stDeployButton {display:none !important;}
header[data-testid="stHeader"] {background:transparent;}
[data-testid="stAppViewContainer"] {background-color:#0E1420; background-image:linear-gradient(#ffffff05 1px,transparent 1px),linear-gradient(90deg,#ffffff05 1px,transparent 1px); background-size:88px 88px;}
/* Symmetric breathing room: as much empty space below the content as above the title,
   so the page always scrolls a little past the illustration (never clips it). */
.block-container {padding-top:1.6rem; padding-bottom:7rem; max-width:1320px;}

.app-title {text-align:center; font-family:'Lato',-apple-system,Segoe UI,sans-serif; color:#EAF1FB; font-weight:900; font-size:2.35rem; letter-spacing:-.01em; margin-bottom:.12rem;}
.app-sub {text-align:center; color:#9AA4B4; font-size:1.0rem; max-width:880px; margin:0 auto 1.5rem auto; line-height:1.45;}

/* tabs: ONE joined full-width bar, split in half. Each box is fully colored
   (per-button background + border, so no uncolored strip at the bottom). */
.stTabs [data-baseweb="tab-list"] {display:flex; width:100%; gap:0; border:none; padding:0; margin:0;}
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] {display:none !important; height:0 !important; background:transparent !important;}
.stTabs [data-baseweb="tab"] {flex:1; justify-content:center; margin:0; background:#1F2A44; background-clip:border-box; border:1px solid #2E3C52; border-radius:0; padding:.6rem 1rem; color:#C9D2DE; box-shadow:none !important;}
.stTabs [data-baseweb="tab"]::after, .stTabs [data-baseweb="tab"]::before {display:none !important;}
.stTabs [data-baseweb="tab"]:first-of-type {border-radius:10px 0 0 10px;}
.stTabs [data-baseweb="tab"]:last-of-type {border-radius:0 10px 10px 0; border-left:none;}
.stTabs [data-baseweb="tab"] p {font-size:1.25rem; font-weight:700; color:#C9D2DE;}
.stTabs [aria-selected="true"] {background:#2E6DB4; border-color:#2E6DB4;}
.stTabs [aria-selected="true"] p {color:#fff;}

.field-label {font-size:1.08rem; font-weight:600; color:#EAF1FB; margin:.65rem 0 .3rem 0;}
.lede {color:#C9D2DE; font-size:1.2rem; line-height:1.5; margin:.7rem 0 .9rem 0;}
.hint {color:#8A94A6; font-size:.95rem; margin:.3rem 0 .2rem 0;}
.datastatus {background:#16202E; border:1px solid #2E3C52; color:#D6DCE6; padding:.6rem .85rem; border-radius:6px; font-size:.98rem; margin:.5rem 0 .6rem 0;}
.datachip {display:inline-block; background:#1A2231; border:1px solid #3A4660; color:#C4CCD8; border-radius:12px; padding:.1rem .65rem; font-size:.92rem; margin:.45rem .3rem 0 0;}

/* Browse files == Use sample data: identical width, identical right inset */
section[data-testid="stFileUploaderDropzone"] {padding-right:1rem;}
section[data-testid="stFileUploaderDropzone"] button {min-width:160px; width:160px; font-size:1.0rem;}
section[data-testid="stFileUploaderDropzone"] small {font-size:.92rem;}
div[class*="st-key-sample_"] .stButton {display:flex; justify-content:flex-end; padding-right:1rem;}
div[class*="st-key-sample_"] button {min-width:160px; width:160px; font-size:1.0rem;}
.st-key-gen_btn button, .st-key-ask_btn button {min-width:200px;}
.stTextArea textarea::placeholder, .stTextInput input::placeholder {font-style:italic; color:#7C8696;}

/* illustration: input  ->  arrow + prompt  ->  output.
   Fixed-width blocks + one uniform gap == identical space on BOTH sides of the middle. */
.hero {display:flex; align-items:center; justify-content:center; gap:3rem; flex-wrap:wrap; margin-top:1rem;}
.hero-col {flex:0 0 auto; width:340px; display:flex; flex-direction:column; align-items:center; text-align:center;}
.hero-cap {letter-spacing:.08em; font-size:.9rem; color:#9AA4B4; font-weight:700; margin-bottom:.55rem;}
.hero-mid {display:flex; flex-direction:column; align-items:center; gap:.7rem; flex:0 0 auto; width:210px;}
.hero-prompt {background:#1A2231; border:1px solid #3A4660; border-radius:11px; padding:.6rem .8rem; font-size:.92rem; color:#C4CCD8; text-align:left; line-height:1.42;}
.straight-arrow {line-height:0;}
.stack {position:relative; width:300px; height:196px; margin:0 auto;}
.filecard {position:absolute; left:50%; top:6px; width:288px; background:#fff; border:1px solid #C0C5C9; border-radius:9px; box-shadow:0 10px 26px rgba(0,0,0,.5); padding:.5rem .6rem .35rem .6rem;}
.filecard.back {transform:translate(-66%,30px) rotate(-5deg);}
.filecard.front {transform:translate(-50%,0);}
.fc-tag {display:inline-block; font-size:.88rem; font-weight:700; color:#fff; border-radius:3px; padding:.06rem .45rem; margin-bottom:.45rem;}
.tag-csv {background:#2E6DB4;} .tag-xlsx {background:transparent; color:#1F2A44; padding:0;}
.minitbl {width:100%; border-collapse:collapse; font-size:.86rem;}
.minitbl th {background:#1F2A44; color:#fff; padding:2px 5px; text-align:left;}
.minitbl td {border-bottom:1px solid #E6E8EB; padding:2px 5px; color:#3C4450;}
.report-thumb {width:300px; margin:0 auto; background:#fff; border:1px solid #C0C5C9; border-radius:9px; box-shadow:0 10px 26px rgba(0,0,0,.5); padding:.6rem; text-align:left;}
.rt-kicker {font-size:.86rem; color:#2E6DB4; font-weight:700; letter-spacing:.08em;}
.rt-title {font-family:Georgia,serif; color:#1F2A44; font-weight:700; font-size:1.0rem; line-height:1.18; margin:.25rem 0 .65rem 0;}
.rt-bars {display:flex; align-items:flex-end; gap:3px; height:50px;}
.rt-bars span {flex:1; background:#C0C5C9; border-radius:2px 2px 0 0;}
.rt-bars span.hi {background:#2E6DB4;}
.rt-take {margin-top:.65rem; background:#EAF2FB; border-left:3px solid #2E6DB4; border-radius:3px; padding:.45rem .55rem; font-size:.86rem; color:#1F2A44; line-height:1.35;}
/* chat bubbles */
.chat {width:300px; margin:0 auto; text-align:left;}
.bubble {max-width:86%; padding:.55rem .75rem; border-radius:14px; font-size:.96rem; margin-bottom:.55rem; line-height:1.3;}
.bubble.user {background:#2E6DB4; color:#fff; margin-left:auto;}
.bubble.ai {background:#fff; color:#1F2A44; border:1px solid #C0C5C9;}
/* subtle footer links + the standalone privacy/terms pages */
.footlink {color:#6E7889; text-decoration:none; font-size:.9rem; margin:0 .55rem;}
.footlink:hover {color:#C9D2DE; text-decoration:underline;}
.footsep {color:#3A4453;}
.policy-title {text-align:center; font-family:'Lato',-apple-system,Segoe UI,sans-serif; color:#EAF1FB; font-weight:900; font-size:2rem; margin:.6rem 0 .3rem 0;}
.policy-back {color:#9AA4B4; text-decoration:none; font-size:.95rem;}
.policy-back:hover {color:#C9D2DE; text-decoration:underline;}
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


def _limit_msg(kind: str) -> str:
    return (f"You've used all {LIMITS[kind]} free {LABEL[kind]} this month. This is a free demo. "
            f"If you'd like to use it for real, or have a custom version built for your team, "
            f"get in touch: {CONTACT_EMAIL}.")


def _usage_caption(kind: str) -> None:
    left = remaining(_client_id(), kind)
    st.markdown(f"<div class='hint'>{left} of {LIMITS[kind]} free {LABEL[kind]} left this month.</div>",
                unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Shared data handling (one upload, used by both tabs, via session_state)
# --------------------------------------------------------------------------- #
def _safe_table(name: str) -> str:
    t = re.sub(r"[^a-z0-9_]", "_", Path(name).stem.lower()).strip("_") or "data"
    return "t_" + t if t[0].isdigit() else t


def _process_uploads(files) -> None:
    st.session_state.setdefault("tables", {})
    st.session_state.setdefault("processed", set())
    for f in files:
        sig = (f.name, f.size)
        if sig in st.session_state["processed"]:
            continue
        table = _safe_table(f.name)
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


def _load_sample() -> None:
    st.session_state.setdefault("tables", {})
    if Path(settings.db_path).exists():
        try:
            prof = profile_dataset(table="sales")
            st.session_state["tables"]["sales"] = {"rows": prof.n_rows, "file": "sample sales data"}
            st.session_state["active_table"] = "sales"
            return
        except Exception:  # noqa: BLE001
            pass
    sample = Path(settings.out_dir) / "sales_sample.csv"
    if not sample.exists():
        # Fresh deploy with no baked-in data: generate the sample on demand.
        import subprocess
        gen = Path(__file__).resolve().parents[1] / "scripts" / "gen_sales_data.py"
        try:
            subprocess.run([sys.executable, str(gen)], check=True, capture_output=True, timeout=180)
        except Exception:  # noqa: BLE001
            pass
    if sample.exists():
        n = load_file_to_sqlite(sample, table="sales")
        st.session_state["tables"]["sales"] = {"rows": n, "file": "sample sales data"}
        st.session_state["active_table"] = "sales"


def data_panel(suffix: str) -> str | None:
    """Uploader + shared status + active-dataset picker. Returns the active table."""
    field_label("Upload your data (CSV or Excel, one or more files)")
    files = st.file_uploader("data", type=UPLOAD_TYPES, accept_multiple_files=True,
                             key=f"up_{suffix}", label_visibility="collapsed")
    if files:
        _process_uploads(files)

    tables = st.session_state.get("tables", {})
    if not tables:
        # Hint on the left, "Use sample data" on the right (same row, aligned under Browse files).
        c_hint, c_btn = st.columns([5, 1.6])
        c_hint.markdown("<div class='hint' style='margin-top:.55rem'>Upload a file, or click "
                        '"Use sample data", to begin.</div>', unsafe_allow_html=True)
        if c_btn.button("Use sample data", key=f"sample_{suffix}"):
            _load_sample()
            # Pre-fill this tab's prompt so the user can generate/ask right away. (Only the
            # current tab's widget is set (it is created after this, so the write is safe).
            if suffix == "gen" and not st.session_state.get("gen_prompt"):
                st.session_state["gen_prompt"] = SAMPLE_GEN_PROMPT
            elif suffix == "chat" and not st.session_state.get("chat_q"):
                st.session_state["chat_q"] = SAMPLE_CHAT_Q
            tables = st.session_state.get("tables", {})
    if not tables:
        return None

    names = list(tables.keys())
    is_sample = tables[names[0]]["file"] == "sample sales data"
    msg = ("Using the bundled <b>sample sales data</b>." if is_sample
           else "Your data is loaded and <b>shared across both tabs</b>.")
    chips = "".join(f"<span class='datachip'>{t} · {tables[t]['rows']:,} rows</span>" for t in names)
    st.markdown(f"<div class='datastatus'>&#10003; {msg}<br>{chips}</div>", unsafe_allow_html=True)

    if len(names) > 1:
        hint("Each file loads as its own dataset. Pick which one to use. (Cross-file joins are coming.)")
        cur = st.session_state.get("active_table", names[0])
        active = st.selectbox("Active dataset", names,
                              index=names.index(cur) if cur in names else 0, key=f"act_{suffix}")
        st.session_state["active_table"] = active
        return active
    return names[0]


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
                  'fill="none" stroke="#4A90D9" stroke-width="5" stroke-linecap="round" '
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

HERO_CHAT = f"""
<div class="hero">
  {_DATA_CARDS}
  <div class="hero-mid">
    <div class="hero-prompt">Ask anything in plain English, and the agent writes safe SQL and
    answers from your data.</div>
    {STRAIGHT_ARROW}
  </div>
  <div class="hero-col">
    <div class="hero-cap">LIVE CONVERSATION</div>
    <div class="chat">
      <div class="bubble user">Which region declined the most last month?</div>
      <div class="bubble ai">LATAM, down 12% versus the prior month ($112k).</div>
      <div class="bubble user">And the top product?</div>
      <div class="bubble ai">Wireless Earbuds at $173k, up 8%.</div>
    </div>
  </div>
</div>
"""


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.markdown('<div class="app-title">AI Report Generator</div>', unsafe_allow_html=True)
st.markdown('<div class="app-sub">Upload your sales, finance, or operations data and get a finished, '
            'board-ready report in seconds, with charts and a narrative grounded in the real figures. '
            'Or ask questions in plain English and get instant answers, all computed from your own '
            'data.</div>', unsafe_allow_html=True)

tab_gen, tab_chat = st.tabs(["Generate Report", "Ask Your Data"])

# --------------------------------------------------------------------------- #
# Tab 1 - Generate Report
# --------------------------------------------------------------------------- #
with tab_gen:
    active = data_panel("gen")

    # Optional brand template: the deck adopts its colors + fonts.
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
        if not active:
            st.warning('Upload a data file or click "Use sample data" first.')
        elif not prompt.strip():
            st.warning("Describe the report you want (see the example in the box).")
        elif remaining(cid, "report") <= 0:
            st.warning(_limit_msg("report"))
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
        d1.download_button("⬇ Download PPTX", Path(res["pptx"]).read_bytes(), "report.pptx",
                           "application/vnd.openxmlformats-officedocument.presentationml.presentation")
        if res["pdf"]:
            d2.download_button("⬇ Download PDF", Path(res["pdf"]).read_bytes(),
                               "report.pdf", "application/pdf")
    _usage_caption("report")
    st.markdown(HERO_GENERATE, unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Tab 2 - Ask Your Data
# --------------------------------------------------------------------------- #
with tab_chat:
    active = data_panel("chat")
    field_label("What do you want to know?")
    q = st.text_area("question", key="chat_q", label_visibility="collapsed", height=68,
                     placeholder="Example: Which region declined the most last month?")
    if st.button("Ask about your data", type="primary", key="ask_btn"):
        cid = _client_id()
        if not active:
            st.warning('Upload a data file or click "Use sample data" first.')
        elif not q.strip():
            st.warning("Type a question (see the example in the box).")
        elif remaining(cid, "question") <= 0:
            st.warning(_limit_msg("question"))
        else:
            with st.spinner("Working it out…"):
                res = answer_data_question(q, table=active)
            if res.error:
                st.error(res.error)
            else:
                consume(cid, "question")  # count a completed answer (rows or a valid empty result)
                if res.rows:
                    st.dataframe(pd.DataFrame(res.rows, columns=res.columns), use_container_width=True)
                else:
                    st.info("Query returned no rows.")
                with st.expander("View the SQL query"):
                    st.code(res.sql, language="sql")
    _usage_caption("question")
    st.markdown(HERO_CHAT, unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Footer: subtle, centered Privacy / Terms links (each opens its own themed page)
# --------------------------------------------------------------------------- #
st.markdown(
    "<div style='text-align:center; margin-top:3rem;'>"
    "<a class='footlink' href='?page=privacy' target='_blank'>Privacy</a>"
    "<span class='footsep'>&middot;</span>"
    "<a class='footlink' href='?page=terms' target='_blank'>Terms of Use</a>"
    "</div>", unsafe_allow_html=True)
