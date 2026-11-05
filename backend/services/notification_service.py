"""
Notification Service for Citizen and Police Alerts.
Ensures notifications are dispatched only to authorized parties (FIR citizen & assigned officers).
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.db import get_db_connection


def create_notification(
    user_id: str,
    fir_id: Optional[str] = None,
    title: str = "",
    message: str = "",
    notification_type: str = "FIR_UPDATE",
    event_id: Optional[str] = None,
    severity: str = "INFO",
    complaint_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a persistent notification for a specific authorized user.

    Either ``fir_id`` or ``complaint_id`` identifies the underlying case.
    When ``event_id`` is supplied the insert is de-duplicated so the same
    database event never produces two alerts for the same user.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if event_id:
        cursor.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND event_id = ? LIMIT 1",
            (user_id, event_id),
        )
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return dict(existing)

    notif_id = f"ntf-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO notifications (
            id, user_id, fir_id, complaint_id, event_id, type, title, message,
            is_read, severity, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
    """, (
        notif_id, user_id, fir_id or None, complaint_id or None, event_id,
        notification_type, title, message, severity, now,
    ))

    conn.commit()
    conn.close()

    payload = {
        "id": notif_id,
        "user_id": user_id,
        "fir_id": fir_id,
        "complaint_id": complaint_id,
        "title": title,
        "message": message,
        "type": notification_type,
        "severity": severity,
        "is_read": 0,
        "created_at": now
    }
    try:
        from backend.services.realtime_events import publish
        publish({"type": "NOTIFICATION_CREATED", "user_id": user_id, "notification": payload})
    except Exception:
        pass

    return payload


def get_user_notifications(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve all notifications for a specific user."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT n.*, COALESCE(f.fir_number, cf.fir_number) AS fir_number,
               COALESCE(n.fir_id, c.fir_id) AS case_fir_id,
               c.reference AS complaint_reference,
               COALESCE(fu.name, cu.name) AS citizen_name
        FROM notifications n
        LEFT JOIN firs f ON n.fir_id = f.id
        LEFT JOIN complaints c ON n.complaint_id = c.id
        LEFT JOIN firs cf ON c.fir_id = cf.id
        LEFT JOIN users fu ON f.citizen_id = fu.id
        LEFT JOIN users cu ON c.citizen_id = cu.id
        WHERE n.user_id = ?
        ORDER BY n.created_at DESC
        LIMIT ?
    """, (user_id, limit))

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_unread_count(user_id: str) -> int:
    """Get count of unread notifications for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS count FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row["count"] if row else 0


def mark_notification_read(notification_id: str, user_id: str) -> bool:
    """Mark a notification as read (must belong to the user)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notification_id, user_id))
    conn.commit()
    affected = cursor.rowcount > 0
    conn.close()
    if affected:
        _publish_read_update(user_id)
    return affected


def mark_all_read(user_id: str) -> bool:
    """Mark all notifications for a user as read."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    _publish_read_update(user_id)
    return True


def _publish_read_update(user_id: str) -> None:
    try:
        from backend.services.realtime_events import publish
        publish({"type": "NOTIFICATION_UPDATED", "user_id": user_id})
    except Exception:
        pass
