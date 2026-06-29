"""
Audit logger — SQLite backend.

Schema (M3 — extended in M4/M5):
  submissions table: one row per POST /submit call
  appeals table: added in M5

Every field the spec requires in a log entry is captured here.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", "audit.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                submission_id  TEXT PRIMARY KEY,
                creator_id     TEXT,
                timestamp      TEXT NOT NULL,
                text_hash      TEXT NOT NULL,
                verdict        TEXT NOT NULL,
                confidence     REAL NOT NULL,
                llm_score      REAL,
                stylometric_score REAL,
                llm_reasoning  TEXT,
                label          TEXT NOT NULL,
                status         TEXT NOT NULL DEFAULT 'classified',
                short_text_warning INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS appeals (
                appeal_id      TEXT PRIMARY KEY,
                submission_id  TEXT NOT NULL,
                creator_id     TEXT NOT NULL,
                reasoning      TEXT NOT NULL,
                timestamp      TEXT NOT NULL,
                original_verdict    TEXT,
                original_confidence REAL,
                FOREIGN KEY (submission_id) REFERENCES submissions(submission_id)
            )
        """)
        conn.commit()


def insert_submission(
    submission_id: str,
    creator_id: str,
    text_hash: str,
    verdict: str,
    confidence: float,
    llm_score,
    stylometric_score,
    llm_reasoning: str,
    label: str,
    short_text_warning: bool = False,
):
    ts = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO submissions
              (submission_id, creator_id, timestamp, text_hash, verdict,
               confidence, llm_score, stylometric_score, llm_reasoning,
               label, status, short_text_warning)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'classified', ?)
            """,
            (
                submission_id,
                creator_id or "",
                ts,
                text_hash,
                verdict,
                confidence,
                llm_score,
                stylometric_score,
                llm_reasoning or "",
                label,
                int(short_text_warning),
            ),
        )
        conn.commit()
    return ts


def get_log(limit: int = 50, offset: int = 0, verdict_filter: str = None) -> list:
    """
    Return audit entries joined with any appeal, in reviewer-facing shape.
    """
    with _connect() as conn:
        query = """
            SELECT
                s.submission_id, s.creator_id, s.timestamp, s.verdict,
                s.confidence, s.llm_score, s.stylometric_score,
                s.llm_reasoning, s.label, s.status, s.short_text_warning,
                a.appeal_id, a.reasoning AS appeal_reasoning,
                a.timestamp AS appeal_timestamp, a.creator_id AS appeal_creator_id
            FROM submissions s
            LEFT JOIN appeals a ON s.submission_id = a.submission_id
        """
        params = []
        if verdict_filter:
            query += " WHERE s.verdict = ?"
            params.append(verdict_filter)
        query += " ORDER BY s.timestamp DESC LIMIT ? OFFSET ?"
        params += [limit, offset]

        rows = conn.execute(query, params).fetchall()

    entries = []
    for r in rows:
        entry = {
            "submission_id": r["submission_id"],
            "creator_id": r["creator_id"],
            "timestamp": r["timestamp"],
            "verdict": r["verdict"],
            "confidence": r["confidence"],
            "llm_score": r["llm_score"],
            "stylometric_score": r["stylometric_score"],
            "llm_reasoning": r["llm_reasoning"],
            "label": r["label"],
            "status": r["status"],
            "short_text_warning": bool(r["short_text_warning"]),
            "appeal": None,
        }
        if r["appeal_id"]:
            entry["appeal"] = {
                "appeal_id": r["appeal_id"],
                "creator_id": r["appeal_creator_id"],
                "reasoning": r["appeal_reasoning"],
                "timestamp": r["appeal_timestamp"],
            }
        entries.append(entry)
    return entries


def update_status(submission_id: str, new_status: str):
    with _connect() as conn:
        conn.execute(
            "UPDATE submissions SET status = ? WHERE submission_id = ?",
            (new_status, submission_id),
        )
        conn.commit()


def get_submission(submission_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE submission_id = ?", (submission_id,)
        ).fetchone()
    if not row:
        return None
    return dict(row)


def get_appeal(submission_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM appeals WHERE submission_id = ?", (submission_id,)
        ).fetchone()
    return dict(row) if row else None