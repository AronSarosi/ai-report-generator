"""Usage caps: a per-user monthly allowance PLUS a global daily ceiling.

Two layers, because this is a public demo running on the owner's own OpenAI credit:

  1. Per-client monthly cap (best-effort, keyed by client IP) — stops one visitor from
     treating the demo as a free production tool. A lead-magnet gate, not a hard boundary.
  2. Global DAILY ceiling across ALL clients — the real backstop. No matter how many IPs
     (or spoofed forwarded headers) hit the app, total LLM-backed work per day is bounded,
     so a single abuser cannot drain the credit. This is the cheap, high-impact control.

The hardest backstop of all is still the OpenAI account-level spend cap (set that too).

Usage is stored in a small SQLite table. On a scale-to-zero host the file can reset when
the instance recycles — that only ever makes the caps *more* lenient briefly, never a
crash, and the global daily ceiling + account spend cap remain as backstops.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_settings

# Per-user monthly allowance.
LIMITS = {"report": 5, "question": 50}
LABEL = {"report": "reports", "question": "questions"}


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "")))
    except (ValueError, TypeError):
        return default


# Global daily ceiling across every client combined (env-overridable for tuning).
# Defaults bound worst-case spend: 100 reports/day * a fraction of a cent each is trivial.
GLOBAL_DAILY = {
    "report": _int_env("GLOBAL_DAILY_REPORTS", 100),
    "question": _int_env("GLOBAL_DAILY_QUESTIONS", 500),
}
_GLOBAL_CLIENT = "__global__"


def _db_path() -> Path:
    p = Path(get_settings().db_path).parent / "usage.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_db_path()), timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS usage ("
              "client_id TEXT, period TEXT, kind TEXT, count INTEGER, "
              "PRIMARY KEY (client_id, period, kind))")
    return c


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _used(conn: sqlite3.Connection, client_id: str, period: str, kind: str) -> int:
    row = conn.execute("SELECT count FROM usage WHERE client_id=? AND period=? AND kind=?",
                       (client_id, period, kind)).fetchone()
    return int(row[0]) if row else 0


def used(client_id: str, kind: str) -> int:
    with closing(_conn()) as c:
        return _used(c, client_id, _month(), kind)


def remaining(client_id: str, kind: str) -> int:
    return max(0, LIMITS[kind] - used(client_id, kind))


def global_used(kind: str) -> int:
    with closing(_conn()) as c:
        return _used(c, _GLOBAL_CLIENT, _day(), kind)


def global_remaining(kind: str) -> int:
    return max(0, GLOBAL_DAILY[kind] - global_used(kind))


def check(client_id: str, kind: str) -> tuple[bool, str]:
    """Gate one request. Returns (allowed, reason). Checks the global daily ceiling first
    (the hard backstop), then the per-client monthly allowance."""
    if global_remaining(kind) <= 0:
        return False, ("The demo has reached today's overall capacity for "
                       f"{LABEL[kind]}. Please try again tomorrow.")
    if remaining(client_id, kind) <= 0:
        return False, (f"You've used all {LIMITS[kind]} free {LABEL[kind]} this month.")
    return True, ""


def consume(client_id: str, kind: str) -> None:
    """Record one successful use against BOTH the per-client month and the global day.
    Call only after the work succeeds."""
    with closing(_conn()) as c, c:
        for cid, period in ((client_id, _month()), (_GLOBAL_CLIENT, _day())):
            c.execute(
                "INSERT INTO usage (client_id, period, kind, count) VALUES (?,?,?,1) "
                "ON CONFLICT(client_id, period, kind) DO UPDATE SET count = count + 1",
                (cid, period, kind))
