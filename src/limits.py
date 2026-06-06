"""Best-effort per-user monthly usage caps — a lead-magnet gate, not a security boundary.

The HARD budget protection is OpenAI's account spend cap. These caps just stop the demo from
being used as a free production tool: a visitor gets a generous trial, then is asked to get in
touch. Usage is keyed by client IP (best-effort) and stored in a small SQLite table. On an
ephemeral / scale-to-zero host the table resets when the instance recycles — acceptable for a
demo, where the spend cap is the real backstop.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_settings

# Monthly allowance per user.
LIMITS = {"report": 5, "question": 50}
LABEL = {"report": "reports", "question": "questions"}


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


def _period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def used(client_id: str, kind: str) -> int:
    with _conn() as c:
        row = c.execute("SELECT count FROM usage WHERE client_id=? AND period=? AND kind=?",
                        (client_id, _period(), kind)).fetchone()
    return int(row[0]) if row else 0


def remaining(client_id: str, kind: str) -> int:
    return max(0, LIMITS[kind] - used(client_id, kind))


def consume(client_id: str, kind: str) -> None:
    """Record one successful use (call only after the work succeeds)."""
    with _conn() as c:
        c.execute(
            "INSERT INTO usage (client_id, period, kind, count) VALUES (?,?,?,1) "
            "ON CONFLICT(client_id, period, kind) DO UPDATE SET count = count + 1",
            (client_id, _period(), kind))
