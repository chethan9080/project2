"""
Database Initialization & Data Cleanup Service.
Ensures relational schemas and Genesis Block exist without creating dummy records.
"""

from backend.services.blockchain_service import ensure_genesis_block
from backend.services.db import get_db_connection, init_database


def clean_all_dummy_data(keep_users: bool = False) -> None:
    """
    Remove all dummy complaints, FIRs, tracking, audit logs,
    sessions, alerts, chat messages, notifications, and blockchain blocks (>0).
    Keeps Genesis Block (block_index = 0) and database schemas intact.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF")
    cursor.execute("DELETE FROM notifications")
    cursor.execute("DELETE FROM fir_change_events")
    cursor.execute("DELETE FROM fir_versions")
    cursor.execute("DELETE FROM officer_assignments")
    cursor.execute("DELETE FROM blockchain_transactions")
    cursor.execute("DELETE FROM blockchain_blocks WHERE block_index > 0")
    cursor.execute("DELETE FROM complaints")
    cursor.execute("DELETE FROM chat_messages")
    cursor.execute("DELETE FROM citizen_verifications")
    cursor.execute("DELETE FROM officer_sessions")
    cursor.execute("DELETE FROM otp_sessions")
    cursor.execute("DELETE FROM officer_activity_logs")
    cursor.execute("DELETE FROM case_tracking")
    cursor.execute("DELETE FROM security_alerts")
    cursor.execute("DELETE FROM system_audit_logs")
    cursor.execute("DELETE FROM firs")
    if not keep_users:
        cursor.execute("DELETE FROM users")
    conn.commit()
    cursor.execute("PRAGMA foreign_keys = ON")
    conn.close()
    ensure_genesis_block()


def seed_database(force_reseed: bool = False) -> None:
    """
    Clean startup initialization:
    Initializes database tables and verifies Genesis Block existence.
    Does NOT inject dummy complaints, fake FIRs, or sample activity.
    """
    init_database()
    ensure_genesis_block()


if __name__ == "__main__":
    import sys

    keep_users = "--drop-users" not in sys.argv
    clean_all_dummy_data(keep_users=keep_users)
    print("Database cleaned. Schemas, Genesis Block, and user accounts preserved."
          if keep_users else "Database cleaned. Schemas and Genesis Block preserved.")
