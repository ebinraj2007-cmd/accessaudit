"""storage.py — SQLite persistence for audit findings and the remediation
action log (a real audit trail: who/what was revoked or reset, and when)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "accessaudit.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    employee_email TEXT,
    employee_name TEXT,
    system TEXT,
    access_level TEXT,
    issue_type TEXT,
    severity INTEGER,
    reasoning TEXT,
    engine TEXT,
    status TEXT DEFAULT 'open',
    detected_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id TEXT,
    action TEXT,
    user_email TEXT,
    system TEXT,
    result TEXT,
    note TEXT,
    performed_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Indexes on the columns the dashboard filters/sorts by (checklist #7).
-- Targeted only: findings list orders by (severity, detected_at) and filters
-- by status; the action log orders by performed_at and joins on finding_id.
CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);
CREATE INDEX IF NOT EXISTS idx_findings_sort ON findings(severity DESC, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_actionlog_time ON action_log(performed_at DESC);
CREATE INDEX IF NOT EXISTS idx_actionlog_finding ON action_log(finding_id);
"""


def get_connection(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_findings(conn: sqlite3.Connection, findings: list) -> None:
    for f in findings:
        conn.execute(
            """INSERT INTO findings
               (id, employee_email, employee_name, system, access_level, issue_type,
                severity, reasoning, engine)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 severity=excluded.severity, reasoning=excluded.reasoning,
                 engine=excluded.engine, detected_at=CURRENT_TIMESTAMP
            """,
            (f.id, f.employee_email, f.employee_name, f.system, f.access_level,
             f.issue_type, f.severity, f.reasoning, f.engine),
        )
    conn.commit()


def get_all_findings(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM findings ORDER BY severity DESC, detected_at DESC"
    ).fetchall()


def get_finding(conn: sqlite3.Connection, finding_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()


def update_finding_status(conn: sqlite3.Connection, finding_id: str, status: str) -> None:
    conn.execute("UPDATE findings SET status = ? WHERE id = ?", (status, finding_id))
    conn.commit()


def log_action(conn: sqlite3.Connection, finding_id: str, result: dict) -> None:
    conn.execute(
        """INSERT INTO action_log (finding_id, action, user_email, system, result, note)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (finding_id, result["action"], result["user_email"], result["system"],
         result["result"], result.get("note", "")),
    )
    conn.commit()


def get_action_log(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM action_log ORDER BY performed_at DESC"
    ).fetchall()


def get_stats(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT issue_type, COUNT(*) as n FROM findings WHERE status='open' GROUP BY issue_type"
    ).fetchall()
    open_count = conn.execute("SELECT COUNT(*) as n FROM findings WHERE status='open'").fetchone()["n"]
    critical_count = conn.execute(
        "SELECT COUNT(*) as n FROM findings WHERE status='open' AND severity >= 4"
    ).fetchone()["n"]
    return {
        "open_total": open_count,
        "critical_open": critical_count,
        "by_issue_type": {row["issue_type"]: row["n"] for row in rows},
    }


def clear_all(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM findings")
    conn.execute("DELETE FROM action_log")
    conn.commit()
