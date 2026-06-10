"""Usage caps: per-client monthly allowance + global daily ceiling."""

import importlib


def _fresh_limits(tmp_path, monkeypatch, daily_reports=10_000, daily_questions=10_000):
    """A freshly-imported limits module pointed at a temp usage DB, with the global
    daily ceilings set via env (read at import time)."""
    monkeypatch.setenv("GLOBAL_DAILY_REPORTS", str(daily_reports))
    monkeypatch.setenv("GLOBAL_DAILY_QUESTIONS", str(daily_questions))
    import src.config as config
    monkeypatch.setattr(config.get_settings(), "db_path", tmp_path / "db" / "x.sqlite")
    import src.limits as lim
    return importlib.reload(lim)


def test_per_client_monthly_cap(tmp_path, monkeypatch):
    lim = _fresh_limits(tmp_path, monkeypatch)  # generous global ceiling
    for _ in range(lim.LIMITS["report"]):
        ok, _ = lim.check("1.2.3.4", "report")
        assert ok
        lim.consume("1.2.3.4", "report")
    ok, reason = lim.check("1.2.3.4", "report")
    assert not ok and "month" in reason.lower()


def test_other_client_unaffected_by_first(tmp_path, monkeypatch):
    lim = _fresh_limits(tmp_path, monkeypatch)
    for _ in range(lim.LIMITS["report"]):
        lim.consume("1.1.1.1", "report")
    ok, _ = lim.check("2.2.2.2", "report")  # different client still has its allowance
    assert ok


def test_global_daily_ceiling_blocks_all_clients(tmp_path, monkeypatch):
    lim = _fresh_limits(tmp_path, monkeypatch, daily_reports=3)
    for i in range(3):                        # 3 distinct clients each do one report
        ok, _ = lim.check(f"ip{i}", "report")
        assert ok
        lim.consume(f"ip{i}", "report")
    ok, reason = lim.check("ip-new", "report")  # fresh client, but global is exhausted
    assert not ok and "capacity" in reason.lower()


def test_consume_counts_against_both_layers(tmp_path, monkeypatch):
    lim = _fresh_limits(tmp_path, monkeypatch)
    lim.consume("ip0", "question")
    assert lim.global_used("question") == 1
    assert lim.used("ip0", "question") == 1
