"""_plan_sections: deterministic planning - section specs, charts, approved figures."""

from src.report import _FIG_RE, _plan_sections


def test_plan_structure(sales_battery, sales_profile):
    specs = _plan_sections(sales_battery, sales_profile)
    ids = [s["id"] for s in specs]
    assert ids[0] == "exec"
    assert "performance" in ids
    assert ids[-1] == "reco"
    for dim in sales_profile.dimensions:
        assert f"dim_{dim}" in ids


def test_insight_sections_have_charts(sales_battery, sales_profile):
    specs = _plan_sections(sales_battery, sales_profile)
    for s in specs:
        if s["kind"] == "insight":
            chart = s["chart"]
            assert chart is not None
            assert chart.x, f"chart for {s['id']} has empty x axis"
            name, values = next(iter(chart.series.items()))
            assert values, f"chart for {s['id']} has empty series"
        else:
            assert s["chart"] is None


def test_every_approved_figure_is_verifiable(sales_battery, sales_profile):
    # The verify node can only catch violations if the approved strings themselves
    # are matched by the figure regex - otherwise the writer cites them and the
    # verifier flags its own approved values.
    specs = _plan_sections(sales_battery, sales_profile)
    for s in specs:
        for fig in s["approved"]:
            assert _FIG_RE.fullmatch(fig), f"approved figure {fig!r} in {s['id']} not regex-matchable"


def test_grounding_is_nonempty(sales_battery, sales_profile):
    for s in _plan_sections(sales_battery, sales_profile):
        assert s["grounding"].strip()
        assert s["instruction"].strip()
        assert s["kicker"].strip()
