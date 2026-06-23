"""Smoke test for src/render.py.

Deterministic and LLM-free: build a small fixed Report by hand, render it, and assert
that a .pptx deck and at least one chart PNG are written without error. PDF export needs
LibreOffice, so it is allowed to be absent (the renderer degrades to PPTX-only).
"""

from __future__ import annotations

from src.render import render_report
from src.schemas import ChartSpec, KeyMessage, Report, ReportSection


def _small_report() -> Report:
    return Report(
        title="Monthly Sales Review",
        subtitle="A small fixed report used only to exercise the renderer.",
        period="2026-05",
        governing_thought="Revenue grew, led by the North region.",
        key_messages=[
            KeyMessage(text="Total revenue rose versus the prior month.", status="positive"),
            KeyMessage(text="North led the regional breakdown.", status="neutral"),
        ],
        sections=[
            ReportSection(
                kicker="TREND",
                action_title="Revenue climbed through the period",
                narrative="Revenue rose steadily across the months shown.",
                bullets=["Up versus prior month", "Driven by North"],
                so_what="Momentum is positive heading into next month.",
                chart=ChartSpec(
                    kind="trend",
                    title="Monthly revenue",
                    x=["Jan", "Feb", "Mar"],
                    series={"revenue": [100.0, 130.0, 160.0]},
                ),
                citations=["sales"],
            ),
            ReportSection(
                kicker="BREAKDOWN",
                action_title="North leads the regional split",
                narrative="North accounts for the largest share of revenue.",
                bullets=["North is the top region"],
                so_what="Focus retention effort on North.",
                chart=ChartSpec(
                    kind="bar",
                    title="Revenue by region",
                    x=["North", "South", "East"],
                    series={"revenue": [160.0, 90.0, 60.0]},
                    highlight="North",
                ),
                citations=["sales"],
            ),
        ],
        recommendations=["Keep investing in the North region."],
        sources=["sales"],
    )


def test_render_report_writes_pptx_and_charts(tmp_path):
    out_dir = tmp_path / "out"
    charts_dir = tmp_path / "charts"

    paths = render_report(_small_report(), out_dir=out_dir, charts_dir=charts_dir)

    pptx_path = paths["pptx"]
    assert pptx_path.exists(), "renderer did not write a .pptx file"
    assert pptx_path.suffix == ".pptx"
    assert pptx_path.stat().st_size > 0

    charts = list(charts_dir.glob("*.png"))
    assert charts, "renderer did not write any chart PNGs"
    assert all(c.stat().st_size > 0 for c in charts)

    # PDF export depends on LibreOffice being installed; when it is absent the renderer
    # returns None rather than failing, so we only check the key is present.
    assert "pdf" in paths
