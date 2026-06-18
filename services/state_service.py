"""
SQLite local state management service.

Provides CRUD operations for outreach records with full audit trail.
Thread-safe via connection-per-call pattern.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import logger

# ── Module-level path to the database ─────────────────────────
_DB_PATH: str = "./data/state.db"
_SCHEMA_PATH: str = ""


def init_db(db_path: str = "./data/state.db",
            schema_path: str = "./schema.sql") -> None:
    """
    Initialize the SQLite database from schema.sql.

    Creates the data directory and database file if they don't exist.
    Safe to call multiple times (CREATE IF NOT EXISTS).
    """
    global _DB_PATH, _SCHEMA_PATH
    _DB_PATH = db_path
    _SCHEMA_PATH = schema_path

    # Ensure data directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    schema_file = Path(schema_path)
    if not schema_file.exists():
        logger.error(f"Schema file not found: {schema_path}")
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    schema_sql = schema_file.read_text(encoding="utf-8")

    conn = _get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
        logger.info(f"Database initialized at {db_path}")
    finally:
        conn.close()


def _get_connection() -> sqlite3.Connection:
    """Get a new SQLite connection (thread-safe pattern)."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
    return conn


# ── CRUD Operations ───────────────────────────────────────────

def upsert_record(linkedin_url: str, **kwargs) -> int:
    """
    Insert or update an outreach record.

    If a record with the given linkedin_url exists, update it.
    Otherwise, insert a new record.

    Returns the record ID.
    """
    conn = _get_connection()
    try:
        # Check if record exists
        existing = conn.execute(
            "SELECT id FROM outreach_records WHERE linkedin_url = ?",
            (linkedin_url,)
        ).fetchone()

        if existing:
            # Update
            record_id = existing["id"]
            if kwargs:
                set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
                values = list(kwargs.values()) + [record_id]
                conn.execute(
                    f"UPDATE outreach_records SET {set_clause} WHERE id = ?",
                    values,
                )
            conn.commit()
            logger.debug(f"Updated record {record_id} for {linkedin_url}")
            return record_id
        else:
            # Insert
            kwargs["linkedin_url"] = linkedin_url
            columns = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" * len(kwargs))
            cursor = conn.execute(
                f"INSERT INTO outreach_records ({columns}) VALUES ({placeholders})",
                list(kwargs.values()),
            )
            conn.commit()
            record_id = cursor.lastrowid
            logger.debug(f"Inserted record {record_id} for {linkedin_url}")
            return record_id
    finally:
        conn.close()


def get_record(linkedin_url: str) -> Optional[Dict[str, Any]]:
    """Get a single outreach record by LinkedIn URL."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM outreach_records WHERE linkedin_url = ?",
            (linkedin_url,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_records_by_status(status: str) -> List[Dict[str, Any]]:
    """Get all records with a given status."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM outreach_records WHERE status = ? ORDER BY created_at",
            (status,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_stale_sent_records(days: int = 14) -> List[Dict[str, Any]]:
    """
    Get records with status='sent' that were sent more than `days` ago.

    Used by the follow-up job to find requests that should be
    checked for acceptance or withdrawn.
    """
    cutoff = datetime.now() - timedelta(days=days)
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM outreach_records WHERE status = 'sent' AND sent_at <= ?",
            (cutoff.isoformat(),)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_pending_targets() -> List[Dict[str, Any]]:
    """
    Get records that haven't been processed yet (status = 'pending').
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM outreach_records WHERE status = 'pending' ORDER BY created_at",
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def mark_sent(linkedin_url: str, note_draft: str, note_reviewed: str,
              note_final: str, posts_liked: int = 0,
              comment_final: str = "", char_limit: int = 300) -> None:
    """Mark a record as sent with all the details."""
    upsert_record(
        linkedin_url,
        status="sent",
        note_draft=note_draft,
        note_reviewed=note_reviewed,
        note_final=note_final,
        note_char_limit=char_limit,
        posts_liked=posts_liked,
        comment_final=comment_final,
        post_commented=1 if comment_final else 0,
        sent_at=datetime.now().isoformat(),
    )
    logger.info(f"✅ Marked as SENT: {linkedin_url}")


def mark_accepted(linkedin_url: str) -> None:
    """Mark a record as accepted."""
    upsert_record(
        linkedin_url,
        status="accepted",
        accepted_at=datetime.now().isoformat(),
        last_checked_at=datetime.now().isoformat(),
    )
    logger.info(f"🤝 Marked as ACCEPTED: {linkedin_url}")


def mark_withdrawn(linkedin_url: str) -> None:
    """Mark a record as withdrawn."""
    upsert_record(
        linkedin_url,
        status="withdrawn",
        withdrawn_at=datetime.now().isoformat(),
        last_checked_at=datetime.now().isoformat(),
    )
    logger.info(f"↩️  Marked as WITHDRAWN: {linkedin_url}")


def mark_error(linkedin_url: str, error_message: str,
               screenshot_path: str = "") -> None:
    """Mark a record as errored."""
    upsert_record(
        linkedin_url,
        status="error",
        error_message=error_message,
        screenshot_path=screenshot_path,
    )
    logger.error(f"❌ Marked as ERROR: {linkedin_url} — {error_message}")


def mark_skipped(linkedin_url: str, reason: str = "") -> None:
    """Mark a record as skipped (e.g., already connected)."""
    upsert_record(
        linkedin_url,
        status="skipped",
        error_message=reason,
    )
    logger.info(f"⏭️  Marked as SKIPPED: {linkedin_url} — {reason}")


def update_profile_context(linkedin_url: str, name: str = "",
                           headline: str = "", current_role: str = "",
                           company: str = "", about_snippet: str = "",
                           mutual_connections: int = 0,
                           profile_context: Optional[dict] = None) -> None:
    """Update the extracted profile context for a record."""
    upsert_record(
        linkedin_url,
        name=name,
        headline=headline,
        current_role=current_role,
        company=company,
        about_snippet=about_snippet,
        mutual_connections=mutual_connections,
        profile_context=json.dumps(profile_context) if profile_context else "",
    )


def get_all_records() -> List[Dict[str, Any]]:
    """Get all outreach records."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM outreach_records ORDER BY created_at"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_summary() -> Dict[str, int]:
    """Get a count summary of records by status."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM outreach_records GROUP BY status"
        ).fetchall()
        return {row["status"]: row["count"] for row in rows}
    finally:
        conn.close()
