"""Pure helpers in src.report: formatting, the figure regex, and the verifier."""

from src.report import (
    _FIG_RE,
    _no_dashes,
    _period_from_intent,
    _unapproved_figures,
    money,
    pct,
    signed_money,
    smart_title,
)


def test_money():
    assert money(1_234_567) == "$1.23M"
    assert money(45_200) == "$45k"
    assert money(950) == "$950"
    assert money(None) == "n/a"
    assert money(2_500_000_000) == "$2.50B"
    assert money(3_100_000_000_000) == "$3.10T"
    assert money(float("nan")) == "n/a"


def test_signed_money():
    assert signed_money(-3000) == "-$3k"
    assert signed_money(3000) == "+$3k"
    assert signed_money(None) == "n/a"


def test_pct():
    assert pct(0.123) == "+12.3%"
    assert pct(-0.05) == "-5.0%"
    assert pct(0.123, signed=False) == "12.3%"
    assert pct(None) == "n/a"


def test_smart_title():
    assert smart_title("revenue by region for q4") == "Revenue by Region for Q4"
    assert smart_title("the big picture") == "The Big Picture"  # first word always capped
    assert smart_title("") == "Business Review"


def test_no_dashes():
    assert _no_dashes("up — sharply") == "up, sharply"
    assert _no_dashes("a–b") == "a-b"
    assert _no_dashes("") == ""


def test_fig_regex_matches_report_figures():
    text = "Revenue hit $1.23M ($1,200 over plan, +4.5%), or $120k of margin (55.4%)."
    # matches may carry trailing whitespace (the regex allows space before a k/M/B
    # suffix); _norm strips it before comparison, so the test strips it too
    found = [m.strip() for m in _FIG_RE.findall(text)]
    assert "$1.23M" in found
    assert "$1,200" in found
    assert "+4.5%" in found
    assert "$120k" in found
    assert "55.4%" in found


def test_fig_regex_ignores_bare_years():
    assert _FIG_RE.findall("In 2026 we opened 3 stores") == []


def test_fig_regex_does_not_swallow_trailing_comma():
    # "$1,591, and" must match "$1,591" — not "$1,591," (numbers end on a digit)
    found = [m.strip() for m in _FIG_RE.findall("spent $1,591, and more")]
    assert found == ["$1,591"]


def test_unapproved_figures_pass_when_grounded():
    approved = ["$45k", "+4.5%", "$1.23M"]
    text = "Revenue reached $45k, up +4.5%, on track to $1.23M."
    assert _unapproved_figures(text, approved) == []


def test_unapproved_figures_normalizes_spacing_and_case():
    # "$ 45K" should match approved "$45k" via _norm
    assert _unapproved_figures("we made $ 45K", ["$45k"]) == []


def test_unapproved_figures_sign_in_prose():
    # "declined by $10k" cites approved "-$10k" with the sign carried by the words
    assert _unapproved_figures("actual declined by $10k", ["-$10k"]) == []
    # but a wrong magnitude is still flagged
    assert _unapproved_figures("actual declined by $12k", ["-$10k"]) == ["$12k"]


def test_unapproved_figures_flags_invented():
    bad = _unapproved_figures("Revenue reached $99k, up +12.0%", ["$45k", "+4.5%"])
    assert "$99k" in bad
    assert "+12.0%" in bad


def test_period_from_intent():
    assert _period_from_intent("review for March 2026") == "2026-03"
    assert _period_from_intent("the 2026-05 numbers") == "2026-05"
    assert _period_from_intent("monthly business review") is None
    assert _period_from_intent(None) is None
