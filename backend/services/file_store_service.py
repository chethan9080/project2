"""
Persistent File Store Service.

Stores uploaded file bytes in a SQLite table (file_blobs) so that files
survive Render redeploys even when no persistent disk is mounted.

Write path: bytes → disk (if writable) + file_blobs table in DB.
Read  path: disk first → DB blob fallback.

This means:
  • On local dev:   files live on disk as usual; DB blob is a backup copy.
  • On Render free: DB blob IS the primary store (Render Disk optional).
  • On Render paid: Render Disk holds both DB and files; blobs are redundant
    but harmless and cost only a few extra bytes per file.

No existing code paths or database schemas are changed; this module is
imported as an optional layer by the file-serving helpers.
"""

import hashlib
import os
import sqlite3
from typing import Optional

from backend.services.db import get_db_connection


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

_SCHEMA_CREATED = False


def _ensure_schema() -> None:
    global _SCHEMA_CREATED
    if _SCHEMA_CREATED:
        return
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_blobs (
            storage_key  TEXT PRIMARY KEY,
            content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            sha256       TEXT NOT NULL,
            size_bytes   INTEGER NOT NULL,
            blob         BLOB NOT NULL,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()
    _SCHEMA_CREATED = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_blob(storage_key: str, data: bytes, content_type: str = 'application/octet-stream') -> None:
    """
    Persist *data* under *storage_key* in the file_blobs table.
    Existing rows are replaced (upsert) so regenerated documents stay current.
    """
    _ensure_schema()
    digest = hashlib.sha256(data).hexdigest()
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO file_blobs (storage_key, content_type, sha256, size_bytes, blob)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(storage_key) DO UPDATE SET
            content_type = excluded.content_type,
            sha256       = excluded.sha256,
            size_bytes   = excluded.size_bytes,
            blob         = excluded.blob,
            created_at   = datetime('now')
    """, (storage_key, content_type, digest, len(data), sqlite3.Binary(data)))
    conn.commit()
    conn.close()


def load_blob(storage_key: str) -> Optional[bytes]:
    """Return the raw bytes for *storage_key*, or None if not found."""
    _ensure_schema()
    conn = get_db_connection()
    row = conn.execute(
        "SELECT blob FROM file_blobs WHERE storage_key = ?", (storage_key,)
    ).fetchone()
    conn.close()
    return bytes(row[0]) if row else None


def delete_blob(storage_key: str) -> None:
    """Remove a stored blob (e.g. after expiry or replacement)."""
    _ensure_schema()
    conn = get_db_connection()
    conn.execute("DELETE FROM file_blobs WHERE storage_key = ?", (storage_key,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Convenience helpers used by file-serving services
# ---------------------------------------------------------------------------

def read_file_with_fallback(disk_path: Optional[str], storage_key: str) -> Optional[bytes]:
    """
    Try to read bytes from *disk_path* first; fall back to the DB blob.
    Returns None if neither source has the file.
    """
    if disk_path and os.path.isfile(disk_path):
        try:
            with open(disk_path, 'rb') as fh:
                return fh.read()
        except OSError:
            pass
    return load_blob(storage_key)


def write_file_with_blob(disk_path: str, data: bytes,
                         storage_key: str,
                         content_type: str = 'application/octet-stream') -> None:
    """
    Write *data* to *disk_path* (creating parent dirs) AND save a DB blob
    under *storage_key* so the file survives disk loss.
    """
    try:
        os.makedirs(os.path.dirname(disk_path), exist_ok=True)
        with open(disk_path, 'wb') as fh:
            fh.write(data)
    except OSError:
        pass  # Disk write failed; blob is the only copy — that's fine.
    save_blob(storage_key, data, content_type)
